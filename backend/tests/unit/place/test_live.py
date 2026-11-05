"""place.live: the property at a point and the addresses on it, from a fake map service (httpx.get patched). No real
services (PCR-0011)."""

import httpx
import pytest
from shapely.geometry import shape

from place import live
from tests.unit.place.snapshot import square

PROPERTY = shape(square(17.640, 59.850, 17.642, 59.851))


def register(*entries, status=200):
    def get(url, **kwargs):
        assert url.endswith("/11/query") and kwargs["params"]["geometryType"] == "esriGeometryEnvelope"
        features = [{"attributes": {"Name": name}, "geometry": {"x": x, "y": y}} for name, x, y in entries]
        return httpx.Response(status, json={"features": features}, request=httpx.Request("GET", url))
    return get


def test_lists_the_addresses_on_the_property_in_natural_order(monkeypatch):
    monkeypatch.setattr(live.httpx, "get", register(("Kungsgatan 10", 17.6410, 59.8505), ("Kungsgatan 9", 17.6405, 59.8502),
                                                     ("Kungsgatan 9", 17.6406, 59.8503), ("Grannvägen 1", 17.6500, 59.8505)))
    assert live._addresses_on(PROPERTY) == ["Kungsgatan 9", "Kungsgatan 10"]  # the neighbour's address left out


def test_a_failing_register_gives_no_answer_not_an_error(monkeypatch):
    monkeypatch.setattr(live.httpx, "get", register(status=503))
    assert live._addresses_on(PROPERTY) is None


# --- the property, from a service that errors now and then --------------------------------------------------------

ERROR = {"error": {"code": 500, "message": "Error performing query operation", "details": []}}
PARCEL = {"type": "Feature", "properties": {"fastighet": "FLOGSTA 11:1"},
          "geometry": square(17.600, 59.850, 17.610, 59.855)}


def service(*answers):
    """Uppsala's map service: the property layer answers with `answers` in turn, the address layer with nothing."""
    answers = list(answers)
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        if url.endswith("/11/query"):
            return httpx.Response(200, json={"features": []}, request=httpx.Request("GET", url))
        answer = answers.pop(0)
        if isinstance(answer, int):
            return httpx.Response(answer, text="", request=httpx.Request("GET", url))
        return httpx.Response(200, json=answer, request=httpx.Request("GET", url))
    get.calls = calls
    return get


def features(*parcels):
    return {"type": "FeatureCollection", "features": list(parcels)}


def test_the_property_is_found_when_the_service_errors_once(monkeypatch):
    """An error answer on the first try is asked again, so a momentary failure does not lose the property."""
    monkeypatch.setattr(live.httpx, "get", service(ERROR, features(PARCEL), features(PARCEL)))
    assert live.property_at("0380", 17.6051, 59.8521)["designation"] == "Uppsala Flogsta 11:1"


def test_a_server_error_status_is_asked_again_too(monkeypatch):
    monkeypatch.setattr(live.httpx, "get", service(500, features(PARCEL), features(PARCEL)))
    assert live.property_at("0380", 17.6052, 59.8522)["designation"] == "Uppsala Flogsta 11:1"


def test_a_service_that_keeps_erroring_is_unavailable(monkeypatch):
    """After PROPERTY_TRIES failures the lookup gives up, so a dead service does not hang a pin."""
    get = service(*[ERROR] * live.PROPERTY_TRIES)
    monkeypatch.setattr(live.httpx, "get", get)
    with pytest.raises(live.PlaceSourceUnavailable):
        live.property_at("0380", 17.6053, 59.8523)
    assert len(get.calls) == live.PROPERTY_TRIES


def test_a_service_that_answers_is_asked_once(monkeypatch):
    get = service(features(PARCEL), features(PARCEL))
    monkeypatch.setattr(live.httpx, "get", get)
    live.property_at("0380", 17.6054, 59.8524)
    assert len([url for url in get.calls if url.endswith("/51/query")]) == 2  # the point, then the whole property

"""place.live: the addresses on a property, from a fake address register (httpx.get patched). No real services
(PCR-0011)."""

import httpx
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

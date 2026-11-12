"""place.check_search: register addresses searched through a fake search, scored on distance and property, with a
fake address register (httpx.MockTransport) and a fake property service. No real services (PCR-0011)."""

import json

import httpx

from place.check_search import (
    distance_m,
    query_for,
    run_check,
    sample_addresses,
    score_address,
    summarise,
)
from place.live import PlaceSourceUnavailable

ROW = {"address": "Kungsgatan 47A", "city": "Uppsala", "lat": 59.8600, "lon": 17.6400, "query": "Kungsgatan 47A, Uppsala"}


def match(lat, lon, label="Kungsgatan 47A, Uppsala", kind="house"):
    return {"label": label, "lat": lat, "lon": lon, "kind": kind, "kommun": "Uppsala kommun", "in_pilot": True}


def property_at(code, lon, lat):
    """Kungsängen 7:8 west of 17.641, the street Kungsängen 1:2 east of it."""
    return {"designation": "Uppsala Kungsängen 7:8" if lon < 17.641 else "Uppsala Kungsängen 1:2"}


def test_distance_is_in_metres():
    assert round(distance_m((59.86, 17.64), (59.861, 17.64))) == 111
    assert round(distance_m((59.86, 17.64), (59.86, 17.642))) == 111


def test_a_house_match_on_the_same_property_scores_right():
    scored = score_address(ROW, [match(59.86001, 17.64001)], "0380", property_at)
    assert scored["found"] and scored["label_ok"] and scored["same_property"] is True
    assert scored["top_m"] < 2


def test_a_street_match_lands_on_another_property():
    scored = score_address(ROW, [match(59.8600, 17.6430, "Kungsgatan, Uppsala", "road")], "0380", property_at)
    assert scored["label_ok"] is False and scored["same_property"] is False
    assert 100 < scored["top_m"] < 200


def test_no_match_is_not_found():
    assert score_address(ROW, [], "0380", property_at)["found"] is False


def test_same_property_is_unknown_when_the_property_service_fails():
    def down(code, lon, lat):
        raise PlaceSourceUnavailable("down")
    assert score_address(ROW, [match(59.86, 17.64)], "0380", down)["same_property"] is None


def test_samples_addresses_from_the_register_in_batches():
    def handler(request):
        if request.url.params.get("returnIdsOnly") == "true":
            return httpx.Response(200, json={"objectIds": list(range(1, 301))})
        ids = request.url.params["objectIds"].split(",")
        return httpx.Response(200, json={"features": [
            {"attributes": {"Name": f"Gatan {i}", "PostCode": 75320, "PostCity": "Uppsala"},
             "geometry": {"x": 17.6, "y": 59.8}} for i in ids]})
    rows = sample_addresses("0380", 150, seed=1, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert len(rows) == 150 and rows[0]["city"] == "Uppsala" and rows[0]["address"].startswith("Gatan ")


def test_a_run_searches_as_typed_and_summarises(tmp_path):
    asked = []
    def search(query):
        asked.append(query)
        return [match(59.86001, 17.64001)] if "47A" in query else []
    addresses = [ROW, {**ROW, "address": "Okänd väg 1", "query": None}]
    result = run_check("0380", search=search, property_at=property_at, addresses=addresses, out_dir=tmp_path)
    assert asked == ["Kungsgatan 47A, Uppsala", "Okänd väg 1, Uppsala"]
    saved = json.loads((tmp_path / result["path"].split("/")[-1]).read_text())
    assert saved["summary"]["found"] == 0.5 and saved["summary"]["same_property"] == 1.0


def test_summary_counts_shares_over_all_addresses():
    rows = [{"found": True, "top_m": 10, "label_ok": True, "same_property": True},
            {"found": True, "top_m": 300, "label_ok": False, "same_property": False},
            {"found": False, "top_m": None, "label_ok": False, "same_property": None}]
    summary = summarise(rows)
    assert summary["within_30m"] == 0.333 and summary["within_500m"] == 0.667
    assert summary["same_property"] == 0.5 and summary["median_top_m"] == 300


def test_the_query_forms_are_what_people_type():
    assert query_for(ROW) == "Kungsgatan 47A, Uppsala"
    assert query_for(ROW, "lower") == "kungsgatan 47a uppsala"
    assert query_for(ROW, "no_letter") == "Kungsgatan 47, Uppsala"
    assert query_for({**ROW, "address": "Risby 39", "city": "Björklinge"}, "no_letter") == "Risby 39, Björklinge"

"""place.check_sources: the snapshot against the providers' answers at a point, with a fake snapshot and fake
providers (identify and WFS through httpx.MockTransport). No real services (PCR-0011)."""

import json

import httpx

from place.check_sources import (
    SourceChecker,
    compare,
    identify_keys,
    run_check,
    summarise,
    timed_profile,
    wfs_keys,
)
from place.sources import layer_by_id
from tests.unit.place.snapshot import (
    NATIONAL,
    PIN,
    collection,
    square,
    write_national_snapshot,
)

NATIONAL_WITH_IDS = NATIONAL | {"protected_areas": collection(
    (square(17.630, 59.845, 17.650, 59.855), {"NVRID": "2001234", "NAMN": "Kungsängsängen"}))}


def test_compare_names_what_each_side_lacks():
    assert compare(["1", "2"], ["2", "3"]) == {"ours": ["1", "2"], "theirs": ["2", "3"], "missing": ["3"],
                                              "extra": ["1"], "agree": False}
    assert compare([], [])["agree"] is True


def test_identify_reads_object_ids_by_their_alias():
    """Identify names attributes by alias (OBJEKTID on some Uppsala layers)."""
    def handler(request):
        assert request.url.path.endswith("/identify") and request.url.params["tolerance"] == "0"
        return httpx.Response(200, json={"results": [
            {"layerId": 122, "attributes": {"OBJECTID": "1120"}},
            {"layerId": 128, "attributes": {"OBJEKTID": "8096"}}]})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    layers = [layer_by_id("0380", "plans"), layer_by_id("0380", "zones_allman_plats")]
    found = identify_keys(client, layers[0].url, layers, {122: "OBJECTID", 128: "OBJEKTID"}, 17.64, 59.85)
    assert found == {"plans": ["1120"], "zones_allman_plats": ["8096"]}


def test_wfs_reads_keys_from_the_providers_broken_geometry_json():
    """The WFS writes "geometry": {"type": "MultiPolygon",} when the geometry is left out."""
    def handler(request):
        assert "Intersects" in request.url.params["FILTER"]
        return httpx.Response(200, text='{"type":"FeatureCollection","features":[{"type":"Feature","geometry":'
                                        '{"type":"MultiPolygon",},"properties":{"NVRID":"2011036"}}]}')
    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert wfs_keys(client, layer_by_id("0380", "protected_areas"), 17.64, 59.85) == ["2011036"]


def test_a_point_agrees_where_the_provider_says_the_same(tmp_path):
    store = write_national_snapshot(tmp_path, national=NATIONAL_WITH_IDS)
    snapshot_ids = {layer.id: [] for layer in SourceChecker("0380", store).layers}
    live = lambda lon, lat: snapshot_ids | {"protected_areas": ["2001234"]}
    result = SourceChecker("0380", store, live=live).check(*PIN)
    assert result["error"] is None
    assert result["layers"]["protected_areas"]["agree"] is True
    assert result["layers"]["plans"]["agree"] is True
    # the snapshot still has a Natura 2000 site the provider no longer reports there
    assert result["layers"]["natura2000"]["extra"] == ["SE0210071"]


def test_a_point_names_a_feature_the_snapshot_misses(tmp_path):
    store = write_national_snapshot(tmp_path, national=NATIONAL_WITH_IDS)
    live = lambda lon, lat: {"protected_areas": ["2001234", "2057244"]}
    row = SourceChecker("0380", store, live=live).check(*PIN)["layers"]["protected_areas"]
    assert row["missing"] == ["2057244"] and not row["extra"]


def test_a_provider_failure_is_reported_not_raised(tmp_path):
    store = write_national_snapshot(tmp_path)
    def down(lon, lat):
        raise httpx.ConnectError("down")
    assert SourceChecker("0380", store, live=down).check(*PIN)["error"].startswith("ConnectError")


def test_a_failing_profile_is_timed_with_its_error():
    def broken(lat, lon):
        raise RuntimeError("boom")
    assert timed_profile(broken, *PIN)["error"] == "RuntimeError: boom"


def test_a_run_samples_points_saves_them_and_summarises(tmp_path):
    store = write_national_snapshot(tmp_path / "geo", national=NATIONAL_WITH_IDS)
    checker = SourceChecker("0380", store, live=lambda lon, lat: {"protected_areas": []})
    build = lambda lat, lon: {"property_status": "found", "section_status": {"ancient_remains": "ok"},
                              "detaljplan": "inside"}
    result = run_check("0380", 6, store=store, checker=checker, build=build, drafts=False, out_dir=tmp_path, workers=1)
    saved = json.loads((tmp_path / result["path"].split("/")[-1]).read_text())
    assert len(saved["points"]) == 6
    summary = saved["summary"]
    assert summary["checked"] == 6 and summary["profile"]["timed"] == 6
    assert summary["profile"]["detaljplan"]["inside"] == 6
    assert summary["layers"]["protected_areas"]["points"] == 6


def test_summary_gives_precision_and_recall_per_layer():
    points = [{"sources": {"error": None, "layers": {"plans": compare(["1"], ["1", "2"])}}, "profile": None},
              {"sources": {"error": None, "layers": {"plans": compare(["3"], [])}}, "profile": None}]
    plans = summarise(points)["layers"]["plans"]
    assert (plans["precision"], plans["recall"], plans["agree"], plans["present"]) == (0.5, 0.5, 0, 2)

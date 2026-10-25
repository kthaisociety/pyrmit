"""place.fetch.fetch_kommun against fake Nominatim, ArcGIS and WFS services."""

import json

import httpx
import pytest

from place.fetch import fetch_kommun
from tests.unit.place.snapshot import square


def fake_services(fail_layer: str | None = None):
    """Nominatim, ArcGIS MapServer and WFS answers for fetch_kommun."""
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "nominatim" in url:
            return httpx.Response(200, json=[{"addresstype": "municipality",
                                              "geojson": square(17.5, 59.7, 17.9, 60.0)}])
        if "/query" in url:
            layer_id = request.url.path.rstrip("/").split("/")[-2]
            if fail_layer and layer_id == fail_layer:
                return httpx.Response(500)
            if request.url.params.get("returnIdsOnly") == "true":
                return httpx.Response(200, json={"objectIds": [1, 2]})
            inside = {"type": "Feature", "geometry": square(17.6, 59.8, 17.61, 59.81),
                      "properties": {"OBJECTID": 1, "Plannamn": "Inne"}}
            outside = {"type": "Feature", "geometry": square(11.9, 57.6, 11.95, 57.65),
                       "properties": {"OBJECTID": 2, "Plannamn": "Ute"}}
            return httpx.Response(200, json={"type": "FeatureCollection", "features": [inside, outside]})
        if "wfs" in url:
            return httpx.Response(200, json={"type": "FeatureCollection", "features": []})
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_writes_a_dated_snapshot(tmp_path):
    """The snapshot command writes the boundary, each layer and a manifest with the fetch date."""
    manifest = fetch_kommun("0380", client=fake_services(), out_dir=tmp_path)
    folder = tmp_path / "0380"
    assert (folder / "kommun.geojson").exists()
    assert (folder / "plans.geojson").exists()
    assert manifest["layers"]["plans"]["fetched"]
    assert manifest["layers"]["plans"]["complete"] is True
    assert json.loads((folder / "manifest.json").read_text())["kommun"]["code"] == "0380"


def test_fetch_keeps_only_national_features_inside_the_kommun(tmp_path):
    """National layers keep only the features that meet the kommun boundary."""
    fetch_kommun("0380", client=fake_services(), out_dir=tmp_path)
    names = [f["properties"].get("Plannamn") for f in
             json.loads((tmp_path / "0380" / "riks_naturvard.geojson").read_text())["features"]]
    assert names == ["Inne"]


def test_fetch_keeps_the_previous_snapshot_of_a_failing_layer(tmp_path):
    """A layer whose fetch fails keeps its earlier file and records the error."""
    fetch_kommun("0380", client=fake_services(), out_dir=tmp_path)
    before = (tmp_path / "0380" / "plans.geojson").read_text()
    manifest = fetch_kommun("0380", only={"plans"}, client=fake_services(fail_layer="122"), out_dir=tmp_path)
    assert (tmp_path / "0380" / "plans.geojson").read_text() == before
    assert "last_error" in manifest["layers"]["plans"]


def test_fetch_refuses_a_kommun_that_is_not_a_pilot(tmp_path):
    """Only pilot kommuner can be fetched."""
    with pytest.raises(KeyError):
        fetch_kommun("0115", client=fake_services(), out_dir=tmp_path)

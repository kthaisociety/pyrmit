"""place.fetch.fetch_kommun against fake Nominatim, ArcGIS and WFS services."""

import json

import httpx
import pytest

from place.fetch import fetch_kommun, kommun_boundary
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


def boundary_client(answers: dict[str, list[dict]], asked: list[str] | None = None) -> httpx.Client:
    """A fake Nominatim answering each query from `answers`, nothing for any other."""
    def handler(request: httpx.Request) -> httpx.Response:
        query = request.url.params["q"]
        if asked is not None:
            asked.append(query)
        return httpx.Response(200, json=answers.get(query, []))
    return httpx.Client(transport=httpx.MockTransport(handler))


BOXHOLM_TOWN = {"name": "Boxholm", "addresstype": "town", "category": "place", "type": "town",
                "geojson": {"type": "Point", "coordinates": [15.05, 58.2]}}
BOXHOLM = {"name": "Boxholms kommun", "addresstype": "municipality", "category": "boundary", "type": "administrative",
           "geojson": square(14.9, 58.0, 15.3, 58.3)}


def test_boundary_is_found_under_the_kommuns_genitive_name(monkeypatch):
    """Boxholm is "Boxholms kommun" in OpenStreetMap: when the plain name finds only the town, the genitive is asked."""
    monkeypatch.setattr("place.fetch.RETRY_DELAY_S", 0)
    client = boundary_client({"Boxholm kommun": [BOXHOLM_TOWN], "Boxholms kommun": [BOXHOLM]})
    assert kommun_boundary(client, "0560", "Boxholm") == BOXHOLM["geojson"]


def test_boundary_asks_once_when_the_plain_name_finds_it(monkeypatch):
    """A kommun found under its plain name costs one Nominatim request."""
    monkeypatch.setattr("place.fetch.RETRY_DELAY_S", 0)
    asked: list[str] = []
    named = BOXHOLM | {"name": "Nacka kommun"}
    assert kommun_boundary(boundary_client({"Nacka kommun": [named]}, asked), "0182", "Nacka") == named["geojson"]
    assert asked == ["Nacka kommun"]


def test_boundary_raises_when_neither_name_finds_it(monkeypatch):
    """Only a town under both names is no boundary."""
    monkeypatch.setattr("place.fetch.RETRY_DELAY_S", 0)
    with pytest.raises(RuntimeError, match="No municipality boundary"):
        kommun_boundary(boundary_client({"Boxholm kommun": [BOXHOLM_TOWN]}), "0560", "Boxholm")


def test_boundary_of_a_kommun_with_an_irregular_name(monkeypatch):
    """Falun is "Falu kommun" in OpenStreetMap, which neither the name nor its genitive finds."""
    monkeypatch.setattr("place.fetch.RETRY_DELAY_S", 0)
    falu = BOXHOLM | {"name": "Falu kommun"}
    assert kommun_boundary(boundary_client({"Falu kommun": [falu]}), "2080", "Falun") == falu["geojson"]

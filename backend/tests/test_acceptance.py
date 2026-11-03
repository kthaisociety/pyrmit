"""Acceptance tests of #52: place lookup covers every kommun with an open plan layer. One file for the ticket,
folded into the module test files by unit-test-ticket. No real services (PCR-0011): fake Nominatim, ArcGIS and WFS."""

import csv
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dependencies import get_current_user
from place.plan_layers import (
    COVERAGE_REPORT,
    PLAN_KEY,
    fetch_plan_layer,
    fetch_registry,
)
from place.profile import build_profile
from place.registry import (
    SURVEY_PATH,
    PlanSource,
    build_registry,
    load_registry,
    save_registry,
)
from place.sources import today
from place.store import PlaceStore
from routers import place as place_router
from tests.unit.place.snapshot import (
    PIN,
    fake_property,
    no_remains,
    registry,
    square,
    write_snapshot,
)

# --- fakes ------------------------------------------------------------------------------------------------------

NACKA_BOUNDARY = square(18.0, 59.25, 18.4, 59.40)
IN_NACKA = (59.31, 18.16)            # lat, lon: covered by NEWER and OLDER
NO_PLAN_IN_NACKA = (59.38, 18.05)    # inside the kommun, no plan
NEWER = square(18.15, 59.30, 18.17, 59.32)
OLDER = square(18.10, 59.28, 18.20, 59.35)
ELSEWHERE = square(18.30, 59.26, 18.35, 59.28)
OUTSIDE_NACKA = square(17.0, 59.0, 17.1, 59.1)

NACKA_FEATURES = [
    (NEWER, {"OBJECTID": 1, "aktbeteckning": "0182-P2015/3", "plannamn": "Kvarnholmen etapp 4",
             "lagakraft": "2015-06-01", "plantyp": "Detaljplan",
             "url": "http://infobank.nacka.se/ext/planer/kvarnholmen.pdf"}),
    (OLDER, {"OBJECTID": 2, "aktbeteckning": "0182-P1988/12", "plannamn": "Sicklaön", "lagakraft": "19880309",
             "plantyp": "Stadsplan", "url": "https://www.nacka.se/planer/sicklaon/"}),
    (ELSEWHERE, {"OBJECTID": 3, "aktbeteckning": None, "plannamn": "Utan akt", "lagakraft": None, "plantyp": None,
                 "url": None}),
]


def source(**fields) -> PlanSource:
    base = {"code": "0182", "name": "Nacka", "status": "A", "service": "arcgis",
            "url": "https://karta.nacka.se/arcgis/rest/services/Plan/MapServer/3", "layer": "Gällande detaljplaner",
            "akt_fields": ("aktbeteckning",), "url_fields": ("url",), "name_fields": ("plannamn",),
            "date_fields": ("lagakraft",), "type_fields": ("plantyp",), "survey_count": 3}
    return PlanSource(**(base | fields))


def fake_services(features=NACKA_FEATURES, *, fail_host: str | None = None, boundary=NACKA_BOUNDARY):
    """Nominatim (every kommun gets `boundary`), an ArcGIS layer and a WFS type, both serving `features`."""
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "nominatim" in url:
            return httpx.Response(200, json=[{"addresstype": "municipality", "name": request.url.params["q"],
                                              "geojson": boundary}])
        if fail_host and fail_host in url:
            return httpx.Response(500)
        if "/query" in url:
            if request.url.params.get("returnIdsOnly") == "true":
                return httpx.Response(200, json={"objectIds": [p["OBJECTID"] for _, p in features]})
            ids = {int(i) for i in request.url.params["objectIds"].split(",")}
            return httpx.Response(200, json={"type": "FeatureCollection", "features": [
                {"type": "Feature", "id": p["OBJECTID"], "geometry": g, "properties": p}
                for g, p in features if p["OBJECTID"] in ids]})
        if "getfeature" in url.lower():
            return httpx.Response(200, json={"type": "FeatureCollection", "features": [
                {"type": "Feature", "id": f"plan.{p['OBJECTID']}", "geometry": g, "properties": p}
                for g, p in features]})
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler))


def with_link(link, **extra):
    """The Nacka features with the newest plan's link replaced."""
    geometry, props = NACKA_FEATURES[0]
    return [(geometry, props | {"url": link} | extra)] + NACKA_FEATURES[1:]


def snapshot_plans(out_dir):
    return json.loads((out_dir / "0182" / "plans.geojson").read_text(encoding="utf-8"))["features"]


def plan_block(out_dir, ref):
    return next(f["properties"][PLAN_KEY] for f in snapshot_plans(out_dir) if f["properties"]["aktbeteckning"] == ref)


SURVEY_COLUMNS = ["kod", "kommun", "status", "endpoint_kind", "endpoint_url", "layer_name", "count", "url_fields",
                  "akt_fields", "date_fields", "url_example", "vendor", "viewer_url", "source", "notes"]
SURVEY_ROWS = [
    ["0114", "Upplands Väsby", "D", "", "", "", "", "", "", "", "", "geosecma", "https://vasby/spatialmap", "agent", ""],
    ["0117", "Österåker", "B", "arcgis", "https://gisportal.osteraker.se/arcgis/rest/services/Detaljplaner/MapServer/0",
     "Österåker/Detaljplaner/Detaljplaner", "390", "", "", "LAGAKRAFT|ANT_DATUM", "", "", "", "auto", ""],
    ["0120", "Värmdö", "A", "wfs", "https://karta.varmdo.se/geoserver/ows", "intern_db:vy_gallande_detaljplaner_y",
     "559", "lank_intern|lank_extern|lank", "planbeteckning", "", "https://adfs.comprima.se/x", "", "", "auto", ""],
    ["0126", "Huddinge", "A", "wfs", "https://gd-huddinge.sokigohosting.com/MBF?SERVICE=WFS", "qgs:dp_plan (Detaljplaner)",
     "1377", "dp_planhandlingar", "dp_plannummer|dp_aktnummer", "dp_laga_kraft_datum", "", "sokigo", "", "agent", ""],
    ["0181", "Södertälje", "A", "wms", "https://karta.sodertalje.se/qgs?SERVICE=WMS", "gallande_planer", "",
     "dp_planhandlingar", "dp_plannummer", "", "", "origo", "", "agent", "WMS GetFeatureInfo only"],
    ["0182", "Nacka", "A", "wfs", "https://karta.nacka.se/geoserver/ows", "nacka:detaljplaner_gallande", "993", "url",
     "aktbeteckning", "", "http://infobank.nacka.se/x.pdf", "", "", "auto", ""],
    ["0380", "Uppsala", "A", "arcgis", "https://kartportal.uppsala.se/mapping/rest/services/nUrban/MapServer/3",
     "nUrban/Gällande detaljplaner", "1417", "UrlDokument", "Aktbeteckning", "LagaKraftDatum", "", "", "", "auto", ""],
    ["2260", "Ånge", "A", "wfs", "https://karta.ange.se/geoserver/ows", "RIGES:DetaljplanGallande_minusNGP_yta", "80",
     "url", "aktbet", "", "", "", "", "auto", ""],
    ["2281", "Sundsvall", "A", "wfs", "https://karta.ange.se/geoserver/ows", "RIGES:DetaljplanGallande_minusNGP_yta",
     "590", "url", "aktbet", "", "", "", "", "auto", ""],
]


@pytest.fixture
def survey(tmp_path):
    path = tmp_path / "survey.csv"
    with path.open("w", encoding="utf-8", newline="") as out:
        writer = csv.writer(out)
        writer.writerow(SURVEY_COLUMNS)
        writer.writerows(SURVEY_ROWS)
    return path


# --- the registry -----------------------------------------------------------------------------------------------

def test_registry_is_built_from_the_surveys_open_layers(survey):
    """The registry holds the survey's A and B rows served by ArcGIS or WFS, without the pilot kommuner."""
    assert [s.code for s in build_registry(survey, previous=None)] == ["0117", "0120", "0126", "0182", "2260", "2281"]


def test_registry_entry_carries_the_layers_keys_and_licence(survey):
    """A source carries the service, layer, the aktbeteckning and link attributes, the survey's count and licence 'unknown'."""
    varmdo = next(s for s in build_registry(survey, previous=None) if s.code == "0120")
    assert (varmdo.service, varmdo.url, varmdo.layer) == ("wfs", "https://karta.varmdo.se/geoserver/ows",
                                                          "intern_db:vy_gallande_detaljplaner_y")
    assert varmdo.akt_fields == ("planbeteckning",)
    assert varmdo.url_fields == ("lank_intern", "lank_extern", "lank")
    assert (varmdo.status, varmdo.survey_count, varmdo.licence, varmdo.base_url) == ("A", 559, "unknown", None)


def test_registry_strips_the_title_from_a_wfs_type_name(survey):
    """The survey's 'type (title)' spelling of a WFS layer becomes the bare type name."""
    huddinge = next(s for s in build_registry(survey, previous=None) if s.code == "0126")
    assert huddinge.layer == "qgs:dp_plan"


def test_registry_puts_the_laga_kraft_attribute_first(survey):
    """Among several date attributes, the laga kraft one comes first."""
    osteraker = next(s for s in build_registry(survey, previous=None) if s.code == "0117")
    assert osteraker.date_fields[0] == "LAGAKRAFT"


def test_registry_marks_a_shared_server(survey):
    """A kommun whose endpoint host the survey lists for another kommun too is marked shared."""
    by_code = {s.code: s for s in build_registry(survey, previous=None)}
    assert by_code["2260"].shared is True
    assert by_code["0182"].shared is False


def test_registry_keeps_the_operators_base_pattern_and_licence(survey, tmp_path):
    """A rebuild keeps the base pattern and licence an operator put in the earlier file."""
    previous = tmp_path / "previous.json"
    save_registry([source(service="wfs", base_url="https://infobank.nacka.se/ext/{file}", licence="CC0")], previous)
    nacka = next(s for s in build_registry(survey, previous=previous) if s.code == "0182")
    assert (nacka.base_url, nacka.licence) == ("https://infobank.nacka.se/ext/{file}", "CC0")


def test_registry_round_trips_through_its_file(tmp_path):
    """Saved sources load back unchanged, keyed by kommun code."""
    path = tmp_path / "plan_sources.json"
    save_registry([source(), source(code="0120", name="Värmdö", shared=True)], path)
    assert load_registry(path) == {"0182": source(), "0120": source(code="0120", name="Värmdö", shared=True)}


def test_registry_file_is_required(tmp_path):
    """Loading a missing registry file is an error, not an empty registry."""
    with pytest.raises(FileNotFoundError):
        load_registry(tmp_path / "missing.json")


def test_checked_in_registry_matches_the_survey():
    """The registry in the repo is the one the survey builds, so a kommun in neither is in neither."""
    assert set(load_registry()) == {s.code for s in build_registry(SURVEY_PATH, previous=None)}
    assert len(load_registry()) > 150


# --- the snapshot fetcher ---------------------------------------------------------------------------------------

def test_fetch_writes_a_dated_plan_snapshot(tmp_path):
    """A registry kommun's plan layer lands as a dated snapshot in the pilot kommuner's format."""
    row = fetch_plan_layer(source(), client=fake_services(), out_dir=tmp_path)
    folder = tmp_path / "0182"
    assert row["fetched"] is True and row["reason"] is None
    assert (folder / "kommun.geojson").exists() and (folder / "plans.geojson").exists()
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["kommun"] == {"code": "0182", "name": "Nacka", "fetched": today(),
                                  "source": "OpenStreetMap via Nominatim", "licence": "ODbL"}
    plans = manifest["layers"]["plans"]
    assert (plans["provider"], plans["licence"], plans["count"], plans["fetched"], plans["complete"]) == (
        "Nacka kommun", "unknown", 3, today(), False)


def test_fetch_reads_a_wfs_layer_with_the_endpoints_own_parameters(tmp_path):
    """A WFS source is read with the version and type name its endpoint already carries."""
    haninge = source(code="0136", name="Haninge", service="wfs", layer="planersutbredning",
                     url="https://karta.haninge.se/services/karta/ows?SERVICE=WFS&VERSION=1.1.0&REQUEST=GetFeature"
                         "&TYPENAME=planersutbredning&OUTPUTFORMAT=GeoJSON")
    row = fetch_plan_layer(haninge, client=fake_services(), out_dir=tmp_path)
    assert (row["fetched"], row["count"]) == (True, 3)


def test_fetch_keeps_only_the_polygons_that_meet_the_kommun(tmp_path):
    """A kommun on a shared server gets the polygons inside its own boundary, not its neighbours'."""
    elsewhere = (OUTSIDE_NACKA, {"OBJECTID": 4, "aktbeteckning": "2281-P1", "plannamn": "Grannkommunen",
                                 "lagakraft": None, "plantyp": None, "url": None})
    row = fetch_plan_layer(source(shared=True), client=fake_services(NACKA_FEATURES + [elsewhere]), out_dir=tmp_path)
    assert row["count"] == 3
    assert {f["properties"]["aktbeteckning"] for f in snapshot_plans(tmp_path)} == {"0182-P2015/3", "0182-P1988/12", None}


def test_a_failing_kommun_is_recorded_and_the_run_goes_on(tmp_path):
    """A kommun whose service fails gets a reason in its row and no snapshot; the next kommun is still fetched."""
    varmdo = source(code="0120", name="Värmdö", url="https://karta.varmdo.se/arcgis/rest/services/P/MapServer/1")
    rows = fetch_registry([varmdo, source()], client=fake_services(fail_host="varmdo"), out_dir=tmp_path)
    assert [(row["code"], row["fetched"]) for row in rows] == [("0120", False), ("0182", True)]
    assert rows[0]["reason"]
    assert not (tmp_path / "0120" / "plans.geojson").exists()


def test_a_bare_file_name_becomes_absolute_through_the_base_pattern(tmp_path):
    """A link that is only a file name is completed with the kommun's base pattern."""
    tranas = source(base_url="https://karta.tranas.se/docs/detaljplaner/{file}")
    fetch_plan_layer(tranas, client=fake_services(with_link("akt_06-ADE-316.pdf")), out_dir=tmp_path)
    assert plan_block(tmp_path, "0182-P2015/3")["documents"] == ["https://karta.tranas.se/docs/detaljplaner/akt_06-ADE-316.pdf"]


def test_a_link_wrapped_in_html_keeps_only_its_addresses(tmp_path):
    """An HTML anchor in a link attribute becomes the address it points to, one per anchor."""
    html = ('<a href="https://karta.haninge.se/dok/D1_Plankarta.PDF">Plankarta</a> '
            '<a href="https://karta.haninge.se/dok/D1_Planbeskrivning.pdf">Beskrivning</a>')
    fetch_plan_layer(source(), client=fake_services(with_link(html)), out_dir=tmp_path)
    assert plan_block(tmp_path, "0182-P2015/3")["documents"] == [
        "https://karta.haninge.se/dok/D1_Plankarta.PDF", "https://karta.haninge.se/dok/D1_Planbeskrivning.pdf"]


def test_an_internal_path_is_dropped_and_counted(tmp_path):
    """A server or drive path is no link: it is dropped from the plan and counted in the coverage row."""
    row = fetch_plan_layer(source(), client=fake_services(with_link(r"\\hylte.net\dfs\Plan\D210.pdf")), out_dir=tmp_path)
    assert plan_block(tmp_path, "0182-P2015/3")["documents"] == []
    assert row["dropped_links"] == 1


def test_a_bare_file_name_without_base_pattern_is_dropped_and_counted(tmp_path):
    """Without a base pattern a bare file name cannot become a link, so it is dropped and counted."""
    row = fetch_plan_layer(source(), client=fake_services(with_link("BE 4 Plankarta.pdf")), out_dir=tmp_path)
    assert plan_block(tmp_path, "0182-P2015/3")["documents"] == []
    assert row["dropped_links"] == 1


def test_the_plan_type_is_kept_when_the_layer_states_it(tmp_path):
    """A layer that mixes detaljplaner with stadsplaner keeps them all, each with its type."""
    fetch_plan_layer(source(), client=fake_services(), out_dir=tmp_path)
    assert plan_block(tmp_path, "0182-P1988/12")["type"] == "Stadsplan"
    assert plan_block(tmp_path, "0182-P2015/3")["type"] == "Detaljplan"


def test_an_empty_layer_is_flagged_and_gets_no_snapshot(tmp_path):
    """A layer that returns no polygon is flagged in its row and no snapshot is written."""
    row = fetch_plan_layer(source(), client=fake_services([]), out_dir=tmp_path)
    assert row["fetched"] is False and "no polygon" in row["reason"].lower()
    assert not (tmp_path / "0182" / "plans.geojson").exists()


def test_far_fewer_polygons_than_the_survey_counted_is_flagged(tmp_path):
    """A layer with far fewer polygons than the survey counted is flagged and gets no snapshot."""
    row = fetch_plan_layer(source(survey_count=100), client=fake_services(), out_dir=tmp_path)
    assert row["fetched"] is False and "100" in row["reason"]
    assert not (tmp_path / "0182" / "plans.geojson").exists()


def test_a_shared_server_is_not_flagged_for_fewer_polygons_than_the_survey(tmp_path):
    """The survey counted a shared layer for several kommuner, so fewer polygons than that is no flag."""
    row = fetch_plan_layer(source(survey_count=100, shared=True), client=fake_services(), out_dir=tmp_path)
    assert row["fetched"] is True


def test_the_coverage_row_counts_the_shares_of_keys_and_links(tmp_path):
    """The row says how many polygons the survey counted and the shares with an aktbeteckning and with a link."""
    row = fetch_plan_layer(source(), client=fake_services(), out_dir=tmp_path)
    assert (row["count"], row["survey_count"]) == (3, 3)
    assert row["ref_share"] == pytest.approx(2 / 3)
    assert row["link_share"] == pytest.approx(2 / 3)


def test_the_coverage_report_has_a_line_per_kommun(tmp_path):
    """After the run the report is written with one line per kommun in the registry, fetched or not."""
    varmdo = source(code="0120", name="Värmdö", url="https://karta.varmdo.se/arcgis/rest/services/P/MapServer/1")
    fetch_registry([varmdo, source()], client=fake_services(fail_host="varmdo"), out_dir=tmp_path)
    report = (tmp_path / COVERAGE_REPORT).read_text(encoding="utf-8")
    lines = [line for line in report.splitlines() if line.startswith("| 0")]
    assert [line.split("|")[1].strip() for line in lines] == ["0120", "0182"]
    assert "Värmdö" in lines[0] and "500" in lines[0]
    assert "Nacka" in lines[1] and "| 3 |" in lines[1]


# --- the place profile ------------------------------------------------------------------------------------------

def nacka_store(tmp_path, features=NACKA_FEATURES) -> PlaceStore:
    write_snapshot(tmp_path)
    fetch_plan_layer(source(), client=fake_services(features), out_dir=tmp_path)
    return PlaceStore(tmp_path)


def profile_at(store, at):
    return build_profile(*at, store=store, property_at=fake_property, plan_registry=registry,
                         ancient_remains_at=no_remains)


def test_a_pin_in_a_registry_kommun_names_it_and_lists_every_plan_at_the_point_newest_first(tmp_path):
    """A pin in a kommun with a plan snapshot names the kommun and lists every plan whose polygon covers the point,
    newest first."""
    result = profile_at(nacka_store(tmp_path), IN_NACKA)
    assert result["kommun"] == {"code": "0182", "name": "Nacka"} and result["covered"] is True
    assert [p["ref"] for p in result["plans"]] == ["0182-P2015/3", "0182-P1988/12"]
    assert result["detaljplan"] == "inside"


def test_a_registry_plan_row_carries_its_keys(tmp_path):
    """Each plan row has its aktbeteckning, name, date, page link, absolute document links, licence and snapshot date."""
    newer, older = profile_at(nacka_store(tmp_path), IN_NACKA)["plans"]
    assert (newer["ref"], newer["name"], newer["date"], newer["type"]) == ("0182-P2015/3", "Kvarnholmen etapp 4",
                                                                         "2015-06-01", "Detaljplan")
    assert (newer["page"], newer["documents"]) == (None, ["http://infobank.nacka.se/ext/planer/kvarnholmen.pdf"])
    assert newer["url"] == "http://infobank.nacka.se/ext/planer/kvarnholmen.pdf"
    assert (newer["licence"], newer["source"], newer["fetched"]) == ("unknown", "Nacka kommun", today())
    assert (older["date"], older["page"], older["documents"]) == ("1988-03-09", "https://www.nacka.se/planer/sicklaon/", [])
    assert older["url"] == "https://www.nacka.se/planer/sicklaon/"


def test_a_registry_kommun_has_no_property_lookup(tmp_path):
    """Outside Uppsala there is no property: the plans are those at the point and the property is not covered."""
    result = profile_at(nacka_store(tmp_path), IN_NACKA)
    assert (result["property"], result["property_status"]) == (None, "not_covered")
    assert (result["zones"], result["pending_plans"]) == ([], [])


def test_no_plan_in_a_registry_kommun_says_none_was_found_not_outside(tmp_path):
    """Where the layer is not known to hold every plan, a point without a plan is not 'outside': the profile says
    no plan was found in the kommun's layer."""
    result = profile_at(nacka_store(tmp_path), NO_PLAN_IN_NACKA)
    assert result["detaljplan"] == "unknown"
    assert any("no plan was found" in note.lower() and "Nacka" in note for note in result["notes"])


def test_uppsala_plan_rows_carry_page_documents_and_licence(tmp_path):
    """Uppsala's plan rows carry the new keys too: the page is the document link, the documents are none."""
    atle = next(p for p in profile_at(write_snapshot(tmp_path), PIN)["plans"] if p["ref"] == "0380-P2002/5")
    assert atle["page"] == "https://www.uppsala.se/detaljplan/?aktbeteckning=0380-P2002/5"
    assert atle["documents"] == []
    assert atle["licence"] == "open data"


def test_the_coverage_endpoint_lists_every_kommun_with_a_snapshot(tmp_path):
    """GET /api/place/coverage names Nacka beside Uppsala once Nacka's plan layer has a snapshot."""
    app = FastAPI()
    app.include_router(place_router.router, prefix="/api")
    store = nacka_store(tmp_path)
    app.dependency_overrides[place_router.get_place_store] = lambda: store
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u1")
    assert [k["code"] for k in TestClient(app).get("/api/place/coverage").json()] == ["0182", "0380"]

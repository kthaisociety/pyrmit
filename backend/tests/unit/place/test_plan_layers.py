"""place.plan_layers: a registry kommun's plan layer into a dated snapshot, the links normalised, and the coverage
report, against the fake services of tests.unit.place.plan_layer."""

import json

import pytest

from place.plan_layers import COVERAGE_REPORT, fetch_plan_layer, fetch_registry
from place.sources import today
from tests.unit.place.plan_layer import (
    NACKA_BOUNDARY,
    NACKA_FEATURES,
    OUTSIDE_NACKA,
    fake_services,
    plan_block,
    snapshot_plans,
    source,
    with_link,
)


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


def test_fetch_reads_a_wfs_layer_the_service_cannot_page_in_one_request(tmp_path):
    """A WFS type that answers 400 to a paged request (a GeoServer view without primary key) is read unpaged."""
    view = source(service="wfs", url="https://karta.nacka.se/geoserver/ows", layer="nacka:vy_planer")
    row = fetch_plan_layer(view, client=fake_services(paged=False), out_dir=tmp_path)
    assert (row["fetched"], row["count"]) == (True, 3)


def test_fetch_takes_the_boundary_from_an_administrative_result(tmp_path):
    """Nominatim may list the kommun's polygon as a town's administrative boundary and the municipality as a point."""
    results = [{"addresstype": "town", "class": "boundary", "type": "administrative", "name": "Nacka kommun",
                "geojson": NACKA_BOUNDARY},
               {"addresstype": "municipality", "name": "Nacka kommun",
                "geojson": {"type": "Point", "coordinates": [18.1, 59.3]}}]
    row = fetch_plan_layer(source(), client=fake_services(nominatim=results), out_dir=tmp_path)
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

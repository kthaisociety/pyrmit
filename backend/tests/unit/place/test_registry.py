"""place.registry: the plan source registry built from the survey and kept as a file."""

import csv

import pytest

from place.registry import SURVEY_PATH, build_registry, load_registry, save_registry
from tests.unit.place.plan_layer import source

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

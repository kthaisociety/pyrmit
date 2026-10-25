"""place.profile.build_profile on a fake snapshot with national layers and a fake ancient-remains register: the
protected areas, Natura 2000 sites, national interests, ancient remains and strandskydd around the property, and
whether a section found nothing or could not ask its source."""

import pytest
from shapely.geometry import Point, shape

from place.live import PlaceSourceUnavailable
from place.profile import build_profile
from tests.unit.place.snapshot import (
    EMPTY_LOT,
    FETCHED,
    NATIONAL,
    PIN,
    STREET,
    collection,
    fake_property,
    registry,
    remains_at,
    square,
    write_national_snapshot,
)


@pytest.fixture
def store(tmp_path):
    return write_national_snapshot(tmp_path)


def profile(store, at=PIN, **kwargs):
    return build_profile(*at, store=store, property_at=fake_property, plan_registry=registry,
                         ancient_remains_at=kwargs.pop("ancient_remains_at", remains_at), **kwargs)


def permit(result, word):
    return next(p for p in result["permits"] if word.lower() in p["title"].lower())


# --- protected areas, Natura 2000, national interests ---------------------------------------------------------

def test_lists_protected_areas_covering_the_property(store):
    """Protected areas on the property come with type, name, deciding authority, decision date and a link."""
    [reservat] = profile(store)["protected_areas"]
    assert reservat["type"] == "Naturreservat"
    assert reservat["name"] == "Kungsängsängen"
    assert reservat["authority"] == "Länsstyrelsen"
    assert reservat["date"] == "1951-03-02"
    assert reservat["url"] == "https://skyddadnatur.naturvardsverket.se/sknat/?nvrid=2001234"


def test_finds_an_area_whose_provider_polygon_is_invalid(tmp_path):
    """Naturvårdsverket sends some areas with a ring outside the shell it is listed under (16 % of Uppsala's
    protected areas): the pin in that ring is still in the area, as the provider's own point query says."""
    shell = square(17.660, 59.860, 17.670, 59.865)["coordinates"][0]
    outside_ring = square(17.639, 59.849, 17.643, 59.852)["coordinates"][0]  # covers the property, outside the shell
    national = NATIONAL | {"protected_areas": collection(
        ({"type": "Polygon", "coordinates": [shell, outside_ring]},
         {"NVRID": "2057244", "NAMN": "Gula stigen", "SKYDDSTYP": "Naturreservat", "BESLUTSMYNDIGHET": "Kommun"}))}
    store = write_national_snapshot(tmp_path, national=national)
    assert [area["name"] for area in profile(store)["protected_areas"]] == ["Gula stigen"]


def test_lists_natura2000_sites_with_code_and_link(store):
    """Natura 2000 sites on the property come with their site code and a link to the site description."""
    [site] = profile(store)["natura2000"]
    assert site["ref"] == "SE0210071"
    assert site["url"] == "https://natura2000.eea.europa.eu/Natura2000/SDF.aspx?site=SE0210071"


def test_lists_national_interests_with_kind_name_and_legal_basis(store):
    """National interests on the property come with kind, name, legal basis and a link when there is one."""
    interests = {row["name"]: row for row in profile(store)["national_interests"]}
    assert interests["Fyrisån"]["law"] == "MB 3:6"
    assert interests["Fyrisån"]["url"].startswith("https://geodata.naturvardsverket.se/")
    assert interests["Uppsala stad"]["type"] == "Riksintresse kulturmiljövård"
    assert interests["Uppsala stad"]["law"] == "MB 3 kap. 6 §"
    assert interests["Uppsala stad"]["url"] == "https://www.raa.se/riksintressen/c40"


def test_leaves_out_protected_areas_elsewhere(store):
    """A protected area that does not touch the property is not listed."""
    assert "Långt bort" not in [row["name"] for row in profile(store)["protected_areas"]]


# --- ancient remains -------------------------------------------------------------------------------------------

def test_lists_ancient_remains_on_the_property(store):
    """Remains on the property come with RAÄ number, type, antikvarisk bedömning and a Fornsök link."""
    remains = {row["ref"]: row for row in profile(store)["ancient_remains"]}
    gravfalt = remains["Uppsala 123:1"]
    assert gravfalt["type"] == "Gravfält"
    assert gravfalt["status"] == "Fornlämning"
    assert gravfalt["url"] == "https://pub.raa.se/visa/objekt/lamning/d4e16ab8"


def test_names_a_remain_without_raa_number_by_its_lamningsnummer(store):
    """A remain with no RAÄ number is named by its lämningsnummer."""
    assert "L1941:4000" in [row["ref"] for row in profile(store)["ancient_remains"]]


def test_lists_remains_near_the_pin_when_there_is_no_property(store):
    """Without a property, the register is asked around the pin."""
    asked = []

    def record(geometry):
        asked.append(shape(geometry))
        return []
    profile(store, at=STREET, ancient_remains_at=record)
    [area] = asked
    assert area.contains(Point(STREET[1], STREET[0]))
    assert area.area > 0


def test_reports_the_ancient_remains_register_unavailable(store):
    """A failing register makes the section unavailable rather than empty."""
    def broken(geometry):
        raise PlaceSourceUnavailable("timeout")
    result = profile(store, ancient_remains_at=broken)
    assert result["ancient_remains"] == []
    assert result["section_status"]["ancient_remains"] == "unavailable"


# --- strandskydd -----------------------------------------------------------------------------------------------

def test_strandskydd_is_not_checked_with_a_reason_and_a_reminder(store):
    """Strandskydd shows as not checked, with the reason and the 100 m reminder."""
    strandskydd = profile(store)["strandskydd"]
    assert strandskydd["status"] == "not_checked"
    assert "länsstyrelse" in strandskydd["reason"].lower()
    assert "100 m" in strandskydd["note"]
    assert "strandskyddsdispens" in strandskydd["note"].lower()


# --- none found vs. not reached --------------------------------------------------------------------------------

def test_sections_say_ok_when_their_sources_answered(store):
    """An answered section with nothing in it is 'ok' (none found), not unavailable."""
    result = profile(store, at=EMPTY_LOT)
    assert result["protected_areas"] == []
    assert result["section_status"]["protected_areas"] == "ok"


def test_a_section_is_unavailable_when_a_snapshot_is_missing(tmp_path):
    """A missing snapshot file makes its section unavailable rather than empty."""
    store = write_national_snapshot(tmp_path, missing=("natura2000",))
    assert profile(store)["section_status"]["natura2000"] == "unavailable"


def test_new_rows_name_their_source_and_date(store):
    """Protected areas, Natura 2000 sites, national interests and ancient remains name their source and date."""
    result = profile(store)
    assert result["protected_areas"][0]["source"] == "Naturvårdsverket"
    assert result["protected_areas"][0]["fetched"] == FETCHED
    assert result["natura2000"][0]["source"] == "Naturvårdsverket"
    assert all(row["source"].startswith("Boverket") for row in result["national_interests"])
    assert all(row["source"] == "Riksantikvarieämbetet" and row["fetched"] for row in result["ancient_remains"])

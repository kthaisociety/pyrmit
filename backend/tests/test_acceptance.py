"""Acceptance tests for #36: protected areas, national interests, ancient remains and likely permits on the place
card. Temporary, folded into tests/unit/ by refactor-issue. No real services (PCR-0011)."""

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from shapely.geometry import Point, shape

from dependencies import get_current_user
from place.live import PlaceSourceUnavailable
from place.profile import build_profile
from place.sources import NATIONAL_LAYERS, layer_by_id
from routers import place as place_router
from tests.unit.place.snapshot import (EMPTY_LOT, FETCHED, LAYERS, OUTSIDE, PIN, STREET, collection, fake_property,
                                       registry, square, write_snapshot)

AROUND_PROPERTY = square(17.630, 59.845, 17.650, 59.855)
FAR_AWAY = square(17.80, 59.95, 17.81, 59.96)

NATIONAL = {layer.id: collection() for layer in NATIONAL_LAYERS} | {
    "protected_areas": collection(
        (AROUND_PROPERTY, {"NVRID": "2001234", "NAMN": "Kungsängsängen", "SKYDDSTYP": "Naturreservat",
                           "BESLUTSSTATUS": "Gällande", "BESLUTSMYNDIGHET": "Länsstyrelsen",
                           "PROVNINGSMYNDIGHET_DISPENS": "Länsstyrelsen", "URSPR_BESLUTSDATUM": "1951-03-02"}),
        (FAR_AWAY, {"NVRID": "2009999", "NAMN": "Långt bort", "SKYDDSTYP": "Biotopskyddsområde",
                    "BESLUTSMYNDIGHET": "Kommun"}),
    ),
    "natura2000": collection(
        (AROUND_PROPERTY, {"OMRADESKOD": "SE0210071", "OMRADESNAMN": "Kungsängen", "OMRADESTYP": "SCI",
                           "UPPGIFTSLAMNARE": "Länsstyrelsen i Uppsala län"}),
    ),
    "riks_naturvard": collection(
        (AROUND_PROPERTY, {"NAMN": "Fyrisån", "AMNESOMRAD": "Naturvård", "LAGRUM": "MB 3:6", "RIKSID": "3068",
                           "BESKRIVNIN": "https://geodata.naturvardsverket.se/handlingar/rest/dokument/202397"}),
    ),
    "riks_kulturmiljo": collection(
        (AROUND_PROPERTY, {"NAMN": "Uppsala stad", "ORIGINALID": "C 40",
                           "OBJEKTLANK": "https://www.raa.se/riksintressen/c40"}),
    ),
}

REMAINS = [
    {"properties": {"lamningsnummer": "L1941:2381", "raa_nummer": "Uppsala 123:1", "lamningstyp": "Gravfält",
                    "antikvarisk_bedomning": "Fornlämning",
                    "url": "https://pub.raa.se/visa/objekt/lamning/d4e16ab8"},
     "geometry": square(17.6405, 59.8502, 17.6410, 59.8505)},
    {"properties": {"lamningsnummer": "L1941:3039", "raa_nummer": "Uppsala 586:1", "lamningstyp": "Boplats",
                    "antikvarisk_bedomning": "Möjlig fornlämning",
                    "url": "https://pub.raa.se/visa/objekt/lamning/82572d22"},
     "geometry": square(17.6412, 59.8502, 17.6415, 59.8505)},
    {"properties": {"lamningsnummer": "L1941:4000", "raa_nummer": None, "lamningstyp": "Färdväg",
                    "antikvarisk_bedomning": "Övrig kulturhistorisk lämning",
                    "url": "https://pub.raa.se/visa/objekt/lamning/aa11"},
     "geometry": square(17.6416, 59.8506, 17.6418, 59.8508)},
]


def remains_at(geometry):
    area = shape(geometry)
    return [remain for remain in REMAINS if shape(remain["geometry"]).intersects(area)]


def snapshot(tmp_path, missing=()):
    store = write_snapshot(tmp_path, layers=LAYERS | NATIONAL, missing=missing)
    manifest_path = tmp_path / "0380" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for layer_id, entry in manifest["layers"].items():
        entry["provider"] = layer_by_id("0380", layer_id).provider
    manifest_path.write_text(json.dumps(manifest))
    return type(store)(tmp_path)


@pytest.fixture
def store(tmp_path):
    return snapshot(tmp_path)


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


# --- likely permits --------------------------------------------------------------------------------------------

def test_bygglov_is_tested_against_the_detaljplan_inside_one(store):
    """Inside a detaljplan the bygglov is tested against the plan, by the kommun's byggnadsnämnd."""
    bygglov = permit(profile(store), "bygglov")
    assert "detaljplan" in bygglov["reason"].lower()
    assert bygglov["law"] == "PBL 9 kap."
    assert bygglov["authority"] == "Byggnadsnämnden, Uppsala kommun"
    assert bygglov["kind"] == "permit"


def test_bygglov_is_tested_against_pbl_outside_a_detaljplan(store):
    """Outside a detaljplan the bygglov is tested against PBL 2 and 8 kap."""
    assert "PBL 2 and 8 kap." in permit(profile(store, at=EMPTY_LOT), "bygglov")["reason"]


def test_a_nature_reserve_needs_a_dispens_from_its_regulations(store):
    """A naturreservat on the property gives a dispens from its regulations, decided by the dispens authority."""
    dispens = permit(profile(store), "Kungsängsängen")
    assert dispens["law"] == "MB 7 kap. 7 §"
    assert dispens["authority"] == "Länsstyrelsen"
    assert dispens["kind"] == "permit"


def test_a_natura2000_site_needs_a_tillstand_if_affected(store):
    """A Natura 2000 site gives a tillstånd from the länsstyrelse, needed if the site may be significantly affected."""
    tillstand = permit(profile(store), "Natura 2000")
    assert tillstand["law"] == "MB 7 kap. 28 a §"
    assert tillstand["authority"] == "Länsstyrelsen"
    assert "significantly" in tillstand["reason"]


def test_a_fornlamning_needs_a_tillstand(store):
    """A remain assessed as Fornlämning gives a tillstånd for ingrepp, decided by the länsstyrelse."""
    tillstand = permit(profile(store), "Uppsala 123:1")
    assert tillstand["law"] == "KML 2 kap. 12 §"
    assert tillstand["authority"] == "Länsstyrelsen"
    assert tillstand["kind"] == "permit"


def test_a_possible_fornlamning_asks_to_contact_the_lansstyrelse(store):
    """A Möjlig fornlämning asks the user to contact the länsstyrelse; it is not a permit."""
    contact = permit(profile(store), "Uppsala 586:1")
    assert contact["kind"] == "consideration"
    assert "länsstyrelse" in contact["title"].lower()


def test_other_cultural_remains_give_no_permit(store):
    """An Övrig kulturhistorisk lämning gives no permit."""
    assert not [p for p in profile(store)["permits"] if "L1941:4000" in p["title"]]


def test_a_national_interest_is_a_consideration_not_a_permit(store):
    """A national interest appears as something the prövning must not significantly harm."""
    consideration = permit(profile(store), "Fyrisån")
    assert consideration["kind"] == "consideration"
    assert "must not significantly harm" in consideration["title"]
    assert consideration["law"] == "MB 3:6"


def test_an_uncovered_place_has_no_permits(store):
    """Outside the pilot kommuner there are no permits and no sections."""
    result = profile(store, at=OUTSIDE)
    assert result["permits"] == []
    assert set(result["section_status"].values()) == {"not_covered"}


# --- none found vs. not reached --------------------------------------------------------------------------------

def test_sections_say_ok_when_their_sources_answered(store):
    """An answered section with nothing in it is 'ok' (none found), not unavailable."""
    result = profile(store, at=EMPTY_LOT)
    assert result["protected_areas"] == []
    assert result["section_status"]["protected_areas"] == "ok"


def test_a_section_is_unavailable_when_a_snapshot_is_missing(tmp_path):
    """A missing snapshot file makes its section unavailable rather than empty."""
    store = snapshot(tmp_path, missing=("natura2000",))
    assert profile(store)["section_status"]["natura2000"] == "unavailable"


def test_new_rows_name_their_source_and_date(store):
    """Protected areas, Natura 2000 sites, national interests and ancient remains name their source and date."""
    result = profile(store)
    assert result["protected_areas"][0]["source"] == "Naturvårdsverket"
    assert result["protected_areas"][0]["fetched"] == FETCHED
    assert result["natura2000"][0]["source"] == "Naturvårdsverket"
    assert all(row["source"].startswith("Boverket") for row in result["national_interests"])
    assert all(row["source"] == "Riksantikvarieämbetet" and row["fetched"] for row in result["ancient_remains"])


# --- the API ---------------------------------------------------------------------------------------------------

def test_profile_endpoint_carries_the_new_sections(store):
    """GET /api/place/profile returns the constraints and permits."""
    app = FastAPI()
    app.include_router(place_router.router, prefix="/api")
    app.dependency_overrides[place_router.get_place_store] = lambda: store
    app.dependency_overrides[place_router.get_property_lookup] = lambda: fake_property
    app.dependency_overrides[place_router.get_plan_registry] = lambda: registry
    app.dependency_overrides[place_router.get_ancient_remains_lookup] = lambda: remains_at
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u1")
    body = TestClient(app).get("/api/place/profile", params={"lat": PIN[0], "lon": PIN[1]}).json()
    assert body["protected_areas"][0]["name"] == "Kungsängsängen"
    assert any("Bygglov" in p["title"] for p in body["permits"])

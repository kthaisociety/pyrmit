"""place.permits.likely_permits, through the profile of the fake property with national layers and remains."""

import pytest

from glossary import GLOSSARY
from place.profile import build_profile
from tests.unit.place.snapshot import (
    EMPTY_LOT,
    OUTSIDE,
    PIN,
    fake_property,
    registry,
    remains_at,
    write_national_snapshot,
)


@pytest.fixture
def store(tmp_path):
    return write_national_snapshot(tmp_path)


def profile(store, at=PIN, **kwargs):
    return build_profile(*at, store=store, property_at=fake_property, plan_registry=registry,
                         ancient_remains_at=kwargs.pop("ancient_remains_at", remains_at), **kwargs)


def bygglov(result):
    return next(p for p in result["permits"] if p["key"] == "bygglov")


def permit(result, word):
    return next(p for p in result["permits"] if word.lower() in p["title"].lower())


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


def test_swedish_permits_keep_the_same_keys(store):
    """Language "sv" changes how the permits are worded, not which permits there are."""
    english, swedish = profile(store)["permits"], profile(store, language="sv")["permits"]
    assert [p["key"] for p in swedish] == [p["key"] for p in english]


def test_permit_reasons_are_in_swedish_when_asked(store):
    """With language "sv" every permit's reason is worded differently from its English one."""
    english, swedish = profile(store)["permits"], profile(store, language="sv")["permits"]
    assert all(sv["reason"] != en["reason"] for sv, en in zip(swedish, english))


def test_swedish_bygglov_title_carries_no_english_explanation(store):
    """In Swedish the bygglov is titled "Bygglov", with no English explanation in parentheses."""
    assert bygglov(profile(store, language="sv"))["title"] == "Bygglov"


def test_english_permit_reason_explains_a_glossary_term_on_first_use(store):
    """In English a glossary term in a permit's reason keeps its Swedish form, followed by its explanation."""
    reason = bygglov(profile(store, at=EMPTY_LOT))["reason"]
    assert f"förhandsbesked ({GLOSSARY['förhandsbesked']})" in reason

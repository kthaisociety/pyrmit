"""place.context: the pinned place written out for the agent, and the compact profile kept in the trace."""

from place.context import compact_profile, place_context
from tests.unit.place.snapshot import PIN


def test_the_place_context_says_this_is_the_place_of_the_question(profile_of):
    """The agent is told the pin is the place the question is about, so it does not ask where."""
    text = place_context(profile_of(*PIN)).lower()
    assert "pinned" in text
    assert "do not ask where" in text


def test_the_place_context_asks_to_check_a_different_place(profile_of):
    """The agent is told to ask which place is meant when the question names another one."""
    assert "names a different place" in place_context(profile_of(*PIN)).lower()


def test_the_place_context_lists_the_card(profile_of):
    """The place block lists the detaljplan status, zones, plans in progress, strandskydd and permits."""
    text = place_context(profile_of(*PIN))
    for fact in ("inside a detaljplan", "BCK", "Kungsängen 7:8 m.fl.", "strandskyddsdispens", "MB 7 kap. 7 §",
                 "Registry data, not a decision"):
        assert fact.lower() in text.lower()


def test_the_place_context_of_an_uncovered_place_says_so(profile_of):
    """Outside the pilot kommuner the block says the map does not cover the place."""
    assert "not cover" in place_context(profile_of(57.70, 11.97)).lower()


def test_the_compact_profile_keeps_everything_but_geometry(profile_of):
    """The compact profile has the same rows, without geometry."""
    profile = profile_of(*PIN)
    compact = compact_profile(profile)
    assert [row["ref"] for row in compact["plans"]] == [row["ref"] for row in profile["plans"]]
    assert "geometry" not in compact["property"]
    assert all("geometry" not in row for row in compact["zones"] + compact["ancient_remains"])

"""place.context: the pinned place written out for the agent, and the compact profile kept in the trace."""

from place.context import (
    CLOSING,
    compact_profile,
    permit_sections,
    place_context,
    question_with_place,
)
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


def test_the_place_context_names_the_addresses_on_the_property(profile_of):
    """The agent sees the pinned property's addresses, so it can tell when the question names another place."""
    profile = profile_of(*PIN)
    profile["property"]["addresses"] = ["Kungsgatan 63A", "Kungsgatan 63B"]
    assert "addresses on it: Kungsgatan 63A, Kungsgatan 63B" in place_context(profile)


def test_a_long_address_list_is_cut(profile_of):
    profile = profile_of(*PIN)
    profile["property"]["addresses"] = [f"Vägen {n}" for n in range(1, 21)]
    text = place_context(profile)
    assert "Vägen 8 and 12 more" in text and "Vägen 9," not in text


def test_the_question_follows_the_rule_to_ask_when_it_names_another_place(profile_of):
    """The rule comes again right before the question, where the model reads it last."""
    sent = question_with_place("Kan vi gräva en källare på Övre Slottsgatan 26B?", profile_of(*PIN))
    before_question = sent.split("\n\n")[0].splitlines()[-1]
    assert before_question == CLOSING and "ask" in CLOSING.lower() and "address" in CLOSING.lower()


def fake_law_text(law, section):
    """A corpus that knows two sections."""
    return {("MB", "7 kap. 7 §"): "[c:aa11bb22cc33dd44] Miljöbalk 7 kap. 7 § ... dispens ...",
            ("KML", "2 kap. 12 §"): "[c:bb22cc33dd44ee55] Kulturmiljölag 2 kap. 12 § ... tillstånd ..."}.get((law, section))


def test_permit_sections_are_the_sections_the_permits_cite(profile_of):
    """Each permit's law as (law, section), in card order, without chapters alone (PBL 9 kap.) and with ranges spread."""
    sections = permit_sections(profile_of(*PIN))
    assert ("MB", "7 kap. 7 §") in sections and ("KML", "2 kap. 12 §") in sections
    assert ("MB", "7 kap. 28 a §") in sections and ("MB", "3 kap. 6 §") in sections
    assert all(law != "PBL" for law, _ in sections)
    assert len(sections) == len(set(sections))


def test_a_range_of_sections_gives_each_section():
    profile = {"permits": [{"law": "MB 7 kap. 21-22 §"}, {"law": "3 kap. 6 § MB"}, {"law": "KML 2 kap."}]}
    assert permit_sections(profile) == [("MB", "7 kap. 21 §"), ("MB", "7 kap. 22 §"), ("MB", "3 kap. 6 §")]


def test_the_place_context_carries_the_statute_text_of_the_permits(profile_of):
    """The agent gets the cited sections' text with their chunk ids, so it need not look them up."""
    text = question_with_place("Kan jag bygga?", profile_of(*PIN), law_text=fake_law_text)
    assert "[c:aa11bb22cc33dd44] Miljöbalk 7 kap. 7 §" in text and "[c:bb22cc33dd44ee55]" in text
    assert text.index("Statute text") < text.index(CLOSING)


def test_without_a_law_lookup_the_context_has_no_statute_text(profile_of):
    assert "Statute text" not in place_context(profile_of(*PIN))


def test_the_place_context_gives_the_kommun_code(profile_of):
    """The kommun code is given, so the agent need not call find_kommun."""
    assert "kommun code 0380" in place_context(profile_of(*PIN))

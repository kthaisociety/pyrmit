"""place.context: the pinned place written out for the agent, and the compact profile kept in the trace."""

import pytest

from place.context import (
    ANSWERED,
    CLOSING,
    NO_PIN_HINT,
    compact_profile,
    permit_sections,
    place_context,
    question_with_place,
)
from place.profile import CorpusUnavailable, build_profile
from tests.unit.place.hosted import (
    ATLE,
    DESCRIPTION_ID,
    ELSEWHERE,
    MAP_ID,
    TILLAGG,
    TILLAGG_ID,
    amended_snapshot,
    every_document,
)
from tests.unit.place.snapshot import PIN, fake_property, no_remains


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


def test_the_rule_follows_a_choice_already_made_in_the_conversation():
    """After the user has picked a place, the next pinned question must not ask the same thing again."""
    assert "already settled" in CLOSING and "do not ask again" in CLOSING


def test_an_answer_to_the_agents_question_says_so_right_before_it(profile_of):
    """The user's clicked choice is marked as their answer, last before the message, with or without a pin."""
    for profile in (profile_of(*PIN), None):
        sent = question_with_place("Use Södermalm instead", profile, answered=True)
        assert sent.endswith(ANSWERED + "\n\nUse Södermalm instead")
    assert "pinned place" in ANSWERED and "do not ask" in ANSWERED.lower()


# --- the plans at the pin ---------------------------------------------------------------------------------------------

PAGE = "https://www.uppsala.se/detaljplan/?aktbeteckning="


def statement(store, corpus_documents=every_document):
    return place_context(build_profile(*PIN, store=store, corpus_documents=corpus_documents, property_at=fake_property,
                                       plan_registry=lambda code: [], ancient_remains_at=no_remains))


def line_of(text, ref):
    return next(line for line in text.splitlines() if line.startswith("- ") and f' {ref} "' in line)


def no_documents(doc_ids):
    return {}


def corpus_down(doc_ids):
    raise CorpusUnavailable("down")


@pytest.mark.parametrize("words", ["Detaljplan 0380-P2002/5", "Tillägg 0380-P2012/9", "Detaljplan 0380-P1990/3"])
def test_the_statement_gives_every_plan_its_type(tmp_path, words):
    assert words in statement(amended_snapshot(tmp_path))


@pytest.mark.parametrize("words", ["2002-01-09", f"plankarta {MAP_ID}", f"planbeskrivning {DESCRIPTION_ID}"])
def test_the_statement_gives_a_plan_its_date_and_documents(tmp_path, words):
    assert words in line_of(statement(amended_snapshot(tmp_path)), ATLE)


def test_the_statement_says_how_to_read_a_plan(tmp_path):
    """A plan with documents is stated with the call that reads them, plan map first."""
    assert f"read_plan(doc_ids=['{MAP_ID}', '{DESCRIPTION_ID}'])" in line_of(statement(amended_snapshot(tmp_path)), ATLE)


@pytest.mark.parametrize("corpus_documents", [no_documents, corpus_down])
@pytest.mark.parametrize("words", ["Del av Atle", "Text not read", f"{PAGE}{ATLE}"])
def test_a_plan_without_text_is_named_as_not_read_with_the_kommuns_link(tmp_path, corpus_documents, words):
    """No document in the corpus, or a corpus out of reach: the plan is named, not read, with the kommun's link."""
    assert words in line_of(statement(amended_snapshot(tmp_path), corpus_documents), ATLE)


def test_a_plan_without_text_is_given_no_call_that_reads_it(tmp_path):
    assert "read_plan" not in line_of(statement(amended_snapshot(tmp_path), no_documents), ATLE)


def test_an_install_without_a_link_table_states_the_plans_as_not_read(tmp_path):
    """Before the link table has reached this install the plans are stated as not read, without a failure."""
    assert "Text not read" in line_of(statement(amended_snapshot(tmp_path, links=False)), ATLE)


def test_a_plan_without_a_link_says_so():
    profile_plan = {"kind": "plan", "ref": "0380-1", "name": "Gammal", "date": None, "url": None}
    profile = {"point": {"lat": 59.8, "lon": 17.6}, "covered": True, "kommun": {"code": "0380", "name": "Uppsala"},
               "property": None, "property_status": "none", "detaljplan": "inside", "plans": [profile_plan], "zones": [],
               "pending_plans": [], "protected_areas": [], "natura2000": [], "national_interests": [], "ancient_remains": [],
               "section_status": dict.fromkeys(("protected_areas", "natura2000", "national_interests", "ancient_remains"), "ok"),
               "strandskydd": {"reason": "", "note": ""}, "permits": [], "notes": []}
    assert "no link to it is known" in line_of(place_context(profile), "0380-1")


def test_an_amendment_is_read_together_with_the_plan_it_amends(tmp_path):
    """The amendment's line says which plan it goes with."""
    text = statement(amended_snapshot(tmp_path, addition_note=f"Gäller tillsammans med {ATLE}"))
    assert f"Read together with {ATLE}" in line_of(text, TILLAGG)


def test_the_call_for_an_amendment_reads_it_and_then_the_plan_it_amends(tmp_path):
    text = statement(amended_snapshot(tmp_path, addition_note=f"Gäller tillsammans med {ATLE}"))
    assert f"read_plan(doc_ids=['{TILLAGG_ID}', '{MAP_ID}', '{DESCRIPTION_ID}'])" in line_of(text, TILLAGG)


def test_a_named_plan_without_text_is_stated_as_not_read_on_the_amendment(tmp_path):
    text = statement(amended_snapshot(tmp_path, addition_note="Gäller tillsammans med 03-89:387"))
    assert "03-89:387 (text not read)" in line_of(text, TILLAGG)


def test_a_plan_named_by_an_amendment_may_lie_outside_the_pin(tmp_path):
    text = statement(amended_snapshot(tmp_path, addition_note=f"Läses tillsammans med {ELSEWHERE}"))
    assert f"Read together with {ELSEWHERE}" in line_of(text, TILLAGG)


# --- a question without a pin, and a general question ------------------------------------------------------------------

@pytest.mark.parametrize("words", ["offer_pin", "before any search", "general question"])
def test_the_no_pin_hint_asks_for_a_pin_on_a_specific_question(words):
    """Without a pin a specific question gets a request for one before any search, a general one an offer."""
    assert words in NO_PIN_HINT


def test_a_pinned_general_question_is_told_to_stay_general(tmp_path):
    """The pinned block leaves room for a general question."""
    assert "general question" in statement(amended_snapshot(tmp_path)).lower()

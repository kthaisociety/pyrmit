"""The claim check puts each claim of an answer to the decision model with the sources it cites, flags what they do
not back, never rewrites the answer, and never costs the answer when it fails. The model is a scripted fake
(PCR-0011)."""

import time

import pytest

from agentic.claim_check import (
    Claim,
    ClaimCheck,
    Support,
    _sentences,
    _stretches,
    check_claims,
)
from localrag.index import chunk_text
from tests.unit.agentic.claims import (
    CHUNKS,
    FEE,
    FEE_UNCITED,
    FEE_UNSUPPORTED,
    HOUSE,
    HOUSE_SUPPORTED,
    RAW,
    A,
    B,
    get_chunk,
)

ADVICE = "Contact the kommun early to discuss your plans"


C_LAW = "e" * 16
LAW_CHUNK = {"chunk_id": C_LAW, "kind": "law", "title": "PBL", "header": "PBL 9 kap. 4 §",
             "text": "Plan- och bygglag (2010:900), 9 kap. 4 § (9 kap. Bygglov)\nBygglov krävs för nybyggnad av en byggnad."}


def check(answer: str = RAW, get=get_chunk, **kwargs) -> ClaimCheck:
    return check_claims(answer, get, **kwargs)


def as_dicts(result: ClaimCheck) -> list[dict]:
    return result.as_event()["claims"]


# --- cited claims ---------------------------------------------------------------------------------------------

def test_a_claim_its_source_states_is_supported(jev):
    """A claim the model says its cited source states is supported, with the source sentence that states it."""
    jev(supported={HOUSE: 0.9})
    assert as_dicts(check())[0] == HOUSE_SUPPORTED


def test_a_claim_its_source_does_not_state_is_unsupported(jev):
    """A claim the model says its cited source does not state is flagged unsupported, with the chunk it cites."""
    jev(supported={HOUSE: 0.9, FEE: 0.1})
    assert as_dicts(check())[1] == FEE_UNSUPPORTED


def test_the_model_gets_the_claim_and_the_full_text_of_its_source(jev):
    """Each claim is put to the model with the full text of the chunks it cites."""
    fake = jev(supported={HOUSE: 0.9})
    check()
    [state] = [state for state, _ in fake.calls if state.get("claim") == HOUSE]
    assert state == {"claim": HOUSE, "sources": [chunk_text(CHUNKS[A])]}


def test_a_claim_is_judged_against_its_own_citations_only(jev):
    """The fee is judged against B, which it cites, not against A, which the house rule cites."""
    fake = jev()
    check()
    [state] = [state for state, _ in fake.calls if state.get("claim") == FEE]
    assert state["sources"] == [chunk_text(CHUNKS[B])]


def test_every_cited_claim_is_put_to_the_model(jev):
    fake = jev()
    check()
    assert sorted(fake.claims_asked()) == sorted([HOUSE, FEE])


def test_a_claim_is_found_after_a_list_marker_and_a_bold_label(jev):
    """The claim's text is the claim alone, so it can be marked in the answer: no "- **Answer:**" before it."""
    jev(supported={HOUSE: 0.9})
    result = check(f"- **Answer:** {HOUSE} [c:{A}].")
    assert [claim.text for claim in result.claims] == [HOUSE]


def test_a_citation_backs_all_the_text_before_it_on_its_line(jev):
    """The agent often states a rule, quotes it and cites after the full stop: the citation backs both sentences."""
    rule = f"{HOUSE}. PBL 9 kap. 4 § says it applies to every new building"
    fake = jev(supported={rule: 0.9})
    result = check(f"- {rule}. [c:{A}]")
    assert (fake.claims_asked(), [claim.verdict for claim in result.claims]) == ([rule], ["supported"])


def test_a_sentence_after_the_last_citation_is_judged_on_its_own(jev):
    fake = jev(supported={HOUSE: 0.9}, needs_source={FEE: 0.9})
    result = check(f"{HOUSE} [c:{A}]. {FEE}.")
    assert (fake.claims_asked(), [claim.text for claim in result.claims]) == ([HOUSE], [HOUSE, FEE])


def test_the_supporting_sentence_is_from_the_source_text_not_its_title(jev):
    """A statute chunk's title line ("Plan- och bygglag (2010:900), ...") is never offered as a supporting sentence."""
    fake = jev(supported={HOUSE: 0.9})
    check(f"{HOUSE} [c:{C_LAW}].", get=lambda chunk_id: LAW_CHUNK)
    [questions] = [questions for state, questions in fake.calls if "sentence" in questions]
    assert list(questions["sentence"]["criteria"].values()) == ["Bygglov krävs för nybyggnad av en byggnad."]


def test_a_law_reference_does_not_cut_the_claim(jev):
    """ "PBL 4 kap. 2 § ..." is one claim: an abbreviation before a number is no sentence end."""
    claim = "Enligt PBL 4 kap. 2 § krävs en detaljplan för ny sammanhållen bebyggelse"
    fake = jev(supported={claim: 0.9})
    check(f"{claim} [c:{A}].")
    assert fake.claims_asked() == [claim]


def test_a_claim_whose_source_cannot_be_read_is_uncited(jev):
    """A miscopied citation id leaves nothing to judge against: the claim is flagged uncited, the rest is checked."""
    jev(supported={HOUSE: 0.9})
    result = check(f"{HOUSE} [c:{A}]. {FEE} [c:{'d' * 16}].")
    assert (result.status, as_dicts(result)) == ("checked", [HOUSE_SUPPORTED, FEE_UNCITED])


# --- sentences without a citation -----------------------------------------------------------------------------

def test_an_uncited_statement_of_fact_is_flagged_uncited(jev):
    """A sentence with no citation that the model says needs a source is flagged uncited."""
    jev(supported={HOUSE: 0.9}, needs_source={FEE: 0.9})
    assert as_dicts(check(f"{HOUSE} [c:{A}]. {FEE}."))[1] == FEE_UNCITED


def test_uncited_advice_is_not_flagged(jev):
    """A sentence with no citation that the model says needs none (advice, a summary) is left out."""
    jev(supported={HOUSE: 0.9}, needs_source={ADVICE: 0.1})
    assert as_dicts(check(f"{HOUSE} [c:{A}]. {ADVICE}.")) == [HOUSE_SUPPORTED]


def test_all_uncited_sentences_go_in_one_call(jev):
    fake = jev()
    check(f"{FEE}. {ADVICE}.")
    assert len(fake.calls) == 1


def test_an_answer_without_claims_has_none(jev):
    fake = jev()
    assert (check("Ja.").claims, fake.calls) == ([], [])


# --- the pinned place's data as a source ------------------------------------------------------------------------

PLACE = "Property: Uppsala Kvarngärdet 27:2. Protected areas: Vattenskyddsområde Uppsala- och Vattholmaåsarna."
SITE_FACT = "The property lies in the water protection area of Uppsala- och Vattholmaåsarna"


def test_a_claim_is_judged_against_its_chunks_and_the_place_data(jev):
    """The agent states site facts from the pinned place's data and cites the statute: both are the claim's sources."""
    fake = jev(supported={HOUSE: 0.9})
    check(f"{HOUSE} [c:{A}].", place=PLACE)
    [state] = [state for state, _ in fake.calls if state.get("claim") == HOUSE]
    assert state["sources"] == [chunk_text(CHUNKS[A]), PLACE]


def test_an_uncited_site_fact_the_place_data_backs_is_not_flagged(jev):
    jev(needs_source={SITE_FACT: 0.9}, place_backs={SITE_FACT: 0.9})
    assert check(f"{SITE_FACT}.", place=PLACE).claims == []


def test_an_uncited_site_fact_the_place_data_does_not_back_is_flagged(jev):
    jev(needs_source={SITE_FACT: 0.9}, place_backs={SITE_FACT: 0.1})
    assert [claim.verdict for claim in check(f"{SITE_FACT}.", place=PLACE).claims] == ["uncited"]


def test_without_a_pin_the_place_is_not_asked_about(jev):
    fake = jev(needs_source={SITE_FACT: 0.9})
    check(f"{SITE_FACT}.")
    [(_, questions)] = fake.calls
    assert not any(name.startswith("place_") for name in questions)


# --- speed and failure ----------------------------------------------------------------------------------------

def test_the_answer_is_not_rewritten(jev):
    """The check only judges: it returns verdicts and has no rewritten answer."""
    jev(supported={HOUSE: 0.9})
    assert not hasattr(check(), "answer")


def test_the_claims_are_judged_in_parallel(jev):
    """Two claims each taking 0.5 s are judged in well under 1 s together."""
    jev(supported={HOUSE: 0.9}, delay=0.5)
    started = time.time()
    check()
    assert time.time() - started < 0.9


def test_a_model_error_fails_the_check(jev):
    jev(error=RuntimeError("model down"))
    assert check() == ClaimCheck(status="failed")


def test_one_failed_call_costs_only_its_own_claim(jev):
    """A call that fails (a rate limit, a broken reply) leaves its claim out; the other claims keep their verdicts."""
    jev(supported={HOUSE: 0.9}, fail_on=FEE)
    result = check()
    assert (result.status, as_dicts(result)) == ("checked", [HOUSE_SUPPORTED])


def test_a_check_over_its_time_fails(jev):
    jev(delay=2.0)
    assert check(timeout_s=0.2).status == "failed"


def test_a_check_over_its_time_does_not_wait_for_the_model(jev):
    jev(delay=2.0)
    started = time.time()
    check(timeout_s=0.2)
    assert time.time() - started < 1.0


# --- what is saved --------------------------------------------------------------------------------------------

def test_a_check_is_saved_as_its_verdicts_and_supporting_sentences():
    result = ClaimCheck(status="checked", claims=[
        Claim(text=HOUSE, verdict="supported", chunk_ids=[A],
              supporting=[Support(chunk_id=A, sentence="Bygglov krävs för nybyggnad av en byggnad.")]),
        Claim(text=FEE, verdict="unsupported", chunk_ids=[B]),
    ])
    assert result.as_event() == {"status": "checked", "claims": [HOUSE_SUPPORTED, FEE_UNSUPPORTED]}


def test_a_failed_check_is_saved_as_failed():
    assert ClaimCheck(status="failed").as_event() == {"status": "failed", "claims": []}


@pytest.mark.parametrize("probability, verdict", [(0.5, "supported"), (0.49, "unsupported")])
def test_a_claim_counts_as_supported_from_an_even_chance(jev, probability, verdict):
    jev(supported={HOUSE: probability})
    assert check(f"{HOUSE} [c:{A}].").claims[0].verdict == verdict


# --- what a claim is, on realistic agent markdown (review of #105) ----------------------------------------------------

def stretches(answer: str) -> list[tuple[str, bool]]:
    return [(stretch.text, bool(stretch.chunk_ids)) for stretch in _stretches(answer)]


def test_a_citation_mid_sentence_backs_the_whole_sentence():
    """ "Strandskyddet gäller [c] 100 meter ..." is one cited claim, not a cited head and an uncited tail."""
    assert stretches(f"Strandskyddet gäller [c:{A}] 100 meter från strandlinjen vid havet.") == [
        ("100 meter från strandlinjen vid havet", True)]


def test_jev_reads_the_whole_sentence_around_a_mid_sentence_citation():
    [stretch] = _stretches(f"Strandskyddet gäller [c:{A}] 100 meter från strandlinjen.")
    assert stretch.judged == "Strandskyddet gäller 100 meter från strandlinjen"


def test_bold_cut_by_a_citation_is_not_part_of_the_marked_text():
    """Marking a text that opens bold it does not close would show literal ** in the answer."""
    [(text, _)] = stretches(f"**Byggnadshöjden får vara högst [c:{A}] 7,5 meter enligt planen.**")
    assert "*" not in text


@pytest.mark.parametrize("line", [f"> Det krävs bygglov för en ny byggnad [c:{A}].",
                                  f"1) Det krävs bygglov för en ny byggnad [c:{A}]."])
def test_a_quote_or_numbered_list_marker_is_not_part_of_the_claim(line):
    assert stretches(line) == [("Det krävs bygglov för en ny byggnad", True)]


def test_an_abbreviation_does_not_end_a_sentence():
    assert stretches(f"Enligt bl.a. Boverket krävs bygglov för ett nytt hus [c:{A}].") == [
        ("Enligt bl.a. Boverket krävs bygglov för ett nytt hus", True)]


def test_a_cited_repeat_of_an_uncited_sentence_is_judged_as_cited():
    """The answer-first summary often repeats a later, cited sentence: the cited one is the one judged."""
    assert stretches(f"Bygglov krävs för ett nytt hus.\n- Bygglov krävs för ett nytt hus [c:{A}].") == [
        ("Bygglov krävs för ett nytt hus", True)]


def test_a_wrapped_statute_line_is_one_sentence():
    """Hard-wrapped statute text gives whole sentences as supporting sentences, and only the title line is dropped."""
    text = "Plan- och bygglag (2010:900), 9 kap. 2 §\nDet krävs bygglov för\nnybyggnad av ett hus.\nEnligt miljöbalken (1998:808) gäller också annat här."
    assert _sentences(text) == ["Det krävs bygglov för nybyggnad av ett hus.",
                                "Enligt miljöbalken (1998:808) gäller också annat här."]


def test_the_supporting_sentence_names_the_chunk_the_id_resolved_to(jev):
    """A shortened or miscopied id the chat resolves gets the resolved chunk's id, which the source panel looks up."""
    jev(supported={HOUSE: 0.9})
    result = check(f"{HOUSE} [c:{A[:10]}].", get=lambda chunk_id: CHUNKS[A] if A.startswith(chunk_id) else None)
    assert (result.claims[0].chunk_ids, result.claims[0].supporting[0].chunk_id) == ([A], A)

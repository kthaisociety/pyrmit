"""The claim check puts each claim of an answer to the decision model with the sources it cites, flags what they do
not back, never rewrites the answer, and never costs the answer when it fails. The model is a scripted fake
(PCR-0011)."""

import time

import pytest

from agentic import claim_check
from agentic.claim_check import (
    CheckOptions,
    Claim,
    ClaimCheck,
    Support,
    check_claims,
)
from localrag.index import chunk_text
from tests.unit.agentic.claims import (
    CHUNKS,
    EARLIER,
    FEE,
    FEE_UNCITED,
    FEE_UNSUPPORTED,
    HOUSE,
    HOUSE_SUPPORTED,
    RAW,
    TWO_SENTENCES,
    A,
    B,
    C,
    get_chunk,
)

ADVICE = "Contact the kommun early to discuss your plans"
HEDGE = "Det kan krävas bygglov för en altan"


C_LAW = "e" * 16
LAW_CHUNK = {"chunk_id": C_LAW, "kind": "law", "title": "PBL", "header": "PBL 9 kap. 4 §",
             "text": "Plan- och bygglag (2010:900), 9 kap. 4 § (9 kap. Bygglov)\nBygglov krävs för nybyggnad av en byggnad."}


def check(answer: str = RAW, get=get_chunk, **kwargs) -> ClaimCheck:
    return check_claims(answer, get, **kwargs)


def as_dicts(result: ClaimCheck) -> list[dict]:
    return result.as_event()["claims"]


def verdicts(result: ClaimCheck) -> dict[str, str]:
    return {claim.text: claim.verdict for claim in result.claims}


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
    quote = "PBL 9 kap. 4 § says it applies to every new building"
    fake = jev(supported={HOUSE: 0.9, quote: 0.9})
    result = check(f"- {HOUSE}. {quote}. [c:{A}]")
    assert (sorted(fake.claims_asked()), [claim.verdict for claim in result.claims]) == (sorted([HOUSE, quote]), ["supported"])


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
    result = check()
    assert (result.status, result.claims) == ("failed", [])


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
    return [(stretch.text, bool(stretch.chunk_ids)) for stretch in claim_check.stretches(answer)]


def test_a_citation_mid_sentence_backs_the_whole_sentence():
    """ "Strandskyddet gäller [c] 100 meter ..." is one cited claim, not a cited head and an uncited tail."""
    assert stretches(f"Strandskyddet gäller [c:{A}] 100 meter från strandlinjen vid havet.") == [
        ("100 meter från strandlinjen vid havet", True)]


def test_jev_reads_the_whole_sentence_around_a_mid_sentence_citation():
    [stretch] = claim_check.stretches(f"Strandskyddet gäller [c:{A}] 100 meter från strandlinjen.")
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


@pytest.mark.parametrize("cited", [f"[FBL 3 kap. 1 §][c:{A}]", f"[FBL 3 kap. 1 §] [c:{A}]", f"[c:{A}][FBL 3 kap. 1 §]"])
def test_a_law_label_in_its_own_brackets_beside_the_citation_keeps_the_claim(cited):
    """The agent sometimes writes the statute as its own bracket group next to the citation; the claim was dropped."""
    assert stretches(f"Avstyckning kräver en godtagbar vatten- och avloppslösning. {cited}") == [
        ("Avstyckning kräver en godtagbar vatten- och avloppslösning", True)]


def test_a_markdown_link_after_a_citation_is_not_taken_for_a_label():
    assert stretches(f"Bygglov krävs för ett nytt hus [c:{A}] [läs mer](https://x.se).")[0] == (
        "Bygglov krävs för ett nytt hus", True)


def test_a_wrapped_statute_line_is_one_sentence(jev):
    """Hard-wrapped statute text gives whole sentences as supporting sentences, and only the title line is dropped."""
    text = "Plan- och bygglag (2010:900), 9 kap. 2 §\nDet krävs bygglov för\nnybyggnad av ett hus.\nEnligt miljöbalken (1998:808) gäller också annat här."
    fake = jev(supported={HOUSE: 0.9})
    check(f"{HOUSE} [c:{C_LAW}].", get=lambda chunk_id: {**LAW_CHUNK, "text": text})
    [questions] = [questions for state, questions in fake.calls if "sentence" in questions]
    assert list(questions["sentence"]["criteria"].values()) == [
        "Det krävs bygglov för nybyggnad av ett hus.", "Enligt miljöbalken (1998:808) gäller också annat här."]


def test_the_supporting_sentence_names_the_chunk_the_id_resolved_to(jev):
    """A shortened or miscopied id the chat resolves gets the resolved chunk's id, which the source panel looks up."""
    jev(supported={HOUSE: 0.9})
    result = check(f"{HOUSE} [c:{A[:10]}].", get=lambda chunk_id: CHUNKS[A] if A.startswith(chunk_id) else None)
    assert (result.claims[0].chunk_ids, result.claims[0].supporting[0].chunk_id) == ([A], A)


def test_the_claims_are_checked_on_the_users_own_key(jev, monkeypatch):
    """Every decision model call, each in the claim check's thread pool, runs on the key of the request (#108)."""
    import llm

    fake = jev(supported={HOUSE: 0.9})
    keys = []

    def asking(state, questions, timeout_s=20.0):
        keys.append(llm.openrouter_api_key())
        return fake(state, questions, timeout_s)

    monkeypatch.setattr(claim_check, "ask_decision_model", asking)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-shared")
    with llm.openrouter_key("sk-or-user"):
        check_claims(RAW, get_chunk)
    assert len(keys) == 2 and set(keys) == {"sk-or-user"}


# --- the check's options (CheckOptions) -------------------------------------------------------------------------

def test_a_lower_support_threshold_counts_a_weaker_yes_as_supported(jev):
    """With supported_at lowered, a claim Jev backs below the live threshold but above the new one is supported."""
    jev(supported={HOUSE: 0.4})
    result = check(f"{HOUSE} [c:{A}].", options=CheckOptions(supported_at=0.3))
    assert verdicts(result) == {HOUSE: "supported"}


def test_a_higher_support_threshold_counts_a_weak_yes_as_unsupported(jev):
    """With supported_at raised, a claim Jev backs above the live threshold but below the new one is unsupported."""
    jev(supported={HOUSE: 0.6})
    result = check(f"{HOUSE} [c:{A}].", options=CheckOptions(supported_at=0.7))
    assert verdicts(result) == {HOUSE: "unsupported"}


def test_the_support_threshold_also_sets_when_the_place_backs_an_uncited_sentence(jev):
    """With supported_at lowered, an uncited sentence the place data backs above the new threshold is not flagged."""
    jev(needs_source={FEE: 0.9}, place_backs={FEE: 0.4})
    result = check(f"{HOUSE} [c:{A}]. {FEE}.", place=PLACE, options=CheckOptions(supported_at=0.3))
    assert verdicts(result).get(FEE) != "uncited"


def test_the_support_threshold_leaves_when_a_sentence_needs_a_source_unchanged(jev):
    """With supported_at lowered, an uncited sentence Jev says needs a source below the live 0.5 is still not
    flagged: the threshold sets when sources back a claim, not when a sentence needs one."""
    jev(needs_source={FEE: 0.4})
    result = check(f"{HOUSE} [c:{A}]. {FEE}.", options=CheckOptions(supported_at=0.3))
    assert verdicts(result).get(FEE) != "uncited"


def test_a_cited_hedge_is_skipped_when_hedges_are_skipped(jev):
    """With skip_hedges, a cited hedge is kept in the result with verdict "skipped", whatever its sources say."""
    jev(supported={}, hedge={HEDGE: 0.9})
    result = check(f"{HEDGE} [c:{A}].", options=CheckOptions(skip_hedges=True))
    assert verdicts(result) == {HEDGE: "skipped"}


def test_an_uncited_hedge_is_skipped_not_flagged_when_hedges_are_skipped(jev):
    """With skip_hedges, an uncited hedge that would need a source is kept with verdict "skipped", not "uncited"."""
    jev(supported={HOUSE: 0.9}, needs_source={HEDGE: 0.9}, hedge={HEDGE: 0.9})
    result = check(f"{HOUSE} [c:{A}]. {HEDGE}.", options=CheckOptions(skip_hedges=True))
    assert verdicts(result)[HEDGE] == "skipped"


def test_a_claim_that_is_no_hedge_is_still_judged_when_hedges_are_skipped(jev):
    """With skip_hedges, a claim Jev does not take for a hedge is judged against its sources as before."""
    jev(supported={HOUSE: 0.9}, hedge={})
    result = check(f"{HOUSE} [c:{A}].", options=CheckOptions(skip_hedges=True))
    claim = result.claims[0]
    assert claim.verdict == "supported" and claim.supporting


def test_a_skipped_claim_is_in_the_event(jev):
    """A skipped hedge goes into the claim_check event with its verdict, like every other claim."""
    jev(supported={}, hedge={HEDGE: 0.9})
    event = check(f"{HEDGE} [c:{A}].", options=CheckOptions(skip_hedges=True)).as_event()
    assert [claim["verdict"] for claim in event["claims"]] == ["skipped"]


def test_per_sentence_puts_only_the_citing_sentence_to_its_sources(jev):
    """With per_sentence, the claim judged against the cited chunk is the sentence holding the citation only."""
    fake = jev(supported={HOUSE: 0.9})
    check(TWO_SENTENCES, options=CheckOptions(per_sentence=True))
    assert fake.claims_asked() == [HOUSE]


def test_per_sentence_judges_the_earlier_sentences_as_uncited(jev):
    """With per_sentence, a sentence before the citing one is judged as a sentence without a citation."""
    jev(supported={HOUSE: 0.9}, needs_source={EARLIER: 0.9})
    result = check(TWO_SENTENCES, options=CheckOptions(per_sentence=True))
    assert verdicts(result) == {EARLIER: "uncited", HOUSE: "supported"}


def test_the_core_question_asks_jev_something_other_than_the_strict_one(jev):
    """With question "core", the support question put to Jev differs from the live strict one."""
    strict = jev(supported={HOUSE: 0.9})
    check(f"{HOUSE} [c:{A}].")
    core = jev(supported={HOUSE: 0.9})
    check(f"{HOUSE} [c:{A}].", options=CheckOptions(question="core"))
    assert core.calls and core.calls[0][1].get("supported") != strict.calls[0][1]["supported"]


def test_a_failed_call_with_options_costs_only_its_own_claims(jev):
    """With options set, a failed call leaves out only the claims it was about; the check still succeeds."""
    jev(supported={HOUSE: 0.4, FEE: 0.9}, fail_on=FEE)
    result = check(f"{HOUSE} [c:{A}]. {FEE} [c:{C}].", options=CheckOptions(supported_at=0.3))
    assert result.status == "checked" and verdicts(result) == {HOUSE: "supported"}


# --- the check's own time and calls ---------------------------------------------------------------------------------

def test_the_check_counts_the_decision_model_calls_it_made(jev):
    """The check's result says how many decision model calls it started."""
    fake = jev()
    assert check().calls == len(fake.calls) > 0


def test_the_check_says_how_long_it_took(jev):
    """The check's result says how many seconds the whole check took."""
    jev(delay=0.05)
    assert 0.05 <= check().seconds < 5


def test_a_failed_check_still_counts_its_calls(jev):
    """A check whose every call failed reports the calls it started."""
    jev(error=RuntimeError("down"))
    result = check()
    assert (result.status, result.calls > 0) == ("failed", True)


# --- a better check: each sentence, additions, levels (CheckOptions) -------------------------------------------------

HOUSE_AND_FEE = f"{HOUSE}. {FEE}"  # one claim of two sentences
TWO_SENTENCE_CLAIM = f"{HOUSE_AND_FEE} [c:{A}]."
REFERENCE = "PBL 9 kap. 4 §"
WITH_REFERENCE = f"{HOUSE}. {REFERENCE} [c:{A}]."
EACH, ADDITIONS, LEVELS = CheckOptions(each_sentence=True), CheckOptions(additions=True), CheckOptions(levels=True)


def claim_of(answer: str, options: CheckOptions):
    """The check's one cited claim of `answer`."""
    (claim,) = [claim for claim in check_claims(answer, get_chunk, options=options).claims if claim.chunk_ids]
    return claim


# --- every sentence of a claim against the claim's sources ----------------------------------------------------------

def test_a_claim_fails_when_its_sources_do_not_back_one_of_its_sentences(jev):
    """Judged sentence by sentence, a claim is unsupported when one sentence that states a fact is not backed."""
    jev(supported={HOUSE: 0.9, HOUSE_AND_FEE: 0.9})
    assert claim_of(TWO_SENTENCE_CLAIM, EACH).verdict == "unsupported"


def test_a_claim_names_the_sentences_its_sources_do_not_back(jev):
    """The claim lists the sentences that were not backed, as they stand in its text."""
    jev(supported={HOUSE: 0.9})
    assert claim_of(TWO_SENTENCE_CLAIM, EACH).unbacked == [FEE]


def test_a_claim_is_supported_when_every_sentence_is_backed(jev):
    """A claim whose every sentence the sources back is supported and names no unbacked sentence."""
    jev(supported={HOUSE: 0.9, FEE: 0.9})
    claim = claim_of(TWO_SENTENCE_CLAIM, EACH)
    assert (claim.verdict, claim.unbacked) == ("supported", [])


def test_a_sentence_that_states_no_fact_does_not_fail_the_claim(jev):
    """A sentence that is only a legal reference or a fragment never fails the claim it stands in."""
    jev(supported={HOUSE: 0.9}, fact={REFERENCE: 0.1})
    claim = claim_of(WITH_REFERENCE, EACH)
    assert (claim.verdict, claim.unbacked) == ("supported", [])


def test_the_sentences_of_a_claim_are_judged_against_the_claims_own_sources(jev):
    """Each sentence goes to the decision model with the full text of the chunks the claim cites."""
    fake = jev(supported={HOUSE: 0.9})
    claim_of(TWO_SENTENCE_CLAIM, EACH)
    sources = {state["claim"]: state["sources"] for state, questions in fake.calls if "supported" in questions}
    assert (set(sources) >= {HOUSE, FEE}, all("Bygglov krävs" in " ".join(texts) for texts in sources.values())) == (True, True)


# --- what the claim adds to its sources -----------------------------------------------------------------------------

def test_a_backed_claim_that_adds_something_is_unsupported(jev):
    """With the additions question a claim its sources back is unsupported when it says something they do not state."""
    jev(supported={HOUSE: 0.9}, addition={HOUSE: 0.9})
    assert claim_of(f"{HOUSE} [c:{A}].", ADDITIONS).verdict == "unsupported"


def test_a_backed_claim_that_adds_nothing_is_supported(jev):
    """With the additions question, asked in the claim's own call, a backed claim that adds nothing stays supported."""
    fake = jev(supported={HOUSE: 0.9}, addition={HOUSE: 0.1})
    verdict = claim_of(f"{HOUSE} [c:{A}].", ADDITIONS).verdict
    assert (verdict, [sorted(name for name in questions if name in ("supported", "addition"))
                      for state, questions in fake.calls]) == ("supported", [["addition", "supported"]])


def test_the_additions_question_is_put_to_each_sentence_of_a_claim(jev):
    """Judged by sentence, a backed sentence that adds something is one the sources do not back."""
    jev(supported={HOUSE: 0.9, FEE: 0.9}, addition={FEE: 0.9})
    assert claim_of(TWO_SENTENCE_CLAIM, CheckOptions(each_sentence=True, additions=True)).unbacked == [FEE]


# --- a level for a partly supported claim ---------------------------------------------------------------------------

def test_a_supported_claim_has_the_level_full(jev):
    """With levels on, a supported claim is backed in full."""
    jev(supported={HOUSE: 0.9})
    assert claim_of(f"{HOUSE} [c:{A}].", LEVELS).level == "full"


def test_an_unsupported_claim_whose_sources_state_part_of_it_is_partly_backed(jev):
    """With levels on, a claim whose sources state part of it is "partly" and keeps the verdict "unsupported", so it
    is flagged as before."""
    jev(supported={HOUSE: 0.1}, part={HOUSE: 0.8})
    claim = claim_of(f"{HOUSE} [c:{A}].", LEVELS)
    assert (claim.verdict, claim.level) == ("unsupported", "partly")


def test_an_unsupported_claim_whose_sources_state_none_of_it_has_the_level_none(jev):
    """With levels on, an unsupported claim is "none" when its sources state no part of it."""
    jev(supported={HOUSE: 0.1}, part={HOUSE: 0.1})
    assert claim_of(f"{HOUSE} [c:{A}].", LEVELS).level == "none"


def test_a_claim_judged_by_sentence_is_partly_backed_when_some_sentences_are(jev):
    """With levels and each sentence judged, a claim with one backed and one unbacked sentence is "partly"."""
    jev(supported={HOUSE: 0.9})
    assert claim_of(TWO_SENTENCE_CLAIM, CheckOptions(each_sentence=True, levels=True)).level == "partly"


def test_a_claim_judged_by_sentence_has_the_level_none_when_no_sentence_is_backed(jev):
    """With levels and each sentence judged, a claim none of whose sentences is backed is "none"."""
    jev()
    assert claim_of(TWO_SENTENCE_CLAIM, CheckOptions(each_sentence=True, levels=True)).level == "none"


def test_a_claim_whose_sources_cannot_be_read_has_no_level(jev):
    """With levels on, only a claim judged against its sources gets a level: an "uncited" one (no readable cited
    chunk) has none."""
    jev(supported={HOUSE: 0.9})
    claims = check_claims(f"{HOUSE} [c:{A}]. {FEE} [c:{'9' * 16}].", get_chunk, options=LEVELS).claims
    assert [(claim.verdict, claim.level) for claim in claims] == [("supported", "full"), ("uncited", None)]


def test_the_saved_event_carries_the_level_and_the_unbacked_sentences(jev):
    """The claim_check event holds each claim's level and unbacked sentences."""
    jev(supported={HOUSE: 0.9})
    event = check_claims(TWO_SENTENCE_CLAIM, get_chunk, options=CheckOptions(each_sentence=True, levels=True)).as_event()
    assert [(claim["level"], claim["unbacked"]) for claim in event["claims"]] == [("partly", [FEE])]

"""The claim check judges every factual claim of an answer against its cited sources, rewrites the answer once when
some are not backed, and never costs the answer when it fails. The model is a scripted fake (PCR-0011)."""

import time

import pytest

from agentic.claim_check import (
    Claim,
    ClaimCheck,
    Support,
    VerifiedAnswer,
    verify_answer,
)
from tests.unit.agentic.claims import (
    CHUNKS,
    FEE,
    FEE_CITING_B,
    FEE_SUPPORTED,
    FEE_UNCITED,
    FEE_UNSUPPORTED,
    HOUSE,
    HOUSE_SUPPORTED,
    RAW,
    REVISED,
    SHORTENED,
    A,
    B,
    C,
    get_chunk,
    judged,
)

UNREADABLE = f"{HOUSE} [c:{A}]. {FEE} [c:{'d' * 16}]."


def verify(answer: str = RAW, seen: tuple[str, ...] = (A, B, C), **kwargs) -> VerifiedAnswer:
    return verify_answer(answer, get_chunk, list(seen), **kwargs)


def rewritten_but_unfixed(model):
    """A check whose rewrite leaves the fee unsupported."""
    return model(judged(HOUSE_SUPPORTED, FEE_UNSUPPORTED), RAW, judged(HOUSE_SUPPORTED, FEE_UNSUPPORTED))


# --- the check ------------------------------------------------------------------------------------------------

def test_a_supported_answer_is_kept_as_it_is(model):
    """An answer whose claims are all supported comes back unchanged."""
    model(judged(HOUSE_SUPPORTED))
    assert verify(SHORTENED).answer == SHORTENED


def test_a_supported_answer_is_checked(model):
    """An answer whose claims are all supported is marked checked."""
    model(judged(HOUSE_SUPPORTED))
    assert verify(SHORTENED).check.status == "checked"


def test_a_supported_answer_is_not_rewritten(model):
    """When every claim is supported, the judge is the only model call."""
    client = model(judged(HOUSE_SUPPORTED))
    verify(SHORTENED)
    assert len(client.calls) == 1


def test_each_claim_gets_its_verdict_and_supporting_sentences(model):
    """A supported claim keeps its cited chunks and the sentences of them that back it."""
    model(judged(HOUSE_SUPPORTED))
    [claim] = verify(SHORTENED).check.claims
    assert claim == Claim(text=HOUSE, verdict="supported", chunk_ids=[A],
                          supporting=[Support(chunk_id=A, sentence="Bygglov krävs för nybyggnad av en byggnad.")])


@pytest.mark.parametrize("cited", [A, B])
def test_the_judge_reads_the_full_text_of_every_cited_source(model, cited):
    """The judge is given the whole text of each chunk the answer cites."""
    client = model(judged(HOUSE_SUPPORTED, FEE_CITING_B))
    verify()
    assert CHUNKS[cited]["text"] in client.seen(0)


def test_an_answer_without_claims_has_none(model):
    """An answer the judge finds no factual claim in is checked with no claims."""
    model(judged())
    assert verify("Feel free to ask the kommun.", seen=()).check.claims == []


def test_an_answer_without_claims_is_not_rewritten(model):
    """An answer without claims needs no rewrite."""
    client = model(judged())
    verify("Feel free to ask the kommun.", seen=())
    assert len(client.calls) == 1


def test_the_check_uses_the_claim_check_model(model, monkeypatch):
    """CLAIM_CHECK_MODEL picks the judge's model."""
    monkeypatch.setenv("CLAIM_CHECK_MODEL", "openai/claim-judge")
    client = model(judged(HOUSE_SUPPORTED))
    verify(SHORTENED)
    assert client.calls[0]["model"].endswith("claim-judge")


# --- one rewrite ----------------------------------------------------------------------------------------------

def test_an_unsupported_claim_is_rewritten(model):
    """An unsupported claim goes back once, and the rewritten answer is what the user gets."""
    model(judged(HOUSE_SUPPORTED, FEE_UNSUPPORTED), REVISED, judged(HOUSE_SUPPORTED, FEE_SUPPORTED))
    assert verify().answer == REVISED


def test_an_uncited_claim_is_rewritten(model):
    """A claim with no citation goes back for the rewrite like an unsupported one."""
    model(judged(HOUSE_SUPPORTED, FEE_UNCITED), SHORTENED, judged(HOUSE_SUPPORTED))
    assert verify(f"{HOUSE} [c:{A}]. {FEE}.").answer == SHORTENED


def test_the_rewrite_is_told_which_claims_to_fix(model):
    """The rewrite is given the claims the sources do not back."""
    client = model(judged(HOUSE_SUPPORTED, FEE_UNSUPPORTED), REVISED, judged(HOUSE_SUPPORTED, FEE_SUPPORTED))
    verify()
    assert FEE in client.seen(1)


def test_the_rewrite_reads_the_chunks_the_agent_read(model):
    """The rewrite may re-cite a chunk the agent read but did not cite."""
    client = model(judged(HOUSE_SUPPORTED, FEE_UNSUPPORTED), REVISED, judged(HOUSE_SUPPORTED, FEE_SUPPORTED))
    verify()
    assert CHUNKS[C]["text"] in client.seen(1)


def test_the_verdicts_are_those_of_the_rewritten_answer(model):
    """After a rewrite, the claims are judged again and those verdicts are kept."""
    model(judged(HOUSE_SUPPORTED, FEE_UNSUPPORTED), REVISED, judged(HOUSE_SUPPORTED, FEE_SUPPORTED))
    assert [claim.verdict for claim in verify().check.claims] == ["supported", "supported"]


def test_a_claim_still_unsupported_after_the_rewrite_keeps_its_verdict(model):
    """A claim the rewrite did not fix stays in the answer as unsupported, to be flagged."""
    rewritten_but_unfixed(model)
    claims = verify().check.claims
    assert [(claim.text, claim.verdict) for claim in claims] == [(HOUSE, "supported"), (FEE, "unsupported")]


def test_an_answer_is_rewritten_at_most_once(model):
    """Still-unsupported claims after the rewrite do not start a second one."""
    client = rewritten_but_unfixed(model)
    verify()
    assert len(client.calls) == 3


# --- failures -------------------------------------------------------------------------------------------------

def test_a_model_error_keeps_the_answer(model):
    """When the judge fails, the answer stays as it was."""
    model(RuntimeError("model down"))
    assert verify().answer == RAW


def test_a_model_error_fails_the_check(model):
    """When the judge fails, the check is marked failed."""
    model(RuntimeError("model down"))
    assert verify().check.status == "failed"


def test_a_failed_check_has_no_claims(model):
    """A check that could not run lists no claims."""
    model(RuntimeError("model down"))
    assert verify().check.claims == []


def test_a_judge_reply_that_is_not_json_fails_the_check(model):
    """A judge reply that cannot be read is a failed check."""
    model("I think the answer is fine.")
    assert verify().check.status == "failed"


def test_a_check_over_its_time_fails(model):
    """A judge that stalls past the timeout gives a failed check."""
    model(2.0)
    assert verify(timeout_s=0.3).check.status == "failed"


def test_a_check_over_its_time_keeps_the_answer(model):
    """A judge that stalls past the timeout leaves the answer as it was."""
    model(2.0)
    assert verify(timeout_s=0.3).answer == RAW


def test_a_check_over_its_time_does_not_wait_for_the_judge(model):
    """The check returns at its timeout, not when the stalled judge does."""
    model(2.0)
    started = time.perf_counter()
    verify(timeout_s=0.3)
    assert time.perf_counter() - started < 1.5


def test_an_unreadable_cited_source_fails_the_check(model):
    """A cited chunk that cannot be read fails the check."""
    model(judged(HOUSE_SUPPORTED, FEE_UNSUPPORTED))
    assert verify_answer(UNREADABLE, get_chunk, [A]).check.status == "failed"


def test_an_unreadable_cited_source_keeps_the_answer(model):
    """A cited chunk that cannot be read leaves the answer as it was."""
    model(judged(HOUSE_SUPPORTED, FEE_UNSUPPORTED))
    assert verify_answer(UNREADABLE, get_chunk, [A]).answer == UNREADABLE


def test_a_failed_rewrite_keeps_the_answer(model):
    """When the rewrite fails, the answer stays as it was."""
    model(judged(HOUSE_SUPPORTED, FEE_UNSUPPORTED), RuntimeError("model down"))
    assert verify().answer == RAW


def test_a_failed_rewrite_keeps_the_first_verdicts(model):
    """When the rewrite fails, the first check's verdicts are kept, so the claim is flagged."""
    model(judged(HOUSE_SUPPORTED, FEE_UNSUPPORTED), RuntimeError("model down"))
    assert [claim.verdict for claim in verify().check.claims] == ["supported", "unsupported"]


def test_a_failed_second_check_keeps_the_answer(model):
    """When judging the rewritten answer fails, the original answer is kept."""
    model(judged(HOUSE_SUPPORTED, FEE_UNSUPPORTED), REVISED, RuntimeError("model down"))
    assert verify().answer == RAW


def test_a_failed_second_check_keeps_the_first_verdicts(model):
    """When judging the rewritten answer fails, the original answer's verdicts are kept."""
    model(judged(HOUSE_SUPPORTED, FEE_UNSUPPORTED), REVISED, RuntimeError("model down"))
    assert [claim.verdict for claim in verify().check.claims] == ["supported", "unsupported"]


# --- the saved form -------------------------------------------------------------------------------------------

def test_a_check_is_saved_as_its_verdicts_and_supporting_sentences():
    """The check's trace data lists every claim with its verdict, chunks and supporting sentences."""
    check = ClaimCheck(status="checked", claims=[
        Claim(text=HOUSE, verdict="supported", chunk_ids=[A],
              supporting=[Support(chunk_id=A, sentence="Bygglov krävs för nybyggnad av en byggnad.")]),
        Claim(text=FEE, verdict="uncited"),
    ])
    assert check.as_event() == {"status": "checked", "claims": [HOUSE_SUPPORTED, FEE_UNCITED]}


def test_a_failed_check_is_saved_as_failed():
    """A failed check's trace data says so, with no claims."""
    assert ClaimCheck(status="failed").as_event() == {"status": "failed", "claims": []}

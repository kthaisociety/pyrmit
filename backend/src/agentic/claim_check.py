"""
Live claim check of a chat answer (issue #82): every factual claim of the agent's answer is judged against the full
text of the sources it cites; what they don't back goes back for one rewrite, and what is still unsupported after
that is flagged in the answer. Generic advice is not a claim.

    CLAIM_CHECK_MODEL=openai/gpt-6-luna  # default: AGENT_MODEL, else the agent's default model
    CLAIM_CHECK_TIMEOUT_S=60             # the whole check: judge, rewrite and second judge

The model is reached through llm.get_openai_client (PCR-0003). The judge answers JSON only, in the shape of the
claims below: {"claims": [{"text", "verdict", "chunk_ids", "supporting": [{"chunk_id", "sentence"}]}]}; the rewrite
answers with the revised answer text alone.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

Verdict = Literal["supported", "unsupported", "uncited"]


@dataclass
class Support:
    """One sentence of a cited chunk that backs a claim, copied verbatim from the chunk's text."""

    chunk_id: str
    sentence: str


@dataclass
class Claim:
    """One factual claim of an answer.

    `text` is an exact substring of the answer that holds no citation marker, so it is found both in the raw answer
    ("[c:<id>]") and in the numbered one the user sees ("[n]"). `chunk_ids` are the chunks the answer cites for it
    (empty when `verdict` is "uncited"); `supporting` is empty unless `verdict` is "supported"."""

    text: str
    verdict: Verdict
    chunk_ids: list[str] = field(default_factory=list)
    supporting: list[Support] = field(default_factory=list)


@dataclass
class ClaimCheck:
    """The verdicts of an answer's claims. `status` is "failed" when the check could not run (model error, timeout,
    a cited chunk that cannot be read); `claims` is then empty."""

    status: Literal["checked", "failed"]
    claims: list[Claim] = field(default_factory=list)

    def as_event(self) -> dict:
        """The data of the answer's "claim_check" pipeline event (ADR-0004: saved in the trace, no new column):
        {"status", "claims": [{"text", "verdict", "chunk_ids", "supporting": [{"chunk_id", "sentence"}]}]}."""
        raise NotImplementedError


@dataclass
class VerifiedAnswer:
    """`answer` is the raw answer ("[c:<id>]" citations) after at most one rewrite: the answer as given when nothing
    was rewritten or the check failed. `check` holds the verdicts of that final answer's claims."""

    answer: str
    check: ClaimCheck


def verify_answer(answer: str, get_chunk: Callable[[str], dict | None], seen_chunk_ids: list[str],
                  timeout_s: float | None = None) -> VerifiedAnswer:
    """Check the claims of a raw agent answer against the full text of the chunks it cites, and rewrite it once.

    1. A judge lists the answer's factual claims and judges each against its cited chunks (`get_chunk`, the full
       chunk text); generic advice is ignored.
    2. When any claim is "unsupported" or "uncited", one rewrite gets those claims and the chunks the agent read
       (`seen_chunk_ids`), and re-cites or removes each; no tools, no new search.
    3. The rewritten answer is judged again; what is still not supported stays in the answer with its verdict, to be
       flagged. There is never a second rewrite.

    Never raises. A model error, a run over `timeout_s` (None: CLAIM_CHECK_TIMEOUT_S, default 60) or a cited chunk
    that `get_chunk` cannot read in step 1 gives the answer unchanged with status "failed". A failure in step 2 or 3
    keeps the answer unchanged with step 1's verdicts."""
    raise NotImplementedError

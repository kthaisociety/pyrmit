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

import json
import logging
import os
import re
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Literal

from llm import get_openai_client, get_response_output_text, resolve_model_name

logger = logging.getLogger(__name__)

Verdict = Literal["supported", "unsupported", "uncited"]
VERDICTS = ("supported", "unsupported", "uncited")
CITED = re.compile(r"c:([0-9a-f]{8,16})(?![0-9a-f])")

JUDGE_INSTRUCTIONS = """You check whether each factual claim of an answer is backed by the sources it cites.
List the specific factual claims of the answer: rules, numbers, deadlines, fees, document facts, legal references.
Ignore generic advice, offers, questions and headings. A claim's citations are the [c:<chunk_id>] right after it.
For each claim decide:
- "supported": a cited source states it; copy the source sentences that state it verbatim into "supporting".
- "unsupported": it cites sources, but none of them states it.
- "uncited": it cites no source.
"text" must be copied exactly from the answer, character for character, and must not contain any citation
("[c:...]" or brackets): the shortest span that states the claim, usually the sentence without its citations.
Return JSON only:
{"claims": [{"text": "<exact span>", "verdict": "supported|unsupported|uncited", "chunk_ids": ["<cited ids>"],
  "supporting": [{"chunk_id": "<id>", "sentence": "<verbatim sentence of that source>"}]}]}"""

REVISE_INSTRUCTIONS = """You correct an answer whose listed claims are not backed by the sources they cite.
For each listed claim: if one of the sources below states it, keep it and cite that source as [c:<chunk_id>] (copy the
id exactly); otherwise remove the claim, or say that it must be checked, without stating it as a fact.
Change nothing else: keep every other sentence, the format, the headings, the language of the answer and the other
citations exactly as they are; Swedish quotes stay verbatim. Return only the corrected answer."""


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
        return {"status": self.status, "claims": [asdict(claim) for claim in self.claims]}


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
    if timeout_s is None:
        timeout_s = float(os.getenv("CLAIM_CHECK_TIMEOUT_S", "60"))
    state: dict = {}

    def run() -> None:
        try:
            state["first"] = _judge(answer, get_chunk)
            if not any(claim.verdict != "supported" for claim in state["first"]):
                return
            revised = _revise(answer, state["first"], get_chunk, seen_chunk_ids)
            state["final"] = (revised, _judge(revised, get_chunk))
        except Exception:
            logger.warning("Claim check failed", exc_info=True)

    worker = threading.Thread(target=run, name="claim-check", daemon=True)
    worker.start()
    worker.join(timeout_s)
    # Read once: a worker past the timeout may still write
    first, final = state.get("first"), None if worker.is_alive() else state.get("final")
    if first is None:
        return VerifiedAnswer(answer=answer, check=ClaimCheck(status="failed"))
    if final is None:
        return VerifiedAnswer(answer=answer, check=ClaimCheck(status="checked", claims=first))
    return VerifiedAnswer(answer=final[0], check=ClaimCheck(status="checked", claims=final[1]))


def _model() -> str:
    from agentic.agent import DEFAULT_MODEL

    return resolve_model_name(os.getenv("CLAIM_CHECK_MODEL") or os.getenv("AGENT_MODEL") or DEFAULT_MODEL)


def _ask(instructions: str, text: str) -> str:
    response = get_openai_client().responses.create(
        model=_model(), instructions=instructions, input=text,
        reasoning={"effort": os.getenv("CLAIM_CHECK_EFFORT", "low").strip() or "low"},
    )
    return get_response_output_text(response).strip()


def _sources(chunk_ids: list[str], get_chunk: Callable[[str], dict | None], strict: bool) -> str:
    """The full text of each chunk, tagged with its id; `strict`: a chunk that cannot be read is an error."""
    from localrag.index import chunk_text

    parts = []
    for chunk_id in dict.fromkeys(chunk_ids):
        chunk = get_chunk(chunk_id)
        if chunk is None:
            if strict:
                raise LookupError(f"cited chunk {chunk_id} cannot be read")
            continue
        parts.append(f"[c:{chunk_id}]\n{chunk_text(chunk)}")
    return "\n\n".join(parts) or "(none)"


def _judge(answer: str, get_chunk: Callable[[str], dict | None]) -> list[Claim]:
    sources = _sources(CITED.findall(answer), get_chunk, strict=True)
    reply = _ask(JUDGE_INSTRUCTIONS, f"Cited sources:\n\n{sources}\n\nAnswer:\n{answer}")
    parsed = json.loads(reply.strip("`").removeprefix("json").strip())
    claims = []
    for item in parsed["claims"]:
        if item["verdict"] not in VERDICTS or not isinstance(item["text"], str):
            raise ValueError(f"not a claim: {item!r}")
        supporting = [Support(chunk_id=str(s["chunk_id"]), sentence=str(s["sentence"]))
                      for s in item.get("supporting") or []] if item["verdict"] == "supported" else []
        claims.append(Claim(text=item["text"], verdict=item["verdict"],
                            chunk_ids=[str(i) for i in item.get("chunk_ids") or []], supporting=supporting))
    return claims


def _revise(answer: str, claims: list[Claim], get_chunk: Callable[[str], dict | None],
            seen_chunk_ids: list[str]) -> str:
    wrong = "\n".join(f"- {claim.text} ({claim.verdict})" for claim in claims if claim.verdict != "supported")
    sources = _sources(CITED.findall(answer) + list(seen_chunk_ids), get_chunk, strict=False)
    revised = _ask(REVISE_INSTRUCTIONS, f"Claims to fix:\n{wrong}\n\nSources:\n\n{sources}\n\nAnswer:\n{answer}")
    if not revised:
        raise ValueError("empty rewrite")
    return revised

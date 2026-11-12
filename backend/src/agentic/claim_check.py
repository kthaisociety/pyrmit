"""
Live claim check of a chat answer (issue #82), by the decision model Jev (llm.ask_decision_model, PCR-0003): each
claim of the agent's answer is put to it with the full text of the sources the claim cites, and it says whether they
state it. What they do not back is flagged in the answer; nothing is rewritten.

    DECISION_MODEL=typesafe/jev-1.14   # the decision model (llm.py)
    CLAIM_CHECK_TIMEOUT_S=20           # the whole check

A claim is a stretch of a sentence followed by its citations ([c:<chunk_id>]): Jev judges it against those chunks
(a yes/no question) and picks the chunk sentence that states it (a choice question), in one call per claim, all calls
in parallel. A sentence without any citation is put to Jev too, in one call: only one that states a rule, number,
fee, deadline or legal reference as fact is flagged, as "uncited". Calls are answered in about half a second.
"""

import logging
import os
import re
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import Literal

from agentic.service import CITATION
from llm import ask_decision_model

logger = logging.getLogger(__name__)

Verdict = Literal["supported", "unsupported", "uncited"]
_DEFAULT_TIMEOUT_S = "20"
SUPPORTED_AT = 0.5  # Jev's yes probability from which the sources count as stating the claim
_MAX_SENTENCES = 255  # the most options a choice question takes
_MIN_WORDS = 4  # a shorter stretch (a label, "See below") is not judged
_STATUTE_TITLE = re.compile(r"\(\d{4}:\d+\)")  # "(2010:900)": the title line a statute chunk opens with

# One citation group as the agent writes it: "[c:<id>]", "[c:<id>; c:<id>]", "[PBL 9 kap. 4 §; c:<id>]"
_CITATION_GROUP = re.compile(r"\s*\[[^\[\]\n]*c:[0-9a-f]{8,16}[^\[\]\n]*\]")
# What leads a line without being part of a claim: a list marker, and a bold label such as "**Answer:**"
_LEAD = re.compile(r"^\s*(?:[-*+]\s+|\d+\.\s+)?(?:\*\*[^*\n]{1,60}:\*\*\s*)?")
# A sentence ends at ".", "!" or "?" before a capital letter or an opening quote or bracket, so "4 kap. 2 §" and
# "t.ex. en" stay whole
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-ZÅÄÖ\"“‘(*])")

_SUPPORTED = {
    "type": "noul",
    "instructions": "Does any passage in `sources` state what `claim` says?",
    "criteria": {"true": "a passage states the claim, in other words or in another language",
                 "false": "no passage states the claim, or a passage says something else"},
}
_NEEDS_SOURCE = {
    "true": "it states a specific rule, permit requirement, number, fee, deadline, date or legal reference as fact",
    "false": "it is advice, a question, an offer, a heading, a general remark, or it sums up points made elsewhere",
}


@dataclass
class Support:
    """One sentence of a cited chunk that backs a claim, copied verbatim from the chunk's text."""

    chunk_id: str
    sentence: str


@dataclass
class Claim:
    """One claim of an answer.

    `text` is an exact substring of the answer that holds no citation marker, so it is found both in the raw answer
    ("[c:<id>]") and in the numbered one the user sees ("[n]"). `chunk_ids` are the chunks the answer cites for it
    (empty when `verdict` is "uncited"); `supporting` is empty unless `verdict` is "supported"."""

    text: str
    verdict: Verdict
    chunk_ids: list[str] = field(default_factory=list)
    supporting: list[Support] = field(default_factory=list)


@dataclass
class ClaimCheck:
    """The verdicts of an answer's claims. `status` is "failed" when the check could not run (a decision model
    error or timeout); `claims` is then empty."""

    status: Literal["checked", "failed"]
    claims: list[Claim] = field(default_factory=list)

    def as_event(self) -> dict:
        """The data of the answer's "claim_check" pipeline event (ADR-0004: saved in the trace, no new column):
        {"status", "claims": [{"text", "verdict", "chunk_ids", "supporting": [{"chunk_id", "sentence"}]}]}."""
        return {"status": self.status, "claims": [asdict(claim) for claim in self.claims]}


@dataclass
class _Stretch:
    """A stretch of the answer to judge: its text and the chunk ids cited right after it (none: uncited)."""

    text: str
    chunk_ids: list[str]


def check_claims(answer: str, get_chunk: Callable[[str], dict | None],
                 timeout_s: float | None = None) -> ClaimCheck:
    """The verdicts of a raw agent answer's claims ("[c:<chunk_id>]" citations), judged by the decision model.

    - A cited claim is "supported" when Jev says its readable cited chunks (`get_chunk`, the full text) state it,
      with the chunk sentence Jev picks as `supporting`; else "unsupported". A claim whose cited chunks cannot be
      read (a miscopied id) has nothing to be judged against: "uncited".
    - A sentence without citations is "uncited" when Jev says it states a rule, number, fee, deadline or legal
      reference as fact; any other uncited sentence is left out.
    - "supported" claims are kept in `claims` too, for the source panel's supporting sentences.

    Never raises: a decision model error or a check over `timeout_s` (None: CLAIM_CHECK_TIMEOUT_S, default 20 s)
    gives status "failed"."""
    if timeout_s is None:
        timeout_s = float(os.getenv("CLAIM_CHECK_TIMEOUT_S", _DEFAULT_TIMEOUT_S))
    outcome: dict = {}

    def run() -> None:
        try:
            outcome["claims"] = _judge_all(_stretches(answer), get_chunk)
        except Exception:
            logger.warning("Claim check failed", exc_info=True)

    worker = threading.Thread(target=run, name="claim-check", daemon=True)
    worker.start()
    worker.join(timeout_s)
    claims = outcome.get("claims") if not worker.is_alive() else None
    if claims is None:
        return ClaimCheck(status="failed")
    return ClaimCheck(status="checked", claims=claims)


def _stretches(answer: str) -> list[_Stretch]:
    """The answer cut into stretches to judge, in order and without repeats. On each line, the text since the line's
    start or its previous citation group is one claim citing the next group's chunks: the agent often states a rule,
    quotes it and only then cites ("Rule. PBL 4 kap. 2 § says ... [c:<id>]"). Each sentence after a line's last
    citation, and each sentence of a line without one, is a stretch with no citation."""
    found: dict[str, _Stretch] = {}
    for line in answer.splitlines():
        if not line.strip() or line.lstrip().startswith(("#", "---", "|")):
            continue
        rest = line[_LEAD.match(line).end():]
        start = 0
        for group in _CITATION_GROUP.finditer(rest):
            _add(found, rest[start:group.start()], CITATION.findall(group.group()))
            start = group.end()
        for sentence in _split_sentences(rest[start:]):
            _add(found, sentence, [])
    return list(found.values())


def _split_sentences(text: str) -> list[str]:
    """`text` cut at each sentence end, verbatim, without empty pieces."""
    return [part for part in _SENTENCE_END.split(text) if part.strip(" .,;:")]


def _add(found: dict[str, "_Stretch"], text: str, chunk_ids: list[str]) -> None:
    text = text.strip().lstrip(".,;:)").strip().rstrip(" ,;:(.")
    if len(text.split()) >= _MIN_WORDS and "[" not in text and "]" not in text and text not in found:
        found[text] = _Stretch(text=text, chunk_ids=list(dict.fromkeys(chunk_ids)))


def _judge_all(stretches: list[_Stretch], get_chunk: Callable[[str], dict | None]) -> list[Claim]:
    """Every stretch judged by Jev: one call per cited stretch and one for all uncited ones, in parallel."""
    cited = [stretch for stretch in stretches if stretch.chunk_ids]
    uncited = [stretch for stretch in stretches if not stretch.chunk_ids]
    with ThreadPoolExecutor(max_workers=8) as pool:
        judged = pool.map(lambda stretch: _judge_cited(stretch, get_chunk), cited)
        flagged = pool.submit(_needs_source, uncited)
        by_text = {claim.text: claim for claim in [*judged, *flagged.result()]}
    return [by_text[stretch.text] for stretch in stretches if stretch.text in by_text]


def _judge_cited(stretch: _Stretch, get_chunk: Callable[[str], dict | None]) -> Claim:
    """A cited stretch's verdict: do its readable chunks state it, and which of their sentences does."""
    from localrag.index import chunk_text

    chunks = {chunk_id: chunk for chunk_id in stretch.chunk_ids if (chunk := get_chunk(chunk_id))}
    if not chunks:
        return Claim(text=stretch.text, verdict="uncited")
    texts = {chunk_id: chunk_text(chunk) for chunk_id, chunk in chunks.items()}
    sentences = [(chunk_id, sentence) for chunk_id, chunk in chunks.items()
                 for sentence in _sentences(chunk.get("text") or "")]
    sentences = sentences[:_MAX_SENTENCES]
    questions = {"supported": _SUPPORTED}
    if sentences:
        questions["sentence"] = {
            "type": "choice",
            "instructions": "Which sentence of `sources` states what `claim` says most directly?",
            "criteria": {f"s{index}": sentence for index, (_, sentence) in enumerate(sentences)},
        }
    answers = ask_decision_model({"claim": stretch.text, "sources": list(texts.values())}, questions)
    chunk_ids = list(texts)
    if float(answers["supported"]["noul"]) < SUPPORTED_AT:
        return Claim(text=stretch.text, verdict="unsupported", chunk_ids=chunk_ids)
    picked = answers.get("sentence", {}).get("choice", "")
    index = int(picked[1:]) if re.fullmatch(r"s\d+", picked or "") and int(picked[1:]) < len(sentences) else None
    supporting = [Support(chunk_id=sentences[index][0], sentence=sentences[index][1])] if index is not None else []
    return Claim(text=stretch.text, verdict="supported", chunk_ids=chunk_ids, supporting=supporting)


def _needs_source(uncited: list[_Stretch]) -> list[Claim]:
    """The uncited stretches Jev says state something as fact that needs a source, as "uncited" claims."""
    if not uncited:
        return []
    state = {f"sentence_{index}": stretch.text for index, stretch in enumerate(uncited)}
    questions = {f"needs_{index}": {
        "type": "noul",
        "instructions": f"In an answer about Swedish planning and building law, does `sentence_{index}` need a source?",
        "criteria": _NEEDS_SOURCE,
    } for index in range(len(uncited))}
    answers = ask_decision_model(state, questions)
    return [Claim(text=stretch.text, verdict="uncited") for index, stretch in enumerate(uncited)
            if float(answers[f"needs_{index}"]["noul"]) >= SUPPORTED_AT]


def _sentences(text: str) -> list[str]:
    """A chunk's own text (no header) cut into its sentences and lines, each verbatim; short fragments and a statute's
    title line ("Plan- och bygglag (2010:900), 4 kap. 2 § ...") left out."""
    return [part.strip() for line in text.splitlines() if not _STATUTE_TITLE.search(line)
            for part in _SENTENCE_END.split(line) if len(part.split()) >= _MIN_WORDS]

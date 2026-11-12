"""
Live claim check of a chat answer (issue #82), by the decision model Jev (llm.ask_decision_model, PCR-0003): each
claim of the agent's answer is put to it with the full text of the sources the claim cites, and it says whether they
back it. What they do not back is flagged in the answer; nothing is rewritten.

    DECISION_MODEL=typesafe/jev-1.14   # the decision model (llm.py)
    CLAIM_CHECK_TIMEOUT_S=20           # the whole check

A claim is the text of a line from its start (or the previous claim) to the end of the sentence that holds a citation
group ([c:<chunk_id>]): the agent cites after a full stop ("Rule. Quote. [c:<id>]") as well as mid-sentence. Jev
judges it against those chunks (a yes/no question) and picks the chunk sentence that states it (a choice question),
one call per claim, all calls in parallel on a shared pool. A sentence without any citation is put to Jev too, in one
call: only one that states a rule, number, fee, deadline or legal reference as fact is flagged, as "uncited".
Headings, table rows and text holding brackets (markdown links) are not judged. Calls are answered in about half a
second; a call that fails or runs out of time costs only its own verdicts.

The pinned place's registry data (`place`: the property, its plans, protected areas, riksintressen...) is a source
too: the agent states facts about the site from it, and cites the statute the fact bears on. Every claim is judged
against its cited chunks and that data, and an uncited sentence the data backs is not flagged.

The question's wording was chosen on 380 claim-source pairs refereed by another model (2026-11-12): 88 % agreement,
8 % of backed claims flagged, against 86 % and 14 % for the LLM judge it replaced.
"""

import logging
import os
import re
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass, field
from typing import Literal

from agentic.service import CITATION
from llm import ask_decision_model

logger = logging.getLogger(__name__)

Verdict = Literal["supported", "unsupported", "uncited"]
_DEFAULT_TIMEOUT_S = 20.0
SUPPORTED_AT = 0.5  # Jev's yes probability from which the sources count as backing the claim
_MAX_SENTENCES = 255  # the most options a choice question takes
_MIN_WORDS = 4  # a shorter stretch (a label, "See below") is not judged
_MAX_PARALLEL = 16  # Jev calls in flight at once, over all answers being checked
_POOL = ThreadPoolExecutor(max_workers=_MAX_PARALLEL, thread_name_prefix="claim-check")

# One citation group as the agent writes it: "[c:<id>]", "[c:<id>; c:<id>]", "[PBL 9 kap. 4 §; c:<id>]"
_CITATION_GROUP = re.compile(r"\s*\[[^\[\]\n]*c:[0-9a-f]{8,16}[^\[\]\n]*\]")
# What leads a line without being part of a claim: a blockquote, a list marker ("-", "1.", "1)") and a bold label
_LEAD = re.compile(r"^\s*(?:>\s*)*(?:[-*+]\s+|\d+[.)]\s+)?(?:\*\*[^*\n]{1,60}:\*\*\s*)?")
# A sentence ends at ".", "!" or "?" before a capital letter or an opening quote or bracket, so "4 kap. 2 §" stays
# whole; an abbreviation before the capital ("bl.a. Boverket") is no end either
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-ZÅÄÖ\"“‘(*])")
_ABBREVIATIONS = {"bl.a.", "t.ex.", "enl.", "ca.", "m.m.", "s.k.", "dvs.", "d.v.s.", "resp.", "jfr.", "kap.", "st.",
                  "p.", "nr.", "osv.", "e.g.", "i.e.", "etc.", "mfl.", "m.fl."}
_STATUTE_TITLE = re.compile(r"\(\d{4}:\d+\)")  # "(2010:900)": the title line a statute chunk opens with

_BACKED = {
    "true": "the sources say the same as the claim or clearly imply it, even when the claim words it differently, "
            "shortens it, explains it or is in English while the sources are Swedish",
    "false": "the claim adds a fact, number or condition the sources do not give, or contradicts them, or the "
             "sources are about something else",
}
_SUPPORTED = {"type": "noul", "instructions": "Do `sources` back what `claim` says?", "criteria": _BACKED}
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
    """The verdicts of an answer's claims. `status` is "failed" when the check could not run (every decision model
    call failed or ran out of time); `claims` is then empty."""

    status: Literal["checked", "failed"]
    claims: list[Claim] = field(default_factory=list)

    def as_event(self) -> dict:
        """The data of the answer's "claim_check" pipeline event (ADR-0004: saved in the trace, no new column):
        {"status", "claims": [{"text", "verdict", "chunk_ids", "supporting": [{"chunk_id", "sentence"}]}]}."""
        return {"status": self.status, "claims": [asdict(claim) for claim in self.claims]}


@dataclass
class _Stretch:
    """A stretch of the answer to judge. `text` is the part marked in the answer when flagged (an exact substring
    without citations or unbalanced emphasis), `judged` what Jev reads (the whole stretch, citations taken out) and
    `chunk_ids` the chunks it cites (none: uncited)."""

    text: str
    judged: str
    chunk_ids: list[str]


def check_claims(answer: str, get_chunk: Callable[[str], dict | None], place: str | None = None,
                 timeout_s: float | None = None) -> ClaimCheck:
    """The verdicts of a raw agent answer's claims ("[c:<chunk_id>]" citations), judged by the decision model.

    - A cited claim is "supported" when Jev says its readable cited chunks (`get_chunk`, the full text) back it, with
      the chunk sentence Jev picks as `supporting`; else "unsupported". A claim whose cited chunks cannot be read
      (a miscopied id) has nothing to be judged against: "uncited".
    - A sentence without citations is "uncited" when Jev says it states a rule, number, fee, deadline or legal
      reference as fact; any other uncited sentence is left out.
    - "supported" claims are kept in `claims` too, for the source panel's supporting sentences.
    - `place`, the pinned place's registry data as the agent got it, counts as a source of every claim; it offers no
      supporting sentence, since it is no chunk.

    Never raises. A call that fails or is not done within `timeout_s` (None: CLAIM_CHECK_TIMEOUT_S, default 20 s)
    leaves its claims out; status "failed" when no call succeeded."""
    if timeout_s is None:
        timeout_s = float(os.getenv("CLAIM_CHECK_TIMEOUT_S", _DEFAULT_TIMEOUT_S))
    try:
        stretches = _stretches(answer)
    except Exception:
        logger.warning("Claim check failed to read the answer", exc_info=True)
        return ClaimCheck(status="failed")
    cited = [stretch for stretch in stretches if stretch.chunk_ids]
    uncited = [stretch for stretch in stretches if not stretch.chunk_ids]
    calls: list[Future] = [_POOL.submit(_judge_cited, stretch, get_chunk, place) for stretch in cited]
    if uncited:
        calls.append(_POOL.submit(_needs_source, uncited, place))
    done, late = wait(calls, timeout=timeout_s)
    for call in late:
        call.cancel()
    judged: list[Claim] = []
    for call in calls:
        if call in done and call.exception() is None:
            result = call.result()
            judged.extend(result if isinstance(result, list) else [result])
        else:
            logger.warning("Claim check call failed or timed out: %r", call.exception() if call in done else "late")
    if calls and not any(call in done and call.exception() is None for call in calls):
        return ClaimCheck(status="failed")
    by_text = {claim.text: claim for claim in judged}
    return ClaimCheck(status="checked", claims=[by_text[s.text] for s in stretches if s.text in by_text])


def _stretches(answer: str) -> list[_Stretch]:
    """The answer cut into stretches to judge, in order, one per marked text (a cited one wins over an uncited one
    with the same text). On each line, a claim runs from the line's start, or the end of the previous claim, to the
    end of the sentence holding its next citation group, and cites every group in that span; each sentence after a
    line's last claim, and each sentence of a line without citations, is a stretch with no citation. Headings, rules
    ("---") and table rows are skipped."""
    found: dict[str, _Stretch] = {}
    for line in answer.splitlines():
        if not line.strip() or line.lstrip().startswith(("#", "---", "|")):
            continue
        rest = line[_LEAD.match(line).end():]
        groups = list(_CITATION_GROUP.finditer(rest))
        start, index = 0, 0
        while index < len(groups):
            end = _sentence_end(rest, groups[index].end())
            in_claim = [group for group in groups[index:] if group.start() < end]
            _add(found, rest[start:end], [chunk_id for group in in_claim for chunk_id in CITATION.findall(group.group())])
            index, start = index + len(in_claim), end
        for sentence_start, sentence_end in _sentence_spans(rest, start):
            _add(found, rest[sentence_start:sentence_end], [])
    return list(found.values())


def _is_sentence_end(text: str, match: re.Match) -> bool:
    """Whether a _SENTENCE_END match in `text` ends a sentence: not when the word before it is an abbreviation."""
    before = text[:match.start()].split()
    return not before or before[-1].lower() not in _ABBREVIATIONS


def _sentence_end(text: str, at: int) -> int:
    """The index where the sentence holding position `at` of `text` ends (after its full stop), or len(text)."""
    for match in _SENTENCE_END.finditer(text, at):
        if _is_sentence_end(text, match):
            return match.start()
    return len(text)


def _sentence_spans(text: str, start: int = 0) -> Iterator[tuple[int, int]]:
    """(start, end) of each sentence of text[start:], the whitespace between sentences left out."""
    while True:
        while start < len(text) and text[start].isspace():
            start += 1
        if start >= len(text):
            return
        end = _sentence_end(text, start)
        yield start, end
        start = end


def _add(found: dict[str, _Stretch], span: str, chunk_ids: list[str]) -> None:
    """Add the stretch of `span` (raw answer text, citations included) to `found`, unless it is too short to judge,
    has no markable text, or repeats a text already found (a cited stretch replaces an uncited one)."""
    judged = " ".join(_CITATION_GROUP.sub(" ", span).replace("**", "").split()).strip(" .,;:")
    pieces = [_markable(piece) for piece in _CITATION_GROUP.split(span)]
    text = max(pieces, key=lambda piece: len(piece.split()), default="")
    if len(judged.split()) < _MIN_WORDS or len(text.split()) < 2:
        return
    earlier = found.get(text)
    if earlier is None or (chunk_ids and not earlier.chunk_ids):
        found[text] = _Stretch(text=text, judged=judged, chunk_ids=list(dict.fromkeys(chunk_ids)))


def _markable(piece: str) -> str:
    """The part of `piece` that can be marked in the answer as markdown link text: no brackets, trimmed of edge
    punctuation and emphasis markers, and without bold the claim opens or closes but does not hold whole."""
    if "[" in piece or "]" in piece:
        return ""
    text = piece.strip().strip(".,;:()").strip().strip("*_").strip()
    if text.count("**") % 2:
        text = max(text.split("**"), key=lambda part: len(part.split())).strip().strip(".,;:()*_ ")
    return text


def _judge_cited(stretch: _Stretch, get_chunk: Callable[[str], dict | None], place: str | None) -> Claim:
    """A cited stretch's verdict: do its readable chunks (with the pinned place's data) back it, and which of the
    chunks' sentences states it."""
    from localrag.index import chunk_text

    chunks = [chunk for chunk_id in stretch.chunk_ids if (chunk := get_chunk(chunk_id))]
    if not chunks:
        return Claim(text=stretch.text, verdict="uncited")
    chunk_ids = list(dict.fromkeys(str(chunk.get("chunk_id")) for chunk in chunks))
    sentences = [(str(chunk.get("chunk_id")), sentence) for chunk in chunks
                 for sentence in _sentences(chunk.get("text") or "")][:_MAX_SENTENCES]
    questions = {"supported": _SUPPORTED}
    if sentences:
        questions["sentence"] = {
            "type": "choice",
            "instructions": "Which sentence of `sources` states what `claim` says most directly?",
            "criteria": {f"s{index}": sentence for index, (_, sentence) in enumerate(sentences)},
        }
    sources = [*(chunk_text(chunk) for chunk in chunks), *([place] if place else [])]
    answers = ask_decision_model({"claim": stretch.judged, "sources": sources}, questions)
    if float(answers["supported"]["noul"]) < SUPPORTED_AT:
        return Claim(text=stretch.text, verdict="unsupported", chunk_ids=chunk_ids)
    picked = _picked_sentence(answers.get("sentence"), sentences)
    return Claim(text=stretch.text, verdict="supported", chunk_ids=chunk_ids,
                 supporting=[Support(chunk_id=picked[0], sentence=picked[1])] if picked else [])


def _picked_sentence(answer: dict | None, sentences: list[tuple[str, str]]) -> tuple[str, str] | None:
    """The (chunk_id, sentence) Jev chose in the sentence question ("s<index>"), or None when it chose none."""
    match = re.fullmatch(r"s(\d+)", str((answer or {}).get("choice", "")))
    return sentences[int(match.group(1))] if match and int(match.group(1)) < len(sentences) else None


def _needs_source(uncited: list[_Stretch], place: str | None) -> list[Claim]:
    """The uncited stretches Jev says state something as fact that needs a source, as "uncited" claims, unless the
    pinned place's data backs them (asked in the same call)."""
    state: dict = {f"sentence_{index}": stretch.judged for index, stretch in enumerate(uncited)}
    questions = {f"needs_{index}": {
        "type": "noul",
        "instructions": f"In an answer about Swedish planning and building law, does `sentence_{index}` need a source?",
        "criteria": _NEEDS_SOURCE,
    } for index in range(len(uncited))}
    if place:
        state["place"] = place
        questions |= {f"place_{index}": {"type": "noul", "instructions": f"Does `place` back what `sentence_{index}` says?",
                                         "criteria": _BACKED} for index in range(len(uncited))}
    answers = ask_decision_model(state, questions)

    def flagged(index: int) -> bool:
        backed = place and float(answers[f"place_{index}"]["noul"]) >= SUPPORTED_AT
        return float(answers[f"needs_{index}"]["noul"]) >= SUPPORTED_AT and not backed
    return [Claim(text=stretch.text, verdict="uncited") for index, stretch in enumerate(uncited) if flagged(index)]


def _sentences(text: str) -> list[str]:
    """A chunk's own text (no header) cut into its sentences, each verbatim but for line breaks: a line wrapped mid-
    sentence (the next starts in lower case after no closing punctuation) is joined to it. The statute title line a
    chunk may open with ("Plan- och bygglag (2010:900), 4 kap. 2 § ...") and short fragments are left out."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines and _STATUTE_TITLE.search(lines[0]):
        lines = lines[1:]
    joined: list[str] = []
    for line in lines:
        if joined and not joined[-1].endswith((".", ":", ";", ",", "!", "?")) and line[:1].islower():
            joined[-1] += " " + line
        else:
            joined.append(line)
    return [line[start:end].strip() for line in joined for start, end in _sentence_spans(line)
            if len(line[start:end].split()) >= _MIN_WORDS]

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

import contextvars
import logging
import os
import re
import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass, field
from typing import Literal

from agentic.service import CITATION
from llm import ask_decision_model

logger = logging.getLogger(__name__)

Verdict = Literal["supported", "unsupported", "uncited", "skipped"]
_DEFAULT_TIMEOUT_S = 20.0
SUPPORTED_AT = 0.5  # Jev's yes probability from which the sources count as backing the claim
_HEDGE_AT = 0.5  # Jev's yes probability from which a claim or sentence counts as a hedge
_YES_AT = 0.5  # Jev's yes probability from which a claim adds to its sources, states a fact, or is backed in part
_MAX_SENTENCES = 255  # the most options a choice question takes
_MIN_WORDS = 4  # a shorter stretch (a label, "See below") is not judged
_MAX_PARALLEL = 16  # Jev calls in flight at once, over all answers being checked
_POOL = ThreadPoolExecutor(max_workers=_MAX_PARALLEL, thread_name_prefix="claim-check")
# The calls about one claim's sentences (CheckOptions.each_sentence) wait in a pool of their own: a claim's worker of
# _POOL waits for them, and would wait for ever on calls queued behind itself in the same pool
_SENTENCE_POOL = ThreadPoolExecutor(max_workers=_MAX_PARALLEL, thread_name_prefix="claim-check-sentence")

# One citation group as the agent writes it: "[c:<id>]", "[c:<id>; c:<id>]", "[PBL 9 kap. 4 §; c:<id>]", also with
# the statute as its own bracket group right before or after it ("[FBL 3 kap. 1 §][c:<id>]"): left in the text, its
# brackets made the claim unmarkable and it was dropped (~10 % of the cited stretches of answers without a pin)
_CITATION_GROUP = re.compile(r"(?:\s*\[[^\[\]\n]*\](?=\s*\[[^\[\]\n]*c:[0-9a-f]{8,16}))*"
                             r"\s*\[[^\[\]\n]*c:[0-9a-f]{8,16}[^\[\]\n]*\]"
                             r"(?:\s*\[[^\[\]\n]*\](?![(\[]))*")
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
_SUPPORTED_CORE = {
    "type": "noul",
    "instructions": "Do `sources` back the main point of `claim`?",
    "criteria": {
        "true": "the sources state or clearly imply what the claim mainly says, even when the claim adds a detail, "
                "example or explanation they do not give, words it differently or is in English while the sources "
                "are Swedish",
        "false": "the sources do not give the claim's main point, contradict it, or are about something else",
    },
}
_HEDGE_CRITERIA = {
    "true": "it is a caution, a possibility or a referral: something may or can be needed, the reader should check "
            "or contact someone, or the answer says what it could not find",
    "false": "it states a rule, permit requirement, number, fee, deadline, legal reference or fact about the site",
}
_HEDGE = {"type": "noul", "instructions": "Is `claim` a hedge rather than a statement of fact?",
          "criteria": _HEDGE_CRITERIA}
_ADDITION = {"type": "noul", "instructions": "Does `claim` say something that `sources` do not state?", "criteria": {
    "true": "it states a fact, a condition, a conclusion or advice that no source states",
    "false": "everything it says is stated in the sources, or it only rewords or sums up what they state",
}}
_PART = {"type": "noul", "instructions": "Do `sources` state at least part of what `claim` says?", "criteria": {
    "true": "the sources state some of what it says, even when the rest is missing from them",
    "false": "the sources state nothing of what it says",
}}
_NEEDS_SOURCE = {
    "true": "it states a specific rule, permit requirement, number, fee, deadline, date or legal reference as fact",
    "false": "it is advice, a question, an offer, a heading, a general remark, or it sums up points made elsewhere",
}


@dataclass(frozen=True)
class CheckOptions:
    """How the claim check judges an answer (#126). The defaults are the live check: the chat, the benchmarks and the
    referee's recheck run it unless told otherwise. Each field is one change measured against the referee reference
    (agentic.claim_referee tune); a change that wins becomes the default.

    - `question`: "strict", the sources must back everything the claim says; "core", they must back what it mainly
      says, and an extra detail they do not give does not fail the whole claim.
    - `supported_at`: Jev's yes probability from which the sources (a claim's cited chunks, or the pinned place's
      data) count as backing it.
    - `skip_hedges`: a hedge (a caution or a "may": "Kontakta kommunen för att bekräfta", "Det kan krävas bygglov") is
      not judged; it is kept in the result with verdict "skipped" and never flagged.
    - `per_sentence`: a claim is only the sentence holding its citation group, not the run from the line's start (or
      the previous claim); the sentences before it are judged as sentences without a citation.
    - `each_sentence` (#129): a claim of several sentences is judged sentence by sentence against the claim's own
      sources, each sentence in a decision model call of its own, asked what a whole claim is asked plus whether the
      sentence states a fact. The claim is "unsupported" when the sources do not back a sentence that states a fact;
      a sentence that states none (a fragment, a bare legal reference) never fails it. The sentences not backed are
      the claim's `unbacked`. A claim of one sentence, or with no sentence that states a fact, is judged whole.
    - `additions` (#129): Jev is also asked, in the same call, whether the claim (or sentence) says something its
      sources do not state; it is backed only when the sources back it and it adds nothing (Jev's yes below 0.5).
    - `levels` (#129): each cited claim judged gets a `level`: "full" when supported; when unsupported "partly" or
      "none". With `each_sentence` on a claim judged by sentence: "partly" when the sources back at least one of its
      fact-stating sentences. Otherwise Jev is asked, in the same call, whether the sources state at least part of
      what the claim says ("partly" from 0.5). The verdict stays "unsupported" either way (ADR-0024)."""

    question: Literal["strict", "core"] = "strict"
    supported_at: float = SUPPORTED_AT
    skip_hedges: bool = False
    per_sentence: bool = False
    each_sentence: bool = True
    additions: bool = False
    levels: bool = False


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
    (empty when `verdict` is "uncited"); `supporting` is empty unless `verdict` is "supported". A "skipped" claim is a
    hedge the check left unjudged (CheckOptions.skip_hedges): never flagged, like a "supported" one.

    `level` (#129) says how much of a cited claim its sources back, "full" / "partly" / "none": set only under
    CheckOptions.levels, None otherwise and for an "uncited" or "skipped" claim. `unbacked` (#129) holds, under
    CheckOptions.each_sentence, the sentences of the claim its sources do not back, each an exact substring of
    `text`, in order; empty otherwise. Both are part of the saved event."""

    text: str
    verdict: Verdict
    chunk_ids: list[str] = field(default_factory=list)
    supporting: list[Support] = field(default_factory=list)
    level: Literal["full", "partly", "none"] | None = None
    unbacked: list[str] = field(default_factory=list)


@dataclass
class ClaimCheck:
    """The verdicts of an answer's claims. `status` is "failed" when the check could not run (every decision model
    call failed or ran out of time); `claims` is then empty. `calls` is the number of decision model calls the check
    started (a call that failed or ran out of time counts, a retry inside one call does not) and `seconds` the time
    the whole check took; both are set on a failed check too and stay out of `as_event` (#128)."""

    status: Literal["checked", "failed"]
    claims: list[Claim] = field(default_factory=list)
    calls: int = 0
    seconds: float = 0.0

    def as_event(self) -> dict:
        """The data of the answer's "claim_check" pipeline event (ADR-0004: saved in the trace, no new column):
        {"status", "claims": [{"text", "verdict", "chunk_ids", "supporting": [{"chunk_id", "sentence"}], "level",
        "unbacked"}]}."""
        return {"status": self.status, "claims": [asdict(claim) for claim in self.claims]}


@dataclass
class Stretch:
    """A stretch of the answer to judge. `text` is the part marked in the answer when flagged (an exact substring
    without citations or unbalanced emphasis), `judged` what Jev reads (the whole stretch, citations taken out) and
    `chunk_ids` the chunks it cites (none: uncited)."""

    text: str
    judged: str
    chunk_ids: list[str]


def check_claims(answer: str, get_chunk: Callable[[str], dict | None], place: str | None = None,
                 timeout_s: float | None = None, options: CheckOptions | None = None) -> ClaimCheck:
    """The verdicts of a raw agent answer's claims ("[c:<chunk_id>]" citations), judged by the decision model.

    - A cited claim is "supported" when Jev says its readable cited chunks (`get_chunk`, the full text) back it, with
      the chunk sentence Jev picks as `supporting`; else "unsupported". A claim whose cited chunks cannot be read
      (a miscopied id) has nothing to be judged against: "uncited".
    - A sentence without citations is "uncited" when Jev says it states a rule, number, fee, deadline or legal
      reference as fact; any other uncited sentence is left out.
    - "supported" claims are kept in `claims` too, for the source panel's supporting sentences.
    - `place`, the pinned place's registry data as the agent got it, counts as a source of every claim; it offers no
      supporting sentence, since it is no chunk.
    - `options` (None: CheckOptions(), the live check) sets the question, the support threshold, whether hedges are
      "skipped" instead of judged, and whether a claim is cut per sentence. Saved answers keep the verdicts they got.

    Never raises. A call that fails or is not done within `timeout_s` (None: CLAIM_CHECK_TIMEOUT_S, default 20 s)
    leaves its claims out; status "failed" when no call succeeded."""
    options = options or CheckOptions()
    began = time.monotonic()
    started: list[None] = []  # one entry per decision model call started (list.append is atomic)

    def result(status: str, claims: list[Claim] | None = None) -> ClaimCheck:
        return ClaimCheck(status=status, claims=claims or [], calls=len(started), seconds=time.monotonic() - began)

    if timeout_s is None:
        timeout_s = float(os.getenv("CLAIM_CHECK_TIMEOUT_S", _DEFAULT_TIMEOUT_S))
    try:
        cut = stretches(answer, per_sentence=options.per_sentence)
    except Exception:
        logger.warning("Claim check failed to read the answer", exc_info=True)
        return result("failed")
    cited = [stretch for stretch in cut if stretch.chunk_ids]
    uncited = [stretch for stretch in cut if not stretch.chunk_ids]
    # Each call in its own copy of this context, so Jev runs on the user's own key (llm.openrouter_key, #108)
    calls: list[Future] = [_POOL.submit(contextvars.copy_context().run, _judge_cited, stretch, get_chunk, place, options, started)
                           for stretch in cited]
    if uncited:
        calls.append(_POOL.submit(contextvars.copy_context().run, _needs_source, uncited, place, options, started))
    done, late = wait(calls, timeout=timeout_s)
    for call in late:
        call.cancel()
    judged: list[Claim] = []
    for call in calls:
        if call in done and call.exception() is None:
            found = call.result()
            judged.extend(found if isinstance(found, list) else [found])
        else:
            logger.warning("Claim check call failed or timed out: %r", call.exception() if call in done else "late")
    if calls and not any(call in done and call.exception() is None for call in calls):
        return result("failed")
    by_text = {claim.text: claim for claim in judged}
    return result("checked", [by_text[s.text] for s in cut if s.text in by_text])


def stretches(answer: str, per_sentence: bool = False) -> list[Stretch]:
    """The answer cut into stretches to judge, in order, one per marked text (a cited one wins over an uncited one
    with the same text). On each line, a claim runs from the line's start, or the end of the previous claim, to the
    end of the sentence holding its next citation group, and cites every group in that span; each sentence after a
    line's last claim, and each sentence of a line without citations, is a stretch with no citation. With
    `per_sentence`, a claim is only the sentence holding its citation group, and each sentence before it is a stretch
    with no citation. Headings, rules ("---") and table rows are skipped."""
    found: dict[str, Stretch] = {}
    for line in answer.splitlines():
        if not line.strip() or line.lstrip().startswith(("#", "---", "|")):
            continue
        rest = line[_LEAD.match(line).end():]
        groups = list(_CITATION_GROUP.finditer(rest))
        start, index = 0, 0
        while index < len(groups):
            end = _sentence_end(rest, groups[index].end())
            if per_sentence:
                for sentence_start, sentence_end in _sentence_spans(rest, start):
                    if sentence_end > groups[index].start():
                        start = sentence_start
                        break
                    _add(found, rest[sentence_start:sentence_end], [])
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


def _add(found: dict[str, Stretch], span: str, chunk_ids: list[str]) -> None:
    """Add the stretch of `span` (raw answer text, citations included) to `found`, unless it is too short to judge,
    has no markable text, or repeats a text already found (a cited stretch replaces an uncited one)."""
    judged = " ".join(_CITATION_GROUP.sub(" ", span).replace("**", "").split()).strip(" .,;:")
    pieces = [_markable(piece) for piece in _CITATION_GROUP.split(span)]
    text = max(pieces, key=lambda piece: len(piece.split()), default="")
    if len(judged.split()) < _MIN_WORDS or len(text.split()) < 2:
        return
    earlier = found.get(text)
    if earlier is None or (chunk_ids and not earlier.chunk_ids):
        found[text] = Stretch(text=text, judged=judged, chunk_ids=list(dict.fromkeys(chunk_ids)))


def _markable(piece: str) -> str:
    """The part of `piece` that can be marked in the answer as markdown link text: no brackets, trimmed of edge
    punctuation and emphasis markers, and without bold the claim opens or closes but does not hold whole."""
    if "[" in piece or "]" in piece:
        return ""
    text = piece.strip().strip(".,;:()").strip().strip("*_").strip()
    if text.count("**") % 2:
        text = max(text.split("**"), key=lambda part: len(part.split())).strip().strip(".,;:()*_ ")
    return text


_FACT = {"type": "noul", "instructions": "Does `claim` state something as fact?", "criteria": {
    "true": "it states a rule, permit requirement, number, fee, deadline, date, place fact or what the user should do",
    "false": "it is only a legal reference, a heading, a fragment, a question, or a link to what was said before",
}}


def _judge_cited(stretch: Stretch, get_chunk: Callable[[str], dict | None], place: str | None,
                 options: CheckOptions, started: list) -> Claim:
    """A cited stretch's verdict: do its readable chunks (with the pinned place's data) back it, and which of the
    chunks' sentences states it; "skipped" when hedges are skipped and Jev says it is one. With
    CheckOptions.each_sentence a stretch of several sentences is judged sentence by sentence (`_judge_by_sentence`)."""
    chunks = [chunk for chunk_id in stretch.chunk_ids if (chunk := get_chunk(chunk_id))]
    if not chunks:
        return Claim(text=stretch.text, verdict="uncited")
    chunk_ids = list(dict.fromkeys(str(chunk.get("chunk_id")) for chunk in chunks))
    if options.each_sentence:
        claim = _judge_by_sentence(stretch, chunks, chunk_ids, place, options, started)
        if claim is not None:
            return claim
    judged = _ask_about(stretch.judged, chunks, place, options, started)
    if judged["hedge"]:
        return Claim(text=stretch.text, verdict="skipped", chunk_ids=chunk_ids)
    if not judged["backed"]:
        return Claim(text=stretch.text, verdict="unsupported", chunk_ids=chunk_ids,
                     level=("partly" if judged["part"] else "none") if options.levels else None)
    return Claim(text=stretch.text, verdict="supported", chunk_ids=chunk_ids, level="full" if options.levels else None,
                 supporting=[Support(*judged["picked"])] if judged["picked"] else [])


def _ask_about(text: str, chunks: list[dict], place: str | None, options: CheckOptions, started: list,
               ask_fact: bool = False) -> dict:
    """One decision model call about a claim, or one sentence of a claim, against the chunks it cites and the place
    data: {"backed": the sources back it (and, with CheckOptions.additions, it adds nothing to them), "hedge": it is a
    hedge (asked with skip_hedges), "fact": it states a fact (asked with `ask_fact`, else True), "part": the sources
    state at least part of it (asked with levels), "picked": the (chunk_id, sentence) that states it, or None}."""
    from localrag.index import chunk_text

    sentences = [(str(chunk.get("chunk_id")), sentence) for chunk in chunks
                 for sentence in _sentences(chunk.get("text") or "")][:_MAX_SENTENCES]
    questions = {"supported": _SUPPORTED_CORE if options.question == "core" else _SUPPORTED}
    if options.skip_hedges:
        questions["hedge"] = _HEDGE
    if options.additions:
        questions["addition"] = _ADDITION
    if options.levels:
        questions["part"] = _PART
    if ask_fact:
        questions["fact"] = _FACT
    if sentences:
        questions["sentence"] = {
            "type": "choice",
            "instructions": "Which sentence of `sources` states what `claim` says most directly?",
            "criteria": {f"s{index}": sentence for index, (_, sentence) in enumerate(sentences)},
        }
    sources = [*(chunk_text(chunk) for chunk in chunks), *([place] if place else [])]
    started.append(None)
    answers = ask_decision_model({"claim": text, "sources": sources}, questions)

    def yes(name: str, at: float = _YES_AT) -> bool:
        return name in questions and float(answers[name]["noul"]) >= at
    return {"backed": yes("supported", options.supported_at) and not yes("addition"), "hedge": yes("hedge", _HEDGE_AT),
            "fact": yes("fact") if ask_fact else True, "part": yes("part"),
            "picked": _picked_sentence(answers.get("sentence"), sentences)}


def _judge_by_sentence(stretch: Stretch, chunks: list[dict], chunk_ids: list[str], place: str | None,
                       options: CheckOptions, started: list) -> Claim | None:
    """A cited stretch of several sentences judged sentence by sentence against its own chunks (CheckOptions.
    each_sentence), each sentence in a call of its own, all at once: "unsupported" when the sources do not back a
    sentence that states a fact, those sentences in `unbacked`. None when the stretch is one sentence or none of its
    sentences states a fact (a hedge, with hedges skipped, states none): it is then judged whole."""
    sentences = [stretch.text[start:end].rstrip(".!?: ") for start, end in _sentence_spans(stretch.text)]
    sentences = [sentence for sentence in sentences if sentence]
    if len(sentences) < 2:
        return None
    calls = [_SENTENCE_POOL.submit(contextvars.copy_context().run, _ask_about, sentence, chunks, place, options, started,
                                   True) for sentence in sentences]
    judged = [(sentence, call.result()) for sentence, call in zip(sentences, calls, strict=True)]
    facts = [(sentence, found) for sentence, found in judged if found["fact"] and not found["hedge"]]
    if not facts:
        return None
    unbacked = [sentence for sentence, found in facts if not found["backed"]]
    level = None
    if options.levels:
        level = "full" if not unbacked else "partly" if len(unbacked) < len(facts) else "none"
    if unbacked:
        return Claim(text=stretch.text, verdict="unsupported", chunk_ids=chunk_ids, level=level, unbacked=unbacked)
    picked = list(dict.fromkeys(found["picked"] for _, found in facts if found["picked"]))
    return Claim(text=stretch.text, verdict="supported", chunk_ids=chunk_ids, level=level,
                 supporting=[Support(chunk_id=chunk_id, sentence=sentence) for chunk_id, sentence in picked])


def _picked_sentence(answer: dict | None, sentences: list[tuple[str, str]]) -> tuple[str, str] | None:
    """The (chunk_id, sentence) Jev chose in the sentence question ("s<index>"), or None when it chose none."""
    match = re.fullmatch(r"s(\d+)", str((answer or {}).get("choice", "")))
    return sentences[int(match.group(1))] if match and int(match.group(1)) < len(sentences) else None


def _needs_source(uncited: list[Stretch], place: str | None, options: CheckOptions, started: list) -> list[Claim]:
    """The uncited stretches Jev says state something as fact that needs a source, as "uncited" claims, unless the
    pinned place's data backs them (asked in the same call); with hedges skipped, those Jev says are hedges as
    "skipped" claims."""
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
    if options.skip_hedges:
        questions |= {f"hedge_{index}": {"type": "noul", "criteria": _HEDGE_CRITERIA,
                                         "instructions": f"Is `sentence_{index}` a hedge rather than a statement of fact?"}
                      for index in range(len(uncited))}
    started.append(None)
    answers = ask_decision_model(state, questions)

    def verdict(index: int) -> Verdict | None:
        if options.skip_hedges and float(answers[f"hedge_{index}"]["noul"]) >= _HEDGE_AT:
            return "skipped"
        backed = place and float(answers[f"place_{index}"]["noul"]) >= options.supported_at
        return "uncited" if float(answers[f"needs_{index}"]["noul"]) >= SUPPORTED_AT and not backed else None
    return [Claim(text=stretch.text, verdict=found) for index, stretch in enumerate(uncited)
            if (found := verdict(index))]


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

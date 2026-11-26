"""
Grade the live claim check (agentic.claim_check) against a stronger referee model (#125).

A locked question set (the Uppsala place cases of place/cases_answers.jsonl, each with a pin and with the address
typed, plus the general Uppsala questions of referee_questions.json) is answered once by the agent and judged by the
claim check (`run`). A referee (Claude Opus 5.5 through OpenRouter) then labels every claim and uncited sentence of
the saved answers (`referee`), and the result is frozen as the reference, tagged with the check's version. `report`
gives the agreement between check and referee; `recheck` runs the current check on the reference's validation
answers, without new agent answers, so a change to the check can be measured against the frozen agreement.

    python -m agentic.claim_referee run --out data/agentic/referee-answers.json   # paid: the agent and Jev
    python -m agentic.claim_referee referee data/agentic/referee-answers.json --out data/agentic/referee-reference.json
    python -m agentic.claim_referee report data/agentic/referee-reference.json --out reports/claim_referee.md
    python -m agentic.claim_referee recheck data/agentic/referee-reference.json [--per-sentence ...]
    python -m agentic.claim_referee prompts data/agentic/referee-reference.json --per-sentence --out prompts/
    python -m agentic.claim_referee labels data/agentic/referee-reference.json prompts/
    python -m agentic.claim_referee tune data/agentic/referee-reference.json --out reports/claim_check_tune.md
    python -m agentic.claim_referee second data/agentic/referee-reference.json     # paid: the second referee
    python -m agentic.claim_referee cases data/agentic/referee-reference.json --out data/agentic/referee-cases.json
    python -m agentic.claim_referee measure data/agentic/referee-reference.json data/agentic/referee-cases.json --out reports/claim_check_measure.md
    python -m agentic.claim_referee improve data/agentic/referee-reference.json data/agentic/referee-cases.json --out reports/claim_check_improve.md

Tuning the check (#126): each change of agentic.claim_check.CheckOptions is rechecked on the reference alone, then the
kept ones together, against the current check rechecked in the same run (`tune`). A change is kept when it raises the
validation agreement without lowering the share of the referee's "no" claims still flagged; the tuning numbers are
shown, never decisive. A change that cuts the answer into other stretches (per_sentence) needs labels for them first:
`prompts` writes one referee prompt per answer with unlabelled stretches, to answer outside this code (no API
spend), and `labels` reads the replies back with the referee's parser. Making a winner live is a manual step: set it
as the CheckOptions default.

Every question is tuning or validation, split by case: tune the check on the tuning half and read the validation
half only to confirm. A cited claim agrees when the check calls it "supported" exactly when the referee says "yes"
("partly" counts as not backed); an uncited sentence agrees when the check flags it exactly when the referee says it
needed a source. A claim the check did not judge (the check failed, or its call did) is "not_checked" and stays out
of the agreement; a question card has no claims and is only counted.

A measure to trust (#128): `second` has a second referee of another model family label the same stretches (cost shown
first; the labels go beside the first referee's, never over them). A stretch the two disagree on is disputed and left
out of every agreement figure. `cases` builds the known-answer cases from the claims both call supported: the claim
untouched, with a number changed, and with its source swapped. `measure` runs the check on the agreed stretches and
the cases and times it per answer, one answer at a time.

A better check (#129): `improve` measures each change of IMPROVE_VARIANTS (every sentence of a claim judged against the
claim's sources, the question about what a claim adds, a level for a partly supported claim) with `measure`, against
the current check measured in the same run, then the winning ones together. A change wins when it beats the current
check on both the agreed stretches and the known-answer cases, on validation. Making the winner live is done by hand.
"""

import argparse
import hashlib
import json
import os
import re
import statistics
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import datetime
from functools import partial
from pathlib import Path

from agentic.claim_check import CheckOptions, stretches
from place.sources import SWEDEN_TZ

QUESTIONS_PATH = Path(__file__).with_name("referee_questions.json")
CLAIM_CHECK_PATH = Path(__file__).with_name("claim_check.py")
REFEREE_MODEL = "anthropic/claude-opus-5.5"
PRICE_IN, PRICE_OUT = 4.0, 20.0  # USD per million tokens of the referee model
SECOND_REFEREE_MODEL = "openai/gpt-6-luna"  # another model family than the referee (#128)
SECOND_PRICE = (0.10, 0.50)  # USD per million tokens (in, out) of the second referee model, OpenRouter 2026-11-25
KNOWN_KINDS = ("untouched", "number", "source")  # a known-answer case: the claim as it was, or made wrong by rule
SLOW_SECONDS = 2.0  # a check slower than this per answer gets a line in the measure report
CHARS_PER_TOKEN = 4
OUTPUT_TOKENS_PER_ITEM = 60  # a label is a short JSON object
REFEREE_ATTEMPTS = 2  # an unreadable reply is asked again once
MISSING_CHARS = 300  # of the referee's "missing", and of a failed run's error, kept
VERSION_CHARS = 12
PLACE_CONDITIONS = ("pin", "address")
SPLITS = ("tuning", "validation")
BACKED = ("yes", "partly", "no")
NEEDS = ("fact", "advice", "hedge", "summary")
SPLIT_LABELS = ("one", "several", "part")
# The changes `tune` measures from the command line, each one field of CheckOptions off its default
TUNE_VARIANTS = {"core": CheckOptions(question="core"), "threshold_0.3": CheckOptions(supported_at=0.3),
                 "threshold_0.7": CheckOptions(supported_at=0.7), "hedges": CheckOptions(skip_hedges=True),
                 "per_sentence": CheckOptions(per_sentence=True)}

# The changes `improve` measures from the command line (#129), each one field of CheckOptions off its default
IMPROVE_VARIANTS = {"additions": CheckOptions(additions=True), "levels": CheckOptions(levels=True)}

REFEREE_INSTRUCTIONS = """You referee claims taken from an assistant's answer about Swedish planning and building law.

You get numbered items. A CLAIM comes with the full text of every source it cites and the place data the assistant
was given (the place data counts as a source of every claim). An UNCITED sentence comes without sources.

For each CLAIM return:
- "supported": "yes" when its sources state everything it says, "partly" when they state some of it, "no" when they
  state none of it;
- "missing": what the claim says that no source states ("" when supported is "yes");
- "needs_source": "fact" (a rule, number, fee, deadline, place fact or legal reference stated as fact), "advice" (what
  the user should do), "hedge" (a caution or a "may"), "summary" (a restatement of what was said before);
- "split": "one" when it is one claim, "several" when it joins several claims, "part" when it is only part of one.

For each UNCITED sentence return "needed": true when it states something as fact that needs a source, else false.

Reply with JSON only: {"items": [{"n": 1, "supported": ..., "missing": ..., "needs_source": ..., "split": ...},
{"n": 2, "needed": ...}, ...]}, one entry per item, in order."""


def check_version() -> str:
    """The claim check's version: a hash of its source, so a reference tells which check it froze."""
    return hashlib.sha256(CLAIM_CHECK_PATH.read_bytes()).hexdigest()[:VERSION_CHARS]


def _load(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# --- the question set ---------------------------------------------------------------------------------------------

def load_questions(path: Path = QUESTIONS_PATH) -> dict:
    """The general questions and the validation place cases. Raises ValueError when the set is not locked."""
    data = _load(path)
    if not data.get("locked"):
        raise ValueError(f"the question set {path} is not locked")
    return data


def question_set(cases: list[dict], questions: dict) -> list[dict]:
    """Every question to answer, [{"id", "case", "condition", "split"}]: each place case with a pin and with the address
    (both in the case's split), then each general question."""
    validation = set(questions["validation_places"])
    items = [{"id": f"{case['id']}:{condition}", "case": case["id"], "condition": condition,
              "split": "validation" if case["id"] in validation else "tuning"}
             for case in cases for condition in PLACE_CONDITIONS]
    return items + [{"id": f"{general['id']}:general", "case": general["id"], "condition": "general",
                     "split": general["split"], "question": general["question"]} for general in questions["general"]]


# --- the run -------------------------------------------------------------------------------------------------------

def _judged_items(answer: str, check: dict, per_sentence: bool = False) -> list[dict]:
    """Every stretch of the answer (cut per sentence or not) with the check's verdict on it: a cited claim "supported"
    / "unsupported" / "uncited" (no cited chunk readable) / "skipped" (a hedge), or "not_checked" when the check left it
    out; an uncited sentence "uncited" when flagged, "skipped" when a hedge, "passed" when neither, or "not_checked"
    when the whole check failed."""
    verdicts = {claim["text"]: claim["verdict"] for claim in check.get("claims") or []}
    levels = {claim["text"]: claim["level"] for claim in check.get("claims") or [] if claim.get("level")}
    failed = check.get("status") != "checked"
    items = []
    for stretch in stretches(answer, per_sentence=per_sentence):
        if failed:
            verdict = "not_checked"
        elif stretch.chunk_ids:
            verdict = verdicts.get(stretch.text, "not_checked")
        else:
            verdict = verdicts.get(stretch.text) if verdicts.get(stretch.text) in ("uncited", "skipped") else "passed"
        items.append({"text": stretch.text, "cited": bool(stretch.chunk_ids), "chunk_ids": list(stretch.chunk_ids),
                      "check": verdict, **({"level": levels[stretch.text]} if stretch.text in levels else {})})
    return items


def _judge_row(row: dict, check: Callable[[str, list, str | None], dict]) -> None:
    """Put a saved answer to the claim check and store its items; a question card or an empty answer gets none."""
    if row["status"] != "answered":
        row["check"], row["items"] = None, []
        return
    result = check(row["answer"], row.get("seen") or [], row.get("place_text"))
    row["check"], row["items"] = result.get("status"), _judged_items(row["answer"], result)


def run_set(items: list[dict], answer: Callable[[dict], dict], check: Callable[[str, list, str | None], dict],
            path: Path, *, workers: int = 1) -> dict:
    """Answer every question once, put each answer to the check and save it to `path` after each one; questions
    already in `path` are not answered again. `answer(item)` -> {"answer", "questions", "seen", "place_text", "mode",
    "error"?}; `check(answer, seen, place_text)` -> {"status", "claims": [{"text", "verdict", "chunk_ids"}]}."""
    path = Path(path)
    result = (_load(path) if path.exists()
              else {"date": datetime.now(SWEDEN_TZ).isoformat(timespec="seconds"), "check_version": check_version(), "rows": []})
    done = {row["id"] for row in result["rows"]}
    lock = threading.Lock()

    def one(item: dict) -> None:
        got = answer(item)
        status = ("asked" if got.get("questions") else "answered" if got.get("answer") and not got.get("error")
                  else "error")
        row = {**item, "answer": got.get("answer") or "", "questions": got.get("questions") or [],
               "seen": list(got.get("seen") or []), "place_text": got.get("place_text"), "mode": got.get("mode"),
               "error": got.get("error"), "status": status}
        _judge_row(row, check)
        with lock:
            result["rows"].append(row)
            _save(path, result)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, [item for item in items if item["id"] not in done]))
    _save(path, result)
    return result


# --- the referee ---------------------------------------------------------------------------------------------------

def _referee_input(row: dict, chunk_of: Callable[[str], dict | None], chunk_text: Callable[[dict], str]) -> str:
    """The referee's prompt for one answer: the question, the place data in full, then every item numbered, each
    claim with the full text of its cited chunks."""
    parts = [f"Question: {row.get('question') or row['id']}",
             f"Place data the assistant was given:\n{row.get('place_text') or '(none)'}"]
    for n, entry in enumerate(row["items"], start=1):
        if not entry["cited"]:
            parts.append(f"[{n}] UNCITED: {entry['text']}")
            continue
        sources = []
        for chunk_id in entry["chunk_ids"]:
            chunk = chunk_of(chunk_id)
            sources.append(f"--- source {chunk_id}: {chunk.get('header') or chunk.get('title') or ''}\n{chunk_text(chunk)}"
                           if chunk else f"--- source {chunk_id}: (unreadable)")
        parts.append(f"[{n}] CLAIM: {entry['text']}\n" + "\n".join(sources))
    return "\n\n".join(parts)


def _parse_referee(text: str, items: list[dict]) -> list[dict] | None:
    """The referee's labels, one per item in order, or None when the reply is unreadable (not JSON, an item missing or
    a label outside its values)."""
    try:
        entries = json.loads(text[text.find("{"):text.rfind("}") + 1])["items"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    by_n = {entry.get("n"): entry for entry in entries if isinstance(entry, dict)}
    labels = []
    for n, item in enumerate(items, start=1):
        entry = by_n.get(n)
        if entry is None:
            return None
        if not item["cited"]:
            if not isinstance(entry.get("needed"), bool):
                return None
            labels.append({"needed": entry["needed"]})
        elif entry.get("supported") in BACKED and entry.get("needs_source") in NEEDS and entry.get("split") in SPLIT_LABELS:
            labels.append({"supported": entry["supported"], "missing": str(entry.get("missing") or "")[:MISSING_CHARS],
                           "needs_source": entry["needs_source"], "split": entry["split"]})
        else:
            return None
    return labels


def _ask_referee(model: str, prompt: str) -> tuple[str, float]:
    """The referee's reply to one answer's items, and what the call cost (USD)."""
    from llm import get_openai_client, get_response_output_text

    response = get_openai_client().responses.create(model=model, reasoning={"effort": "medium"},
                                                    instructions=REFEREE_INSTRUCTIONS, input=prompt)
    return get_response_output_text(response).strip(), float(getattr(response.usage, "cost", 0) or 0)


def _to_referee(rows: list[dict]) -> list[dict]:
    return [row for row in rows if row["status"] == "answered" and row["items"]]


def _chunk_of(get_chunk: Callable[[str], dict | None], row: dict) -> Callable[[str], dict | None]:
    from agentic.tools import resolve_cited

    return lambda chunk_id: resolve_cited(get_chunk, chunk_id, row.get("seen") or [])


def _estimate(rows: list[dict], get_chunk: Callable[[str], dict | None], chunk_text: Callable[[dict], str],
              price: tuple[float, float] = (PRICE_IN, PRICE_OUT)) -> dict:
    """What the referee will cost: {"calls", "input_tokens", "output_tokens", "dollars"} at its price, one call per
    answered row (a retry costs again)."""
    todo = _to_referee(rows)
    chars = sum(len(REFEREE_INSTRUCTIONS) + len(_referee_input(row, _chunk_of(get_chunk, row), chunk_text)) for row in todo)
    tokens_in = chars // CHARS_PER_TOKEN
    tokens_out = OUTPUT_TOKENS_PER_ITEM * sum(len(row["items"]) for row in todo)
    return {"calls": len(todo), "input_tokens": tokens_in, "output_tokens": tokens_out,
            "dollars": (tokens_in * price[0] + tokens_out * price[1]) / 1e6}


def referee(rows: list[dict], get_chunk: Callable[[str], dict | None], *, model: str = REFEREE_MODEL,
            ask: Callable[[str, str], tuple[str, float]] = _ask_referee, chunk_text: Callable[[dict], str] | None = None,
            announce: Callable[[dict], None] = print, workers: int = 4,
            on_row: Callable[[], None] | None = None) -> dict:
    """Have the referee label every item of the answered rows: each item gets `referee`. The cost estimate goes to
    `announce` before any call. An unreadable reply is asked again once; after a second one the row gets
    `referee` = "no_verdict" and its items no labels. Returns {"rows", "no_verdict", "cost", "estimate"}."""
    if chunk_text is None:
        from localrag.index import chunk_text
    expected = _estimate(rows, get_chunk, chunk_text)
    announce(expected)
    return _label_rows(_to_referee(rows), get_chunk, chunk_text, expected, key="referee", row_key="referee",
                       model=model, ask=ask, workers=workers, on_row=on_row)


def _label_rows(todo: list[dict], get_chunk: Callable[[str], dict | None], chunk_text: Callable[[dict], str],
                expected: dict, *, key: str, row_key: str, model: str, ask: Callable[[str, str], tuple[str, float]],
                workers: int, on_row: Callable[[], None] | None) -> dict:
    """Ask `model` for the labels of each row of `todo`, `workers` at a time: each item gets its label as `key` and the
    row `row_key` = `model`. An unreadable reply (or a failed call) is asked again once; after a second one the row gets
    `row_key` = "no_verdict" and its items no label. `on_row` runs after each row. Returns {"rows", "no_verdict",
    "cost", "estimate": `expected`}."""
    stats = {"rows": len(todo), "no_verdict": 0, "cost": 0.0, "estimate": expected}
    lock = threading.Lock()

    def one(row: dict) -> None:
        prompt, labels, cost = _referee_input(row, _chunk_of(get_chunk, row), chunk_text), None, 0.0
        for _ in range(REFEREE_ATTEMPTS):
            try:
                reply, spent = ask(model, prompt)
            except Exception as exc:  # noqa: BLE001 - a failed call counts as an unreadable reply
                reply, spent = type(exc).__name__, 0.0
            cost += spent
            labels = _parse_referee(reply, row["items"])
            if labels is not None:
                break
        with lock:
            stats["cost"] += cost
            if labels is None:
                row[row_key] = "no_verdict"
                stats["no_verdict"] += 1
            else:
                row[row_key] = model
                for entry, label in zip(row["items"], labels, strict=True):
                    entry[key] = label
            if on_row:
                on_row()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, todo))
    stats["cost"] = round(stats["cost"], 4)
    return stats


def freeze(rows: list[dict], path: Path, *, meta: dict | None = None) -> None:
    """Save the reference: the answers, the check's verdicts and the referee's labels, tagged with the check's
    version."""
    _save(Path(path), {"date": datetime.now(SWEDEN_TZ).isoformat(timespec="seconds"), "check_version": check_version(),
                       "referee_model": REFEREE_MODEL, **(meta or {}), "rows": rows})


# --- the report ----------------------------------------------------------------------------------------------------

_FLAGGED = ("unsupported", "uncited")  # a cited claim's verdicts that flag it; "supported" and "skipped" do not


def _agrees(entry: dict) -> bool | None:
    """Whether check and referee agree on an item; None when either has no verdict on it."""
    label = entry.get("referee")
    if not label or entry["check"] == "not_checked" or entry.get("standing") == "disputed":
        return None
    if entry["cited"]:
        return (entry["check"] not in _FLAGGED) == (label["supported"] == "yes")
    return (entry["check"] == "uncited") == label["needed"]


def _stats(entries: list[dict]) -> dict:
    agree = [_agrees(entry) for entry in entries]
    judged = [value for value in agree if value is not None]
    return {"claims": len(judged), "agree": sum(judged), "share": sum(judged) / len(judged) if judged else None}


def _grouped(entries: list[dict], key: Callable[[dict], str]) -> dict[str, dict]:
    groups: dict[str, list[dict]] = {}
    for entry in entries:
        groups.setdefault(key(entry), []).append(entry)
    return {name: _stats(mine) for name, mine in groups.items()}


def _entries(rows: list[dict]) -> list[dict]:
    return [{**entry, "row": row, "standing": standing(row, entry)} for row in rows for entry in row.get("items") or []]


def _label_word(label: dict | None, cited: bool) -> str:
    """A referee label as one word: "yes" / "partly" / "no" for a claim, "needed" / "not needed" for an uncited
    sentence, "no verdict" without a label."""
    if not isinstance(label, dict):
        return "no verdict"
    return label["supported"] if cited else "needed" if label["needed"] else "not needed"


def _split_numbers(rows: list[dict]) -> dict:
    """The agreement of one split's rows: on cited claims overall, per condition, per form (the referee's
    needs_source) and per split label, and on uncited sentences."""
    entries = _entries(rows)
    cited = [entry for entry in entries if entry["cited"] and _agrees(entry) is not None]
    return {"support": _stats(cited), "condition": _grouped(cited, lambda e: e["row"]["condition"]),
            "form": _grouped(cited, lambda e: e["referee"]["needs_source"]),
            "split": _grouped(cited, lambda e: e["referee"]["split"]),
            "uncited": _stats([entry for entry in entries if not entry["cited"]])}


def summary(rows: list[dict]) -> dict:
    """The report's numbers: the agreement per split (see _split_numbers), every disagreement, and the counts kept
    apart: question cards ("asked"), errors, items the check did not judge ("not_checked") and answers without a
    referee verdict ("no_verdict"). With a second referee (#128) the disputed items (`standing`) are left out of the
    agreement and the disagreements and listed in "disputed": [{"id", "split", "condition", "text", "referee",
    "second"}], each label "yes" / "partly" / "no" for a claim, "needed" / "not needed" for an uncited sentence, and
    "no verdict" for the second referee of a row it could not label."""
    disagreements = []
    for entry in _entries(rows):
        if _agrees(entry) is False:
            label = entry["referee"]
            disagreements.append({"id": entry["row"]["id"], "split": entry["row"]["split"],
                                  "condition": entry["row"]["condition"], "text": entry["text"], "check": entry["check"],
                                  "referee": (label["supported"] if entry["cited"]
                                              else "needed" if label["needed"] else "not needed"),
                                  "missing": label.get("missing", "")})
    disputed = [{"id": entry["row"]["id"], "split": entry["row"]["split"], "condition": entry["row"]["condition"],
                 "text": entry["text"], "referee": _label_word(entry.get("referee"), entry["cited"]),
                 "second": _label_word(entry.get("second"), entry["cited"])}
                for entry in _entries(rows) if entry["standing"] == "disputed"]
    return {"answers": len(rows), "asked": sum(row["status"] == "asked" for row in rows), "disputed": disputed,
            "errors": sum(row["status"] == "error" for row in rows),
            "not_checked": sum(entry["check"] == "not_checked" for entry in _entries(rows)),
            "no_verdict": sum(row.get("referee") == "no_verdict" for row in rows),
            **{split: _split_numbers([row for row in rows if row["split"] == split]) for split in SPLITS},
            "disagreements": disagreements}


def _pct(stats: dict) -> str:
    return "–" if stats["share"] is None else f"{stats['share']:.0%} ({stats['agree']}/{stats['claims']})"


def _table(head: list[str], body: list[list[str]]) -> str:
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(r) + " |" for r in body])


def _number(value: float | None) -> str:
    return "–" if value is None else f"{value:.1f}"


def _right(stats: dict) -> str:
    """Known-answer cases judged right, "95% (19/20)"; a dash without cases."""
    return "–" if stats["share"] is None else f"{stats['share']:.0%} ({stats['right']}/{stats['cases']})"


def _changes(options: dict) -> str:
    """The fields of CheckOptions that `options` sets off their default, "a=1, b=True"; "live check" when none."""
    default = asdict(CheckOptions())
    return ", ".join(f"{key}={value}" for key, value in options.items() if value != default[key]) or "live check"


def _slow_section(head: list[str], rows: list[list[str]]) -> list[str]:
    """The report lines of the answers over SLOW_SECONDS, none without any."""
    if not rows:
        return []
    return [f"## Slow answers (over {SLOW_SECONDS:g} s)", "",
            ("The calls of one answer run in parallel, so its time is the slowest call's plus the wait for a free"
             " worker, not the sum of its calls."), "", _table(head, rows), ""]


def report(rows: list[dict], *, title: str = "Claim check against the referee", meta: dict | None = None) -> str:
    """The report as Markdown: agreement per split, condition, form and split label, then every disagreement and,
    with a second referee, a "Disputed" section with every disputed stretch and both referees' labels."""
    numbers = summary(rows)
    lines = [f"# {title}", ""]
    lines += [f"- {key}: {value}" for key, value in (meta or {}).items()]
    lines += [f"- Answers: {numbers['answers']} (question cards {numbers['asked']}, errors {numbers['errors']})",
              f"- Items the check did not judge: {numbers['not_checked']}",
              f"- Answers without a referee verdict: {numbers['no_verdict']}", ""]
    for split in SPLITS:
        block = numbers[split]
        lines += [f"## {split.capitalize()}", "",
                  f"Cited claims: {_pct(block['support'])}. Uncited sentences: {_pct(block['uncited'])}.", ""]
        for name, key in (("Condition", "condition"), ("Form", "form"), ("Split label", "split")):
            lines += [_table([name, "Agreement"], [[group, _pct(stats)] for group, stats in sorted(block[key].items())]), ""]
    lines += ["## Disagreements", ""]
    lines += [_table(["Answer", "Split", "Check", "Referee", "Claim", "Lacks a source"],
                     [[d["id"], d["split"], d["check"], d["referee"], d["text"].replace("|", "\\|"),
                       d["missing"].replace("|", "\\|")] for d in numbers["disagreements"]])
              if numbers["disagreements"] else "None."]
    if any(row.get("second_referee") for row in rows):
        lines += ["", "## Disputed", "", _disputed_table(numbers["disputed"])]
    return "\n".join(lines) + "\n"


def _disputed_table(disputed: list[dict]) -> str:
    """Every disputed stretch with both referees' labels, as a Markdown table ("None." without any)."""
    if not disputed:
        return "None."
    return _table(["Answer", "Split", "Referee", "Second referee", "Stretch"],
                  [[d["id"], d["split"], d["referee"], d["second"], d["text"].replace("|", "\\|")] for d in disputed])


# --- the second referee and the known-answer cases (#128) -----------------------------------------------------------

def second_referee(rows: list[dict], get_chunk: Callable[[str], dict | None], *, model: str = SECOND_REFEREE_MODEL,
                   price: tuple[float, float] = SECOND_PRICE,
                   ask: Callable[[str, str], tuple[str, float]] = _ask_referee,
                   chunk_text: Callable[[dict], str] | None = None, announce: Callable[[dict], None] = print,
                   workers: int = 4, on_row: Callable[[], None] | None = None) -> dict:
    """Have a second referee, of another model family, label the items the first referee labelled.

    Every answered row whose `referee` is a model name and that has no `second_referee` yet is asked once, with the
    prompt `referee` sends (the same instructions, items and sources). Each item gets `second`, a label of the same
    shape as `referee`; the row gets `second_referee` = `model`. An unreadable reply is asked again once; after a
    second one the row gets `second_referee` = "no_verdict" and its items no `second`. A row that already has
    `second_referee` is not asked again, so an interrupted run resumes.

    The cost estimate at `price` (USD per million tokens, in and out) goes to `announce` before any call, for the
    rows still to ask. Nothing else in the rows changes: not an item's `referee`, `check` or text, nor a row's
    `referee` or `labels` (ADR-0020).

    Returns {"rows": rows asked, "no_verdict", "cost", "estimate"} like `referee`."""
    if chunk_text is None:
        from localrag.index import chunk_text
    todo = [row for row in _to_referee(rows)
            if row.get("referee") not in (None, "no_verdict") and not row.get("second_referee")]
    expected = _estimate(todo, get_chunk, chunk_text, price)
    announce(expected)
    return _label_rows(todo, get_chunk, chunk_text, expected, key="second", row_key="second_referee", model=model,
                       ask=ask, workers=workers, on_row=on_row)


def standing(row: dict, entry: dict) -> str:
    """Where an item of `row` stands between the two referees: "single", "agreed" or "disputed".

    - "single": the row has no `second_referee` (no second referee ran), or the item has no first label.
    - "disputed": the row's `second_referee` is "no_verdict", or the two labels differ on two levels: for a cited claim
      one says "yes" and the other "partly" or "no"; for an uncited sentence their `needed` differ.
    - "agreed": otherwise ("partly" against "no" is agreed: both say the claim is not backed).

    A disputed item is left out of every agreement figure of this module (`summary`, `report`, `recheck`, `tune`,
    `measure`), like an item the check did not judge; a single one counts as before (ADR-0022)."""
    first, second = entry.get("referee"), entry.get("second")
    if not row.get("second_referee") or not isinstance(first, dict):
        return "single"
    if row["second_referee"] == "no_verdict":
        return "disputed"
    if not isinstance(second, dict):
        return "single"
    if entry["cited"]:
        same = (first.get("supported") == "yes") == (second.get("supported") == "yes")
    else:
        same = bool(first.get("needed")) == bool(second.get("needed"))
    return "agreed" if same else "disputed"


_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_REFERENCE_AFTER = re.compile(r"\s*(?:[a-z]\s)?(?:kap\b|§)")  # "9 kap.", "4 §", "4 a §": a legal reference, not a figure


def _plain(number: str) -> str:
    """A number as written ("30,0", "4.50") in one form ("30", "4.5")."""
    whole, _, decimals = number.replace(",", ".").partition(".")
    decimals = decimals.rstrip("0")
    return f"{int(whole)}.{decimals}" if decimals else str(int(whole))


def _number_changed(text: str, sources: list[str], place: str) -> str | None:
    """`text` with one of its numbers replaced so that no source states the new one: the first number of the claim
    that a source states and that is not part of a legal reference ("9 kap.", "4 §", "(2010:900)") becomes a number
    found in no source, in the place data or elsewhere in the claim. None when the claim has no such number."""
    stated = {_plain(number) for source in sources for number in _NUMBER.findall(source)}
    taken = stated | {_plain(number) for number in _NUMBER.findall(place)} | {_plain(n) for n in _NUMBER.findall(text)}
    digits = {run for source in [*sources, place, text] for run in re.findall(r"\d+", source)}
    for match in _NUMBER.finditer(text):
        number = match.group()
        around = text[max(0, match.start() - 1):match.start()] + text[match.end():match.end() + 1]
        if _plain(number) not in stated or ":" in around or _REFERENCE_AFTER.match(text, match.end()):
            continue
        whole, separator, decimals = re.match(r"(\d+)([.,]?)(\d*)", number).groups()
        new = int(whole) + max(1, round(int(whole) / 2))
        while _plain(f"{new}.{decimals or 0}") in taken or str(new) in digits:
            new += 1
        return f"{text[:match.start()]}{new}{separator}{decimals}{text[match.end():]}"
    return None


def _known_case(row: dict, n: int, base: str, kind: str, text: str, chunk_ids: list[str], expect: str) -> dict:
    """One known-answer case of the `n`th item of `row` (its text `base`), as `known_cases` returns it."""
    return {"id": f"{row['id']}#{n}:{kind}", "row": row["id"], "case": row["case"], "split": row["split"],
            "condition": row.get("condition"), "kind": kind, "text": text, "chunk_ids": chunk_ids,
            "seen": list(dict.fromkeys([*(row.get("seen") or []), *chunk_ids])), "place_text": row.get("place_text"),
            "expect": expect, "from": base}


def known_cases(reference: dict, get_chunk: Callable[[str], dict | None], *,
                chunk_text: Callable[[dict], str] | None = None) -> list[dict]:
    """The known-answer cases of a reference: claims whose right verdict is known by construction.

    The base is every cited item both referees label "yes" (`standing` "agreed") in an answered row of a split. Each
    base claim gives:
    - one "untouched" case: the claim as it is, expected "supported";
    - at most one "number" case: one number of the claim that also stands in the text of a cited chunk, replaced by a
      number that stands in none of its cited chunks nor in the row's place data; expected "flagged". A claim with no
      such number gives none;
    - at most one "source" case: the claim as it is, citing instead one chunk that an answer of another case cites and
      that no answer of the claim's own case cites; expected "flagged". Only for a row without place data (the place
      data backs claims on its own), and only when such a chunk can be read (ADR-0023).

    Each case is {"id": "<row id>#<n>:<kind>" (n: the item's place in the row, from 1), "row": row id, "case", "split",
    "condition", "kind", "text", "chunk_ids", "seen": the row's seen ids plus the case's chunk ids, "place_text",
    "expect": "supported" | "flagged", "from": the base claim's text}. The same reference gives the same cases, in the
    same order, on every call. Without a second referee there is no agreed claim and the list is empty. The reference
    is not changed."""
    if chunk_text is None:
        from localrag.index import chunk_text
    rows = [row for row in reference.get("rows") or []
            if row.get("split") in SPLITS and row.get("status") == "answered"]
    cited_in: dict[str, set[str]] = {}  # case -> the chunk ids its answers cite, as resolved
    for row in rows:
        chunk_of = _chunk_of(get_chunk, row)
        for entry in row.get("items") or []:
            for chunk_id in entry.get("chunk_ids") or []:
                chunk = chunk_of(chunk_id)
                cited_in.setdefault(row["case"], set()).update({chunk_id, str((chunk or {}).get("chunk_id") or chunk_id)})
    cases = []
    for row in rows:
        chunk_of = _chunk_of(get_chunk, row)
        others = sorted({chunk_id for case, ids in cited_in.items() if case != row["case"] for chunk_id in ids}
                        - cited_in.get(row["case"], set()))
        for n, entry in enumerate(row.get("items") or [], start=1):
            both_yes = (entry.get("cited") and standing(row, entry) == "agreed"
                        and entry["referee"].get("supported") == "yes")
            if not both_yes:
                continue

            case = partial(_known_case, row, n, entry["text"])
            cases.append(case("untouched", entry["text"], list(entry["chunk_ids"]), "supported"))
            sources = [chunk_text(chunk) for chunk_id in entry["chunk_ids"] if (chunk := chunk_of(chunk_id))]
            changed = _number_changed(entry["text"], sources, row.get("place_text") or "")
            if changed:
                cases.append(case("number", changed, list(entry["chunk_ids"]), "flagged"))
            if not row.get("place_text") and others:
                start = int(hashlib.sha256(f"{row['id']}#{n}".encode()).hexdigest(), 16) % len(others)
                swap = next((chunk_id for chunk_id in others[start:] + others[:start] if get_chunk(chunk_id)), None)
                if swap:
                    cases.append(case("source", entry["text"], [swap], "flagged"))
    return cases


_LEVEL_LABEL = {"full": "yes", "partly": "partly", "none": "no"}  # the check's level -> the referee label it matches


def measure(reference: dict, cases: list[dict], check: Callable[[str, list, str | None], dict], *,
            options: CheckOptions | None = None, workers: int = 4) -> dict:
    """Measure a check on the trusted measure: the agreed stretches, the known-answer cases and its time per answer.

    `check` is the claim check run with `options` (None: the live check), returning its event plus "calls" and
    "seconds" (as `_live_check` does). The saved answers are checked one at a time, as the chat does, so the time is
    what a user waits; the known-answer cases are then checked `workers` at a time, each as an answer holding only the
    case's claim with its citations.

    Returns {"options", "version", "tuning": split, "validation": split}, each split:
    - "agreement": {"cited", "uncited", "all"}, each {"claims", "agree", "share"}, over the agreed stretches only;
    - "disputed": the disputed stretches, "single": the stretches no second referee labelled (both left out);
    - "known": {kind: {"cases", "right", "share"}} for each of KNOWN_KINDS: an "untouched" case is right when the
      check does not flag it, a "number" or "source" case when the check flags it ("unsupported" or "uncited");
      share None without cases;
    - "not_checked": the stretches and cases the check did not judge (left out of every figure above);
    - "answers": the answers checked; "seconds": {"median", "max"} per answer; "calls": the mean per answer;
    - "slow": [{"id", "seconds", "calls", "claims"}] for each answer over SLOW_SECONDS, slowest first;
    - "wrong" (#129): [{"id", "kind", "text", "verdict"}] for each known-answer case the check judged and got wrong
      (an untouched one flagged, a changed one not flagged), in the order of `cases`;
    - "levels" (#129): {"claims", "match", "share"}, the three-level match: over the cited stretches the two referees
      give the same label ("yes" / "partly" / "no") and the check gave a `level`, how many levels equal that label
      ("full" / "partly" / "none"). {"claims": 0, "match": 0, "share": None} for a check that gives no levels.

    The reference and the cases are not changed."""
    options = options or CheckOptions()
    rows = [row for row in reference.get("rows") or [] if row.get("split") in SPLITS]
    answered = [row for row in rows if row.get("status") == "answered"]
    timed = []  # one answer at a time, as the chat runs the check
    for row in answered:
        began = time.monotonic()
        result = check(row["answer"], row.get("seen") or [], row.get("place_text"))
        timed.append({"row": row, "result": result, "seconds": result.get("seconds", time.monotonic() - began),
                      "calls": result.get("calls", 0)})

    def judge(case: dict) -> str:
        cited = "; ".join(f"c:{chunk_id}" for chunk_id in case["chunk_ids"])
        answer = f"{case['text']} [{cited}]."
        found = [entry for entry in _judged_items(answer, check(answer, case.get("seen") or [], case.get("place_text")))
                 if entry["cited"]]
        return found[0]["check"] if len(found) == 1 else "not_checked"

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        verdicts = list(pool.map(judge, cases))
    out = {"options": asdict(options), "version": check_version()}
    for split in SPLITS:
        mine = [one for one in timed if one["row"]["split"] == split]
        items = [entry for one in mine
                 for entry in _labelled(one["row"], _judged_items(one["row"]["answer"], one["result"], options.per_sentence))]
        judged = [entry for entry in items if entry["check"] != "not_checked"]
        known, missed = {}, 0
        wrong = [{"id": case["id"], "kind": case["kind"], "text": case["text"], "verdict": verdict}
                 for case, verdict in zip(cases, verdicts, strict=True)
                 if case["split"] == split and verdict != "not_checked"
                 and (verdict in _FLAGGED) != (case["kind"] != "untouched")]
        same = [entry for entry in judged if entry["standing"] == "agreed" and entry["cited"] and entry.get("level")
                and entry["referee"]["supported"] == entry["second"]["supported"]]
        match = sum(_LEVEL_LABEL[entry["level"]] == entry["referee"]["supported"] for entry in same)
        for kind in KNOWN_KINDS:
            got = [verdict for case, verdict in zip(cases, verdicts, strict=True)
                   if case["split"] == split and case["kind"] == kind]
            missed += sum(verdict == "not_checked" for verdict in got)
            got = [verdict for verdict in got if verdict != "not_checked"]
            right = sum((verdict in _FLAGGED) == (kind != "untouched") for verdict in got)
            known[kind] = {"cases": len(got), "right": right, "share": right / len(got) if got else None}
        seconds = [one["seconds"] for one in mine]
        out[split] = {
            "agreement": _agreement([entry for entry in judged if entry["standing"] == "agreed"]),
            "disputed": sum(entry["standing"] == "disputed" for entry in judged),
            "single": sum(entry["standing"] == "single" for entry in judged),
            "known": known, "not_checked": len(items) - len(judged) + missed, "answers": len(mine), "wrong": wrong,
            "levels": {"claims": len(same), "match": match, "share": match / len(same) if same else None},
            "seconds": {"median": statistics.median(seconds) if seconds else None, "max": max(seconds, default=None)},
            "calls": statistics.mean(one["calls"] for one in mine) if mine else None,
            "slow": sorted(({"id": one["row"]["id"], "seconds": one["seconds"], "calls": one["calls"],
                             "claims": len(one["result"].get("claims") or [])}
                            for one in mine if one["seconds"] > SLOW_SECONDS), key=lambda slow: -slow["seconds"])}
    return out


def _match(levels: dict) -> str:
    return "–" if levels["share"] is None else f"{levels['share']:.0%} ({levels['match']}/{levels['claims']})"


def _wrong_rows(wrong: list[dict]) -> list[list[str]]:
    """The known-answer cases a check got wrong as table rows: case id, kind, verdict, claim."""
    return [[case["id"], case["kind"], case["verdict"], case["text"].replace("|", "\\|")] for case in wrong]


def measure_report(result: dict, *, title: str = "Claim check on the trusted measure",
                   disputed: list[dict] | None = None) -> str:
    """A `measure` result as Markdown: per split the agreement on the agreed stretches (cited, uncited, all) with the
    count of disputed ones, a row per kind of known-answer case, the time per answer (median, max) with the mean
    number of decision model calls, and a "Slow answers" table when any answer took over SLOW_SECONDS; then
    `disputed` (from `summary`), every disputed stretch with both referees' labels. Since #129 also, per split, a
    "Match on three levels" row (a dash for a check that gives no levels) and, when the check got any known-answer
    case wrong, a "Known-answer cases the check got wrong" table with each case's id, kind, verdict and text."""
    names = {"untouched": "Untouched claims passed", "number": "Number-changed claims caught",
             "source": "Source-swapped claims caught"}
    lines = [f"# {title}", "", f"- check: {result.get('version')}",
             f"- options: {', '.join(f'{key}={value}' for key, value in (result.get('options') or {}).items())}", ""]
    slow, wrong = [], []
    for split in SPLITS:
        block = result[split]
        left_out = (f"Disputed stretches left out: {block['disputed']} (stretches no second referee labelled: "
                    f"{block['single']}; not checked: {block['not_checked']}).")
        lines += [f"## {split.capitalize()}", "", left_out, "",
                  _table(["Measure", "Result"],
                         [["Agreement on agreed cited claims", _pct(block["agreement"]["cited"])],
                          ["Agreement on agreed uncited sentences", _pct(block["agreement"]["uncited"])],
                          ["Agreement on all agreed stretches", _pct(block["agreement"]["all"])],
                          ["Match on three levels", _match(block["levels"])],
                          *([names[kind], _right(block["known"][kind])] for kind in KNOWN_KINDS),
                          ["Seconds per answer, median", _number(block["seconds"]["median"])],
                          ["Seconds per answer, max", _number(block["seconds"]["max"])],
                          ["Decision model calls per answer, mean", _number(block["calls"])],
                          ["Answers", str(block["answers"])]]), ""]
        slow += [[split, one["id"], _number(one["seconds"]), str(one["calls"]), str(one["claims"])] for one in block["slow"]]
        wrong += [[split, *row] for row in _wrong_rows(block["wrong"])]
    lines += _slow_section(["Split", "Answer", "Seconds", "Calls", "Claims judged"], slow)
    if wrong:
        lines += ["## Known-answer cases the check got wrong", "",
                  _table(["Split", "Case", "Kind", "Verdict", "Claim"], wrong), ""]
    if disputed is not None:
        lines += ["## Stretches the referees dispute", "", _disputed_table(disputed), ""]
    return "\n".join(lines)


# --- a better check (#129) ------------------------------------------------------------------------------------------

def _known_right(split: dict) -> dict:
    """The known-answer cases of a measured split over the three kinds together: {"cases", "right", "share"}."""
    cases = sum(split["known"][kind]["cases"] for kind in KNOWN_KINDS)
    right = sum(split["known"][kind]["right"] for kind in KNOWN_KINDS)
    return {"cases": cases, "right": right, "share": right / cases if cases else None}


def _missed(variant: dict, baseline: dict) -> list[str]:
    """The measures on which a measured variant does not beat the baseline on validation, of "agreement" (the
    agreement over all agreed stretches) and "known" (the known-answer cases right over the three kinds); a share that
    is None on either side is not beaten."""
    mine, base = variant["validation"], baseline["validation"]
    pairs = (("agreement", mine["agreement"]["all"]["share"], base["agreement"]["all"]["share"]),
             ("known", _known_right(mine)["share"], _known_right(base)["share"]))
    return [name for name, share, base_share in pairs if share is None or base_share is None or share <= base_share]


def wins(variant: dict, baseline: dict) -> bool:
    """Whether a change of the check wins: given two `measure` results on the same reference and cases, the variant
    does better than the baseline on both measures of the validation split:
    - its agreement over all agreed stretches is higher, and
    - its share of known-answer cases judged right, over the three kinds together, is higher.
    A share that is None (nothing judged) on either side never wins. The tuning split never decides."""
    return not _missed(variant, baseline)


def improve(reference: dict, cases: list[dict],
            check_with: Callable[[CheckOptions], Callable[[str, list, str | None], dict]], *,
            variants: dict[str, CheckOptions] | None = None, workers: int = 4) -> dict:
    """Measure each change of the check against the current check, all measured in this run (ADR-0021).

    `check_with(options)` gives the claim check run with those options; `variants` (None: IMPROVE_VARIANTS) names each
    change. The baseline is CheckOptions() measured now with `measure`; each variant is measured the same way and
    wins per `wins`. When two or more win, their changed fields together are measured as "combined".

    Returns {"baseline": measure, "variants": {name: {**measure, "wins": bool, "why": [...]}}, "combined":
    {**measure, "wins", "why"} or None, "won": [names that win, in the order given], "live": name, "combined" or None,
    "options": the options to make live as a dict, None when nothing wins}:
    - "why": the measures the run did not beat the baseline on, of "agreement" and "known" (empty when it wins);
    - "live": "combined" when it wins against the baseline and has a higher validation agreement than every winning
      variant alone; else the winning variant with the highest validation agreement (the first given, on a tie);
      None when nothing wins.

    The reference and the cases are not changed; making "options" the CheckOptions defaults is done by hand."""
    variants = IMPROVE_VARIANTS if variants is None else variants

    def run(options: CheckOptions) -> dict:
        return measure(reference, cases, check_with(options), options=options, workers=workers)

    def share(result: dict) -> float:
        return result["validation"]["agreement"]["all"]["share"] or 0.0

    baseline = run(CheckOptions())
    measured = {}
    for name, options in variants.items():
        result = run(options)
        why = _missed(result, baseline)
        measured[name] = {**result, "wins": not why, "why": why}
    won = [name for name, result in measured.items() if result["wins"]]
    combined = None
    if len(won) >= 2:
        result = run(_together([variants[name] for name in won]))
        why = _missed(result, baseline)
        combined = {**result, "wins": not why, "why": why}
    live = max(won, key=lambda name: share(measured[name]), default=None)
    if combined is not None and combined["wins"] and all(share(combined) > share(measured[name]) for name in won):
        live = "combined"
    options = None if live is None else combined["options"] if live == "combined" else measured[live]["options"]
    return {"baseline": baseline, "variants": measured, "combined": combined, "won": won, "live": live,
            "options": options}


def improve_report(result: dict) -> str:
    """An `improve` result as Markdown: a table with a row for the current check, each change and the combination:
    validation agreement on the agreed stretches, the known-answer cases right (together and per kind), the match on
    three levels, the seconds per answer (median, max), the decision model calls per answer, and "Wins" (yes, or no
    with the measures of "why"); the tuning figures in a second table, for reading. Then a "Slow answers" section for
    each run with an answer over SLOW_SECONDS (run, answer, seconds, calls, claims), and the known-answer cases the
    current check and the run to make live got wrong. It ends with "Make live: <name> (<its changed options>), as the
    CheckOptions default." or, when nothing wins, "No change wins: the live check stays as it is." with each run's
    "why"."""
    def verdict(run: dict) -> str:
        return "yes" if run["wins"] else "no: " + ", ".join(run["why"])

    runs = [("current check", result["baseline"], "")]
    runs += [(name, run, verdict(run)) for name, run in result["variants"].items()]
    if result["combined"]:
        runs.append(("combined", result["combined"], verdict(result["combined"])))
    head = ["Run", "Options", "Agreement", "Cases right", "Untouched passed", "Number caught", "Source caught",
            "Three levels", "Seconds median", "Seconds max", "Calls", "Wins"]

    def table(split: str) -> str:
        body = []
        for name, run, won in runs:
            block = run[split]
            body.append([name, _changes(run["options"]), _pct(block["agreement"]["all"]), _right(_known_right(block)),
                         *(_right(block["known"][kind]) for kind in KNOWN_KINDS), _match(block["levels"]),
                         _number(block["seconds"]["median"]), _number(block["seconds"]["max"]),
                         _number(block["calls"]), won])
        return _table(head, body)

    lines = ["# A better claim check", "",
             f"- check: {result['baseline'].get('version')}",
             ("- A change wins when, on validation, both its agreement on the stretches the two referees agree on and "
              "its share of known-answer cases right are higher than the current check's, measured in the same run. "
              "Tuning is shown, never decisive."), "",
             "## Validation", "", table("validation"), "", "## Tuning", "", table("tuning"), ""]
    slow = [[name, split, one["id"], _number(one["seconds"]), str(one["calls"]), str(one["claims"])]
            for name, run, _ in runs for split in SPLITS for one in run[split]["slow"]]
    lines += _slow_section(["Run", "Split", "Answer", "Seconds", "Calls", "Claims judged"], slow)
    live = result["live"]
    listed = [("current check", result["baseline"])]
    if live is not None:
        listed.append((live, result["combined"] if live == "combined" else result["variants"][live]))
    for name, run in listed:
        wrong = [[split, *row] for split in SPLITS for row in _wrong_rows(run[split]["wrong"])]
        lines += [f"## Known-answer cases the {name} got wrong", "",
                  _table(["Split", "Case", "Kind", "Verdict", "Claim"], wrong) if wrong else "None.", ""]
    if live is None:
        lines += ["No change wins: the live check stays as it is.", ""]
        lines += [f"- {name}: not better on {', '.join(run['why'])}" for name, run, _ in runs[1:]]
    else:
        lines.append(f"Make live: {live} ({_changes(result['options'])}), as the CheckOptions default.")
    return "\n".join(lines) + "\n"


# --- the recheck ---------------------------------------------------------------------------------------------------

def recheck(reference: dict, check: Callable[[str, list, str | None], dict], *,
            options: CheckOptions | None = None, workers: int = 4) -> dict:
    """Run a check on the reference's saved answers (no new agent answers) and set its agreement with the referee's
    labels next to the frozen agreement, per split.

    `check` is the claim check run with `options` (None: CheckOptions(), the live check); the answers are cut into
    stretches as those options cut them, and each stretch takes its label from the frozen items, else from the row's
    `labels` map (written by `add_labels`), else stays unlabelled.

    Returns {"options": the options as a dict, "frozen_version", "version", "tuning": split, "validation": split},
    each split {"frozen": agreement, "now": agreement, "no_claims", "no_still_flagged", "unlabelled"}:
    - an agreement is {"cited", "uncited", "all"}, each {"claims", "agree", "share"} as in the report;
    - "no_claims": the referee's "no" claims the check judged; "no_still_flagged": the share of them the check
      flags (a "skipped" claim is not flagged, like a "supported" one), None without any;
    - "unlabelled": the stretches judged now with no label (left out of the agreement).

    A claim whose call failed, or a row whose check failed, is "not_checked" and stays out of the agreement. With a
    second referee (#128) a disputed stretch (`standing`) stays out of "frozen", "now" and "no_claims" as well, and
    each split gets "disputed": the stretches judged now that are disputed. The reference is not changed."""
    options = options or CheckOptions()
    rows = [row for row in reference.get("rows") or [] if row.get("split") in SPLITS]
    answered = [row for row in rows if row["status"] == "answered"]
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        results = list(pool.map(lambda row: check(row["answer"], row.get("seen") or [], row.get("place_text")),
                                answered))
    now_items = {id(row): _labelled(row, _judged_items(row["answer"], result, options.per_sentence))
                 for row, result in zip(answered, results, strict=True)}
    out = {"options": asdict(options), "frozen_version": reference.get("check_version"), "version": check_version()}
    for split in SPLITS:
        mine = [row for row in rows if row["split"] == split]
        frozen = [{**entry, "standing": standing(row, entry)} for row in mine for entry in row.get("items") or []]
        now = [entry for row in mine for entry in now_items.get(id(row), [])]
        judged = [entry for entry in now if entry["check"] != "not_checked"]
        disputed = [entry for entry in judged if entry.get("standing") == "disputed"]
        judged = [entry for entry in judged if entry.get("standing") != "disputed"]
        labelled = [entry for entry in judged if entry.get("referee")]
        no = [entry for entry in labelled if entry["cited"] and entry["referee"]["supported"] == "no"]
        out[split] = {"frozen": _agreement(frozen), "now": _agreement(labelled), "no_claims": len(no),
                      "no_still_flagged": (sum(entry["check"] in _FLAGGED for entry in no) / len(no)) if no else None,
                      "unlabelled": len(judged) - len(labelled), "disputed": len(disputed)}
    return out


def _labelled(row: dict, items: list[dict]) -> list[dict]:
    """`items` (stretches judged now) each with its referee label: from the row's frozen item of the same text, else
    from the row's `labels` map; none when neither has one."""
    labels = _labels_of(row)
    seconds = {entry["text"]: entry["second"] for entry in row.get("items") or [] if isinstance(entry.get("second"), dict)}
    out = []
    for entry in items:
        if entry["text"] in labels:
            entry = {**entry, "referee": labels[entry["text"]]}
        if entry["text"] in seconds:
            entry = {**entry, "second": seconds[entry["text"]]}
        frozen = any(one["text"] == entry["text"] for one in row.get("items") or [])
        out.append({**entry, "standing": standing(row, entry) if frozen else "single"})
    return out


def _labels_of(row: dict) -> dict[str, dict]:
    """The referee labels a row holds, {stretch text: label}: those on its frozen items, else those of its `labels`
    map."""
    return {**(row.get("labels") or {}),
            **{entry["text"]: entry["referee"] for entry in row.get("items") or [] if isinstance(entry.get("referee"), dict)}}


def _agreement(entries: list[dict]) -> dict:
    """The agreement on cited claims, uncited sentences and all items: {"cited", "uncited", "all"}."""
    return {"cited": _stats([entry for entry in entries if entry["cited"]]),
            "uncited": _stats([entry for entry in entries if not entry["cited"]]), "all": _stats(entries)}


def keeps(variant: dict, baseline: dict) -> bool:
    """Whether a change is kept: given two `recheck` results on the same reference, the variant's validation agreement
    over all items is higher than the baseline's, its validation "no_still_flagged" is not lower, and it left no
    validation stretch unlabelled. The tuning split never decides."""
    mine, base = variant["validation"], baseline["validation"]
    share, base_share = mine["now"]["all"]["share"], base["now"]["all"]["share"]
    if share is None or (base_share is not None and share <= base_share):
        return False
    flagged, base_flagged = mine["no_still_flagged"], base["no_still_flagged"]
    if base_flagged is not None and (flagged is None or flagged < base_flagged):
        return False
    return mine["unlabelled"] == 0


def tune(reference: dict, check_with: Callable[[CheckOptions], Callable[[str, list, str | None], dict]], *,
         variants: dict[str, CheckOptions], workers: int = 4) -> dict:
    """Measure each change of the check against the current check, both rechecked in this run.

    `check_with(options)` gives the claim check run with those options; `variants` names each change (one field of
    CheckOptions off its default). The baseline is CheckOptions() rechecked now, not the frozen numbers. Each variant
    is rechecked and kept per `keeps`; when two or more are kept, their changed fields together are rechecked as
    "combined".

    Returns {"baseline": recheck, "variants": {name: {**recheck, "kept": bool}}, "combined": {**recheck, "options"} or
    None, "kept": [names kept, in the order given], "live": what to make live}: "combined" when it is kept against the
    baseline and beats every kept variant alone on validation agreement, else the kept variant with the highest
    validation agreement, None when nothing is kept."""
    def run(options: CheckOptions) -> dict:
        return recheck(reference, check_with(options), options=options, workers=workers)

    def share(result: dict) -> float:
        return result["validation"]["now"]["all"]["share"] or 0.0

    baseline = run(CheckOptions())
    measured = {name: {**run(options), "kept": False} for name, options in variants.items()}
    for result in measured.values():
        result["kept"] = keeps(result, baseline)
    kept = [name for name, result in measured.items() if result["kept"]]
    combined = None
    if len(kept) >= 2:
        merged = _together([variants[name] for name in sorted(kept, key=lambda name: share(measured[name]))])
        combined = {**run(merged), "options": asdict(merged)}
    best = max(kept, key=lambda name: share(measured[name]), default=None)
    if combined is not None and keeps(combined, baseline) and all(share(combined) > share(measured[name]) for name in kept):
        live = "combined"
    else:
        live = best
    return {"baseline": baseline, "variants": measured, "combined": combined, "kept": kept, "live": live}


def _together(changes: list[CheckOptions]) -> CheckOptions:
    """The live check with every field the given options change; where two change the same field, the later one
    wins."""
    default, merged = asdict(CheckOptions()), CheckOptions()
    for options in changes:
        merged = replace(merged, **{key: value for key, value in asdict(options).items() if value != default[key]})
    return merged


def tune_report(result: dict) -> str:
    """The tune result as Markdown: one row per run (baseline, each variant, combined) with its options, the frozen
    and current validation and tuning agreement, the "no" claims still flagged, the unlabelled stretches and whether it
    is kept; then what to make live, or a line saying no change is kept."""
    runs = [("baseline", result["baseline"], "")]
    runs += [(name, run, "yes" if run["kept"] else "no") for name, run in result["variants"].items()]
    if result["combined"]:
        combined = result["combined"]
        runs.append(("combined", combined, "yes" if result["live"] == "combined" else "no"))
    body = []
    for name, run, kept in runs:
        validation, tuning = run["validation"], run["tuning"]
        still = validation["no_still_flagged"]
        body.append([name, _changes(run["options"]), _pct(validation["frozen"]["all"]), _pct(validation["now"]["all"]),
                     _pct(tuning["frozen"]["all"]), _pct(tuning["now"]["all"]),
                     "–" if still is None else f"{still:.0%} of {validation['no_claims']}",
                     str(validation["unlabelled"]), kept])
    baseline = result["baseline"]
    lines = ["# Claim check tuning", "",
             f"- Frozen check: {baseline['frozen_version']}; current check: {baseline['version']}",
             ("- A change is kept when its validation agreement rises and the referee's \"no\" claims it still flags "
              "do not fall, with no validation stretch unlabelled. Tuning is shown, never decisive."), "",
             _table(["Run", "Options", "Validation frozen", "Validation now", "Tuning frozen", "Tuning now",
                     "\"No\" still flagged", "Unlabelled", "Kept"], body), ""]
    live = result["live"]
    if live is None:
        lines.append("No change is kept: the live check stays as it is.")
    else:
        options = result["combined"]["options"] if live == "combined" else result["variants"][live]["options"]
        lines.append(f"Make live: {live} ({_changes(options)}), as the CheckOptions default.")
    return "\n".join(lines) + "\n"


def prompts(rows: list[dict], get_chunk: Callable[[str], dict | None], *, options: CheckOptions | None = None,
            chunk_text: Callable[[dict], str] | None = None) -> list[dict]:
    """The referee prompts for the stretches that have no label, to answer outside this code.

    Each answered row is cut into stretches as `options` cut it (None: the live check); a stretch is labelled when a
    frozen item or the row's `labels` map holds its text. For an answers file (no labels at all) that is every
    stretch. Returns one {"id": row id, "items": [{"text", "cited"} of each stretch asked, in order], "prompt": the
    referee's instructions and the input of `referee`, for those stretches only} per row with any unlabelled stretch;
    rows without one, question cards and errors get none. Changes nothing."""
    options = options or CheckOptions()
    if chunk_text is None:
        from localrag.index import chunk_text
    out = []
    for row in rows:
        if row.get("status") != "answered" or not row.get("answer"):
            continue
        labelled = _labels_of(row)
        asked = [{"text": stretch.text, "cited": bool(stretch.chunk_ids), "chunk_ids": list(stretch.chunk_ids)}
                 for stretch in stretches(row["answer"], per_sentence=options.per_sentence)
                 if stretch.text not in labelled]
        if not asked:
            continue
        prompt = _referee_input({**row, "items": asked}, _chunk_of(get_chunk, row), chunk_text)
        out.append({"id": row["id"], "items": [{"text": entry["text"], "cited": entry["cited"]} for entry in asked],
                    "prompt": f"{REFEREE_INSTRUCTIONS}\n\n{prompt}"})
    return out


def add_labels(rows: list[dict], asked: list[dict], replies: dict[str, str], *, model: str = REFEREE_MODEL) -> dict:
    """Read the replies to `prompts` back into the rows with the referee's parser.

    `asked` is what `prompts` returned, `replies` the reply text per row id. For a readable reply each asked stretch
    gets its label: on the row's item of the same text when that item has none (and the row's `referee` becomes
    `model`), else in the row's `labels` map {stretch text: label}. Labels already on items are never changed, nor are
    the reference's check_version and date. An unreadable reply leaves its stretches unlabelled and counts as
    no_verdict; a row with no reply is left as it was and counts as missing.

    Returns {"labelled": stretches labelled, "no_verdict": replies unreadable, "missing": rows without a reply}."""
    by_id = {row["id"]: row for row in rows}
    stats = {"labelled": 0, "no_verdict": 0, "missing": 0}
    for entry in asked:
        row, reply = by_id.get(entry["id"]), replies.get(entry["id"])
        if row is None or reply is None:
            stats["missing"] += 1
            continue
        labels = _parse_referee(reply, entry["items"])
        if labels is None:
            stats["no_verdict"] += 1
            continue
        items = {item["text"]: item for item in row.get("items") or []}
        for stretch, label in zip(entry["items"], labels, strict=True):
            item = items.get(stretch["text"])
            if item is not None and not item.get("referee"):
                item["referee"] = label
                row["referee"] = model
            else:
                row.setdefault("labels", {})[stretch["text"]] = label
            stats["labelled"] += 1
    return stats


# --- command line --------------------------------------------------------------------------------------------------

def _agent_answer(cases: list[dict]) -> Callable[[dict], dict]:
    """The chat agent answering one question of the set as the chat asks it: a place case with its pin's data or
    with the address typed, a general question with nothing pinned."""
    from agentic.agent import run_agent
    from agentic.service import get_tools
    from place.bench_answers import AnswerBench, prompt
    from place.context import question_with_place

    bench, tools = AnswerBench(cases), get_tools()

    def answer(item: dict) -> dict:
        if item["condition"] == "general":
            typed, place_text = item["question"], None
            question = question_with_place(typed, None)
        else:
            typed, question, place_text = prompt(bench.cases[item["case"]], item["condition"], bench.cases,
                                                 bench.profile_of, AnswerBench._law_text(tools))
        item["question"] = typed
        try:
            run = run_agent(question, tools, effort=os.getenv("AGENT_EFFORT", "medium").strip(),
                            explore_effort=os.getenv("AGENT_EXPLORE_EFFORT", "medium").strip() or None,
                            max_steps=int(os.getenv("AGENT_MAX_STEPS", "10")))
        except Exception as exc:  # noqa: BLE001 - a failed run is a saved row, not a crash of the run
            return {"error": f"{type(exc).__name__}: {str(exc)[:MISSING_CHARS]}"}
        return {"answer": run.answer, "questions": [{"question": q.question, "options": q.options} for q in run.questions],
                "seen": list(run.seen_chunks), "place_text": place_text, "mode": run.mode, "error": run.error}
    return answer


def _live_check(tools, options: CheckOptions | None = None) -> Callable[[str, list, str | None], dict]:
    """The claim check as the chat runs it (or with `options`), on a stored answer: its event plus "calls" and
    "seconds" (ClaimCheck's, #128)."""
    from agentic.claim_check import check_claims
    from agentic.tools import resolve_cited

    def check(answer: str, seen: list, place_text: str | None) -> dict:
        result = check_claims(answer, lambda chunk_id: resolve_cited(tools.get_chunk, chunk_id, seen), place_text,
                              options=options)
        return {**result.as_event(), "calls": result.calls, "seconds": result.seconds}
    return check


def main() -> None:
    """The command line (see the module docstring)."""
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    os.environ.setdefault("LLM_PROVIDER", "openrouter")
    parser = argparse.ArgumentParser(description="Grade the claim check against a referee model")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="answer the question set and check the answers (paid; resumes)")
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--workers", type=int, default=2)
    ref = sub.add_parser("referee", help="label the saved answers and freeze the reference (paid)")
    ref.add_argument("path", type=Path)
    ref.add_argument("--out", type=Path, required=True)
    ref.add_argument("--model", default=REFEREE_MODEL)
    ref.add_argument("--workers", type=int, default=4)
    ref.add_argument("--yes", action="store_true", help="skip the confirmation after the cost estimate")
    write = sub.add_parser("report")
    write.add_argument("path", type=Path)
    write.add_argument("--out", type=Path, required=True)
    again = sub.add_parser("recheck", help="run the check (with options) on the reference's answers")
    again.add_argument("path", type=Path)
    again.add_argument("--workers", type=int, default=4)
    asked = sub.add_parser("prompts", help="write a referee prompt per answer with unlabelled stretches (free)")
    asked.add_argument("path", type=Path)
    asked.add_argument("--out", type=Path, required=True, help="folder: one <n>.txt per prompt and index.json")
    back = sub.add_parser("labels", help="read the replies to `prompts` into the reference")
    back.add_argument("path", type=Path)
    back.add_argument("folder", type=Path, help="the prompts folder, a reply as <n>.reply.txt beside each prompt")
    back.add_argument("--model", default=REFEREE_MODEL, help="who answered the prompts")
    best = sub.add_parser("tune", help="recheck each check change and the kept ones together (Jev calls)")
    best.add_argument("path", type=Path)
    best.add_argument("--out", type=Path, required=True)
    best.add_argument("--workers", type=int, default=4)
    other = sub.add_parser("second", help="have the second referee label the reference's stretches (paid; resumes)")
    other.add_argument("path", type=Path)
    other.add_argument("--model", default=SECOND_REFEREE_MODEL)
    other.add_argument("--workers", type=int, default=4)
    other.add_argument("--yes", action="store_true", help="skip the confirmation after the cost estimate")
    build = sub.add_parser("cases", help="build the known-answer cases of a reference (free)")
    build.add_argument("path", type=Path)
    build.add_argument("--out", type=Path, required=True)
    gauge = sub.add_parser("measure", help="measure the check on the agreed stretches and the cases (Jev calls)")
    gauge.add_argument("path", type=Path)
    gauge.add_argument("cases", type=Path)
    gauge.add_argument("--out", type=Path, required=True)
    gauge.add_argument("--workers", type=int, default=4)
    better = sub.add_parser("improve", help="measure each check change and the winners together (Jev calls)")
    better.add_argument("path", type=Path)
    better.add_argument("cases", type=Path)
    better.add_argument("--out", type=Path, required=True)
    better.add_argument("--workers", type=int, default=4)
    for command in (again, asked):
        command.add_argument("--core", action="store_true", help="ask Jev the core question")
        command.add_argument("--supported-at", type=float, default=CheckOptions().supported_at)
        command.add_argument("--skip-hedges", action="store_true")
        command.add_argument("--per-sentence", action="store_true")
    args = parser.parse_args()
    options = (CheckOptions(question="core" if args.core else "strict", supported_at=args.supported_at,
                            skip_hedges=args.skip_hedges, per_sentence=args.per_sentence)
               if args.command in ("recheck", "prompts") else None)

    if args.command == "labels":
        data, index = _load(args.path), json.loads((args.folder / "index.json").read_text(encoding="utf-8"))
        replies = {entry["id"]: (args.folder / f"{n}.reply.txt").read_text(encoding="utf-8")
                   for n, entry in enumerate(index, start=1) if (args.folder / f"{n}.reply.txt").exists()}
        stats = add_labels(data["rows"], index, replies, model=args.model)
        _save(args.path, data)
        print(f"{stats['labelled']} stretches labelled, {stats['no_verdict']} replies unreadable, "
              f"{stats['missing']} prompts without a reply -> {args.path}")
        return
    if args.command == "report":
        data = _load(args.path)
        args.out.write_text(report(data["rows"], meta={"Reference": args.path.name, "check": data.get("check_version"),
                                                       "referee": data.get("referee_model")}), encoding="utf-8")
        print(f"-> {args.out}")
        return

    from agentic.service import get_tools

    tools = get_tools()
    if args.command == "prompts":
        asked = prompts(_load(args.path)["rows"], tools.get_chunk, options=options)
        args.out.mkdir(parents=True, exist_ok=True)
        for n, entry in enumerate(asked, start=1):
            (args.out / f"{n}.txt").write_text(entry["prompt"], encoding="utf-8")
        _save(args.out / "index.json", [{"id": entry["id"], "items": entry["items"]} for entry in asked])
        print(f"{len(asked)} prompts -> {args.out} (reply to <n>.txt as <n>.reply.txt, then run labels)")
    elif args.command == "tune":
        result = tune(_load(args.path), lambda chosen: _live_check(tools, chosen), variants=TUNE_VARIANTS,
                      workers=args.workers)
        args.out.write_text(tune_report(result), encoding="utf-8")
        print(f"kept {result['kept'] or 'none'}, live {result['live']} -> {args.out}")
    elif args.command == "run":
        from place.bench_answers import load_cases

        cases = load_cases()
        result = run_set(question_set(cases, load_questions()), _agent_answer(cases), _live_check(tools), args.out,
                         workers=args.workers)
        print(f"{len(result['rows'])} answers -> {args.out}")
    elif args.command == "referee":
        data = _load(args.path)

        def announce(cost: dict) -> None:
            print(f"Referee {args.model}: {cost['calls']} calls, ~{cost['input_tokens']:,} input and "
                  f"~{cost['output_tokens']:,} output tokens, ~${cost['dollars']:.2f}")
            if not args.yes and input("Go on? [y/N] ").strip().lower() != "y":
                raise SystemExit("stopped before any call")
        stats = referee(data["rows"], tools.get_chunk, model=args.model, announce=announce, workers=args.workers,
                        on_row=lambda: freeze(data["rows"], args.out))
        freeze(data["rows"], args.out)
        print(f"{stats['rows']} answers refereed ({stats['no_verdict']} without a verdict), ${stats['cost']} -> {args.out}")
    elif args.command == "second":
        data = _load(args.path)

        def announce(cost: dict) -> None:
            print(f"Second referee {args.model}: {cost['calls']} calls, ~{cost['input_tokens']:,} input and "
                  f"~{cost['output_tokens']:,} output tokens, ~${cost['dollars']:.2f}")
            if cost["calls"] and not args.yes and input("Go on? [y/N] ").strip().lower() != "y":
                raise SystemExit("stopped before any call")
        stats = second_referee(data["rows"], tools.get_chunk, model=args.model, announce=announce,
                               workers=args.workers, on_row=lambda: _save(args.path, data))
        _save(args.path, data)
        disputed = len(summary(data["rows"])["disputed"])
        print(f"{stats['rows']} answers labelled ({stats['no_verdict']} without a verdict), ${stats['cost']}, "
              f"{disputed} stretches disputed -> {args.path}")
    elif args.command == "cases":
        cases = known_cases(_load(args.path), tools.get_chunk)
        _save(args.out, {"reference": args.path.name, "cases": cases})
        print(", ".join(f"{sum(case['kind'] == kind for case in cases)} {kind}" for kind in KNOWN_KINDS) + f" -> {args.out}")
    elif args.command == "improve":
        result = improve(_load(args.path), _load(args.cases)["cases"], lambda chosen: _live_check(tools, chosen),
                         workers=args.workers)
        args.out.write_text(improve_report(result), encoding="utf-8")
        print(f"won {result['won'] or 'none'}, live {result['live']} -> {args.out}")
    elif args.command == "measure":
        data = _load(args.path)
        result = measure(data, _load(args.cases)["cases"], _live_check(tools), workers=args.workers)
        args.out.write_text(measure_report(result, disputed=summary(data["rows"])["disputed"]), encoding="utf-8")
        print(f"validation agreement {_pct(result['validation']['agreement']['all'])} -> {args.out}")
    else:
        out = recheck(_load(args.path), _live_check(tools, options), options=options, workers=args.workers)
        print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()

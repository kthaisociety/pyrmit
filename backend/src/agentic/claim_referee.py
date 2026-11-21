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
    python -m agentic.claim_referee recheck data/agentic/referee-reference.json

Every question is tuning or validation, split by case: tune the check on the tuning half and read the validation
half only to confirm. A cited claim agrees when the check calls it "supported" exactly when the referee says "yes"
("partly" counts as not backed); an uncited sentence agrees when the check flags it exactly when the referee says it
needed a source. A claim the check did not judge (the check failed, or its call did) is "not_checked" and stays out
of the agreement; a question card has no claims and is only counted.
"""

import argparse
import hashlib
import json
import os
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from agentic.claim_check import _stretches
from place.sources import SWEDEN_TZ

QUESTIONS_PATH = Path(__file__).with_name("referee_questions.json")
CLAIM_CHECK_PATH = Path(__file__).with_name("claim_check.py")
REFEREE_MODEL = "anthropic/claude-opus-5.5"
PRICE_IN, PRICE_OUT = 4.0, 20.0  # USD per million tokens of the referee model
CHARS_PER_TOKEN = 4
OUTPUT_TOKENS_PER_ITEM = 60  # a label is a short JSON object
PLACE_CONDITIONS = ("pin", "address")
SPLITS = ("tuning", "validation")
BACKED = ("yes", "partly", "no")
NEEDS = ("fact", "advice", "hedge", "summary")
SPLIT_LABELS = ("one", "several", "part")

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
    return hashlib.sha256(CLAIM_CHECK_PATH.read_bytes()).hexdigest()[:12]


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# --- the question set ---------------------------------------------------------------------------------------------

def load_questions(path: Path = QUESTIONS_PATH) -> dict:
    """The general questions and the validation place cases. Raises ValueError when the set is not locked."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
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

def judged_items(answer: str, check: dict) -> list[dict]:
    """Every stretch of the answer with the check's verdict on it: a cited claim "supported" / "unsupported" /
    "uncited" (no cited chunk readable), or "not_checked" when the check left it out; an uncited sentence "uncited"
    when flagged, "passed" when not, or "not_checked" when the whole check failed."""
    verdicts = {claim["text"]: claim["verdict"] for claim in check.get("claims") or []}
    failed = check.get("status") != "checked"
    items = []
    for stretch in _stretches(answer):
        if failed:
            verdict = "not_checked"
        elif stretch.chunk_ids:
            verdict = verdicts.get(stretch.text, "not_checked")
        else:
            verdict = "uncited" if verdicts.get(stretch.text) == "uncited" else "passed"
        items.append({"text": stretch.text, "cited": bool(stretch.chunk_ids), "chunk_ids": list(stretch.chunk_ids),
                      "check": verdict})
    return items


def judge_row(row: dict, check: Callable[[str, list, str | None], dict]) -> None:
    """Put a saved answer to the claim check and store its items; a question card or an empty answer gets none."""
    if row["status"] != "answered":
        row["check"], row["items"] = None, []
        return
    result = check(row["answer"], row.get("seen") or [], row.get("place_text"))
    row["check"], row["items"] = result.get("status"), judged_items(row["answer"], result)


def run_set(items: list[dict], answer: Callable[[dict], dict], check: Callable[[str, list, str | None], dict],
            path: Path, *, workers: int = 1) -> dict:
    """Answer every question once, put each answer to the check and save it to `path` after each one; questions
    already in `path` are not answered again. `answer(item)` -> {"answer", "questions", "seen", "place_text", "mode",
    "error"?}; `check(answer, seen, place_text)` -> {"status", "claims": [{"text", "verdict", "chunk_ids"}]}."""
    path = Path(path)
    result = (json.loads(path.read_text(encoding="utf-8")) if path.exists()
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
        judge_row(row, check)
        with lock:
            result["rows"].append(row)
            _save(path, result)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, [item for item in items if item["id"] not in done]))
    _save(path, result)
    return result


# --- the referee ---------------------------------------------------------------------------------------------------

def referee_input(row: dict, chunk_of: Callable[[str], dict | None], chunk_text: Callable[[dict], str]) -> str:
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


def parse_referee(text: str, items: list[dict]) -> list[dict] | None:
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
            labels.append({"supported": entry["supported"], "missing": str(entry.get("missing") or "")[:300],
                           "needs_source": entry["needs_source"], "split": entry["split"]})
        else:
            return None
    return labels


def ask_referee(model: str, prompt: str) -> tuple[str, float]:
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


def estimate(rows: list[dict], get_chunk: Callable[[str], dict | None], chunk_text: Callable[[dict], str]) -> dict:
    """What the referee will cost: {"calls", "input_tokens", "output_tokens", "dollars"} at its price, one call per
    answered row (a retry costs again)."""
    todo = _to_referee(rows)
    chars = sum(len(REFEREE_INSTRUCTIONS) + len(referee_input(row, _chunk_of(get_chunk, row), chunk_text)) for row in todo)
    tokens_in = chars // CHARS_PER_TOKEN
    tokens_out = OUTPUT_TOKENS_PER_ITEM * sum(len(row["items"]) for row in todo)
    return {"calls": len(todo), "input_tokens": tokens_in, "output_tokens": tokens_out,
            "dollars": (tokens_in * PRICE_IN + tokens_out * PRICE_OUT) / 1e6}


def referee(rows: list[dict], get_chunk: Callable[[str], dict | None], *, model: str = REFEREE_MODEL,
            ask: Callable[[str, str], tuple[str, float]] = ask_referee, chunk_text: Callable[[dict], str] | None = None,
            announce: Callable[[dict], None] = print, workers: int = 4,
            on_row: Callable[[], None] | None = None) -> dict:
    """Have the referee label every item of the answered rows: each item gets `referee`. The cost estimate goes to
    `announce` before any call. An unreadable reply is asked again once; after a second one the row gets
    `referee` = "no_verdict" and its items no labels. Returns {"rows", "no_verdict", "cost", "estimate"}."""
    if chunk_text is None:
        from localrag.index import chunk_text
    expected = estimate(rows, get_chunk, chunk_text)
    announce(expected)
    todo = _to_referee(rows)
    stats = {"rows": len(todo), "no_verdict": 0, "cost": 0.0, "estimate": expected}
    lock = threading.Lock()

    def one(row: dict) -> None:
        prompt, labels, cost = referee_input(row, _chunk_of(get_chunk, row), chunk_text), None, 0.0
        for _ in range(2):
            try:
                reply, spent = ask(model, prompt)
            except Exception as exc:  # noqa: BLE001 - a failed call counts as an unreadable reply
                reply, spent = type(exc).__name__, 0.0
            cost += spent
            labels = parse_referee(reply, row["items"])
            if labels is not None:
                break
        with lock:
            stats["cost"] += cost
            if labels is None:
                row["referee"] = "no_verdict"
                stats["no_verdict"] += 1
            else:
                row["referee"] = model
                for entry, label in zip(row["items"], labels, strict=True):
                    entry["referee"] = label
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

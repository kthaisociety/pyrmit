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

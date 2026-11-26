"""
Answers two referees have labelled, their sources and a scripted claim check, for tests of the second referee, the
disputed stretches, the known-answer cases and the measure (agentic.claim_referee).

Three sources: N states a figure (30 kvadratmeter), O belongs to another case (100 meter), H states no figure.
"""

import json
import re
import threading
import time

from agentic import claim_check, claim_referee

N, O, H = "1" * 16, "2" * 16, "3" * 16


SOURCES = {
    N: {"chunk_id": N, "kind": "law", "header": "PBL 9 kap. 4 §",
        "text": "En komplementbyggnad får ha en byggnadsarea som är högst 30 kvadratmeter."},
    O: {"chunk_id": O, "kind": "law", "header": "MB 7 kap. 14 §",
        "text": "Strandskydd gäller 100 meter från strandlinjen."},
    H: {"chunk_id": H, "kind": "law", "header": "PBL 9 kap. 3 §", "text": "Bygglov krävs för nybyggnad."},
}


AREA = "En komplementbyggnad får vara högst 30 kvadratmeter"


PERMIT = "Bygglov krävs för ett nytt hus"


SHORE = "Strandskydd gäller 100 meter från stranden"


TIP = "Kontakta kommunen för mer"


PLACE = "Property Uppsala Norby 114:1, inside detaljplan 0380-P90/6."


YES = {"supported": "yes", "missing": "", "needs_source": "fact", "split": "one"}


PARTLY = {**YES, "supported": "partly", "missing": "a detail"}


NO = {**YES, "supported": "no", "missing": "all of it"}


NEEDED, NOT_NEEDED = {"needed": True}, {"needed": False}


def source_chunk(chunk_id):
    return SOURCES.get(chunk_id)


def text_of(chunk):
    return chunk["text"]


def labelled(text, chunk_ids=(), check=None, referee=None, second=None) -> dict:
    out = {"text": text, "cited": bool(chunk_ids), "chunk_ids": list(chunk_ids),
           "check": check or ("supported" if chunk_ids else "passed")}
    if referee:
        out["referee"] = referee
    if second:
        out["second"] = second
    return out


def answered(case, items, *, split="validation", condition="general", place_text=None, second_referee="luna",
        referee="opus") -> dict:
    answer = " ".join(f"{entry['text']} [c:{'; c:'.join(entry['chunk_ids'])}]." if entry["chunk_ids"]
                      else f"{entry['text']}." for entry in items)
    out = {"id": f"{case}:{condition}", "case": case, "condition": condition, "split": split, "answer": answer,
           "seen": sorted({cid for entry in items for cid in entry["chunk_ids"]}), "place_text": place_text,
           "questions": [], "status": "answered", "check": "checked", "items": items, "referee": referee}
    if second_referee:
        out["second_referee"] = second_referee
    return out


def labels_reply(*labels) -> str:
    return json.dumps({"items": [{"n": n, **label} for n, label in enumerate(labels, start=1)]})


def first_only_rows() -> list[dict]:
    """Two rows the first referee labelled and no second referee has seen."""
    return [answered("norby", [labelled(AREA, [N], referee=YES), labelled(TIP, referee=NOT_NEEDED)], second_referee=None),
            answered("dalby", [labelled(SHORE, [O], referee=NO)], second_referee=None, split="tuning")]


def run_second(rows, *answers, events=None, **kwargs):
    """Run the second referee with a scripted reply per call (the last one repeats); returns (prompts, stats)."""
    prompts, events = [], events if events is not None else []

    def ask(model, prompt):
        events.append(("ask", model))
        prompts.append(prompt)
        return answers[min(len(prompts) - 1, len(answers) - 1)], 0.001

    stats = claim_referee.second_referee(rows, source_chunk, ask=ask, chunk_text=text_of,
                                         announce=lambda estimate: events.append(("estimate", estimate)), workers=1,
                                         **kwargs)
    return prompts, stats


def disputed_rows() -> list[dict]:
    """A validation row with one agreed claim the check gets right and one disputed claim it would get wrong."""
    return [answered("norby", [labelled(AREA, [N], check="supported", referee=YES, second=YES),
                          labelled(PERMIT, [H], check="supported", referee=NO, second=YES)])]


def two_referee_reference(**norby) -> dict:
    """Two cases whose claims both referees call supported: norby (a claim with a number, one without) and dalby."""
    return {"check_version": "frozen", "rows": [
        answered("norby", [labelled(AREA, [N], referee=YES, second=YES), labelled(PERMIT, [H], referee=YES, second=YES),
                      labelled(TIP, referee=NOT_NEEDED, second=NOT_NEEDED)], **norby),
        answered("dalby", [labelled(SHORE, [O], referee=YES, second=YES)], split="tuning")]}


def known_for(ref=None, kind=None, text=None) -> list[dict]:
    found = claim_referee.known_cases(ref or two_referee_reference(), source_chunk, chunk_text=text_of)
    return [case for case in found if (kind is None or case["kind"] == kind) and (text is None or case["from"] == text)]


def numbers(text: str) -> list[str]:
    return re.findall(r"\d+", text)


def scripted_check(verdicts: dict[str, str], *, seconds=None, calls: int = 3, seen_answers: list | None = None,
                   active: list | None = None):
    """The claim check, scripted: each stretch of the answer gets the verdict `verdicts` holds for its text (cited
    stretches default to "supported", uncited ones are left out, "not_checked" leaves a stretch out). `seconds` maps
    a text found in the answer to the time reported for it (default 0.5). `seen_answers` collects (answer, seen,
    place_text); `active` collects how many checks ran at once."""
    lock, running = threading.Lock(), [0]

    def check(answer, seen, place_text):
        with lock:
            running[0] += 1
            if active is not None:
                active.append((answer, running[0]))
        time.sleep(0.01)
        if seen_answers is not None:
            seen_answers.append((answer, list(seen), place_text))
        claims = []
        for stretch in claim_check.stretches(answer):
            verdict = verdicts.get(stretch.text, "supported" if stretch.chunk_ids else None)
            if verdict and verdict != "not_checked":
                claims.append({"text": stretch.text, "verdict": verdict, "chunk_ids": list(stretch.chunk_ids)})
        took = next((value for text, value in (seconds or {}).items() if text in answer), 0.5)
        with lock:
            running[0] -= 1
        return {"status": "checked", "claims": claims, "calls": calls, "seconds": took}
    return check


def known(kind, text, expect, case="norby", split="validation", chunk_ids=(N,)) -> dict:
    return {"id": f"{case}:general#1:{kind}", "row": f"{case}:general", "case": case, "split": split,
            "condition": "general", "kind": kind, "text": text, "chunk_ids": list(chunk_ids), "seen": list(chunk_ids),
            "place_text": None, "expect": expect, "from": AREA}


WRONG = AREA.replace("30", "45")


def measured(verdicts=None, some_cases=(), ref=None, **check):
    return claim_referee.measure(ref or two_referee_reference(), list(some_cases), scripted_check(verdicts or {}, **check), workers=2)


def split_result(**over) -> dict:
    stats = {"claims": 10, "agree": 8, "share": 0.8}
    return {"agreement": {"cited": stats, "uncited": stats, "all": stats}, "disputed": 4, "single": 0,
            "known": {"untouched": {"cases": 20, "right": 19, "share": 0.95}, "number": {"cases": 12, "right": 9, "share": 0.75},
                      "source": {"cases": 5, "right": 5, "share": 1.0}},
            "not_checked": 0, "answers": 15, "seconds": {"median": 1.2, "max": 1.9}, "calls": 6.0, "slow": [], "wrong": [],
            "levels": {"claims": 0, "match": 0, "share": None}, **over}


def measure_result(**validation) -> dict:
    return {"options": {"question": "strict"}, "version": "abc", "tuning": split_result(), "validation": split_result(**validation)}

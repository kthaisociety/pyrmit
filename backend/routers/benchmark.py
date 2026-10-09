"""
Benchmark browser and runner for the app's "Benchmark" view:

- GET  /api/benchmark/sets                 the case sets (14 case studies, MÖD rulings, plankarta cases)
- GET  /api/benchmark/cases?set=&q=        cases of a set (paginated, text filter)
- GET  /api/benchmark/case?set=&id=        one case + the results of every benchmark run that included it
- GET  /api/benchmark/image/{case_id}      the plan-map crop of a plankarta case
- POST /api/benchmark/run {set, id}        run the agent on the case now (same settings as the chat) and grade it
- GET  /api/benchmark/run/{job_id}         progress (tool calls so far) and, when done, answer + grade

A run takes 30-60 s, longer than the frontend proxy waits, so it is a background job polled by the page.
Runs spend API credits (agent + judge, ~$0.01).
"""

import json
import os
import re
import threading
import time
import uuid
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from dependencies import get_current_user
import models

router = APIRouter()

CASES_DIR = Path(__file__).resolve().parent.parent / "agentic"
SETS = {
    "cases": ("cases.jsonl", "Case studies", "Hand-written feasibility cases on real projects in the corpus municipalities"),
    "caselaw": ("cases_caselaw.jsonl", "MÖD rulings", "Cases generated from rulings of the Land and Environment Court of Appeal: the court's outcome is the reference"),
    "plans": ("cases_plans.jsonl", "Plankarta", "Questions about a specific property: the answer is only on the plan map (reference read by the vision model)"),
}
RESULT_FILE = re.compile(r"bench-(\d{8}-\d{6})-(?P<systems>[a-z-]+?)-(?P<answer>low|medium|high)"
                         r"-explore-(?P<explore>low|medium|high|same)(?P<tag>-cases_[a-z]+)?(?:-no-(?P<off>[\w-]+))?\.json$")
JOBS: dict[str, dict] = {}


def _cases(set_name: str) -> list[dict]:
    if set_name not in SETS:
        raise HTTPException(status_code=404, detail=f"Unknown set {set_name}")
    path = CASES_DIR / SETS[set_name][0]
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()] if path.exists() else []


def _case(set_name: str, case_id: str) -> dict:
    case = next((c for c in _cases(set_name) if c["id"] == case_id), None)
    if case is None:
        raise HTTPException(status_code=404, detail=f"Unknown case {case_id}")
    return case


@lru_cache(maxsize=64)
def _result_rows(path: str, mtime: float) -> dict[str, list[dict]]:
    """case id -> rows of one result file (cached until the file changes)."""
    by_case: dict[str, list[dict]] = {}
    for row in json.loads(Path(path).read_text(encoding="utf-8")):
        by_case.setdefault(row["case"], []).append(row)
    return by_case


def _results(set_name: str, case_id: str) -> list[dict]:
    from agentic.bench import RESULTS_DIR

    tag = {"cases": None, "caselaw": "-cases_caselaw", "plans": "-cases_plans"}[set_name]
    out = []
    for path in sorted(RESULTS_DIR.glob("bench-*.json")):
        match = RESULT_FILE.search(path.name)
        if not match or match.group("tag") != tag:
            continue
        for row in _result_rows(str(path), path.stat().st_mtime).get(case_id, []):
            config = (f"{row['system']}" + (f", explore {match.group('explore')} / answer {match.group('answer')}"
                                            if row["system"] == "agent" else f", answer {match.group('answer')}")
                      + (f", without {match.group('off').replace('-', ', ')}" if match.group("off") else ""))
            out.append({"run": match.group(1), "config": config, "verdict": row.get("verdict"),
                        "verdict_ok": row.get("verdict_ok"), "points": row.get("points"),
                        "evidence": row.get("evidence"), "grounded": row.get("grounded"),
                        "tool_calls": row.get("tool_calls"), "map_views": row.get("map_views"),
                        "seconds": row.get("seconds"), "cost": row.get("cost"), "comment": row.get("comment"),
                        "answer": row.get("answer")})
    return out


@router.get("/benchmark/sets")
def sets(_user: models.User = Depends(get_current_user)):
    return [{"set": name, "title": title, "description": description, "cases": len(_cases(name))}
            for name, (_, title, description) in SETS.items()]


@router.get("/benchmark/cases")
def cases(set: str = Query(...), q: str | None = None, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
          _user: models.User = Depends(get_current_user)):
    rows = _cases(set)
    if q:
        needle = q.lower()
        rows = [c for c in rows if needle in json.dumps(c, ensure_ascii=False).lower()]
    items = [{"id": c["id"], "question": c["question"], "verdicts": c["verdicts"], "kommun": c.get("kommun"),
              "source": c.get("source"), "has_image": bool(c.get("image"))} for c in rows[offset:offset + limit]]
    return {"total": len(rows), "offset": offset, "limit": limit, "items": items}


@router.get("/benchmark/case")
def case_detail(set: str = Query(...), id: str = Query(...), _user: models.User = Depends(get_current_user)):
    case = _case(set, id)
    return {"case": case, "results": _results(set, id)}


@router.get("/benchmark/image/{case_id}")
def case_image(case_id: str, _user: models.User = Depends(get_current_user)):
    from agentic.cases_from_plans import OUT_DIR

    case = next((c for c in _cases("plans") if c["id"] == case_id), None)
    if case is None or not case.get("image") or not (OUT_DIR / case["image"]).exists():
        raise HTTPException(status_code=404, detail="No map crop for this case")
    return FileResponse(OUT_DIR / case["image"], media_type="image/png")


class RunRequest(BaseModel):
    set: str
    id: str


def _run_job(job: dict, case: dict) -> None:
    from agentic.agent import DEFAULT_MODEL, run_agent
    from agentic.bench import MAP_TOOLS, cited_sources, evidence_recall, judge
    from agentic.service import CitationNumberer, get_tools
    from llm import resolve_model_name

    try:
        tools = get_tools()
        model = resolve_model_name(os.getenv("AGENT_MODEL", DEFAULT_MODEL))

        def on_event(event: dict) -> None:
            if event["type"] == "tool_call":
                job["progress"].append(f"{event['name']}({event.get('input', '')[:120]})")

        # Same settings as the chat (agentic/service.py)
        run = run_agent(case["question"], tools, model=model, effort=os.getenv("AGENT_EFFORT", "medium").strip(),
                        explore_effort=os.getenv("AGENT_EXPLORE_EFFORT", "medium").strip() or None,
                        max_steps=int(os.getenv("AGENT_MAX_STEPS", "10")), on_event=on_event)
        job["progress"].append("grading the answer")
        numberer = CitationNumberer(tools.get_chunk)
        answer = numberer.feed(run.answer) + numberer.close()
        grade = judge(case, run.answer, model, cited_sources(run.answer, tools))
        job["result"] = {
            "answer": answer, "citations": numberer.citations(),
            "verdict": grade.get("verdict"), "verdict_ok": grade.get("verdict") in case["verdicts"],
            "points": sum(grade.get("points") or [0]) / (2 * len(case["key_points"])),
            "point_scores": grade.get("points"), "comment": grade.get("comment"),
            "unsupported": grade.get("unsupported_claims"),
            "evidence": evidence_recall(case, run.seen_chunks, tools),
            "map_views": sum(1 for s in run.steps if s["tool"] in MAP_TOOLS),
            "tool_calls": len(run.steps), "llm_calls": run.llm_calls, "seconds": run.seconds,
            "cost": round(run.usage["cost"] + float(grade.get("judge_cost") or 0), 5),
        }
        job["status"] = "done"
    except Exception as exc:  # reported to the page
        job["status"], job["error"] = "error", repr(exc)


@router.post("/benchmark/run")
def run_case(request: RunRequest, _user: models.User = Depends(get_current_user)):
    case = _case(request.set, request.id)
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"status": "running", "progress": [], "started": time.time(), "case": request.id}
    threading.Thread(target=_run_job, args=(JOBS[job_id], case), daemon=True).start()
    return {"job_id": job_id}


@router.get("/benchmark/run/{job_id}")
def run_status(job_id: str, _user: models.User = Depends(get_current_user)):
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job (the backend may have restarted)")
    return {**{k: v for k, v in job.items() if k != "started"}, "elapsed": round(time.time() - job["started"])}

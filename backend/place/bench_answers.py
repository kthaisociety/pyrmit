"""
The answer benchmark of the map pin: the chat agent answers questions about one place, with and without the pin, and
an LLM judge grades each answer against a reference written and locked before the agent ran (place/cases_answers.jsonl).

Conditions, per case:
  pin       the question with the pinned place's profile before it, exactly as the chat sends it
            (place.context.question_with_place)
  address   the same question naming the address instead, no pin: the agent has to find the place in its corpus
  vague     (cases with "vague") the question without any place and no pin: the agent should ask where
  conflict  (cases with "conflict_with") pinned at this case's place while the question names the other case's
            address: the agent should ask which place is meant

Scores per answer:
  points      reference key points covered, 0-2 each (judge), reported as 0-1 (pin and address only)
  facts       share of the reference place facts the answer names (property, plan, protected areas, ...), by
              string match, no LLM
  wrong_place statements about the place that contradict the reference (judge)
  unsupported specific rules / facts in neither the reference, the place data shown nor the cited sources (judge)
  asks        whether the answer asks which place it is about (judge); right when it matches the condition
              (expected for vague and conflict, not for pin; with an address, asking to pin it is the hint's advice
              when the agent cannot place it, so it is counted, not scored)
  seconds, first token, cost, tool calls

The judge defaults to another model family than the agent (MiMo v2.6 Flash); `rejudge` adds a second judge's grades
to a result file, so a difference counts only when both judges see it.

    cd backend
    python -m place.bench_answers run --repeats 3 --workers 3            # -> data/agentic/place-answers-<time>.json
    python -m place.bench_answers rejudge <result.json> --judge-model openai/gpt-6-luna
    python -m place.bench_answers summary <result.json>
"""

import argparse
import json
import os
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from statistics import fmean

from place.bench import RESULTS_DIR
from place.context import place_context, question_with_place
from place.sources import SWEDEN_TZ

CASES_PATH = Path(__file__).resolve().parent / "cases_answers.jsonl"
CONDITIONS = ("pin", "address", "vague", "conflict")
ASKS_EXPECTED = {"pin": False, "address": None, "vague": True, "conflict": True}  # address: asking to pin is allowed
JUDGE_MODEL = "xiaomi/mimo-v2.6-flash"
MAX_COST_USD = 10.0

JUDGE_INSTRUCTIONS = """You grade answers of a Swedish planning assistant to a question about one specific place, against a reference.
Return JSON only: {"points": [<0|1|2> per key point, in order], "unsupported_claims": <int>, "wrong_place_claims": <int>, "asks_for_place": <true|false>, "comment": "<one sentence>"}.
- points: 2 = the key point is clearly stated, 1 = partially / vaguely, 0 = missing or contradicted. An empty list when there are no key points.
- unsupported_claims: number of specific rules/numbers/facts in the answer that are stated neither in the reference, nor
  in the place data the assistant was given, nor in the cited sources below, or that contradict them. A claim those
  sources state is supported even when the reference does not mention it (the reference is not exhaustive).
- wrong_place_claims: number of statements about this place that contradict the reference place (e.g. another
  detaljplan, "outside detaljplan" when it is inside, a protected area or ancient remain that is not there, another
  property designation). Saying that something is unknown or must be checked is not wrong.
- asks_for_place: true if the answer asks the user which place or property the question is about, or asks them to
  pin it on the map, instead of or before answering for a known place."""


def load_cases(path: Path = CASES_PATH) -> list[dict]:
    """The locked cases of a cases file, in file order. Raises ValueError for an unlocked one: a reference written
    after the agent saw the place would not be a reference."""
    cases = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    unlocked = [case["id"] for case in cases if not case.get("locked")]
    if unlocked:
        raise ValueError(f"unlocked cases in {path}: {', '.join(unlocked)}")
    return cases


def jobs(cases: list[dict], conditions=CONDITIONS, repeats: int = 1) -> list[tuple[str, str, int]]:
    """(case id, condition, repeat) for every case and condition that applies to it: pin and address always,
    vague for cases marked "vague", conflict for cases with "conflict_with"."""
    applies = {"pin": lambda c: True, "address": lambda c: True, "vague": lambda c: bool(c.get("vague")),
               "conflict": lambda c: bool(c.get("conflict_with"))}
    return [(case["id"], condition, repeat) for repeat in range(repeats) for case in cases
            for condition in conditions if applies[condition](case)]


def prompt(case: dict, condition: str, cases_by_id: dict[str, dict],
           profile_of: Callable[[float, float], dict]) -> tuple[str, str, str | None]:
    """(what the user typed, what the agent gets, the place data shown to it or None) for one case and condition."""
    if condition == "address":
        typed, profile = case["question_address"], None
    elif condition == "vague":
        typed, profile = case["question"], None
    elif condition == "conflict":
        typed, profile = cases_by_id[case["conflict_with"]]["question_address"], profile_of(case["pin"]["lat"], case["pin"]["lon"])
    else:
        typed, profile = case["question"], profile_of(case["pin"]["lat"], case["pin"]["lon"])
    return typed, question_with_place(typed, profile), place_context(profile) if profile else None


def facts_named(case: dict, answer: str) -> list[str]:
    """The labels of the case's reference facts the answer names: any alias, case-insensitive."""
    text = answer.lower()
    return [fact["label"] for fact in case.get("facts") or [] if any(alias.lower() in text for alias in fact["any"])]


def _judge_input(case: dict, condition: str, typed: str, answer: str, place_text: str | None, sources: str,
                 cases_by_id: dict[str, dict]) -> str:
    if condition in ("pin", "address"):
        reference = f"Reference place: {case['reference_place']}"
        points = "\n".join(f"{i + 1}. {point}" for i, point in enumerate(case["key_points"]))
    elif condition == "conflict":
        named = cases_by_id[case["conflict_with"]]
        reference = (f"The user pinned one place on the map ({case['pin']['label']}: {case['reference_place']}) but the "
                     f"question names another ({named['pin']['label']}). The assistant should ask which place is meant.")
        points = "(none)"
    else:
        reference = "No place is pinned and the question does not name one: the answer depends on the place."
        points = "(none)"
    return (f"Question as the user wrote it: {typed}\n\n{reference}\n\nReference key points:\n{points}\n\n"
            f"Answer to grade:\n{answer}\n\nPlace data the assistant was given:\n{place_text or '(none)'}\n\n"
            f"Cited sources (excerpts):\n{sources or '(none)'}")


def judge(case: dict, condition: str, typed: str, answer: str, place_text: str | None, sources: str,
          cases_by_id: dict[str, dict], model: str) -> dict:
    """The judge's grade of one answer: {"points": [0-2 ...], "unsupported", "wrong_place", "asks", "comment",
    "cost", "model"}; an unparseable reply grades as zero with the reply in the comment."""
    from llm import get_openai_client, get_response_output_text

    response = get_openai_client().responses.create(
        model=model, reasoning={"effort": "medium"}, instructions=JUDGE_INSTRUCTIONS,
        input=_judge_input(case, condition, typed, answer, place_text, sources, cases_by_id))
    text = get_response_output_text(response).strip()
    text = text[text.find("{"):text.rfind("}") + 1]  # some models wrap the JSON in prose or a code fence
    wanted = len(case["key_points"]) if condition in ("pin", "address") else 0
    try:
        grade = json.loads(text)
    except json.JSONDecodeError:
        grade = {"points": [0] * wanted, "unsupported_claims": 0, "wrong_place_claims": 0, "asks_for_place": None,
                 "comment": f"unparseable judge output: {text[:200]}"}
    scores = (list(grade.get("points") or []) + [0] * wanted)[:wanted]  # the judge returned too few / many
    return {"points": scores, "unsupported": grade.get("unsupported_claims", 0),
            "wrong_place": grade.get("wrong_place_claims", 0), "asks": grade.get("asks_for_place"),
            "comment": grade.get("comment"), "cost": float(getattr(response.usage, "cost", 0) or 0), "model": model}


def scores(row: dict, grade: dict) -> dict:
    """The row's scores under one judge's grade: points (0-1, pin and address only), asks_ok, unsupported and
    wrong_place."""
    points, expected = grade["points"], ASKS_EXPECTED[row["condition"]]
    return {"points": sum(points) / (2 * len(points)) if points else None,
            "asks_ok": None if grade["asks"] is None or expected is None else grade["asks"] == expected,
            "unsupported": grade["unsupported"], "wrong_place": grade["wrong_place"]}


class AnswerBench:
    """Runs the agent on (case, condition, repeat) jobs and grades each answer. `run_agent`, `tools`, `profile_of`,
    `sources_of` (answer, seen chunk ids -> cited source text) and `grade` default to the chat's agent, corpus tools,
    place profile, agentic.bench.cited_sources and judge()."""

    def __init__(self, cases: list[dict], *, judge_model: str = JUDGE_MODEL, run_agent=None, tools=None,
                 profile_of=None, sources_of=None, grade=None, max_cost: float = MAX_COST_USD):
        self.cases = {case["id"]: case for case in cases}
        self.judge_model, self.max_cost = judge_model, max_cost
        self._run_agent, self._tools, self._profile_of = run_agent, tools, profile_of
        self._sources_of, self._grade = sources_of, grade or judge
        self._profiles: dict[tuple[float, float], dict] = {}
        self._lock = threading.Lock()
        self.spent = 0.0

    def profile_of(self, lat: float, lon: float) -> dict:
        if self._profile_of is None:
            from place.profile import build_profile
            self._profile_of = build_profile
        with self._lock:
            cached = self._profiles.get((lat, lon))
        if cached is None:  # the same pin gives the same profile in every repeat
            cached = self._profile_of(lat, lon)
            with self._lock:
                self._profiles[(lat, lon)] = cached
        return cached

    def _agent(self):
        if self._run_agent is None:
            from agentic.agent import run_agent
            from agentic.service import get_tools

            self._run_agent, self._tools = run_agent, get_tools()
        return self._run_agent, self._tools

    def run_one(self, job: tuple[str, str, int]) -> dict | None:
        """One answer and its grade as a result row, or None once the budget is spent."""
        case_id, condition, repeat = job
        if self.spent >= self.max_cost:
            return None
        case = self.cases[case_id]
        typed, question, place_text = prompt(case, condition, self.cases, self.profile_of)
        run_agent, tools = self._agent()
        started = time.perf_counter()
        row = {"case": case_id, "condition": condition, "repeat": repeat, "question": typed}
        try:
            run = run_agent(question, tools, effort=os.getenv("AGENT_EFFORT", "medium").strip(),
                            explore_effort=os.getenv("AGENT_EXPLORE_EFFORT", "medium").strip() or None,
                            max_steps=int(os.getenv("AGENT_MAX_STEPS", "10")))
        except Exception as exc:  # a failed run is a result, not a crash of the benchmark
            row.update(error=f"{type(exc).__name__}: {str(exc)[:300]}", seconds=round(time.perf_counter() - started, 1))
            return row
        row.update(answer=run.answer, mode=run.mode, seconds=run.seconds, first_token_s=run.first_token_s,
                   cost=round(run.usage.get("cost", 0.0), 5), llm_calls=run.llm_calls, error=run.error,
                   tool_calls=len(run.steps), tools=[step.get("tool") for step in run.steps],
                   facts_named=facts_named(case, run.answer) if condition in ("pin", "address") else None,
                   facts=len(case.get("facts") or []))
        row["facts_share"] = (len(row["facts_named"]) / row["facts"] if row["facts_named"] is not None and row["facts"]
                              else None)
        row["seen"], row["place_text"] = list(run.seen_chunks), place_text
        self.add_grade(row, self.judge_model)
        with self._lock:
            self.spent += row["cost"] + row["grades"][self.judge_model]["cost"]
        return row

    def sources(self, row: dict) -> str:
        if self._sources_of is None:
            from agentic.bench import cited_sources

            _, tools = self._agent()
            self._sources_of = lambda answer, seen: cited_sources(answer, tools, seen)
        return self._sources_of(row.get("answer") or "", row.get("seen") or [])

    def add_grade(self, row: dict, model: str) -> None:
        """Grade a row's answer with `model` and store it under row["grades"][model] with its scores."""
        if not row.get("answer"):
            return
        case = self.cases[row["case"]]
        grade = self._grade(case, row["condition"], row["question"], row["answer"], row.get("place_text"),
                            self.sources(row), self.cases, model)
        row.setdefault("grades", {})[model] = {**grade, **scores(row, grade)}


def summarise(rows: list[dict], judge_model: str) -> dict:
    """Means per condition under one judge: {condition: {"answers", "errors", "points", "facts", "wrong_place",
    "unsupported", "asks" (share asking for the place), "asks_ok", "seconds", "first_token_s", "cost",
    "tool_calls"}}, plus "by_case": the points and facts per case and condition."""
    def mean(values):
        values = [value for value in values if value is not None]
        return round(fmean(values), 3) if values else None

    out: dict = {}
    for condition in CONDITIONS:
        mine = [row for row in rows if row["condition"] == condition]
        if not mine:
            continue
        graded = [row["grades"][judge_model] for row in mine if judge_model in (row.get("grades") or {})]
        out[condition] = {
            "answers": len(mine), "errors": sum(bool(row.get("error")) or not row.get("answer") for row in mine),
            "points": mean(g["points"] for g in graded), "facts": mean(row.get("facts_share") for row in mine),
            "wrong_place": mean(g["wrong_place"] for g in graded), "unsupported": mean(g["unsupported"] for g in graded),
            "asks": mean(None if g["asks"] is None else float(g["asks"]) for g in graded),
            "asks_ok": mean(None if g["asks_ok"] is None else float(g["asks_ok"]) for g in graded),
            "seconds": mean(row.get("seconds") for row in mine), "first_token_s": mean(row.get("first_token_s") for row in mine),
            "cost": mean(row.get("cost") for row in mine), "tool_calls": mean(row.get("tool_calls") for row in mine)}
    by_case: dict = {}
    for row in rows:
        grade = (row.get("grades") or {}).get(judge_model)
        cell = by_case.setdefault(row["case"], {}).setdefault(row["condition"], {"points": [], "facts": [], "asks_ok": []})
        if grade:
            cell["points"].append(grade["points"])
            cell["asks_ok"].append(grade["asks_ok"])
        cell["facts"].append(row.get("facts_share"))
    out["by_case"] = {case: {condition: {key: mean(float(v) if isinstance(v, bool) else v for v in values)
                                         for key, values in cell.items()}
                             for condition, cell in conditions.items()} for case, conditions in by_case.items()}
    return out


def _save(path: Path, result: dict) -> None:
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def run_bench(cases: list[dict], *, conditions=CONDITIONS, repeats: int = 3, workers: int = 3,
              bench: AnswerBench | None = None, label: str | None = None, out_dir: Path = RESULTS_DIR,
              resume: Path | None = None) -> dict:
    """Run every job (see jobs) and save the rows to `out_dir`/place-answers-<YYYYmmdd-HHMMSS>[-<label>].json after
    each answer, so an interrupted run keeps what it did; `resume` continues such a file (jobs already there are
    skipped). Stops starting new answers once the bench's budget is spent. Returns {"date", "label", "agent",
    "judge", "rows", "summary", "path"}."""
    bench = bench or AnswerBench(cases)
    if resume:
        path = Path(resume)
        result = json.loads(path.read_text(encoding="utf-8"))
    else:
        stamp = datetime.now(SWEDEN_TZ).strftime("%Y%m%d-%H%M%S")
        path = Path(out_dir) / f"place-answers-{stamp}{'-' + label if label else ''}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        result = {"date": datetime.now(SWEDEN_TZ).isoformat(timespec="seconds"), "label": label,
                  "agent": {"model": os.getenv("AGENT_MODEL", "openai/gpt-6-luna"),
                            "effort": os.getenv("AGENT_EFFORT", "medium"),
                            "explore_effort": os.getenv("AGENT_EXPLORE_EFFORT", "medium"),
                            "max_steps": int(os.getenv("AGENT_MAX_STEPS", "10"))},
                  "judge": bench.judge_model, "cases": [case["id"] for case in cases], "rows": []}
    done = {(row["case"], row["condition"], row["repeat"]) for row in result["rows"]}
    todo = [job for job in jobs(cases, conditions, repeats) if job not in done]
    lock = threading.Lock()

    def one(job):
        row = bench.run_one(job)
        if row is not None:
            with lock:
                result["rows"].append(row)
                result["summary"] = summarise(result["rows"], bench.judge_model)
                _save(path, result)
            print(f"  {job[0]:28} {job[1]:9} r{job[2]}  {row.get('seconds')} s  ${row.get('cost')}"
                  f"  points {(row.get('grades') or {}).get(bench.judge_model, {}).get('points')}", flush=True)
        return row

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, todo))
    result["summary"] = summarise(result["rows"], bench.judge_model)
    result["spent"] = round(bench.spent, 4)
    result["path"] = str(path)
    _save(path, result)
    return result


def rejudge(path: Path, judge_model: str, cases: list[dict], *, bench: AnswerBench | None = None,
            workers: int = 4) -> dict:
    """Add `judge_model`'s grades to every answer of a result file that lacks them, and its summary under
    "summaries"[judge_model]."""
    result = json.loads(Path(path).read_text(encoding="utf-8"))
    bench = bench or AnswerBench(cases, judge_model=judge_model)
    todo = [row for row in result["rows"] if row.get("answer") and judge_model not in (row.get("grades") or {})]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(lambda row: bench.add_grade(row, judge_model), todo))
    result.setdefault("summaries", {})[judge_model] = summarise(result["rows"], judge_model)
    _save(Path(path), result)
    return result


def _print_summary(summary: dict) -> None:
    for condition in CONDITIONS:
        if condition in summary:
            stats = summary[condition]
            print(f"  {condition:9} " + "  ".join(f"{key} {value}" for key, value in stats.items()))


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")  # the chat's settings (agent model, efforts, keys)
    parser = argparse.ArgumentParser(description="Answers about a pinned place: with and without the pin")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--repeats", type=int, default=3)
    run.add_argument("--workers", type=int, default=3)
    run.add_argument("--conditions", nargs="*", default=list(CONDITIONS), choices=CONDITIONS)
    run.add_argument("--cases", nargs="*", help="case ids (default: all)")
    run.add_argument("--judge-model", default=JUDGE_MODEL)
    run.add_argument("--max-cost", type=float, default=MAX_COST_USD, help="stop starting answers past this spend (USD)")
    run.add_argument("--label")
    run.add_argument("--resume", type=Path)
    again = sub.add_parser("rejudge")
    again.add_argument("path", type=Path)
    again.add_argument("--judge-model", default="openai/gpt-6-luna")
    show = sub.add_parser("summary")
    show.add_argument("path", type=Path)
    show.add_argument("--judge-model")
    args = parser.parse_args()

    cases = load_cases()
    if args.command == "run":
        chosen = [case for case in cases if not args.cases or case["id"] in set(args.cases)]
        bench = AnswerBench(cases, judge_model=args.judge_model, max_cost=args.max_cost)
        result = run_bench(chosen, conditions=args.conditions, repeats=args.repeats, workers=args.workers,
                           bench=bench, label=args.label, resume=args.resume)
        print(f"{len(result['rows'])} answers, ${result['spent']} -> {result['path']}")
        _print_summary(result["summary"])
    elif args.command == "rejudge":
        result = rejudge(args.path, args.judge_model, cases)
        _print_summary(result["summaries"][args.judge_model])
    else:
        result = json.loads(args.path.read_text(encoding="utf-8"))
        model = args.judge_model or result["judge"]
        _print_summary(summarise(result["rows"], model))


if __name__ == "__main__":
    main()

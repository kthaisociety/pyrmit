"""
Case-study benchmark: classic RAG vs. the tool-calling agent on feasibility questions with a
known outcome (agentic/cases.jsonl).

Per case and system:
  evidence  share of the case's evidence groups (law sections / kommun passages) that the system
            put in front of the model (retrieved chunks for RAG, every chunk a tool showed for the agent)
  verdict   did the answer reach one of the acceptable verdicts (LLM judge)
  points    coverage of the expected key points, 0-2 each (LLM judge), reported as 0-1
  cost, seconds, tool calls

The judge is the same model as the systems (GPT-6 Luna by default): cheap but self-preferential,
so read its scores as relative between systems, not absolute.

    cd backend
    LLM_PROVIDER=openrouter python -m agentic.bench --systems rag agent
    python -m agentic.bench --systems agent --effort medium --cases kumla-200m2 attefall-vallentuna
"""

import argparse
import json
import os
import random
import threading
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from agentic.agent import ANSWER_FORMAT, DEFAULT_MODEL, ROLE, AgentRun, _add_usage, run_agent
from agentic.run import build_tools
from corpus.common import read_jsonl
from llm import get_openai_client, get_response_output_text, resolve_model_name
from localrag.eval import matches
from localrag.index import INDEX_DIR, chunk_text
from localrag.service import SWEDISH_QUERY_SUFFIX, split_rewrite

CASES_PATH = Path(__file__).resolve().parent / "cases.jsonl"
RESULTS_DIR = INDEX_DIR.parent / "agentic"

RAG_INSTRUCTIONS = f"""{ROLE}

Answer only from the numbered sources below (Swedish statutes and municipal documents). Each source starts with its
chunk id [c:<id>]; cite it like that.

{ANSWER_FORMAT}"""

JUDGE_INSTRUCTIONS = """You grade answers of a Swedish planning assistant against a reference.
Return JSON only: {"verdict": "<feasible|conditional|not_feasible|unclear>", "points": [<0|1|2> per key point, in order], "unsupported_claims": <int>, "comment": "<one sentence>"}.
- verdict: how the answer classifies the project (Feasible -> feasible, Feasible with conditions -> conditional, Not feasible as described -> not_feasible, Unclear -> unclear).
- points: 2 = the key point is clearly stated, 1 = partially / vaguely, 0 = missing or contradicted.
- unsupported_claims: number of specific rules/numbers/facts in the answer that are stated neither in the reference nor
  in the cited sources given below, or that contradict them. A claim the cited sources state is supported even when
  the reference does not mention it (the reference is not exhaustive)."""

MAX_JUDGE_SOURCES, MAX_SOURCE_CHARS = 15, 1500
MAP_TOOLS = {"view_map_area", "view_pdf_page"}


def run_rag(question: str, tools, model: str, effort: str, k: int = 10) -> AgentRun:
    """The chat's local pipeline: rewrite (EN + SV), dense retrieval on the Swedish query with the kommun filter, answer."""
    client = get_openai_client()
    run = AgentRun()
    started = time.perf_counter()
    rewrite = client.responses.create(
        model=model, reasoning={"effort": "low"},
        input=("Translate the following user message to English (return only the translation, no explanation): "
               f"{question}\n\n{SWEDISH_QUERY_SUFFIX}"),
    )
    _add_usage(run.usage, rewrite.usage)
    english, swedish = split_rewrite(get_response_output_text(rewrite), question)
    result = tools.retriever.search(english, query_sv=swedish, k=k, mode="dense", dense_lang="sv")
    hits = result["law"] + result["local"]
    run.seen_chunks = [hit.chunk["chunk_id"] for hit in hits]
    context = "\n\n".join(f"Source {i + 1} [c:{hit.chunk['chunk_id']}]:\n{chunk_text(hit.chunk)}" for i, hit in enumerate(hits))
    answer = client.responses.create(
        model=model, reasoning={"effort": effort}, instructions=RAG_INSTRUCTIONS,
        input=f"Sources:\n\n{context}\n\nQuestion: {question}",
    )
    _add_usage(run.usage, answer.usage)
    run.llm_calls = 2
    run.answer = get_response_output_text(answer)
    run.seconds = round(time.perf_counter() - started, 1)
    run.steps = [{"tool": "retrieve", "kommuner": result["kommuner"], "chunks": run.seen_chunks}]
    return run


def cited_sources(answer: str, tools) -> str:
    """The text of the chunks the answer cites ([c:<id>]), so the judge can tell sourced facts from invented ones."""
    ids = list(dict.fromkeys(re.findall(r"c:([0-9a-f]{8,16})(?![0-9a-f])", answer)))[:MAX_JUDGE_SOURCES]
    chunks = [(chunk_id, tools.get_chunk(chunk_id)) for chunk_id in ids]
    return "\n\n".join(f"[c:{chunk_id}] {chunk_text(chunk)[:MAX_SOURCE_CHARS]}" for chunk_id, chunk in chunks if chunk)


def judge(case: dict, answer: str, model: str, sources: str = "") -> dict:
    client = get_openai_client()
    points = "\n".join(f"{i + 1}. {point}" for i, point in enumerate(case["key_points"]))
    response = client.responses.create(
        model=model, reasoning={"effort": "medium"}, instructions=JUDGE_INSTRUCTIONS,
        input=f"Question: {case['question']}\n\nReference key points:\n{points}\n\n"
              f"Acceptable verdicts: {case['verdicts']}\n\nAnswer to grade:\n{answer}\n\n"
              f"Cited sources (excerpts):\n{sources or '(none)'}",
    )
    text = get_response_output_text(response).strip().strip("`").removeprefix("json").strip()
    try:
        grade = json.loads(text)
    except json.JSONDecodeError:
        grade = {"verdict": "unclear", "points": [0] * len(case["key_points"]), "unsupported_claims": 0,
                 "comment": f"unparseable judge output: {text[:200]}"}
    grade["judge_cost"] = float(getattr(response.usage, "cost", 0) or 0)
    return grade


def evidence_recall(case: dict, seen: list[str], tools) -> float | None:
    if not case["evidence"]:  # e.g. rulings under the old PBL: no current provision to look for
        return None
    seen_chunks = [chunk for chunk in (tools.get_chunk(chunk_id) for chunk_id in seen) if chunk]
    groups = [any(matches(chunk, matcher) for chunk in seen_chunks) for matcher in case["evidence"]]
    return sum(groups) / len(groups)


def _candidates(tools, matcher: dict):
    """Chunks a matcher can match: all of them in memory; with the disk store, the rows of its law / kommun."""
    if not hasattr(tools.retriever, "store"):
        return tools.corpus.chunks.values()
    if "any" in matcher:
        return [chunk for alternative in matcher["any"] for chunk in _candidates(tools, alternative)]
    store = tools.retriever.store
    if "law" in matcher:
        rows = store.query("SELECT * FROM chunks WHERE kind = 'law' AND title LIKE ?", (f"%{matcher['law']}%",))
    elif "doc_id" in matcher:  # plankarta cases: one document, not a scan of the whole table
        rows = store.query("SELECT * FROM chunks WHERE doc_id = ?", (matcher["doc_id"],))
    elif "kommun_code" in matcher:
        rows = store.query("SELECT * FROM chunks WHERE kommun_code = ?", (matcher["kommun_code"],))
    else:
        rows = store.query("SELECT * FROM chunks")
    return [store._chunk(row) for row in rows]


def check_labels(cases: list[dict], tools) -> None:
    missing = [(case["id"], matcher) for case in cases for matcher in case["evidence"]
               if not any(matches(chunk, matcher) for chunk in _candidates(tools, matcher))]
    if missing:
        raise SystemExit("Evidence labels with no matching chunk:\n" + "\n".join(f"  {m}" for m in missing))


def sample_cases(cases: list[dict], n: int, seed: int = 0) -> list[dict]:
    """n cases stratified by expected outcome (rulings are mostly refusals), labelled cases first in each stratum."""
    rng = random.Random(seed)
    strata: dict[str, list[dict]] = {}
    for case in cases:
        verdicts = set(case["verdicts"])
        key = ("negative" if verdicts <= {"not_feasible", "unclear"} and "not_feasible" in verdicts
               else "open" if verdicts <= {"unclear", "conditional"} else "positive")
        strata.setdefault(key, []).append(case)
    for members in strata.values():
        rng.shuffle(members)
        members.sort(key=lambda case: not case["evidence"])  # stable: shuffled within labelled / unlabelled
    picked: list[dict] = []
    while len(picked) < min(n, len(cases)):
        for members in strata.values():
            if members and len(picked) < n:
                picked.append(members.pop(0))
    return picked


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent vs. RAG on feasibility case studies")
    parser.add_argument("--systems", nargs="+", default=["rag", "agent"], choices=["rag", "agent"])
    parser.add_argument("--cases", nargs="*", help="case ids (default: all)")
    parser.add_argument("--effort", default="medium", help="reasoning effort of the answer (RAG answer / agent final answer)")
    parser.add_argument("--explore-effort", default="low", help="agent: effort of the tool-calling turns ('same' = --effort)")
    parser.add_argument("--max-steps", type=int, default=10)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--cases-file", default=CASES_PATH.name, help="cases file in agentic/ (e.g. cases_caselaw.jsonl)")
    parser.add_argument("--store", default="memory", choices=["memory", "disk"],
                        help="memory: laws + the cases' kommuner in RAM; disk: the full corpus from the disk store")
    parser.add_argument("--limit", type=int, default=0, help="only the first N cases")
    parser.add_argument("--sample", type=int, default=0, help="N cases stratified by outcome (fixed seed)")
    parser.add_argument("--repeats", type=int, default=1, help="runs per case and system (variance)")
    parser.add_argument("--resume", type=Path, help="results file of an interrupted run: only the missing runs are made")
    parser.add_argument("--disable-tools", nargs="*", help="agent tools removed for this run (ablation), e.g. view_map_area")
    parser.add_argument("--workers", type=int, default=1,
                        help="cases run in parallel (faster; latencies then include some contention)")
    args = parser.parse_args()
    os.environ.setdefault("LLM_PROVIDER", "openrouter")
    model = resolve_model_name(args.model)

    cases = list(read_jsonl(CASES_PATH.parent / args.cases_file))
    if args.cases:
        cases = [case for case in cases if case["id"] in set(args.cases)]
    if args.limit:
        cases = cases[:args.limit]
    if args.sample:
        cases = sample_cases(cases, args.sample)
    if args.store == "disk":
        from agentic.tools import CorpusTools
        from localrag.store import DiskRetriever

        tools = CorpusTools(DiskRetriever("st-arctic-l-v2"))
        tools.warm_up()
        corpus = "full disk store"
    else:
        kommuner = sorted({code for case in cases for code in case["kommun"]})
        tools = build_tools(kommuner)
        corpus = f"laws + {kommuner} ({len(tools.corpus.chunks)} chunks)"
    check_labels(cases, tools)
    print(f"{len(cases)} cases, corpus: {corpus}, model {model}, effort {args.effort}")

    def run_case(job: tuple[dict, str, int]) -> dict:
        case, system, repeat = job
        try:
            run = (run_rag(case["question"], tools, model, args.effort) if system == "rag"
                   else run_agent(case["question"], tools, model=model, effort=args.effort, max_steps=args.max_steps,
                                  explore_effort=None if args.explore_effort == "same" else args.explore_effort,
                                  disabled_tools=set(args.disable_tools or ())))
        except Exception as exc:  # keep the benchmark going; the failure is reported
            run = AgentRun(error=repr(exc))
        grade = (judge(case, run.answer, model, cited_sources(run.answer, tools)) if run.answer
                 else {"verdict": "none", "points": [], "unsupported_claims": 0, "comment": run.error})
        row = {
            "case": case["id"], "system": system, "repeat": repeat, "effort": args.effort,
            "explore_effort": args.explore_effort,
            "verdict": grade.get("verdict"), "verdict_ok": grade.get("verdict") in case["verdicts"],
            "points": sum(grade.get("points") or [0]) / (2 * len(case["key_points"])),
            "unsupported": grade.get("unsupported_claims", 0),
            "evidence": evidence_recall(case, run.seen_chunks, tools),
            "tool_calls": len(run.steps) if system == "agent" else 0, "llm_calls": run.llm_calls,
            # Map reading (plankarta cases): image views, and whether the case's own plankarta was viewed
            "map_views": sum(1 for s in run.steps if s["tool"] in MAP_TOOLS),
            "map_doc_viewed": (any(s["tool"] in MAP_TOOLS and s["arguments"].get("doc_id") == case["map_doc_id"]
                                   for s in run.steps) if case.get("map_doc_id") else None),
            "seconds": run.seconds, "first_token_s": run.first_token_s,
            "cost": round(run.usage["cost"], 5), "judge_cost": grade.get("judge_cost", 0),
            "tokens_in": run.usage["input_tokens"], "tokens_out": run.usage["output_tokens"],
            "comment": grade.get("comment"), "answer": run.answer, "steps": run.steps, "error": run.error,
        }
        evidence = "-" if row["evidence"] is None else format(row["evidence"], ".2f")
        print(f"  {case['id']:<26} {system:<6} verdict {row['verdict']:<13}{'OK ' if row['verdict_ok'] else 'NO '} "
              f"points {row['points']:.2f}  evidence {evidence:>4}  tools {row['tool_calls']:>2}  "
              f"{row['seconds']:>5.0f}s (1st token {row['first_token_s'] or '-'})  ${row['cost']:.4f}", flush=True)
        return row

    # Results are written after every case (a killed run keeps what it paid for); --resume continues such a file
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    cases_tag = "" if args.cases_file == CASES_PATH.name else f"-{Path(args.cases_file).stem}"
    if args.disable_tools:
        cases_tag += "-no-" + "-".join(sorted(args.disable_tools))
    out = args.resume or RESULTS_DIR / (f"bench-{datetime.now():%Y%m%d-%H%M%S}-{'-'.join(args.systems)}-{args.effort}"
                                        f"-explore-{args.explore_effort}{cases_tag}.json")
    rows: list[dict] = json.loads(out.read_text(encoding="utf-8")) if args.resume and out.exists() else []
    rows = [row for row in rows if not row.get("error")]  # resumed: failed runs (e.g. network errors) are redone
    done = {(row["case"], row["system"], row.get("repeat", 0)) for row in rows}
    jobs = [(case, system, repeat) for repeat in range(args.repeats) for case in cases for system in args.systems
            if (case["id"], system, repeat) not in done]
    if done:
        print(f"resuming {out.name}: {len(done)} runs done, {len(jobs)} to go")
    lock = threading.Lock()

    def run_and_save(job: tuple[dict, str, int]) -> None:
        row = run_case(job)
        with lock:
            rows.append(row)
            out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(run_and_save, jobs))

    print("\nsystem   verdict_ok  points  evidence  unsupported  tool_calls  seconds   cost/case")
    for system in args.systems:
        mine = [row for row in rows if row["system"] == system]
        if not mine:
            continue
        def mean(key: str) -> float:
            values = [row[key] for row in mine if row[key] is not None]
            return sum(values) / len(values) if values else 0.0
        first = [row["first_token_s"] for row in mine if row["first_token_s"] is not None]
        print(f"{system:<8} {mean('verdict_ok'):>10.2f}  {mean('points'):>6.2f}  {mean('evidence'):>8.2f}  "
              f"{mean('unsupported'):>11.2f}  {mean('tool_calls'):>10.1f}  {mean('seconds'):>7.0f}  ${mean('cost'):.4f}"
              f"  llm_calls {mean('llm_calls'):.1f}  first_token {sum(first) / len(first) if first else 0:.0f}s")
        if args.repeats > 1:  # spread of the per-repeat means: how much of a difference is noise
            for key in ("verdict_ok", "points", "evidence"):
                per_repeat = []
                for repeat in range(args.repeats):
                    values = [r[key] for r in mine if r["repeat"] == repeat and r[key] is not None]
                    per_repeat.append(sum(values) / len(values) if values else 0.0)
                print(f"         {key:<11} per repeat: {', '.join(f'{v:.2f}' for v in per_repeat)}")

    print(f"\nSaved {out}")


if __name__ == "__main__":
    main()

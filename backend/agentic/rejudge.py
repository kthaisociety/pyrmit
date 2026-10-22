"""
Inter-judge agreement: re-grade the answers stored in benchmark result files with another judge model and compare
with the original grades (by default GPT-6 Luna, the same model as the agent: possible self-preference).

    cd backend
    python -m agentic.rejudge data/agentic/bench-....json --judge-model xiaomi/mimo-v2.6-flash --sample 50

Writes data/agentic/rejudge-<judge>-<file>.json (the new grades next to the old ones) and prints:
  verdict    share of answers both judges classify the same, and Cohen's kappa on verdict_ok
  points     mean of each judge, mean absolute difference, correlation; exact agreement per key point
  unsupported  mean of each judge
Spends API credits (one judge call per answer, ~$0.001 with MiMo Flash).
"""

import argparse
import json
import os
import random
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from corpus.common import read_jsonl
from agentic.bench import CASES_PATH, RESULTS_DIR, grade_answer
from localrag.store import DiskStore, store_dir
from llm import resolve_model_name


class ChunkLookup:
    """get_chunk over the disk store's SQLite, as CorpusTools.get_chunk (no embedding model loaded)."""

    def __init__(self):
        self.db = sqlite3.connect(store_dir("st-arctic-l-v2") / "corpus.sqlite", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()

    def get_chunk(self, chunk_id: str) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,)).fetchone()
            if row is None and 8 <= len(chunk_id) < 16:
                rows = self.db.execute("SELECT * FROM chunks WHERE chunk_id >= ? AND chunk_id < ? LIMIT 2",
                                       (chunk_id, chunk_id + "g")).fetchall()
                row = rows[0] if len(rows) == 1 else None
        return DiskStore._chunk(row) if row else None


def kappa(pairs: list[tuple[bool, bool]]) -> float | None:
    if not pairs:
        return None
    observed = sum(a == b for a, b in pairs) / len(pairs)
    p_a, p_b = sum(a for a, _ in pairs) / len(pairs), sum(b for _, b in pairs) / len(pairs)
    expected = p_a * p_b + (1 - p_a) * (1 - p_b)
    return None if expected == 1 else (observed - expected) / (1 - expected)


def correlation(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    return None if not sx or not sy else sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def two(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def cases_for(path: Path) -> dict[str, dict]:
    """The cases of a result file, from its name (-cases_<set> tag; none = cases.jsonl)."""
    name = next((f"cases_{part.split('-')[0]}.jsonl" for part in path.stem.split("-cases_")[1:]), CASES_PATH.name)
    return {case["id"]: case for case in read_jsonl(CASES_PATH.parent / name)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-grade stored benchmark answers with another judge")
    parser.add_argument("results", type=Path, nargs="+")
    parser.add_argument("--judge-model", default="xiaomi/mimo-v2.6-flash")
    parser.add_argument("--sample", type=int, default=0, help="N answers drawn at random (fixed seed) over all files")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    os.environ.setdefault("LLM_PROVIDER", "openrouter")
    judge_model = resolve_model_name(args.judge_model)
    lookup = ChunkLookup()

    jobs = []
    for path in args.results:
        cases = cases_for(path)
        jobs.extend((path, cases[row["case"]], row) for row in json.loads(path.read_text(encoding="utf-8"))
                    if row.get("answer") and row["case"] in cases)
    if args.sample:
        jobs = random.Random(0).sample(jobs, min(args.sample, len(jobs)))
    # Written after every answer, and a rerun with the same arguments only grades the missing ones (resume)
    tag = judge_model.split("/")[-1]
    out = RESULTS_DIR / f"rejudge-{tag}-{args.results[0].stem}{'-and-more' if len(args.results) > 1 else ''}.json"
    results: list[dict] = json.loads(out.read_text(encoding="utf-8")) if out.exists() else []
    done = {(r["file"], r["case"], r["system"], r["repeat"]) for r in results}
    jobs = [job for job in jobs if (job[0].name, job[1]["id"], job[2]["system"], job[2].get("repeat", 0)) not in done]
    print(f"{len(jobs)} answers to re-grade by {judge_model}" + (f" ({len(done)} done in {out.name})" if done else ""))
    lock = threading.Lock()

    def regrade(job: tuple[Path, dict, dict]) -> None:
        path, case, row = job
        try:
            seen = [chunk_id for step in row.get("steps") or [] for chunk_id in step.get("chunks") or []]
            new = grade_answer(case, row["answer"], lookup, judge_model, seen)
        except Exception as exc:  # e.g. a network error: left for the next run
            print(f"  {case['id']}: {exc!r}")
            return
        result = {"file": path.name, "case": case["id"], "system": row["system"], "repeat": row.get("repeat", 0),
                  "old": {k: row.get(k) for k in ("verdict", "verdict_ok", "points", "unsupported", "judge_model")},
                  "new": {k: v for k, v in new.items() if k != "comment"} | {"comment": new.get("comment")}}
        with lock:
            results.append(result)
            out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"  {len(results):>3} {case['id']:<26} {row['system']:<6} points {row.get('points') or 0:.2f} -> "
                  f"{new['points']:.2f}", flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(regrade, jobs))

    with_verdict = [r for r in results if r["old"]["verdict_ok"] is not None and r["new"]["verdict_ok"] is not None]
    same = sum(r["old"]["verdict"] == r["new"]["verdict"] for r in with_verdict)
    old_points = [r["old"]["points"] for r in results if r["old"]["points"] is not None]
    new_points = [r["new"]["points"] for r in results if r["old"]["points"] is not None]
    print(f"\nverdict: same class {same}/{len(with_verdict)}, kappa on verdict_ok "
          f"{two(kappa([(r['old']['verdict_ok'], r['new']['verdict_ok']) for r in with_verdict]))} "
          f"(verdict_ok old {sum(r['old']['verdict_ok'] for r in with_verdict) / max(len(with_verdict), 1):.2f}, "
          f"new {sum(r['new']['verdict_ok'] for r in with_verdict) / max(len(with_verdict), 1):.2f})")
    if old_points:
        diff = sum(abs(a - b) for a, b in zip(old_points, new_points)) / len(old_points)
        print(f"points: old {sum(old_points) / len(old_points):.2f}, new {sum(new_points) / len(new_points):.2f}, "
              f"mean |diff| {diff:.2f}, correlation {two(correlation(old_points, new_points))}")
    for system in sorted({r["system"] for r in results}):
        mine = [r for r in results if r["system"] == system]
        print(f"  {system:<6} n {len(mine):>3}  points old {sum(r['old']['points'] or 0 for r in mine) / len(mine):.2f} "
              f"new {sum(r['new']['points'] for r in mine) / len(mine):.2f}  unsupported old "
              f"{sum(r['old']['unsupported'] or 0 for r in mine) / len(mine):.2f} new "
              f"{sum(r['new']['unsupported'] or 0 for r in mine) / len(mine):.2f}")
    print(f"judge cost ${sum(r['new'].get('judge_cost', 0) for r in results):.3f}\nSaved {out}")


if __name__ == "__main__":
    main()

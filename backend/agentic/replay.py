"""
Replay the tool calls the agent really made (stored in the benchmark results) against the current corpus.

Unit tests feed the tools the inputs we imagine; the model writes others ("c:<id>", "[c:<id>]", a doc id as
chunk_id, "9:4", "MPF"...). Before 2026-10-22 a quarter of the reads failed on such forms and no test saw it. This
replays every distinct call (no search: it needs the embedding model, and no image tool) and checks:
  - no call raises (error kind "exception");
  - a read of an id the corpus has (a 16-hex chunk id, or a doc id) returns it, whatever the form it was written in;
  - a law_section of a section the corpus has returns it.
Calls on ids that left the corpus since the run (rebuilds) are counted, not failed. Each call is timed (p50 / p95 /
max per tool, `latency` in the result file): with `--search N`, N stored search calls are replayed too, for their time
only (the corpus grew ~6x with the 2026-10-23 crawl).

    cd backend && python -m agentic.replay                      # all data/agentic/bench-*.json
    python -m agentic.replay data/agentic/bench-*-x-toolfix.json --sample 2000
"""

import argparse
import glob
import json
import random
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import date

from agentic.tools import LAW_ALIASES, CorpusTools, _fold, normalize_section, run_tool
from corpus.common import DATA_DIR, RESULTS_ROOT

RESULTS = RESULTS_ROOT / "agentic"
REPLAYED = ("read", "law_section", "grep", "list_documents", "find_kommun", "plans", "plan_rules")
HEX_ID = re.compile(r"(?<![0-9a-f])[0-9a-f]{16}(?![0-9a-f])")
DOC_ID = re.compile(r"(?:pdf|page|law|legacy):[^\s\]\"']+")


def load_calls(patterns: list[str], replayed: tuple[str, ...] = REPLAYED) -> list[tuple[str, dict]]:
    """Distinct (tool, arguments) pairs of the stored agent runs."""
    seen, calls = set(), []
    for pattern in patterns:
        for path in glob.glob(pattern):
            for row in json.load(open(path, encoding="utf-8")):
                for step in row.get("steps") or []:
                    arguments = step.get("arguments")
                    if step["tool"] not in replayed or not isinstance(arguments, dict):
                        continue
                    key = (step["tool"], json.dumps(arguments, sort_keys=True, ensure_ascii=False))
                    if key not in seen:
                        seen.add(key)
                        calls.append((step["tool"], arguments))
    return calls


def _law_exists(tools: CorpusTools, law: str, section: str) -> bool:
    """Independent of law_section's title matching: any statute whose folded title contains the folded name
    (or alias) has a chunk labelled with the section."""
    wanted = _fold(LAW_ALIASES.get(law.strip().lower(), law.strip().lower()))
    label = normalize_section(section)
    rows = tools.corpus.store.query("SELECT DISTINCT title FROM chunks WHERE kind = 'law'") \
        if hasattr(tools.corpus, "store") else []
    titles = [row["title"] for row in rows if wanted and wanted in _fold(row["title"])]
    return any(tools.corpus.store.query("SELECT 1 FROM chunks WHERE kind = 'law' AND title = ? AND section = ? LIMIT 1",
                                        (title, label)) for title in titles)


def replay(tools: CorpusTools, calls: list[tuple[str, dict]]) -> dict:
    errors, violations, stale, seconds = defaultdict(Counter), defaultdict(list), Counter(), defaultdict(list)
    for tool, arguments in calls:
        started = time.perf_counter()
        result = run_tool(tools, tool, dict(arguments))
        seconds[tool].append(time.perf_counter() - started)
        if tool == "search":  # timed only
            continue
        if result.error:
            errors[tool][result.error] += 1
        if result.error == "exception":
            violations[tool].append(f"{arguments} -> {result.text[:160]}")
        if tool == "read" and result.error:
            written = " ".join(str(arguments.get(key) or "") for key in ("chunk_id", "doc_id"))
            ids = HEX_ID.findall(written)
            docs = DOC_ID.findall(written)
            exists = any(tools.corpus.chunk(i) is not None for i in ids) or \
                any(tools.corpus.doc(d) is not None for d in docs)
            # A document can get shorter between corpora (the corpus-wide dedup of repeated paragraphs drops more of
            # it in a larger corpus): a stored start past its new end is stale, not a failure
            if exists and "is past the end" not in result.text:
                violations[tool].append(f"{arguments} -> {result.text[:120]}")
            else:
                stale[tool] += 1
        if tool == "law_section" and result.error:
            if _law_exists(tools, str(arguments.get("law", "")), str(arguments.get("section", ""))):
                violations[tool].append(f"{arguments} -> {result.text[:120]}")
    latency = {tool: {"p50": round(float(sorted(s)[len(s) // 2]), 3), "p95": round(float(sorted(s)[int(len(s) * 0.95)]), 3),
                      "max": round(max(s), 3)} for tool, s in seconds.items()}
    return {"calls": Counter(tool for tool, _ in calls), "errors": errors, "violations": violations, "stale": stale,
            "latency": latency}


def build_tools() -> CorpusTools:
    from localrag.store import DiskRetriever
    return CorpusTools(DiskRetriever("st-arctic-l-v2"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay stored agent tool calls against the current corpus")
    parser.add_argument("files", nargs="*", default=[str(RESULTS / "bench-*.json")])
    parser.add_argument("--sample", type=int, default=0, help="replay a random sample of the distinct calls")
    parser.add_argument("--search", type=int, default=0, help="also time this many stored search calls")
    args = parser.parse_args()

    calls = load_calls(args.files)
    if args.sample and len(calls) > args.sample:
        calls = random.Random(0).sample(calls, args.sample)
    tools = build_tools()
    if args.search:
        searches = load_calls(args.files, ("search",))
        tools.warm_up()  # the embedding model load is not a search's time
        calls += random.Random(0).sample(searches, min(args.search, len(searches)))
    result = replay(tools, calls)
    print(f"{'tool':<15} {'calls':>6}  {'p50 s':>6} {'p95 s':>6} {'max s':>6}  errors (kind: count)                  violations")
    for tool, count in result["calls"].most_common():
        kinds = ", ".join(f"{k} {v}" for k, v in result["errors"][tool].most_common())
        times = result["latency"][tool]
        print(f"{tool:<15} {count:>6}  {times['p50']:>6} {times['p95']:>6} {times['max']:>6}  {kinds:<38} "
              f"{len(result['violations'][tool])}")
    if result["stale"]:
        print(f"ids no longer in the corpus (not failures): {dict(result['stale'])}")
    for tool, examples in result["violations"].items():
        print(f"\n{tool}: {len(examples)} calls failed on something the corpus has")
        for example in examples[:8]:
            print(f"  {example}")
    summary = {"calls": dict(result["calls"]), "errors": {t: dict(c) for t, c in result["errors"].items()},
               "violations": {t: len(v) for t, v in result["violations"].items()}, "stale": dict(result["stale"]),
               "sample": args.sample or None, "latency": result["latency"]}
    out = RESULTS / f"replay-{date.today():%Y%m%d}.json"
    out.write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(f"-> {out}")
    sys.exit(1 if any(result["violations"].values()) else 0)


if __name__ == "__main__":
    main()

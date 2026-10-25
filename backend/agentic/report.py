"""
PDF report of the agent benchmark (English; a French version on request): the pipeline tested, how the benchmark was built,
example cases, how answers are scored, the results of the effort matrix and what they mean.

    cd backend && python -m agentic.report          # -> ../pyrmit_doc/pyrmit_benchmark_report.pdf (en)
    python -m agentic.report --lang fr              # -> ../pyrmit_doc/pyrmit_rapport_benchmark.pdf (or --lang both)

Reads the result files of agentic.bench (data/agentic/bench-*.json, from the effort matrix on the full disk store)
and prints the HTML to PDF with headless Chrome / Edge. Charts are inline SVG (no plotting dependency).
"""

import html
import json
import re
import shutil
import sqlite3
import subprocess
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from agentic.bench import CASES_PATH, RESULTS_DIR, sample_cases
from corpus.common import DATA_DIR, RESULTS_ROOT, read_jsonl
from localrag.eval import matches
from localrag.index import INDEX_DIR

DOC_DIR = Path(__file__).resolve().parents[2].parent / "pyrmit_doc"
OUTPUT_NAMES = {"fr": "pyrmit_rapport_benchmark", "en": "pyrmit_benchmark_report"}
LANG = "en"  # set by main(); tr() and fmt() follow it
FIRST_MATRIX_RUN = "20261007-211220"
# From this run on the agent classifies the question (answer_ready(mode), formats per mode): later files are kept out of
# the effort matrix and shown in the "tasks beyond the verdict" section (new sets + regression of the old ones)
MODES_RUN = "20261019-000000"
PROPOSE_FIX_RUN = "20261021-000000"  # propose guide + last turn forced to answer_ready
# Short reading of the results for the technical report's summary (the benchmark report has the full one)
NARRATIVE_RESULTS = {"en": """<p>The agent beats the classic RAG on key points and evidence on every set, and the gap
grows with difficulty (MÖD and plan maps): a single search on the user's facts rarely reaches the deciding statute section
or plan map, whereas the agent first works out which rule applies, then looks it up. The RAG is about twice as fast and
four times cheaper, with as high a grounding (it says less). Within the agent, the exploration effort is the setting that
matters; map reading lifts the verdict on plan-map questions; refused projects remain the agent's weak spot (it leans
towards “feasible with conditions”).</p>"""}  # earlier result files used the in-memory corpus subset and older prompts
BROWSERS = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"]

# Earlier runs (14 cases, in-memory corpus of the 5 kommuner of the cases), from pyrmit_agentic_rag_report.md
HISTORY = [  # (French name, English name), verdict, key points, evidence, grounding, latency s, first token s, cost $
    (("RAG classique (1 recherche, réponse high, non streamée)", "Classic RAG (1 search, high-effort answer, not streamed)"),
     1.0, 0.56, 0.58, 0.84, 30, None, 0.0021),
    (("Agent v1 (effort high partout)", "Agent v1 (high effort throughout)"), 1.0, 0.75, 0.86, 0.68, 64, None, 0.0057),
    (("Agent v2 (sources citables, effort medium)", "Agent v2 (citeable sources, medium effort)"),
     1.0, 0.77, 0.96, 0.86, 39, 39, 0.0042),
    (("Agent v3 (exploration low, réponse medium)", "Agent v3 (low exploration, medium answer)"),
     1.0, 0.68, 0.73, 0.82, 19, 13, 0.0025),
    (("Agent v4 (v3 + lecture du document communal)", "Agent v4 (v3 + read the key municipal document)"),
     1.0, 0.65, 0.84, 0.84, 23, 17, 0.0036),
]

FILE = re.compile(r"bench-(\d{8}-\d{6})-(?P<systems>[a-z-]+?)-(?P<answer>low|medium|high)"
                  r"-explore-(?P<explore>low|medium|high|same)(?P<tag>-cases_[a-z]+)?"
                  r"(?:-no-(?P<ablation>[a-z_-]+?))?(?:-x-(?P<label>[\w.-]+))?\.json$")
CASE_SETS = {None: "cases14", "-cases_caselaw": "mod", "-cases_plans": "plans", "-cases_tasks": "tasks",
             "-cases_generated": "generated"}
TASK_SETS = {"tasks", "generated"}


def esc(value) -> str:
    return html.escape(str(value))


def tr(fr: str, en: str) -> str:
    return en if LANG == "en" else fr


def fmt(value, digits: int = 2) -> str:
    if value is None:
        return "–"
    text = f"{value:.{digits}f}"
    return text if LANG == "en" else text.replace(".", ",")


def money(value, digits: int = 4) -> str:
    return f"${fmt(value, digits)}" if LANG == "en" else f"{fmt(value, digits)} $"


def mean(values: list) -> float | None:
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


# --- data --------------------------------------------------------------------------------------------------------

STORE_DB = INDEX_DIR / "store" / "st-arctic-l-v2" / "corpus.sqlite"
CHUNK_ID = re.compile(r"c:([0-9a-f]{8,16})(?![0-9a-f])")


class StoreChunks:
    """Chunks read on demand from the disk store's SQLite; a truncated id (the model sometimes drops characters)
    resolves by unique prefix, as in CorpusTools.get_chunk."""

    def __init__(self):
        self.db = sqlite3.connect(STORE_DB) if STORE_DB.exists() else None
        if self.db is not None:
            self.db.row_factory = sqlite3.Row
        self.cache: dict[str, dict | None] = {}

    def get(self, chunk_id: str) -> dict | None:
        if chunk_id not in self.cache:
            row = None
            if self.db is not None:
                row = self.db.execute("SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,)).fetchone()
                if row is None and len(chunk_id) < 16:
                    rows = self.db.execute("SELECT * FROM chunks WHERE chunk_id >= ? AND chunk_id < ? LIMIT 2",
                                           (chunk_id, chunk_id + "g")).fetchall()
                    row = rows[0] if len(rows) == 1 else None
            self.cache[chunk_id] = dict(row) if row else None
        return self.cache[chunk_id]


def all_cases() -> dict[str, dict]:
    return {case["id"]: case for name in ("cases.jsonl", "cases_caselaw.jsonl", "cases_plans.jsonl",
                                          "cases_tasks.jsonl", "cases_generated.jsonl")
            if (CASES_PATH.parent / name).exists() for case in read_jsonl(CASES_PATH.parent / name)}


def reading_metrics(row: dict, case: dict | None, chunks: StoreChunks) -> None:
    """Two reading measures computed from a result row, no LLM: `seen_n` = distinct passages the system had in
    front of it (retrieved for the RAG, tool outputs for the agent); `evidence_cited` = share of the expected
    evidence that the answer cites ([c:id]), not just saw."""
    seen = {chunk_id for step in row.get("steps") or [] for chunk_id in step.get("chunks") or []}
    row["seen_n"] = len(seen) if row.get("steps") else None
    if not case or not case.get("evidence"):
        row["evidence_cited"] = None
        return
    cited = [c for c in (chunks.get(i) for i in dict.fromkeys(CHUNK_ID.findall(row.get("answer") or ""))) if c]
    row["evidence_cited"] = sum(any(matches(c, m) for c in cited) for m in case["evidence"]) / len(case["evidence"])


def load_runs() -> list[dict]:
    """One entry per (case set, system, explore effort, answer effort), merging every matrix file of that
    configuration (each file's passes count as separate repeats)."""
    files: dict[tuple, list[Path]] = defaultdict(list)
    for path in sorted(RESULTS_DIR.glob("bench-*.json")):
        match = FILE.search(path.name)
        if (not match or match.group(1) < FIRST_MATRIX_RUN or match.group(1) >= MODES_RUN
                or CASE_SETS.get(match.group("tag")) in TASK_SETS):
            continue
        key = (CASE_SETS[match.group("tag")], match.group("systems"), match.group("explore"), match.group("answer"),
               match.group("ablation") or "")
        files[key].append(path)
    runs = []
    cases_by_id, chunks = all_cases(), StoreChunks()
    for (cases, systems, explore, answer, ablation), paths in sorted(files.items()):
        rows = []
        for index, path in enumerate(paths):
            for row in json.loads(path.read_text(encoding="utf-8")):
                row = {**row, "repeat": f"{index}.{row.get('repeat', 0)}"}
                reading_metrics(row, cases_by_id.get(row["case"]), chunks)
                rows.append(row)
        for system in sorted({row["system"] for row in rows}):
            mine = [row for row in rows if row["system"] == system and not row.get("error")]
            if not mine:
                continue
            repeats = sorted({row["repeat"] for row in mine})
            runs.append({
                "cases": cases, "system": system, "explore": explore if system == "agent" else "–", "answer": answer,
                "ablation": ablation, "map_views": mean([r.get("map_views") for r in mine]),
                "seen": mean([r.get("seen_n") for r in mine]), "cited": mean([r.get("evidence_cited") for r in mine]),
                "file": ", ".join(p.name for p in paths), "n": len(mine), "repeats": len(repeats),
                "verdict": mean([float(r["verdict_ok"]) for r in mine]), "points": mean([r["points"] for r in mine]),
                "evidence": mean([r["evidence"] for r in mine]), "grounded": mean([r.get("grounded") for r in mine]),
                "unsupported": mean([r["unsupported"] for r in mine]), "tools": mean([r["tool_calls"] for r in mine]),
                "llm_calls": mean([r["llm_calls"] for r in mine]), "seconds": mean([r["seconds"] for r in mine]),
                "first": mean([r.get("first_token_s") for r in mine]), "cost": mean([r["cost"] for r in mine]),
                "points_by_repeat": [mean([r["points"] for r in mine if r["repeat"] == k]) for k in repeats],
                "rows": mine,
            })
    order = {"low": 0, "medium": 1, "high": 2, "–": 3, "same": 3}
    return sorted(runs, key=lambda r: (r["cases"], r["system"] != "agent", r["ablation"], order[r["explore"]],
                                       order[r["answer"]]))


def mode_rows() -> list[dict]:
    """Every answer of the runs made with the mode prompt (MODES_RUN on): new task sets and regression runs, with the
    set, the run stamp and the reading measures."""
    rows = []
    cases_by_id, chunks = all_cases(), StoreChunks()
    for path in sorted(RESULTS_DIR.glob("bench-*.json")):
        match = FILE.search(path.name)
        if not match or match.group(1) < MODES_RUN or match.group("ablation") or match.group("label"):
            continue
        for row in json.loads(path.read_text(encoding="utf-8")):
            if row.get("error"):
                continue
            row = {**row, "set": CASE_SETS[match.group("tag")], "stamp": match.group(1),
                   "task": row.get("task", "verdict")}
            reading_metrics(row, cases_by_id.get(row["case"]), chunks)
            rows.append(row)
    return rows


TASK_NAMES = {"explain": ("expliquer", "explain"), "propose": ("proposer", "propose"), "develop": ("développer", "develop")}


def task_table(rows: list[dict]) -> str:
    """Per task and system: key points, evidence, mode recognition and the task-specific scores."""
    head = ("<tr><th>Task</th><th>System</th><th>n</th><th>Key points</th><th>Evidence seen</th><th>Evidence cited</th>"
            "<th>Unsupported</th><th>Mode right</th><th>Task-specific</th><th>Latency</th><th>Cost / question</th></tr>")
    body = []
    for task in ("explain", "propose", "develop"):
        groups = [("RAG", [r for r in rows if r["task"] == task and r["system"] == "rag"]),
                  ("Agent", [r for r in rows if r["task"] == task and r["system"] == "agent" and r["stamp"] < PROPOSE_FIX_RUN])]
        if task == "propose":
            groups.append(("Agent, propose fix", [r for r in rows if r["task"] == task and r["system"] == "agent"
                                                  and r["stamp"] >= PROPOSE_FIX_RUN]))
        groups = [(name, mine) for name, mine in groups if mine]
        for i, (name, mine) in enumerate(groups):
            def m(key: str) -> float | None:
                return mean([r.get(key) for r in mine])
            if task == "propose":
                specific = (f"places {fmt(m('anchors'))}, {fmt(m('proposals'), 1)} options, "
                            f"{fmt(m('proposals_sourced'))} sourced")
            elif task == "develop":
                specific = (f"obstacles {fmt(m('points_obstacle'))}, levers {fmt(m('points_lever'))}, "
                            f"asks {fmt(m('points_ask'))}")
            else:
                specific = "–"
            first = f"<td rowspan='{len(groups)}'><b>{TASK_NAMES[task][1]}</b></td>" if i == 0 else ""
            body.append(f"<tr>{first}<td>{esc(name)}</td><td>{len(mine)}</td><td>{fmt(m('points'))}</td>"
                        f"<td>{fmt(m('evidence'))}</td><td>{fmt(m('evidence_cited'))}</td><td>{fmt(m('unsupported'), 1)}</td>"
                        f"<td>{fmt(mean([float(r['mode_ok']) for r in mine if r.get('mode_ok') is not None]))}</td>"
                        f"<td>{specific}</td><td>{fmt(m('seconds'), 0)} s</td><td>{money(m('cost'))}</td></tr>")
    return f"<table>{head}{''.join(body)}</table>"


def regression_table(matrix: list[dict], rows: list[dict]) -> str:
    """The verdict sets before / after the mode prompt (agent, medium / medium, Luna judge), on the same cases."""
    head = ("<tr><th>Set</th><th>Prompt</th><th>n</th><th>Verdict</th><th>Key points</th><th>Evidence seen</th>"
            "<th>Unsupported</th><th>Mode “verdict”</th><th>Latency</th><th>Cost / question</th></tr>")
    body = []
    for key, name in (("cases14", "14 cases"), ("mod", "MÖD")):
        new = [r for r in rows if r["set"] == key and r["system"] == "agent"]
        old_run = next((r for r in matrix if r["cases"] == key and r["system"] == "agent" and r["explore"] == "medium"
                        and r["answer"] == "medium" and not r["ablation"]), None)
        if not new or not old_run:
            continue
        ids = {r["case"] for r in new}
        old = [r for r in old_run["rows"] if r["case"] in ids]
        for i, (prompt, mine) in enumerate((("before (verdict format)", old), ("with modes", new))):
            first = f"<td rowspan='2'><b>{name}</b></td>" if i == 0 else ""
            modes = [r.get("mode") for r in mine]
            body.append(f"<tr>{first}<td>{prompt}</td><td>{len(mine)}</td>"
                        + "".join(f"<td>{fmt(mean([float(r[k]) for r in mine if r.get(k) is not None]))}</td>"
                                  for k in ("verdict_ok", "points", "evidence"))
                        + f"<td>{fmt(mean([r['unsupported'] for r in mine]), 1)}</td>"
                        + f"<td>{fmt(modes.count('verdict') / len(modes)) if any(modes) else '–'}</td>"
                        + f"<td>{fmt(mean([r['seconds'] for r in mine]), 0)} s</td>"
                        + f"<td>{money(mean([r['cost'] for r in mine]))}</td></tr>")
    return f"<table>{head}{''.join(body)}</table>" if body else ""


def judge_agreement() -> dict | None:
    """The second-judge check (agentic.rejudge): stored answers graded again by another model family."""
    files = [f for f in sorted(RESULTS_DIR.glob("rejudge-*.json")) if "-x-" not in f.name]  # not the experiments
    if not files:
        return None
    rows = json.loads(files[-1].read_text(encoding="utf-8"))
    pairs = [(r["old"], r["new"]) for r in rows if r["old"].get("points") is not None]
    verdicts = [(o, n) for o, n in pairs if o.get("verdict_ok") is not None and n.get("verdict_ok") is not None]
    if not pairs:
        return None
    from agentic.rejudge import correlation, kappa

    return {"n": len(pairs), "judge": rows[0]["new"].get("judge_model", "?"),
            "same_verdict": sum(o["verdict"] == n["verdict"] for o, n in verdicts) / max(len(verdicts), 1),
            "kappa": kappa([(o["verdict_ok"], n["verdict_ok"]) for o, n in verdicts]),
            "points_old": mean([o["points"] for o, _ in pairs]), "points_new": mean([n["points"] for _, n in pairs]),
            "corr": correlation([o["points"] for o, _ in pairs], [n["points"] for _, n in pairs]),
            "diff": mean([abs(o["points"] - n["points"]) for o, n in pairs]),
            "unsup_old": mean([o.get("unsupported") or 0 for o, _ in pairs]),
            "unsup_new": mean([n.get("unsupported") or 0 for _, n in pairs])}


# Optimisation round (2026-10-21): result files tagged `bench --label`, the 52 dev cases (14 verdict + 10 seeds +
# 28 generated), MiMo Flash judge in the run, Luna judge again with agentic.rejudge
EXPERIMENTS = [("base", "Luna, prompt before 2026-10-21"),
               ("v2", "Luna, + recipe per mode and site checklist"),
               ("mimo-flash", "MiMo v2.6 Flash as the agent"),
               ("v3", "Luna, + “complete answer” (adopted)")]


# Recommended next steps after the optimisation round, in order (benchmark report section 4, technical report section 9)
NEXT_STEPS = """<ol>
<li><b>Confirm the adopted prompt</b> (“complete answer”): a second pass on the 52 dev cases, and the MÖD sample and
plankarta set, which the optimisation round did not run (≈ $1). A +0.05 gain from one pass is close to the noise.</li>
<li><b>Check step on the draft answer</b>: before streaming, check each claim against the chunk it cites and drop or
flag what the chunk does not state, to bring the unsupported claims down (≈ 1.5–2 per answer for the Luna judge)
without losing the coverage the “complete answer” instruction gained. Measure with both judges and 2 passes.</li>
<li><b>A stronger model for the writing only</b>: the gains are in the answer, not in the exploration; test MiMo v2.6
Pro or GPT-6 Sol on the final turn only (Luna keeps exploring), with the check step, on a subset first: Sol costs
≈ 20× Luna per token.</li>
<li><b>Expert review</b>: a Swedish planning expert scores a sample of answers and reviews the generated references
(key points written by an LLM, reviewed only by the developers).</li>
<li><b>Benchmark coverage</b>: “I have this land, what could I do with it?” (place fixed, project open); multi-turn
cases (iterating on a project with the user); the localisation work as a <code>locate</code> task in the same case
format, after the merge.</li>
<li><b>Latency</b>: two of 52 answers waited over 6 minutes on a stalled provider stream: retry a stream that stalls,
and bring propose (≈ 80 s) closer to the other modes.</li>
</ol>"""


def experiment_rows(label: str) -> list[dict]:
    rows = []
    for path in sorted(RESULTS_DIR.glob(f"bench-*-x-{label}.json")):
        rows += [r for r in json.loads(path.read_text(encoding="utf-8")) if r["system"] == "agent" and not r.get("error")]
    return rows


def experiment_table() -> str:
    """Per configuration: key points and unsupported claims under both judges, evidence, latency, cost."""
    import statistics

    head = ("<tr><th>Configuration</th><th>n</th><th>Key points<br>MiMo judge</th><th>Key points<br>Luna judge</th>"
            "<th>Unsupported<br>MiMo / Luna</th><th>Evidence seen</th><th>Answer length</th><th>Median latency</th>"
            "<th>Cost / question</th></tr>")
    body = []
    for label, name in EXPERIMENTS:
        rows = experiment_rows(label)
        if not rows:
            continue
        luna = next((json.loads(f.read_text(encoding="utf-8")) for f in RESULTS_DIR.glob(f"rejudge-gpt-6-luna-*-x-{label}-and-more.json")), [])
        luna_points = mean([r["new"]["points"] for r in luna])
        luna_unsup = mean([r["new"]["unsupported"] for r in luna])
        body.append(f"<tr><td>{html.escape(name)}</td><td>{len(rows)}</td><td>{fmt(mean([r['points'] for r in rows]))}</td>"
                    f"<td>{fmt(luna_points)}</td><td>{fmt(mean([r['unsupported'] for r in rows]), 1)} / {fmt(luna_unsup, 1)}</td>"
                    f"<td>{fmt(mean([r['evidence'] for r in rows if r.get('evidence') is not None]))}</td>"
                    f"<td>{round(mean([len(r['answer']) for r in rows]) or 0):,} chars</td>"
                    f"<td>{statistics.median(r['seconds'] for r in rows):.0f} s</td>"
                    f"<td>${fmt(mean([r['cost'] for r in rows]), 4)}</td></tr>")
    return f"<table>{head}{''.join(body)}</table>" if body else ""


# Bug round (2026-10-22): the same 52 dev cases before (x-v3, 1 pass) and after the tool / data fixes (x-toolfix, 3 passes)
BUG_ROUND = [("v3", "Before the fixes (2026-10-21, 1 pass)"), ("toolfix", "After the fixes (2026-10-22, 3 passes)")]


def tool_health(rows: list[dict]) -> dict:
    """Tool calls that returned nothing, per answer, from the stored steps."""
    counts = Counter()
    for row in rows:
        for step in row.get("steps") or []:
            if step["tool"] in ("read", "law_section") and not step.get("chunks"):
                counts[step["tool"]] += 1
    return {tool: counts[tool] / max(len(rows), 1) for tool in ("read", "law_section")}


def bugfix_table() -> str:
    import statistics

    head = ("<tr><th>Run</th><th>n</th><th>Failed reads<br>per answer</th><th>Empty law_section<br>per answer</th>"
            "<th>Key points<br>MiMo / Luna</th><th>Unsupported<br>MiMo / Luna</th><th>Evidence seen</th>"
            "<th>Median latency</th><th>Median first token</th><th>Cost / question</th></tr>")
    body = []
    for label, name in BUG_ROUND:
        rows = experiment_rows(label)
        if not rows:
            continue
        luna = next((json.loads(f.read_text(encoding="utf-8"))
                     for f in RESULTS_DIR.glob(f"rejudge-gpt-6-luna-*-x-{label}-and-more.json")), [])
        health = tool_health(rows)
        first = [r["first_token_s"] for r in rows if r.get("first_token_s")]
        first_cell = f"{statistics.median(first):.0f} s" if first else "–"
        body.append(
            f"<tr><td>{html.escape(name)}</td><td>{len(rows)}</td><td>{fmt(health['read'])}</td>"
            f"<td>{fmt(health['law_section'])}</td>"
            f"<td>{fmt(mean([r['points'] for r in rows]))} / {fmt(mean([r['new']['points'] for r in luna]))}</td>"
            f"<td>{fmt(mean([r['unsupported'] for r in rows]))} / {fmt(mean([r['new']['unsupported'] for r in luna]))}</td>"
            f"<td>{fmt(mean([r['evidence'] for r in rows if r.get('evidence') is not None]))}</td>"
            f"<td>{statistics.median(r['seconds'] for r in rows):.0f} s</td><td>{first_cell}</td>"
            f"<td>${fmt(mean([r['cost'] for r in rows]), 4)}</td></tr>")
    return f"<table>{head}{''.join(body)}</table>" if len(body) == 2 else ""


# Section 2.12, written from the numbers of filters_table (update after a new run)
FILTERS_READING = (
    "The agent used the new filters in every answer (54 % of its searches, nearly all its greps and document lists), "
    "made 2.1 fewer tool calls per answer and covered slightly more key points: +0.026 ± 0.015 per case for the MiMo "
    "judge (explain / propose / develop seeds +0.08, generated cases +0.02, the 14 cases unchanged) and +0.065 ± 0.028 "
    "for Luna on the 41 answers it re-judged (30 cases) before the OpenRouter credits ran out; 3 of the 156 answers "
    "were lost the same way. Unsupported claims and cost did not move. The whole answer is ~1.5 s shorter but starts "
    "~3 s later (first token 26 → 29 s). Narrow title filters return nothing more often (5 % of greps, 1 % before). "
    "Measured on the 2026-10-22 corpus, where a municipality has a few hundred documents; on the national corpus, five "
    "times larger, the filters should matter more (not measured yet). Kept.")


def filter_use(rows: list[dict]) -> dict:
    """How often the agent used what the 2026-10-24 tools added: document filters in search / grep, grep's documents
    output, list_documents' doc_types and offset (its doc_type and title_contains existed before)."""
    calls = Counter()
    answers = 0
    for row in rows:
        used = False
        for step in row.get("steps") or []:
            arguments = step.get("arguments") or {}
            tool = step["tool"]
            new = (tool in ("search", "grep") and (arguments.get("doc_types") or arguments.get("title_contains"))
                   or tool == "grep" and arguments.get("output") == "documents"
                   or tool == "list_documents" and (arguments.get("doc_types") or arguments.get("offset")))
            if tool in ("search", "grep", "list_documents"):
                calls[tool] += 1
                calls[f"{tool} new"] += bool(new)
                used |= bool(new)
        answers += used
    return {"answers": answers, "calls": calls}


def filters_table(before: str = "toolfix", after: str = "filters") -> str:
    """The dev set before and after the document filters: means under both judges, and the paired difference per case
    (mean of the repeats, then over the cases) with its standard error."""
    import statistics

    def luna(label: str) -> list[dict]:
        return next((json.loads(f.read_text(encoding="utf-8"))
                     for f in RESULTS_DIR.glob(f"rejudge-gpt-6-luna-*-x-{label}-and-more.json")), [])

    def per_case(rows: list[dict], key) -> dict:
        values = defaultdict(list)
        for row in rows:
            value = key(row)
            if value is not None:
                values[row["case"]].append(value)
        return {case: statistics.mean(v) for case, v in values.items()}

    runs = {label: (experiment_rows(label), luna(label)) for label in (before, after)}
    if not all(rows for rows, _ in runs.values()):
        return ""
    body = []
    for label, name in ((before, "Before (toolfix, 2026-10-22)"), (after, "With the document filters (2026-10-24)")):
        rows, judged = runs[label]
        use = filter_use(rows)
        greps = [step for row in rows for step in row.get("steps") or [] if step["tool"] == "grep"]
        empty_grep = sum(1 for step in greps if not step.get("chunks")) / max(len(greps), 1)
        # A partial re-judging is another subset of cases: its mean is not comparable, the paired difference below is
        partial = len(judged) < 0.9 * len(rows)
        luna_points = f"({len(judged)} rejudged)" if partial else fmt(mean([r['new']['points'] for r in judged]))
        luna_unsup = f"({len(judged)} rejudged)" if partial else fmt(mean([r['new']['unsupported'] for r in judged]))
        body.append(
            f"<tr><td>{name}</td><td>{len(rows)}</td>"
            f"<td>{fmt(mean([r['points'] for r in rows]))} / {luna_points}</td>"
            f"<td>{fmt(mean([r['unsupported'] for r in rows]))} / {luna_unsup}</td>"
            f"<td>{fmt(mean([r['evidence'] for r in rows if r.get('evidence') is not None]))}</td>"
            f"<td>{statistics.median(r['seconds'] for r in rows):.0f} s</td><td>${fmt(mean([r['cost'] for r in rows]), 4)}</td>"
            f"<td>{use['answers'] / len(rows):.0%}</td><td>{empty_grep:.0%}</td></tr>")
    diffs = []
    for judge, key in (("MiMo", lambda r: r.get("points")), ("Luna", None)):
        if key is None:
            a, b = (per_case([r | {"points": r["new"]["points"]} for r in runs[label][1]], lambda r: r.get("points"))
                    for label in (before, after))
        else:
            a, b = (per_case(runs[label][0], key) for label in (before, after))
        common = sorted(set(a) & set(b))
        delta = [b[c] - a[c] for c in common]
        if len(delta) > 1:
            diffs.append(f"{judge} judge {statistics.mean(delta):+.3f} ± {statistics.stdev(delta) / len(delta) ** 0.5:.3f} "
                         f"({len(common)} cases)")
    head = ("<tr><th>Run</th><th>n</th><th>Key points<br>MiMo / Luna</th><th>Unsupported<br>MiMo / Luna</th>"
            "<th>Evidence seen</th><th>Median latency</th><th>Cost / question</th><th>Answers using a new filter</th>"
            "<th>grep calls with no match</th></tr>")
    return (f"<table>{head}{''.join(body)}</table><p>Key points, difference per case (after − before, mean ± standard "
            f"error): {'; '.join(diffs)}.</p>")


def health_table(label: str) -> str:
    """Failed tool calls per tool of a labelled run (agentic.health)."""
    from agentic.health import tool_health

    rows = experiment_rows(label)
    if not rows:
        return ""
    body = "".join(
        f"<tr><td><code>{tool}</code></td><td>{h['calls']:,}</td><td>{h['failed']:,}</td><td>{h['rate']:.0%}</td>"
        f"<td>{html.escape(', '.join(f'{k} {v}' for k, v in h['reasons'].items()) or '–')}</td>"
        f"<td>{'above threshold' if h['flag'] else ''}</td></tr>"
        for tool, h in tool_health(rows).items())
    return ("<table><tr><th>Tool</th><th>Calls</th><th>Failed</th><th>Rate</th><th>Reasons</th><th></th></tr>"
            f"{body}</table>")


def latest_coverage() -> dict | None:
    files = sorted(RESULTS_DIR.glob("coverage-*.json"))
    return json.loads(files[-1].read_text(encoding="utf-8")) | {"file": files[-1].name} if files else None


def coverage_table(coverage: dict) -> str:
    rows = "".join(
        f"<tr><td>{html.escape(kommun)}</td><td>{t['plans']}</td><td>{t['plans_with_a_pdf'] / t['plans']:.0%}</td>"
        f"<td>{t['plans_complete'] / t['plans']:.0%}</td><td>{t['pdfs_found'] / max(t['pdfs'], 1):.0%}</td></tr>"
        for kommun, t in sorted(coverage["by_kommun"].items()))
    total = coverage["total"]
    rows += (f"<tr><td><b>All</b></td><td><b>{total['plans']}</b></td><td><b>{total['plans_with_a_pdf']:.0%}</b></td>"
             f"<td><b>{total['plans_complete']:.0%}</b></td><td><b>{total['pdfs_found']:.0%}</b></td></tr>")
    return ("<table><tr><th>Municipality</th><th>Plans sampled</th><th>At least one PDF in the corpus</th>"
            f"<th>All its PDFs</th><th>PDFs found</th></tr>{rows}</table>")


def coverage_gaps(coverage: dict) -> str:
    """Why the listed PDFs are missing (agentic.coverage CAUSES, per municipality) and the leads they point to."""
    from agentic.coverage import CAUSES

    missing = coverage["total"].get("missing")
    if not missing:
        return ""
    worst = lambda cause: ", ".join(f"{html.escape(k)} {t['missing'][cause]}" for k, t in sorted(
        coverage["by_kommun"].items(), key=lambda item: -item[1].get("missing", {}).get(cause, 0))
        if t.get("missing", {}).get(cause))
    causes = "".join(f"<li><b>{n} PDF{'' if n == 1 else 's'}</b>: {html.escape(CAUSES[cause])}. {worst(cause)}.</li>"
                     for cause, n in missing.items())
    map_only = sum("map" in note for note in coverage.get("unmeasured", {}).values())
    sampled = coverage["total"]["municipalities"] + coverage["total"].get("unmeasured", 0)
    return f"""<p>Why the {sum(missing.values())} missing PDFs are missing, read from each municipality's crawl record:</p>
<ul>{causes}</ul>
<p>The crawler handles the first two causes since October 2026: a plan page at the last depth still gives the plan
pages it links, and every PDF of a plan page that is not off topic is taken, whatever its name; a copy of a kept
document counts as found. The
{map_only} of {sampled} sampled
municipalities that publish their plans only in a map or search application need another source: Lantmäteriet's
national access to digital detailed plans or the municipality's plan layers (WMS / WFS), which also give the plan
boundaries (address → plan); otherwise, a browser agent driving the map application, used as a crawler: once per
municipality it lists the plans and their document links, which the crawler then downloads (a one-off cost per
municipality; at answer time it would be slow, costly and fragile).</p>"""


def stratum(case: dict) -> str:
    """The expected outcome, as in bench.sample_cases: refused / granted / open (remitted, depends on facts)."""
    verdicts = set(case["verdicts"])
    if verdicts <= {"not_feasible", "unclear"} and "not_feasible" in verdicts:
        return "negative"
    return "open" if verdicts <= {"unclear", "conditional"} else "positive"


def verdict_table(runs: list[dict], cases: dict[str, dict]) -> str:
    """Verdict accuracy by expected outcome, and what the agent answered on refused projects."""
    head = tr("<tr><th>Configuration</th><th>Projet refusé<br>(verdict juste)</th><th>Projet accepté</th>"
              "<th>Issue ouverte</th><th>Sur les refus, réponses « sous conditions »</th></tr>",
              "<tr><th>Configuration</th><th>Project refused<br>(correct verdict)</th><th>Project granted</th>"
              "<th>Open outcome</th><th>On refusals, answers “with conditions”</th></tr>")
    body = []
    for run in runs:
        by = defaultdict(list)
        hedged = 0
        for row in run["rows"]:
            case = cases.get(row["case"])
            if case is None:
                continue
            by[stratum(case)].append(row["verdict_ok"])
            hedged += stratum(case) == "negative" and row["verdict"] == "conditional"
        negatives = len(by["negative"]) or 1
        body.append(f"<tr><td>{esc(label(run))}</td>"
                    + "".join(f"<td>{fmt(mean([float(v) for v in by[k]]))} <span class='n'>({len(by[k])})</span></td>"
                              for k in ("negative", "positive", "open"))
                    + f"<td>{fmt(hedged / negatives)}</td></tr>")
    return f"<table>{head}{''.join(body)}</table>"


def short(run: dict) -> str:
    """Chart label: 'low / medium' (exploration / answer effort)."""
    return "RAG" if run["system"] == "rag" else f"{run['explore']} / {run['answer']}"


ABLATIONS = {"view_map_area": ("sans view_map_area", "no view_map_area"),
             "view_map_area-view_pdf_page": ("sans lecture de carte", "no map reading at all")}


def label(run: dict) -> str:
    if run["system"] == "rag":
        return tr(f"RAG classique (réponse {run['answer']})", f"Classic RAG ({run['answer']} answer)")
    name = tr(f"Agent, exploration {run['explore']} / réponse {run['answer']}",
              f"Agent, exploration {run['explore']} / answer {run['answer']}")
    if run.get("ablation"):
        name += f" – {tr(*ABLATIONS.get(run['ablation'], (run['ablation'], run['ablation'])))}"
    return name


# --- charts (inline SVG) -------------------------------------------------------------------------------------------

def bar_chart(groups: list[tuple[str, list[tuple[str, float | None]]]], series: list[str], colors: list[str],
              width: int = 640, height: int = 230, top: float = 1.0) -> str:
    """Grouped bars: groups = [(group label, [(series, value), ...])]."""
    left, bottom, plot_h = 34, 46, height - 70
    group_w = (width - left - 10) / max(len(groups), 1)
    bar_w = min(26, group_w * 0.8 / max(len(series), 1))
    parts = [f'<svg viewBox="0 0 {width} {height}" class="chart" xmlns="http://www.w3.org/2000/svg">']
    for tick in (0, 0.25, 0.5, 0.75, 1.0):
        y = 12 + plot_h * (1 - tick / top)
        parts.append(f'<line x1="{left}" x2="{width - 10}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>'
                     f'<text x="{left - 6}" y="{y + 3:.1f}" class="tick" text-anchor="end">{fmt(tick * top, 2)}</text>')
    for g, (group, values) in enumerate(groups):
        x0 = left + g * group_w + (group_w - bar_w * len(series)) / 2
        for s, (_, value) in enumerate(values):
            if value is None:
                continue
            h = plot_h * value / top
            x = x0 + s * bar_w
            parts.append(f'<rect x="{x:.1f}" y="{12 + plot_h - h:.1f}" width="{bar_w - 3:.1f}" height="{h:.1f}" '
                         f'fill="{colors[s]}" rx="2"/>'
                         f'<text x="{x + (bar_w - 3) / 2:.1f}" y="{12 + plot_h - h - 3:.1f}" class="val" '
                         f'text-anchor="middle">{fmt(value)}</text>')
        parts.append(f'<text x="{left + g * group_w + group_w / 2:.1f}" y="{height - bottom + 18}" class="lbl" '
                     f'text-anchor="middle">{esc(group)}</text>')
    legend_x = left
    for s, name in enumerate(series):
        parts.append(f'<rect x="{legend_x}" y="{height - 16}" width="10" height="10" fill="{colors[s]}" rx="2"/>'
                     f'<text x="{legend_x + 14}" y="{height - 7}" class="lbl">{esc(name)}</text>')
        legend_x += 24 + 5.6 * len(name)
    parts.append("</svg>")
    return "".join(parts)


def scatter(points: list[tuple[str, float, float, str]], x_label: str, y_label: str, width: int = 640,
            height: int = 260, x_max: float | None = None) -> str:
    """Quality (y, 0-1) against latency or cost (x)."""
    left, bottom, top_pad, right = 46, 40, 14, 170
    plot_w, plot_h = width - left - right, height - bottom - top_pad
    x_max = x_max or max(p[1] for p in points) * 1.15
    y_min = 0.1
    parts = [f'<svg viewBox="0 0 {width} {height}" class="chart" xmlns="http://www.w3.org/2000/svg">']
    for tick in (0.1, 0.3, 0.5, 0.7, 0.9):
        y = top_pad + plot_h * (1 - (tick - y_min) / (1 - y_min))
        parts.append(f'<line x1="{left}" x2="{left + plot_w}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>'
                     f'<text x="{left - 6}" y="{y + 3:.1f}" class="tick" text-anchor="end">{fmt(tick, 1)}</text>')
    for k in range(5):
        value = x_max * k / 4
        x = left + plot_w * k / 4
        parts.append(f'<text x="{x:.1f}" y="{top_pad + plot_h + 14}" class="tick" text-anchor="middle">'
                     f'{fmt(value, 0 if x_max > 5 else 3)}</text>')
    parts.append(f'<text x="{left + plot_w / 2}" y="{height - 6}" class="lbl" text-anchor="middle">{esc(x_label)}</text>'
                 f'<text x="12" y="{top_pad + plot_h / 2}" class="lbl" text-anchor="middle" '
                 f'transform="rotate(-90 12 {top_pad + plot_h / 2})">{esc(y_label)}</text>')
    for i, (name, x_value, y_value, color) in enumerate(points):
        x = left + plot_w * x_value / x_max
        y = top_pad + plot_h * (1 - (max(y_value, y_min) - y_min) / (1 - y_min))
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="{color}"/>'
                     f'<text x="{x:.1f}" y="{y - 9:.1f}" class="val" text-anchor="middle">{i + 1}</text>'
                     f'<circle cx="{left + plot_w + 18}" cy="{top_pad + 8 + i * 18}" r="5" fill="{color}"/>'
                     f'<text x="{left + plot_w + 28}" y="{top_pad + 12 + i * 18}" class="lbl">{i + 1}. {esc(name)}</text>')
    parts.append("</svg>")
    return "".join(parts)


# --- content -------------------------------------------------------------------------------------------------------

def md_to_html(text: str, limit: int = 1800) -> str:
    """Enough markdown for answer excerpts: bold, bullets, paragraphs."""
    text = text[:limit] + (" […]" if len(text) > limit else "")
    out, in_list = [], False
    for line in text.splitlines():
        line = esc(line.strip())
        line = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", line)
        line = re.sub(r"\[c:[0-9a-f]{16}\]", "<span class='cite'>[source]</span>", line)
        if line.startswith(("- ", "* ")):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{line[2:]}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if line:
            out.append(f"<p>{line}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def runs_table(runs: list[dict], map_views: bool = False) -> str:
    """One row per configuration; `map_views` adds the mean number of map images looked at (plankarta cases)."""
    extra = f"<th>{tr('Vues de carte', 'Map views')}</th>" if map_views else ""
    head = tr("<tr><th>Configuration</th><th>n</th><th>Verdict</th><th>Points clés</th><th>Preuves vues</th>"
              "<th>Preuves citées</th><th>Ancrage</th><th>Passages vus</th>"
              f"<th>Appels outils</th>{extra}<th>Latence</th><th>1er token</th><th>Coût / question</th></tr>",
              "<tr><th>Configuration</th><th>n</th><th>Verdict</th><th>Key points</th><th>Evidence seen</th>"
              "<th>Evidence cited</th><th>Grounding</th><th>Passages seen</th>"
              f"<th>Tool calls</th>{extra}<th>Latency</th><th>1st token</th><th>Cost / question</th></tr>")
    body = []
    best = {key: max((r[key] for r in runs if r[key] is not None), default=None)
            for key in ("verdict", "points", "evidence", "cited", "grounded")}
    for run in runs:
        def cell(key):
            value = run[key]
            text = fmt(value)
            return f"<td class='{'best' if value is not None and value == best[key] else ''}'>{text}</td>"
        body.append(f"<tr><td>{esc(label(run))}</td><td>{run['n']}</td>{cell('verdict')}{cell('points')}"
                    f"{cell('evidence')}{cell('cited')}{cell('grounded')}<td>{fmt(run['seen'], 0)}</td>"
                    f"<td>{fmt(run['tools'], 1)}</td>"
                    + (f"<td>{fmt(run['map_views'], 1)}</td>" if map_views else "")
                    + f"<td>{fmt(run['seconds'], 0)} s</td><td>{fmt(run['first'], 0)} s</td>"
                    f"<td>{money(run['cost'])}</td></tr>")
    return f"<table>{head}{''.join(body)}</table>"


def example_case(case: dict, rows_by_config: list[tuple[str, dict | None]]) -> str:
    expected = ", ".join(case["verdicts"])
    points = "".join(f"<li>{esc(p)}</li>" for p in case["key_points"])
    evidence = "; ".join(esc(e.get("contains") or e.get("section") or e.get("title") or json.dumps(e, ensure_ascii=False))
                         for e in case.get("evidence", [])) or tr("aucune (ancienne loi)", "none (old law)")
    colon = tr(" :", ":")
    outcome = tr(" – issue réelle : ", " – actual outcome: ") + esc(case["outcome"]) if case.get("outcome") else ""
    blocks = [f"<div class='case'><p class='q'>{tr('« ', '“')}{esc(case['question'])}{tr(' »', '”')}</p>"
              f"<p><b>Source</b>{colon} {esc(case.get('source', ''))}{outcome}</p>"
              f"<p><b>{tr('Verdicts acceptés', 'Accepted verdicts')}</b>{colon} {esc(expected)}. "
              f"<b>{tr('Preuves attendues', 'Expected evidence')}</b>{colon} {evidence}</p>"
              f"<p><b>{tr('Points clés attendus', 'Expected key points')}</b>{colon}</p><ul>{points}</ul>"]
    for config, row in rows_by_config:
        if row is None:
            continue
        correct = tr("juste", "correct") if row["verdict_ok"] else tr("faux", "wrong")
        tools = tr("appels d'outils", "tool calls")
        blocks.append(f"<p class='res'><b>{esc(config)}</b>{colon} verdict {tr('« ', '“')}{esc(row['verdict'])}"
                      f"{tr(' »', '”')} ({correct}), {tr('points', 'key points')} {fmt(row['points'])}, "
                      f"{tr('preuves', 'evidence')} {fmt(row['evidence'])}, {row['tool_calls']} {tools}, "
                      f"{fmt(row['seconds'], 0)} s. <i>{tr('Juge :', 'Judge:')} {esc(row.get('comment') or '')}</i></p>")
    blocks.append("</div>")
    return "".join(blocks)


STYLE = """<style>
@page { size: A4; margin: 16mm 15mm 16mm 15mm; }
body { font-family: "Segoe UI", Arial, sans-serif; font-size: 10pt; line-height: 1.45; color: #1f2937; }
h1 { font-size: 22pt; margin: 0 0 4pt; color: #111827; }
h2 { font-size: 14pt; margin: 18pt 0 6pt; padding-bottom: 3pt; border-bottom: 2px solid #2563eb; color: #111827;
     break-after: avoid; }
h3 { font-size: 11pt; margin: 12pt 0 4pt; color: #1e3a8a; break-after: avoid; }
p { margin: 4pt 0; } ul { margin: 3pt 0 3pt 16pt; padding: 0; } li { margin: 1.5pt 0; }
.sub { color: #6b7280; font-size: 10pt; margin-bottom: 12pt; }
.box { background: #eff6ff; border-left: 4px solid #2563eb; padding: 8pt 10pt; margin: 8pt 0; break-inside: avoid; }
.warn { background: #fffbeb; border-left: 4px solid #f59e0b; padding: 8pt 10pt; margin: 8pt 0; break-inside: avoid; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0; font-size: 8.5pt; break-inside: avoid; }
th, td { border: 1px solid #e5e7eb; padding: 3pt 5pt; text-align: left; vertical-align: top; }
th { background: #f3f4f6; font-weight: 600; } td.best { font-weight: 700; color: #065f46; background: #ecfdf5; }
code { font-family: Consolas, monospace; font-size: 8.5pt; background: #f3f4f6; padding: 0 2pt; border-radius: 2pt; }
.chart { width: 100%; max-width: 640px; margin: 4pt 0 8pt; }
.chart .grid { stroke: #e5e7eb; } .chart .tick, .chart .val { font-size: 9px; fill: #6b7280; }
.chart .lbl { font-size: 10px; fill: #374151; }
.case { border: 1px solid #e5e7eb; border-radius: 6pt; padding: 7pt 9pt; margin: 7pt 0; break-inside: avoid; }
.case .q { font-style: italic; color: #111827; } .case .res { font-size: 9pt; color: #374151; }
.answer { border: 1px solid #e5e7eb; border-radius: 6pt; padding: 6pt 10pt; font-size: 8.8pt; background: #fafafa; }
.cite { color: #2563eb; font-size: 8pt; } .n { color: #9ca3af; font-size: 7.5pt; }
.flow { display: flex; flex-wrap: wrap; gap: 4pt; align-items: center; margin: 6pt 0; }
.flow span { background: #f3f4f6; border: 1px solid #d1d5db; border-radius: 4pt; padding: 3pt 6pt; font-size: 8.5pt; }
.flow b { color: #9ca3af; }
</style>"""


def examples_html(runs: list[dict], cases_key: str, cases: list[dict]) -> str:
    """Example cases of one set with what every configuration answered (verdict, scores, judge comment)."""
    def rows_for(case):
        return [(label(run), next((r for r in run["rows"] if r["case"] == case["id"]), None))
                for run in runs if run["cases"] == cases_key]
    return "".join(example_case(case, rows_for(case)) for case in cases)


def overview_table(pairs: list[tuple[str, list[dict]]]) -> str:
    """Per benchmark set, the systems side by side (main metrics only)."""
    head = tr("<tr><th>Jeu de cas</th><th>Système</th><th>n</th><th>Verdict</th><th>Points clés</th><th>Preuves vues</th>"
              "<th>Preuves citées</th><th>Ancrage</th><th>Passages vus</th><th>Latence</th><th>1er token</th>"
              "<th>Coût / question</th></tr>",
              "<tr><th>Case set</th><th>System</th><th>n</th><th>Verdict</th><th>Key points</th><th>Evidence seen</th>"
              "<th>Evidence cited</th><th>Grounding</th><th>Passages seen</th><th>Latency</th><th>1st token</th>"
              "<th>Cost / question</th></tr>")
    body = []
    for name, runs in pairs:
        runs = [r for r in runs if r]
        for i, run in enumerate(runs):
            first = f"<td rowspan='{len(runs)}'><b>{esc(name)}</b></td>" if i == 0 else ""
            system = "RAG" if run["system"] == "rag" else f"Agent ({run['explore']} / {run['answer']})"
            body.append(f"<tr>{first}<td>{esc(system)}</td><td>{run['n']}</td>"
                        + "".join(f"<td>{fmt(run[k])}</td>" for k in ("verdict", "points", "evidence", "cited", "grounded"))
                        + f"<td>{fmt(run['seen'], 0)}</td><td>{fmt(run['seconds'], 0)} s</td><td>{fmt(run['first'], 0)} s</td>"
                          f"<td>{money(run['cost'])}</td></tr>")
    return f"<table>{head}{''.join(body)}</table>"


def build_html() -> str:
    runs = load_runs()
    by_key = {(r["cases"], r["system"], r["explore"], r["answer"], r["ablation"]): r for r in runs}

    def pick(cases: str, system: str, explore: str = "–", answer: str = "medium", ablation: str = "") -> dict | None:
        return by_key.get((cases, system, explore, answer, ablation))

    runs14 = [r for r in runs if r["cases"] == "cases14"]
    runs_mod = [r for r in runs if r["cases"] == "mod"]
    runs_plans = [r for r in runs if r["cases"] == "plans"]
    cases14 = list(read_jsonl(CASES_PATH))
    caselaw = list(read_jsonl(CASES_PATH.parent / "cases_caselaw.jsonl"))
    plan_cases = list(read_jsonl(CASES_PATH.parent / "cases_plans.jsonl"))
    sample = sample_cases(list(caselaw), 50)
    rulings = list(read_jsonl(DATA_DIR / "raw" / "caselaw" / "mod.jsonl"))
    relevant = sum(1 for r in rulings if r.get("relevant"))
    # The runs of this report searched the corpus of 2026-10-22, kept as the data/small snapshot (the crawl of
    # 2026-10-23 is ~5x larger and not benchmarked yet)
    bench_corpus = RESULTS_ROOT / "small" / "corpus"
    plans_path = (bench_corpus if (bench_corpus / "plans.jsonl").exists() else DATA_DIR) / "plans.jsonl"
    plans = sum(1 for _ in plans_path.open(encoding="utf-8")) if plans_path.exists() else 0
    plans_n = f"{plans:,}" if LANG == "en" else f"{plans:,}".replace(",", " ")
    cases_label = {"cases14": tr("14 cas", "14 cases"), "mod": "MÖD", "plans": "plankarta"}

    colors = ["#2563eb", "#f59e0b", "#10b981", "#8b5cf6", "#ef4444", "#0891b2", "#64748b", "#db2777"]
    quality_chart = ""
    configs = runs_mod or runs14
    if configs:
        quality_chart = bar_chart(
            [(m, [(short(r), r[k]) for r in configs]) for m, k in
             [("Verdict", "verdict"), (tr("Points clés", "Key points"), "points"),
              (tr("Preuves", "Evidence"), "evidence"), (tr("Ancrage", "Grounding"), "grounded")]],
            [("exploration " + short(r)) if r["system"] == "agent" else "RAG" for r in configs], colors)
    compared = runs14 + runs_mod  # agent configurations and the classic RAG
    tradeoff = cost_chart = ""
    if compared:
        names = [f"{cases_label[r['cases']]} – {short(r)}" for r in compared]

        def points(key: str) -> list:
            return [(names[i], r[key], r["points"], colors[i % len(colors)]) for i, r in enumerate(compared)]
        tradeoff = scatter(points("seconds"), tr("latence moyenne par question (s)", "mean latency per question (s)"),
                           tr("points clés", "key points"), x_max=max(r["seconds"] for r in compared) * 1.15)
        cost_chart = scatter(points("cost"), tr("coût moyen par question ($)", "mean cost per question ($)"),
                             tr("points clés", "key points"), x_max=max(r["cost"] for r in compared) * 1.2)

    # Per-case wins of medium exploration over low, on the MÖD cases
    low, med = pick("mod", "agent", "low"), pick("mod", "agent", "medium")
    duel = ""
    if low and med:
        def per_case(run):
            values = defaultdict(list)
            for row in run["rows"]:
                values[row["case"]].append(row["points"])
            return {case: sum(v) / len(v) for case, v in values.items()}
        a, b = per_case(low), per_case(med)
        common = set(a) & set(b)
        wins = sum(1 for c in common if b[c] > a[c] + 0.05)
        losses = sum(1 for c in common if b[c] < a[c] - 0.05)
        duel = tr(f"<p>Cas par cas sur les {len(common)} cas MÖD, l'exploration <code>medium</code> fait mieux que "
                  f"<code>low</code> sur {wins} cas, moins bien sur {losses}, et à égalité (±0,05) sur "
                  f"{len(common) - wins - losses}.</p>",
                  f"<p>Case by case on the {len(common)} MÖD cases, <code>medium</code> exploration beats "
                  f"<code>low</code> on {wins} cases, does worse on {losses}, and ties (±0.05) on "
                  f"{len(common) - wins - losses}.</p>")

    spread = "".join(
        f"<li>{esc(label(r))} ({cases_label[r['cases']]}){tr(' : points par passage ', ': key points per pass ')}"
        f"{' / '.join(fmt(v) for v in r['points_by_repeat'])}</li>"
        for r in runs if r["repeats"] > 1)

    examples14 = [c for c in cases14 if c["id"] in ("kumla-200m2", "ydre-lake-house")]
    examples_mod = [c for c in sample if c["id"] in ("mod-2026-13", "mod-2026-17")] or sample[:2]
    examples = examples_html(runs, "cases14", examples14) + examples_html(runs, "mod", examples_mod)
    answer_excerpt = ""
    if med or low:
        source_run = med or low
        row = next((r for r in source_run["rows"] if r["case"] == examples_mod[0]["id"]), source_run["rows"][0])
        heading = tr("Extrait d'une réponse de l'agent", "Excerpt of an agent answer")
        answer_excerpt = (f"<h3>{heading} ({esc(row['case'])}, {esc(label(source_run))})</h3>"
                          f"<div class='answer'>{md_to_html(row['answer'])}</div>")

    total_cost = sum(r["cost"] * r["n"] for r in runs)
    verdict_counts = defaultdict(int)
    for case in caselaw:
        verdict_counts[" / ".join(case["verdicts"])] += 1
    verdict_split = ", ".join(f"{esc(k)}{tr(' : ', ': ')}{v}"
                              for k, v in sorted(verdict_counts.items(), key=lambda kv: -kv[1])[:5])
    history = "".join(
        f"<tr><td>{esc(tr(*n))}</td><td>{fmt(v)}</td><td>{fmt(p)}</td><td>{fmt(e)}</td><td>{fmt(g)}</td><td>{s} s</td>"
        f"<td>{'–' if f is None else str(f) + ' s'}</td><td>{money(c)}</td></tr>" for n, v, p, e, g, s, f, c in HISTORY)
    table14 = runs_table(runs14) if runs14 else "<p>–</p>"
    table_mod = runs_table(runs_mod) if runs_mod else "<p>–</p>"
    table_plans = runs_table(runs_plans, map_views=True) if runs_plans else "<p>–</p>"
    verdicts_mod = verdict_table(runs_mod, {c["id"]: c for c in caselaw})
    files = ", ".join(sorted({esc(r["file"]) for r in runs})) or "–"
    stamps = sorted(m.group(1) for r in runs for name in r["file"].split(", ") if (m := FILE.search(name)))
    period = (f"{stamps[0][:4]}-{stamps[0][4:6]}-{stamps[0][6:8]} to {stamps[-1][:4]}-{stamps[-1][4:6]}-{stamps[-1][6:8]}"
              if stamps else "–")
    overview = overview_table([(cases_label[key], [pick(key, "rag"), pick(key, "agent", "medium")])
                               for key in ("cases14", "mod", "plans")])
    today = date.today()

    # Tasks beyond the verdict (English body only): new sets, regression of the verdict sets, second judge
    new_rows = mode_rows()
    task_rows = [r for r in new_rows if r["set"] in TASK_SETS]
    tasks_table = task_table(task_rows) if task_rows else ""
    regression = regression_table(runs, new_rows)
    agreement = judge_agreement()
    experiment_table_html = experiment_table()
    bugfix_html = bugfix_table()
    health_html = health_table("toolfix")
    filters_html = filters_table()
    coverage = latest_coverage()
    seed_cases = list(read_jsonl(CASES_PATH.parent / "cases_tasks.jsonl")) if (CASES_PATH.parent / "cases_tasks.jsonl").exists() else []
    gen_cases = (list(read_jsonl(CASES_PATH.parent / "cases_generated.jsonl"))
                 if (CASES_PATH.parent / "cases_generated.jsonl").exists() else [])

    def task_mean(task: str, system: str, key: str, fixed: bool | None = None) -> str:
        mine = [r for r in task_rows if r["task"] == task and r["system"] == system
                and (fixed is None or (r["stamp"] >= PROPOSE_FIX_RUN) == fixed)]
        return fmt(mean([float(r[key]) for r in mine if r.get(key) is not None]))

    def val(run: dict | None, key: str, digits: int = 2) -> str:
        return fmt(run[key], digits) if run and run.get(key) is not None else "–"

    rag14, agent14 = pick("cases14", "rag"), pick("cases14", "agent", "medium")
    rag_mod, agent_mod = pick("mod", "rag"), med
    rag_plans, agent_plans = pick("plans", "rag"), pick("plans", "agent", "medium")
    no_map = pick("plans", "agent", "medium", ablation="view_map_area-view_pdf_page")

    # Conclusions, written from the numbers above (re-read them after new runs: the wording states directions)
    high_mod = pick("mod", "agent", "medium", "high")
    no_view = pick("plans", "agent", "medium", ablation="view_map_area")
    caselaw_by_id = {c["id"]: c for c in caselaw}

    def by_outcome(run: dict | None) -> dict:
        outcomes = defaultdict(list)
        for row in run["rows"] if run else []:
            if row["case"] in caselaw_by_id:
                outcomes[stratum(caselaw_by_id[row["case"]])].append(float(row["verdict_ok"]))
        return {key: mean(values) for key, values in outcomes.items()}

    def outcome(run: dict | None, key: str) -> str:
        value = by_outcome(run).get(key)
        return f"{value * 100:.0f} %" if value is not None else "–"

    agents_all = [r for r in runs if r["system"] == "agent" and not r["ablation"]]
    seen_range = f"{min(r['seen'] for r in agents_all):.0f}–{max(r['seen'] for r in agents_all):.0f}" if agents_all else "–"
    tools_range = f"{min(r['tools'] for r in agents_all):.0f}–{max(r['tools'] for r in agents_all):.0f}" if agents_all else "–"
    summary = f"""<li>Compared: a <b>tool-using agent</b> and a <b>classic RAG</b> (one search, one answer), same model and same
corpus, on three sets: 14 hand-written case studies, {len(sample)} cases from real rulings of the Land and Environment
Court of Appeal (MÖD) and {len(plan_cases)} questions on a property of a real plan map.</li>
<li><b>The agent wins on everything that requires finding the deciding rule</b>, and the gap grows with difficulty.
Key points: {val(agent14, 'points')} vs {val(rag14, 'points')} (14 cases), {val(agent_mod, 'points')} vs
{val(rag_mod, 'points')} (MÖD), {val(agent_plans, 'points')} vs {val(rag_plans, 'points')} (plankarta). Expected evidence
seen: {val(agent14, 'evidence')} / {val(agent_mod, 'evidence')} / {val(agent_plans, 'evidence')} vs {val(rag14, 'evidence')} /
{val(rag_mod, 'evidence')} / {val(rag_plans, 'evidence')}.</li>
<li><b>The RAG is about twice as fast and four times cheaper</b>: {val(rag14, 'seconds', 0)}–{val(rag_plans, 'seconds', 0)} s
per question (first word after {val(rag14, 'first', 0)}–{val(rag_plans, 'first', 0)} s), {money(rag_mod['cost'] if rag_mod else None)}
per question, against {val(agent14, 'seconds', 0)}–{val(agent_plans, 'seconds', 0)} s and {money(agent14['cost'] if agent14 else None)}–{money(agent_plans['cost'] if agent_plans else None)}
for the agent. Its grounding is as high or higher ({val(rag_plans, 'grounded')}–{val(rag14, 'grounded')}): it says less, but what it says
is in its sources.</li>
<li><b>Verdict</b>: all systems score ≥ {fmt(min(r['verdict'] for r in runs14)) if runs14 else '–'} on the 14 cases; on MÖD the agent gets {val(agent_mod, 'verdict')}–{val(low, 'verdict')}
against {val(rag_mod, 'verdict')} for the RAG, on the plan maps {val(agent_plans, 'verdict')} against {val(rag_plans, 'verdict')}.
The agent's weak spot is still the projects the court refused ({outcome(agent_mod, 'negative')}–{outcome(low, 'negative')}
correct): it leans towards “feasible with conditions”.</li>
<li><b>Map reading matters</b> on the plan-map cases: without the map tools the agent's verdict drops from
{val(agent_plans, 'verdict')} to {val(no_map, 'verdict')} and its key points from {val(agent_plans, 'points')} to
{val(no_map, 'points')}, but the map adds about {(agent_plans['seconds'] - no_map['seconds']) if agent_plans and no_map else 0:.0f} s
per question.</li>
<li><b>Exploration effort is the agent setting that matters</b>: <i>low</i> → <i>medium</i> on MÖD raises evidence
{val(low, 'evidence')} → {val(agent_mod, 'evidence')}, grounding {val(low, 'grounded')} → {val(agent_mod, 'grounded')} and
key points {val(low, 'points')} → {val(agent_mod, 'points')}, for +{(agent_mod['seconds'] - low['seconds']) if low and agent_mod else 0:.0f} s
and {(agent_mod['cost'] / low['cost']) if low and agent_mod else 0:.1f}× the cost; a <i>high</i> final answer brings nothing
measurable.</li>""" + (f"""
<li><b>Beyond the verdict</b> ({len(seed_cases) + len(gen_cases)} cases asking to explain a procedure, propose where a
project could go, or develop a project idea; section 2.7): agent vs RAG key points {task_mean('explain', 'agent', 'points')} vs
{task_mean('explain', 'rag', 'points')} (explain), {task_mean('propose', 'agent', 'points', False)} vs
{task_mean('propose', 'rag', 'points')} (propose), {task_mean('develop', 'agent', 'points')} vs {task_mean('develop', 'rag', 'points')}
(develop). The agent recognises the kind of question (mode right {task_mean('explain', 'agent', 'mode_ok')} /
{task_mean('propose', 'agent', 'mode_ok', False)} → {task_mean('propose', 'agent', 'mode_ok', True)} after the propose fix /
{task_mean('develop', 'agent', 'mode_ok')}), and the mode prompt leaves the verdict sets unchanged (section 2.8).</li>""" if task_rows else "")

    overview_text = f"""<p>The agent reads {seen_range} passages per question through {tools_range} tool calls, each with its
own query; the RAG reads the 20 passages of a single search. The number is not the point (a case has 1 to 2 expected
passages): the RAG's single query, written from the user's facts, rarely lands on the statute section or the plan map
that decides the case, whereas the agent first works out which rule applies, then looks it up. Of what it sees, the
agent cites about three quarters of the expected evidence (evidence cited vs seen); the RAG cites most of what it
finds, but outside the 14 case studies it finds little.</p>"""

    plans_text = f"""<p>With both map tools the agent gets the verdict right in {val(agent_plans, 'verdict')} of the answers and
covers {val(agent_plans, 'points')} of the key points; without <code>view_map_area</code> (whole-page images only)
{val(no_view, 'verdict')} / {val(no_view, 'points')}; with no map at all {val(no_map, 'verdict')} / {val(no_map, 'points')}:
it has to guess the zone from the text. The map views make this set slow ({val(agent_plans, 'seconds', 0)} s per question).
Grounding is lower with the map ({val(agent_plans, 'grounded')} vs {val(no_map, 'grounded')}), probably because what is
read on the image (which zone the property is in) cannot be checked by the grounding judge, which only gets text. The
classic RAG, with one search and no map, has the plan map of the case among its passages in {val(rag_plans, 'evidence')}
of the answers and gets the verdict right in {val(rag_plans, 'verdict')}.</p>"""

    reading = f"""<li><b>The search strategy separates the systems, not the volume read.</b> The RAG has 20 slots for 1–2
expected passages, but one query. On the MÖD cases every expected passage is a statute section, among several thousand,
and the question describes facts (a house by a lake, a barn on farmland) rather than the rule: the rewrite rarely
reaches the deciding section (evidence {val(rag_mod, 'evidence')}). The agent reasons first (“this is shoreline protection:
exemption and its special reasons”) and then fetches the section.</li>
<li><b>Where the RAG is enough.</b> On the 14 case studies (short questions, well-covered municipalities, answers in
one municipal page or a well-known section) it reaches the verdict every time, with the best grounding and half the
latency; it still covers {(agent14['points'] - rag14['points']) if agent14 and rag14 else 0:.2f} fewer key points than the
agent.</li>
<li><b>Verdict calibration.</b> The RAG is right more often than the agent on refused projects
({outcome(rag_mod, 'negative')} vs {outcome(agent_mod, 'negative')}) but much less on granted ones
({outcome(rag_mod, 'positive')} vs {outcome(agent_mod, 'positive')}): missing the conditions and exceptions that make a project
possible, it is more negative rather than better calibrated. The agent's “with conditions” on refusals seems to come
from treating the conditions it finds as requirements to meet rather than as blockers.</li>
<li><b>Exploration effort</b>: at <i>low</i> the agent makes ~12 tool calls per question, at <i>medium</i> ~20–26, better
targeted; it then sees and cites much more of the expected evidence. More exploration also finds more conditions, hence
a slightly lower verdict score on MÖD ({val(low, 'verdict')} → {val(agent_mod, 'verdict')}) despite better evidence.</li>
<li><b>Grounding is not quality on its own.</b> The RAG has the highest grounding and the lowest key-point coverage: the
measure says that stated claims are supported, not that the important ones are there. Read it together with key
points and evidence.</li>
<li><b>Difficulty.</b> The MÖD and plan-map cases separate the systems; the 14 case studies saturate on the verdict and
only show differences in key points and evidence.</li>"""

    recommendations = f"""<li><b>Default app setting</b>: the agent, <i>medium</i> exploration and <i>medium</i> answer; <i>low</i>
exploration as a fast mode (≈ {val(low, 'seconds', 0)} s). A <i>high</i> answer is not worth its cost.</li>
<li><b>The classic RAG is not a substitute</b> for feasibility questions beyond the simplest ones; it could serve where
speed matters more than completeness (a first quick answer while the agent explores), to be evaluated as such.</li>
<li><b>Verdict prompt</b>: state that an unmet substantive condition (productive farmland without an essential public
interest, shoreline protection without a special reason, a project that requires a detailed plan) makes the project
“not feasible as described”, and measure it on the refused MÖD cases.</li>
<li><b>Map reading</b>: keep <code>view_map_area</code>; make it cheaper (one crop instead of crop + page, smaller
images) since it doubles the time on plan questions.</li>
<li><b>Benchmark</b>: run the MÖD sample (50 cases, 2 passes), the plan-map set and the explain / propose / develop
sets for every prompt or model change; next, multi-turn cases (iterating on a project with the user), which no set
measures yet.</li>
<li><b>Propose</b>: the fix makes the agent recognise every propose question and name more of the designated places,
but it reads less of the expected evidence than before; keep the step budget, and check the cost of the extra
places it names.</li>
<li><b>Judge</b>: have a domain expert review a sample of scores and of plan-map references.</li>
<li><b>Prompt</b> (section 2.9): the “complete answer” instruction is the default since 2026-10-21; more instructions
on how to explore did not help, and MiMo Flash as the agent invents too much.</li>"""

    if LANG == "en":
        body = f"""
<h1>Pyrmit – benchmark report</h1>
<div class="sub">Feasibility questions on Swedish planning law: tool-using agent vs. classic RAG. Model: GPT-6 Luna via
OpenRouter. Runs: {period}; report generated on {today:%Y-%m-%d}. How the system works and how each benchmark set is
built are explained in the <b>technical report</b>; this report gives the test conditions and the results.</div>

<div class="box"><b>Summary</b>
<ul>
{summary}
</ul></div>

<h2>1. Test conditions</h2>
<h3>1.1 Systems compared</h3>
<table>
<tr><th>System</th><th>What it does</th><th>Settings tested</th></tr>
<tr><td><b>Classic RAG</b></td><td>One rewrite call (English question + Swedish search query, effort low) → one dense
search on the Swedish query (arctic-embed-l-v2, municipality filter detected from the question) → the top 10 statute
sections and top 10 municipal passages → one answer call, streamed. It cannot open a document, list plans or look at a
map.</td><td>Answer effort <i>medium</i>, streamed (the history table also shows an earlier <i>high</i>,
non-streamed run)</td></tr>
<tr><td><b>Agent</b></td><td>Tool loop: exploration turns (search, grep, read a document, statute section, plan registry
and plan rules, map crop around a property, PDF page image), tools of a turn run in parallel, then <code>answer_ready</code>
and one streamed final answer.</td><td>Exploration effort <i>low</i> / <i>medium</i> × answer effort <i>medium</i> /
<i>high</i>; on the plankarta cases, ablations without the map tools</td></tr>
</table>
<p>Both answer in the same format (verdict, key rules with [c:id] citations, process, uncertainties) and search the same
corpus: the full disk store (15 statutes, the crawled websites of the municipalities, {plans_n} indexed detailed plans),
as of 2026-10-22. The larger crawl of 2026-10-23 (about five times the documents) is not benchmarked yet.</p>

<h3>1.2 Benchmark sets</h3>
<table>
<tr><th>Set</th><th>Origin</th><th>Cases run</th><th>What it tests</th><th>Reference</th></tr>
<tr><td><b>14 case studies</b></td><td>Hand-written from real documents of 5 municipalities (detailed plans of 3 real
projects, municipal guidance pages, statutes) and questions from user feedback</td><td>14 (all)</td><td>Combining
national and local rules on common projects</td><td>Accepted verdicts, 3–5 key points, expected evidence (statute
section or exact municipal excerpt)</td></tr>
<tr><td><b>MÖD rulings</b></td><td>Real appeals decided by the Land and Environment Court of Appeal ({len(rulings)} rulings
since 2011, {relevant} on our topics); the facts become the applicant's question, asked before the decision</td>
<td>{len(sample)} of {len(caselaw)} (stratified by outcome, fixed seed)</td><td>Legal judgement on real disputes;
verdict against the real outcome</td><td>Outcome → accepted verdicts; court's reasons → key points; statutes applied →
evidence (current wording)</td></tr>
<tr><td><b>Plankarta</b></td><td>Real plan maps (in force or adopted) of {len({c['kommun'][0] for c in plan_cases})}
municipalities, a property number printed on the map; the project is designed so that its feasibility depends on the
zone rules</td><td>{len(plan_cases)} (high-confidence references)</td><td>Reading the map: which zone the property is
in, which codes apply</td><td>Codes and values read on the map crop + legend by a vision model; evidence = the plan
map document</td></tr>
<tr><td><b>Explain / propose / develop</b></td><td>{len(seed_cases)} cases written by hand from real documents (Vallentuna,
Norrtälje, Uppsala, Gotland; questions from user feedback and the ReGen Villages vision) + {len(gen_cases)} drafted by
MiMo v2.6 Flash from corpus documents (municipal guidance pages, the growth and rural passages of comprehensive plans,
statutes), in other municipalities</td><td>all</td><td>Explaining a procedure; proposing where a project could go
(places the comprehensive plan designates); developing a project idea (obstacles, ways to make it work, what to ask
the user)</td><td>Key points with a verbatim quote each (checked automatically); propose: the designated places
(anchors); develop: points labelled Obstacle / Lever / Ask; no verdict</td></tr>
</table>

<h3>1.3 Protocol and scoring</h3>
<ul>
<li>Same model for the systems and the judges (GPT-6 Luna via OpenRouter); judge effort medium. The explain / propose /
develop sets are judged by MiMo v2.6 Flash, another model family, which also drafted their generated cases.</li>""" + (f"""
<li><b>Judge check</b>: {agreement['n']} stored answers (14 cases and MÖD, agent and RAG) graded again by
{esc(agreement['judge'])}: same verdict class in {fmt(agreement['same_verdict'] * 100, 0)} % (kappa on “verdict correct”
{fmt(agreement['kappa'])}), key points {fmt(agreement['points_old'])} vs {fmt(agreement['points_new'])} (correlation
{fmt(agreement['corr'])}, mean gap {fmt(agreement['diff'])}). The second judge counts fewer unsupported claims
({fmt(agreement['unsup_new'], 1)} vs {fmt(agreement['unsup_old'], 1)}): Luna is stricter, not lenient towards its own
answers.</li>""" if agreement else "") + f"""
<li>Each configuration runs 2 passes or more (n = answers = cases × passes); cases run 3 in parallel, so latencies
include some contention. Answers are streamed: “1st token” is the time until the first word of the answer.</li>
<li>Results are written per answer (<code>data/agentic/bench-*.json</code>) with the full answer, the tool calls and the
judge's comment.</li>
</ul>
<table>
<tr><th>Measure</th><th>Definition</th><th>How</th></tr>
<tr><td>Verdict</td><td>The answer's verdict (feasible / with conditions / not feasible / unclear) is among the accepted
verdicts</td><td>LLM judge</td></tr>
<tr><td>Key points</td><td>Each expected point 0 (missing or contradicted), 1 (partial), 2 (clear); scaled to 0–1</td>
<td>LLM judge</td></tr>
<tr><td>Evidence seen</td><td>Share of the expected evidence the system <i>actually had in front of it</i> (retrieved
passages for the RAG, tool outputs for the agent)</td><td>Automatic, no LLM</td></tr>
<tr><td>Evidence cited</td><td>Share of the expected evidence the answer <i>cites</i>: did the system recognise the
decisive passage among what it read? The gap with “evidence seen” is the passages read but not used</td><td>Automatic,
no LLM</td></tr>
<tr><td>Passages seen</td><td>Distinct passages the system had in front of it per question: the reading volume. A
precision (“relevant / read”) is not measurable: the labels list the decisive passages, not every useful one</td>
<td>Automatic</td></tr>
<tr><td>Grounding</td><td>Share of the answer's factual claims supported by the text of the sources it cites</td>
<td>Second LLM judge, full source text</td></tr>
<tr><td>Latency, 1st token, cost</td><td>Total time, time to the first answer word, OpenRouter cost of the system's calls
(judges excluded)</td><td>Measured</td></tr>
</table>
<div class="warn"><b>Limits.</b> The judge is the system's own model: cheap but possibly lenient, so its scores
<i>compare</i> settings rather than give absolute quality. MÖD key points and plankarta references are written by an
LLM (from the ruling, from the map); no human review yet. A difference below ~0.05 between configurations is within the
pass-to-pass noise (section 2.6). <b>Scope</b>: the first three sets check the feasibility of a defined project at a known place; the
explain / propose / develop sets (section 2.7) add explaining, proposing places and developing an idea, in a single
turn; multi-turn guidance is still not measured (technical report, section 7.8).</div>

<h2>2. Results</h2>
<h3>2.1 Overview: classic RAG vs. agent (default setting, medium / medium)</h3>
{overview}
{overview_text}

<h3>2.2 14 case studies</h3>
<p><b>History</b> (5-municipality sub-corpus, successive versions):</p>
<table><tr><th>Version</th><th>Verdict</th><th>Key points</th><th>Evidence</th><th>Grounding</th><th>Latency</th><th>1st token</th>
<th>Cost</th></tr>
{history}
</table>
<p>v1 → v2: citeable identifiers in every tool output and a “no claim without a source read” rule (grounding 0.68 →
0.86). v2 → v3/v4: parallel tools, <code>answer_ready</code>, streamed answer and <i>low</i> exploration effort: latency
halved, lower quality. The RAG of this table ran with a <i>high</i>, non-streamed answer; it is re-measured below at
<i>medium</i>, streamed.</p>
<p><b>Effort matrix</b> (full corpus on disk):</p>
{table14}

<h3>2.3 MÖD cases ({len(sample)} sampled rulings)</h3>
{table_mod}
<p>Best value of each column in green. n = number of answers (cases × passes).</p>
{quality_chart}
{duel}
<p><b>Verdict by actual outcome</b> (in brackets: number of answers; “open outcome” = remitted or fact-dependent
decision, accepted verdicts “with conditions” / “unclear”):</p>
{verdicts_mod}

<h3>2.4 Plankarta cases (map reading)</h3>
{table_plans}
<p>Map views = images of the plan map the agent looked at per question (<code>view_map_area</code>,
<code>view_pdf_page</code>). Evidence = the plan map of the case was among the passages seen.</p>
{plans_text}

<h3>2.5 Quality / speed / cost trade-off (14 cases and MÖD)</h3>
{tradeoff}
{cost_chart}

{'<h3>2.6 Variance between passes</h3><ul>' + spread + '</ul><p>Typical gap between two identical passes: a few hundredths; a difference below ~0.05 between configurations is not significant.</p>' if spread else ''}

""" + (f"""<h3>2.7 Tasks beyond the verdict: explain, propose, develop</h3>
<p>From 2026-10-19 the agent first classifies the question (<code>answer_ready(mode)</code>: verdict, explain, propose,
develop) and answers in that mode's format; the RAG gets the same format instructions in one prompt. Judge: MiMo v2.6
Flash. “Mode right” = the agent chose the case's task. Places = share of the plan-designated places the answer names
(string match, at least <code>min_anchors</code> needed); options sourced = share of the proposed options the cited
sources support (judge). Latencies of these runs include the query embedding on the CPU (ONNX), not the GPU.</p>
{tasks_table}
<p>“Agent, propose fix”: the propose guide rewritten (the place is not fixed → propose; work from the comprehensive
plan's growth passages in 4–6 turns) and the last turn forced to <code>answer_ready</code>, so a run that reaches the step
budget still picks its mode.</p>""" if tasks_table else "") + (f"""
<h3>2.8 Verdict sets with the mode prompt (regression)</h3>
{regression}
<p>Same cases, agent medium / medium, Luna judge as in the matrix above. The mode runs used CPU embeddings, hence part
of the extra latency.</p>""" if regression else "") + (f"""
<h3>2.9 Optimisation round (2026-10-21)</h3>
<p>Goal: improve the agent on the four uses (verdict, explain, propose, develop), in order of importance accuracy,
usefulness, cost, time, with cheap models (budget $3.50). Dev set: the 52 cases of the 14-case set, the 10 seeds and
the 28 generated cases, one pass per configuration, graded by MiMo v2.6 Flash in the run and again by GPT-6 Luna
(<code>agentic.rejudge</code>), so that a gain counts only if both model families see it. Before the runs, the
benchmark was fixed: the judge now gets every cited source in full (40 × 3,000 characters instead of 15 × 1,500: a
quarter of the answers cited more than 15 sources, whose facts were counted as unsupported); the 9 of the 14 cases
whose question also asks “how does it work” or “what would it take” accept explain / develop as mode
(<code>modes</code>); 3 reference points the asker does not need were dropped (<code>REVIEW</code>).</p>
{experiment_table_html}
<ul>
<li><b>Recipe per mode + site checklist</b> (choose the mode in the first turn; for explain, read the kommun's page in
full; grep the place's constraints: strandskydd, farmland, flood, noise, risk, radon…): key points unchanged
(−0.00, 90 % CI −0.05 to +0.04), less of the expected evidence read (−0.09): rejected. More instructions on how to
explore do not move the scores.</li>
<li><b>MiMo v2.6 Flash as the agent</b>: more key points under both judges (+0.10 MiMo, +0.09 Luna, CI +0.04 to
+0.15), but 7.5 unsupported claims per answer for the Luna judge (Luna as the agent: 1.4), answers 2.3× slower (median
≈ 2 min, 11k reasoning tokens) and twice the cost: rejected (accuracy first). It read less of the evidence than Luna
yet covered more points: Luna's losses are in writing the answer, not in finding the sources.</li>
<li><b>“Complete answer”</b> (the answer instruction “prefer fewer, well-sourced points” replaced by “include every
rule, condition, step, fee, deadline and site constraint from your tool results, each with its source; silent on what
they do not say”): +0.03 key points with the MiMo judge (CI −0.00 to +0.06), +0.05 with the Luna judge (CI +0.02 to
+0.09), gains on explain / propose / develop, verdict unchanged; same latency and cost; unsupported claims equal for
MiMo, +0.5 for Luna (CI −0.0 to +1.0). <b>Adopted</b> as the default prompt.</li>
<li>Not tried: GPT-6 Sol (≈ 20× Luna's price per token, ≈ $0.10 per answer) and MiMo v2.6 Pro (≈ 4×): MiMo Flash
showed that a stronger writer covers more but invents more, and the budget did not allow measuring them properly.</li>
</ul>
<p>Two runs were cut by the machine (memory) and finished from their saved results; latencies are with the query
embedding on the CPU. One pass per configuration: differences below ~0.05 are within the noise of a single pass.</p>""" if experiment_table_html else "") + (f"""
<h3>2.10 Bug round (2026-10-22)</h3>
<p>The scores of the previous sections hid tool failures: they show what the answer covers, not what the agent tried
and did not get. Reading the tool calls of the 1,108 stored agent answers found these bugs (fixed, with tests in
<code>tests/test_tools.py</code>, <code>tests/test_agent_images.py</code>):</p>
<ul>
<li><b><code>read</code> failed on the id as printed</b>: tool outputs tag chunks <code>[c:&lt;id&gt;]</code> and the agent
passed <code>c:&lt;id&gt;</code> back; 1,845 reads returned nothing, in 57 % of the answers, and 88 % of them were never
retried, so the agent answered without the passage it had chosen to read. <code>read</code> now takes the id in every
form the model writes (with <code>c:</code> or brackets, a doc id, a truncated id).</li>
<li><b>Statute chapters filed under the previous chapter</b>: a chapter heading wrapped onto two lines, “10 Kap.” with a
capital K, a bare “14 kap.” line: MB 4 kap. (national interests), JB 7 / 10 / 11 kap., FBL 1 / 14 kap., MPF 4 kap.,
PBF 7 kap. had wrong chapter headers, so <code>law_section</code> did not find them (~70 calls returned nothing). The
text and the chunk ids were right: headers fixed and the affected chunks re-embedded.</li>
<li><b>Municipality-filtered queries scanned the whole table</b> (<code>kind != 'law'</code> does not use the index):
~0.7 s per query, ~2.3 s per answer. <b><code>grep</code> without a municipality</b> ran a regex over the whole corpus
(12–28 s); it now needs a municipality or the statutes.</li>
<li><b>Every image was sent again on each later turn</b> (plan map crops, PDF pages): it now goes with the next model
call only, and the agent is told to write down what it reads.</li>
<li><b>Miscopied citation ids</b> (~1 % of the cited ids, wrong after the first characters) left the claim without a
source in the chat and for the judge: they now resolve to the chunk shown to the agent with the longest common prefix.</li>
<li><b>Garbled titles</b> (UTF-8 read as Latin-1 by the crawler: “fÃ¶r”) on ~285 documents of 15 municipalities:
repaired at extraction, and these municipalities crawled again (their links were scored on garbled words).</li>
</ul>
<p>Same 52 dev cases, before and after (MiMo judge in the run, Luna judge with <code>agentic.rejudge</code>):</p>
{bugfix_html}
<p>The failures are gone and the agent is faster (median answer 64 → 39 s, first token 54 → 25 s) and better grounded
(unsupported claims for the Luna judge 1.96 → 1.45 per answer), at the same cost. Key points did not move: the agent
made up for the failed calls with more searches, so the bugs cost time and grounding rather than coverage. The results
of sections 2.1–2.9 were measured with these bugs: their latencies are ~20–30 s too high and their unsupported claims
too high; comparisons between configurations stay valid (all had the same bugs).</p>
<p>Failed tool calls of the run after the fixes (<code>agentic.health</code>, printed by every benchmark run since):</p>
{health_html}
<p><code>plan_rules</code> fails on plans whose map was not crawled or has no text layer (no provision extracted:
<code>no_data</code>): a data gap, not a tool bug.</p>""" if bugfix_html else "") + (f"""
<h3>2.11 Coverage of the municipalities' plans</h3>
<p>All the benchmarks above are built from documents of the corpus, so a plan the crawl never fetched cannot appear in
them and its absence costs nothing in their scores. This benchmark starts outside the corpus: for {coverage['total']['municipalities'] + coverage['total'].get('unmeasured', 0)}
sampled municipalities (small, medium and large), their own list of plans in force, fetched live
({coverage['total']['reference_fetched']}), and for up to 20 listed plans the PDFs the plan page links to
(<code>agentic.coverage</code>). Score: the share of those plans and PDFs found in the corpus (matched by URL).</p>
{coverage_table(coverage)}
<p>{coverage['total'].get('unmeasured', 0)} municipalities could not be measured: their list page links to no plan
(they publish their plans in a map or search application, out of reach of a crawler), or was unreachable:
{html.escape(', '.join(f'{k} ({v})' for k, v in sorted(coverage.get('unmeasured', {}).items())))}. For them the
corpus has at most the plans linked elsewhere on the site. File: <code>{coverage['file']}</code>.</p>
{coverage_gaps(coverage)}""" if coverage else "") + (f"""
<h3>2.12 Document filters in the agent tools</h3>
<p>The larger corpus makes a kommun's search results a mix of plans, comprehensive plans, permit pages and
administration. <code>search</code>, <code>grep</code> and <code>list_documents</code> now take document types and a
title filter, applied before ranking; <code>grep</code> can list the documents that match instead of the passages, and
<code>list_documents</code> pages through long lists. The agent is told about them in three lines of its tool guide.
Same dev set and protocol as section 2.10 (52 cases × 3 passes, MiMo judge in the run, Luna re-judging), same corpus
(2026-10-22), so the difference is the tools and those three lines.</p>
{filters_html}
<p>{FILTERS_READING}</p>""" if filters_html else "") + f"""

<h2>3. Reading the results</h2>
<ul>
{reading}
</ul>

<h2>4. Recommendations</h2>
<ul>
{recommendations}
</ul>
<h3>Next steps (recommended order, 2026-10-21)</h3>
{NEXT_STEPS}

<h2>Appendix: reproduce</h2>
<p><code>python -m agentic.bench --systems agent --store disk --explore-effort medium --effort medium --cases-file
cases_caselaw.jsonl --sample 50 --repeats 2 --workers 3</code> (MÖD; <code>--systems rag</code> for the classic RAG;
<code>--cases-file cases_plans.jsonl</code> for the plankarta cases, <code>--disable-tools view_map_area</code> for the
ablations) · <code>python -m agentic.grounding &lt;results&gt;</code> · <code>python -m agentic.report</code>. Total cost
of the answers in this report: ~${fmt(total_cost, 2)} (judges and case generation excluded). Result files used:
{files}.</p>"""
    else:
        body = f"""
<h1>Pyrmit – agent de faisabilité : rapport de benchmark</h1>
<div class="sub">Assistant de faisabilité de projets de construction en Suède (droit de l'urbanisme, PBL, miljöbalken,
détaljplaner). Modèle : GPT-6 Luna via OpenRouter. Rapport généré le {today:%d/%m/%Y}.</div>

<div class="box"><b>En bref</b>
<ul>
<li>Le système testé est un <b>agent à outils</b> qui explore lui-même un corpus local : 15 lois suédoises, les sites
des 290 communes, {plans_n} détaljplaner répertoriées. Il répond avec des sources citées et cliquables.</li>
<li>Deux bancs : <b>14 études de cas</b> faites main (projets réels des communes du corpus) et <b>{len(sample)} cas tirés de
vraies décisions de la Cour d'appel foncière et environnementale (MÖD)</b>, sur {len(caselaw)} générés à partir de
{len(rulings)} arrêts.</li>
<li>Chaque réponse est notée sur le verdict, les points clés attendus, les preuves réellement consultées, l'ancrage des
affirmations dans les sources citées, la latence et le coût.</li>
<li><b>Résultat principal</b> : l'effort de raisonnement des tours d'exploration est le réglage qui compte. Passer
l'exploration de <i>low</i> à <i>medium</i> fait voir à l'agent beaucoup plus de preuves (0,53 → 0,70 sur les cas MÖD),
améliore l'ancrage (0,69 → 0,79) et la couverture des points clés (0,43 → 0,48), au prix de ~17 s et d'un coût ×2,4
(≈ 0,009 $ par question). Monter la réponse finale en <i>high</i> n'apporte rien de mesurable.</li>
<li><b>Point faible</b> : sur les projets que la justice a refusés, l'agent ne conclut « non faisable » que dans 40 à 60 %
des cas ; il penche vers « faisable sous conditions ». C'est le premier chantier de prompt.</li>
<li>Les cas MÖD sont nettement plus durs que les 14 études de cas, qui saturent (verdict ≈ 1) : c'est le banc à utiliser
pour les prochaines décisions.</li>
<li>Coût des réponses de l'agent dans ce rapport : environ {fmt(total_cost, 2)} $ (hors juge et génération des cas).</li>
</ul></div>

<h2>1. Le système testé</h2>
<h3>1.1 Corpus hors ligne</h3>
<table>
<tr><th>Source</th><th>Contenu</th><th>Traitement</th></tr>
<tr><td>Lois (Riksdagen, données ouvertes)</td><td>15 textes consolidés : PBL, PBF, miljöbalken, jordabalken,
fastighetsbildningslag, anläggningslag, eau et assainissement (LAV, FMH), kulturmiljölag…</td>
<td>Un passage par article (§), chapitres et articles à lettre gérés</td></tr>
<tr><td>Sites des 290 communes (Wikidata)</td><td>Pages bygglov, avlopp, taxor, planbesked, ÖP, détaljplaner + PDF liés
(planbeskrivningar, plankartor, ÖP, taxes)</td><td>Crawl respectueux de robots.txt (1 requête/s), texte PyMuPDF,
OCR local (EasyOCR) pour les PDF scannés</td></tr>
<tr><td>Registre des détaljplaner</td><td>{plans_n} plans : statut, date de laga kraft, plankarta / planbeskrivning,
planbestämmelser extraites (byggnadsarea, nockhöjd, fastighetsstorlek…)</td><td>Règles, sans LLM</td></tr>
</table>
<p>Au total 344 199 passages (chunks) dans 31 497 documents, 275 communes représentées (corpus du 22 octobre, celui des
runs de ce rapport ; le crawl du 23 octobre l'a quintuplé). Recherche : embeddings locaux
<code>snowflake-arctic-embed-l-v2</code> (choisi sur un banc de recherche : 0,92 de rappel@5) + BM25 sur les racines suédoises
(SQLite FTS5), fusion RRF, filtre par commune ; le tout sur disque (SQLite + vecteurs sur GPU, ~0,1 s par recherche).</p>

<h3>1.2 Boucle de l'agent</h3>
<div class="flow"><span>Question (anglais)</span><b>→</b><span>Tours d'exploration (effort <i>explore</i>) :
outils en parallèle</span><b>→</b><span>answer_ready</span><b>→</b><span>Réponse finale (effort <i>answer</i>),
streamée</span><b>→</b><span>Citations [n] cliquables</span></div>
<table>
<tr><th>Outil</th><th>Rôle</th></tr>
<tr><td><code>find_kommun</code></td><td>Lieu → commune, et ce que le corpus contient pour elle</td></tr>
<tr><td><code>search</code></td><td>Recherche hybride (sémantique + BM25 suédois) sur les lois et/ou une commune</td></tr>
<tr><td><code>grep</code></td><td>Recherche exacte : n° de plan, désignation cadastrale, « nockhöjd », montants</td></tr>
<tr><td><code>list_documents</code> / <code>read</code></td><td>Lister les documents d'une commune, lire un passage ou un document</td></tr>
<tr><td><code>law_section</code></td><td>Texte exact d'un article (« PBL 9 kap. 4 § »)</td></tr>
<tr><td><code>plans</code> / <code>plan_rules</code></td><td>Registre des détaljplaner et leurs règles sous forme de tableau</td></tr>
<tr><td><code>view_pdf_page</code></td><td>Image d'une page PDF pour le modèle (plankarta)</td></tr>
</table>
<p>Chaque sortie d'outil porte l'identifiant des passages (<code>[c:id]</code>) ; la réponse doit citer ces identifiants pour
toute règle, chiffre ou délai. Deux réglages d'effort de raisonnement : <b>explore</b> pour les tours où l'agent cherche,
<b>answer</b> pour la réponse finale. C'est l'objet principal de ce benchmark.</p>

<h2>2. Comment le benchmark a été constitué</h2>
<h3>2.1 Les 14 études de cas</h3>
<p>Écrites à la main à partir des documents du corpus et des retours d'utilisateurs (questions du type « procédure de
bygglov à Vallentuna », « hauteur maximale à Veda », assainissement, infrastructures). Trois familles : projets réels sur
des détaljplaner (Kumla-Stensta, Mörby backe, Kristineberg), règles nationales + locales (attefallshus, strandskydd,
éco-village sur terre agricole, assainissement individuel, division de parcelle, démolition…), procédures
(förhandsbesked). Chaque cas porte : verdicts acceptés, 3 à 5 points clés, et des <b>preuves attendues</b> (article de loi
ou extrait exact d'un document communal) que l'agent doit avoir consultées.</p>

<h3>2.2 Les cas tirés de vraies décisions (MÖD)</h3>
<ol>
<li><b>Collecte</b> : {len(rulings)} arrêts de Mark- och miljööverdomstolen depuis 2011 (lagen.nu, dont le robots.txt
autorise les pages d'arrêts) ; {relevant} sur nos sujets (bygglov, détaljplan, strandskydd, förhandsbesked,
assainissement…).</li>
<li><b>Transformation</b> par le LLM : les faits deviennent la question, posée comme le ferait le demandeur <i>avant</i>
la décision (sans l'issue ni le raisonnement) ; l'issue réelle donne les verdicts acceptés ; les motifs donnent les points
clés ; les articles appliqués donnent les preuves attendues.</li>
<li><b>Contrôles</b> : arrêts de pure procédure écartés (qualité pour agir, sanctions) ; questions qui mentionnent le
tribunal écartées ; preuves = phrase exacte d'au moins 5 mots du texte de loi <b>actuel</b> (la PBL 9 kap. a été
renumérotée par la SFS 2025:974 et certaines formulations ont changé) ; arrêts sans article actuel gardés sans preuve
attendue (notés sur le verdict et les points).</li>
<li><b>Échantillon</b> : {len(sample)} cas tirés au hasard (graine fixe), équilibrés entre issues négatives, positives et
ouvertes, tous avec preuves attendues.</li>
</ol>
<p>Répartition des {len(caselaw)} cas générés par verdicts acceptés : {verdict_split}. Coût de la génération : ~0,55 $.</p>

<h3>2.3 Exemples de cas</h3>
{examples}

<h2>3. Comment les réponses sont évaluées</h2>
<table>
<tr><th>Mesure</th><th>Définition</th><th>Comment</th></tr>
<tr><td>Verdict</td><td>Le verdict de la réponse (faisable / sous conditions / non faisable / incertain) est parmi les
verdicts acceptés</td><td>Juge LLM</td></tr>
<tr><td>Points clés</td><td>Chaque point attendu noté 0 (absent ou contredit), 1 (partiel), 2 (clair) ; ramené entre 0 et 1</td>
<td>Juge LLM</td></tr>
<tr><td>Preuves</td><td>Part des preuves attendues (article, extrait de document) que l'agent a <i>vraiment vues</i> dans
ses outils</td><td>Automatique, sans LLM</td></tr>
<tr><td>Ancrage</td><td>Part des affirmations factuelles de la réponse soutenues par le texte des sources qu'elle cite</td>
<td>Second juge LLM, avec le texte complet des sources</td></tr>
<tr><td>Affirmations non sourcées</td><td>Règles ou chiffres absents de la référence et des sources citées</td><td>Juge LLM</td></tr>
<tr><td>Latence, 1er token, coût</td><td>Temps total, temps jusqu'au premier mot de la réponse streamée, coût OpenRouter</td>
<td>Mesuré</td></tr>
</table>
<div class="warn"><b>Limites de l'évaluation.</b> Le juge est le même modèle que l'agent (GPT-6 Luna, effort medium) : bon
marché mais potentiellement complaisant ; ses notes servent à <i>comparer</i> des réglages, pas comme valeurs absolues.
Les points clés des cas MÖD sont rédigés par le LLM à partir de l'arrêt : un point peut être formulé plus finement que ce
qu'un bon conseil dirait. Le juge reçoit le texte des sources citées pour ne pas pénaliser un fait juste absent de la
référence. Chaque configuration est passée 2 à 4 fois : la variance d'un passage à l'autre est donnée plus bas. Les cas
tournent 3 en parallèle : les latences incluent un peu de contention.</div>

<h2>4. Résultats</h2>
<h3>4.1 Historique sur les 14 cas (sous-corpus des 5 communes, versions successives)</h3>
<table><tr><th>Version</th><th>Verdict</th><th>Points clés</th><th>Preuves</th><th>Ancrage</th><th>Latence</th><th>1er token</th>
<th>Coût</th></tr>
{history}
</table>
<p>Le verdict est juste pour toutes les versions (14/14) : ces cas saturent sur ce critère. Le RAG tournait avec une
réponse en effort high, non streamée (sa latence est la réponse complète, ~1 700 tokens de raisonnement) : il n'a pas été
relancé en effort medium et streamé comme les agents, ce qui devrait le rendre plus rapide qu'eux (non mesuré). v1 → v2 : identifiants citables dans toutes les sorties d'outils et règle « pas d'affirmation sans source lue »
(ancrage 0,68 → 0,86). v2 → v3/v4 : outils en parallèle, <code>answer_ready</code>, réponse streamée et exploration en
effort <i>low</i> : latence divisée par 2, mais qualité en baisse. D'où la matrice ci-dessous.</p>

<h3>4.2 Matrice des efforts (corpus complet sur disque)</h3>
<h3>14 études de cas</h3>
{table14}
<h3>{len(sample)} cas MÖD</h3>
{table_mod}
<p>Meilleure valeur de chaque colonne en vert. n = nombre de réponses (cas × passages).</p>
{quality_chart and '<h3>4.3 Qualité sur les cas MÖD</h3>' + quality_chart}
<h3>4.4 Compromis qualité / rapidité / coût</h3>
{tradeoff}
{cost_chart}
{duel}
<h3>4.5 Verdict selon l'issue réelle (cas MÖD)</h3>
{verdicts_mod}
<p>Entre parenthèses : nombre de réponses. « Issue ouverte » = renvoi ou décision dépendant des faits (verdicts
acceptés : sous conditions / incertain).</p>
{'<h3>4.6 Variance entre passages</h3><ul>' + spread + '</ul><p>Écart typique entre deux passages identiques : quelques centièmes ; une différence de moins de ~0,05 entre configurations n’est pas significative.</p>' if spread else ''}

{answer_excerpt}

<h2>5. Lecture des résultats</h2>
<ul>
<li><b>L'effort d'exploration compte, pas l'effort de réponse.</b> En <i>low</i>, l'agent fait ~12 appels d'outils par
question ; en <i>medium</i>, ~20 (14 cas) à ~26 (MÖD), mieux ciblés : il lit plus souvent l'article de loi décisif et le
document communal pertinent. Preuves vues : 0,84 → 0,88 sur les 14 cas, 0,53 → 0,70 sur les cas MÖD ; ancrage
0,69 → 0,79 sur les cas MÖD ; points clés +0,05 à +0,07, au-delà de l'écart entre passages (~0,04). La réponse
finale en <i>high</i> ne change ni les points ni les preuves, et ajoute 7 s.</li>
<li><b>Le prix</b> : sur les cas MÖD, latence 26 s → 43 s (premier mot de la réponse : 19 s → 35 s), coût
0,0036 $ → 0,0086 $ par question. Sur les 14 cas, +3 s seulement. À 1 000 questions par mois : ~9 $ au lieu de ~4 $.</li>
<li><b>Calibrage du verdict</b> : sur les cas MÖD, le verdict est juste dans 90 % des issues ouvertes et ~75 % des
projets acceptés, mais seulement 40 à 60 % des projets refusés : l'agent répond « faisable sous conditions » là où le
tribunal a dit non (souvent : terre agricole productive, strandskydd sans motif particulier, besoin de planläggning).
Explorer davantage accentue cette prudence (plus de conditions trouvées → « sous conditions »), d'où un verdict
global légèrement plus bas en <i>medium</i> (0,75 → 0,70) malgré de meilleures preuves.</li>
<li><b>Les cas MÖD sont plus durs</b> que les 14 études de cas : faits juridiques fins (terre « productive », caractère
« substantiel » d'un changement d'usage, conditions du LIS…) et points clés rédigés à partir du raisonnement complet de
la Cour. Les 14 cas, eux, saturent (verdict ≥ 0,96 partout) et ne départagent plus les réglages.</li>
<li><b>Ancrage</b> : 79 à 89 % des affirmations sont soutenues par les sources citées ; le reste vient surtout de
connaissances juridiques générales du modèle, non relues dans le corpus.</li>
</ul>

<h2>6. Recommandations et suite</h2>
<ul>
<li><b>Réglage par défaut de l'app</b> : exploration <i>medium</i>, réponse <i>medium</i> ; garder exploration <i>low</i>
comme mode « rapide » (≈ 25 s). La réponse en <i>high</i> ne vaut pas son coût.</li>
<li><b>Prompt du verdict</b> : dire explicitement qu'une condition de fond non remplie (terre agricole productive sans
intérêt public essentiel, strandskydd sans motif particulier, projet qui exige un détaljplan) rend le projet « non
faisable tel que décrit », et ne pas transformer chaque exigence procédurale en « sous conditions ». Mesurer l'effet sur
les cas MÖD refusés.</li>
<li><b>Banc</b> : utiliser les {len(caselaw)} cas MÖD (échantillons de 50, 2 passages) pour chaque changement de prompt ou de
modèle ; ajouter des cas « plankarta seulement », maintenant que les PDF scannés sont océrisés, une fois la lecture des
cartes en place.</li>
<li><b>Corpus</b> : le crawl d'octobre a quintuplé le corpus, qui n'est pas encore évalué par ces bancs ; l'OCR de ses
PDF scannés (PP-OCRv6, avec la position des mots) est en cours, leur texte entre dans l'index à la reconstruction suivante ;
ensuite, relier chaque code de plan à sa zone sur la carte (modèle de vision), et chaque parcelle à son plan applicable
(WMS des communes / Lantmäteriet).</li>
<li><b>Juge</b> : faire relire un échantillon de notes par une personne du domaine pour calibrer le juge LLM.</li>
</ul>

<h2>Annexe : reproduire</h2>
<p><code>python -m corpus.caselaw</code> (arrêts MÖD) · <code>python -m agentic.cases_from_caselaw</code> (cas) ·
<code>python -m agentic.bench --systems agent --store disk --explore-effort medium --effort medium --cases-file
cases_caselaw.jsonl --sample 50 --repeats 2 --workers 3</code> · <code>python -m agentic.grounding &lt;résultats&gt;</code> ·
<code>python -m agentic.report</code>. Fichiers de résultats utilisés : {files}.</p>"""

    title = tr("Pyrmit – rapport benchmark", "Pyrmit – benchmark report")
    return (f'<!doctype html><html lang="{LANG}"><head><meta charset="utf-8"><title>{title}</title>{STYLE}</head>'
            f"<body>{body}\n</body></html>")


def flatten_outline(pdf_path: Path) -> int:
    """Chrome writes the outline (--generate-pdf-document-outline: one bookmark per heading, at its exact position)
    under a single entry for the h1 title: drop it so the sections are the top level of the viewer's side panel."""
    import pymupdf

    doc = pymupdf.open(pdf_path)
    toc = doc.get_toc(simple=False)
    if toc and toc[0][0] == 1 and all(entry[0] > 1 for entry in toc[1:]):
        toc = [[entry[0] - 1, *entry[1:]] for entry in toc[1:]]
        doc.set_toc(toc)
        tmp = pdf_path.with_name(pdf_path.stem + ".tmp.pdf")
        doc.save(tmp, garbage=3, deflate=True)
        doc.close()
        tmp.replace(pdf_path)
    else:
        doc.close()
    return len(toc)


def find_browser() -> str | None:
    return next((b for b in BROWSERS if Path(b).exists()), None) or shutil.which("chrome") or shutil.which("msedge")


def write_pdf(page_html: str, name: str, browser: str | None) -> None:
    """HTML -> ../pyrmit_doc/<name>.html and .pdf (headless Chrome / Edge), with a clickable outline (bookmarks)."""
    out_html, out_pdf = DOC_DIR / f"{name}.html", DOC_DIR / f"{name}.pdf"
    out_html.write_text(page_html, encoding="utf-8")
    if browser is None:
        print(f"No Chrome/Edge found: open {out_html} and print it to PDF")
        return
    subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    "--generate-pdf-document-outline", f"--print-to-pdf={out_pdf}", out_html.as_uri()],
                   check=True, capture_output=True, timeout=180)
    bookmarks = flatten_outline(out_pdf)
    print(f"{out_pdf} ({out_pdf.stat().st_size // 1024} KB, {bookmarks} bookmarks)")


def main() -> None:
    import argparse

    global LANG
    parser = argparse.ArgumentParser(description="PDF report of the agent benchmark")
    parser.add_argument("--lang", choices=["en", "fr", "both"], default="en")
    args = parser.parse_args()
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    browser = find_browser()
    for LANG in (["fr", "en"] if args.lang == "both" else [args.lang]):
        write_pdf(build_html(), OUTPUT_NAMES[LANG], browser)


if __name__ == "__main__":
    main()

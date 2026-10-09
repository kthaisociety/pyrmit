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
import subprocess
from collections import defaultdict
from datetime import date
from pathlib import Path

from agentic.bench import CASES_PATH, RESULTS_DIR, sample_cases
from corpus.common import DATA_DIR, read_jsonl

DOC_DIR = Path(__file__).resolve().parents[2].parent / "pyrmit_doc"
OUTPUT_NAMES = {"fr": "pyrmit_rapport_benchmark", "en": "pyrmit_benchmark_report"}
LANG = "en"  # set by main(); tr() and fmt() follow it
FIRST_MATRIX_RUN = "20261007-211220"  # earlier result files used the in-memory corpus subset and older prompts
BROWSERS = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"]

# Earlier runs (14 cases, in-memory corpus of the 5 kommuner of the cases), from pyrmit_agentic_rag_report.md
HISTORY = [  # (French name, English name), key points, evidence, grounding, latency s, first token s, cost $
    (("RAG classique (1 recherche, réponse high)", "Classic RAG (1 search, high-effort answer)"),
     0.56, 0.58, 0.84, 30, None, 0.0021),
    (("Agent v1 (effort high partout)", "Agent v1 (high effort throughout)"), 0.75, 0.86, 0.68, 64, None, 0.0057),
    (("Agent v2 (sources citables, effort medium)", "Agent v2 (citeable sources, medium effort)"),
     0.77, 0.96, 0.86, 39, 39, 0.0042),
    (("Agent v3 (exploration low, réponse medium)", "Agent v3 (low exploration, medium answer)"),
     0.68, 0.73, 0.82, 19, 13, 0.0025),
    (("Agent v4 (v3 + lecture du document communal)", "Agent v4 (v3 + read the key municipal document)"),
     0.65, 0.84, 0.84, 23, 17, 0.0036),
]

FILE = re.compile(r"bench-(\d{8}-\d{6})-(?P<systems>[a-z-]+?)-(?P<answer>low|medium|high)"
                  r"-explore-(?P<explore>low|medium|high|same)(?P<tag>-cases_caselaw)?\.json$")


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

def load_runs() -> list[dict]:
    """One entry per (case set, system, explore effort, answer effort), merging every matrix file of that
    configuration (each file's passes count as separate repeats)."""
    files: dict[tuple, list[Path]] = defaultdict(list)
    for path in sorted(RESULTS_DIR.glob("bench-*.json")):
        match = FILE.search(path.name)
        if not match or match.group(1) < FIRST_MATRIX_RUN:
            continue
        key = ("mod" if match.group("tag") else "cases14", match.group("systems"), match.group("explore"),
               match.group("answer"))
        files[key].append(path)
    runs = []
    for (cases, systems, explore, answer), paths in sorted(files.items()):
        rows = []
        for index, path in enumerate(paths):
            for row in json.loads(path.read_text(encoding="utf-8")):
                rows.append({**row, "repeat": f"{index}.{row.get('repeat', 0)}"})
        for system in sorted({row["system"] for row in rows}):
            mine = [row for row in rows if row["system"] == system and not row.get("error")]
            if not mine:
                continue
            repeats = sorted({row["repeat"] for row in mine})
            runs.append({
                "cases": cases, "system": system, "explore": explore if system == "agent" else "–", "answer": answer,
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
    return sorted(runs, key=lambda r: (r["cases"], r["system"] != "agent", order[r["explore"]], order[r["answer"]]))


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


def label(run: dict) -> str:
    if run["system"] == "rag":
        return tr(f"RAG classique (réponse {run['answer']})", f"Classic RAG ({run['answer']} answer)")
    return tr(f"Agent, exploration {run['explore']} / réponse {run['answer']}",
              f"Agent, exploration {run['explore']} / answer {run['answer']}")


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
    y_min = 0.3
    parts = [f'<svg viewBox="0 0 {width} {height}" class="chart" xmlns="http://www.w3.org/2000/svg">']
    for tick in (0.3, 0.5, 0.7, 0.9):
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


def runs_table(runs: list[dict]) -> str:
    head = tr("<tr><th>Configuration</th><th>n</th><th>Verdict</th><th>Points clés</th><th>Preuves</th>"
              "<th>Ancrage</th><th>Appels outils</th><th>Latence</th><th>1er token</th><th>Coût / question</th></tr>",
              "<tr><th>Configuration</th><th>n</th><th>Verdict</th><th>Key points</th><th>Evidence</th>"
              "<th>Grounding</th><th>Tool calls</th><th>Latency</th><th>1st token</th><th>Cost / question</th></tr>")
    body = []
    best = {key: max((r[key] for r in runs if r[key] is not None), default=None)
            for key in ("verdict", "points", "evidence", "grounded")}
    for run in runs:
        def cell(key):
            value = run[key]
            text = fmt(value)
            return f"<td class='{'best' if value is not None and value == best[key] else ''}'>{text}</td>"
        body.append(f"<tr><td>{esc(label(run))}</td><td>{run['n']}</td>{cell('verdict')}{cell('points')}"
                    f"{cell('evidence')}{cell('grounded')}<td>{fmt(run['tools'], 1)}</td>"
                    f"<td>{fmt(run['seconds'], 0)} s</td><td>{fmt(run['first'], 0)} s</td>"
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


def build_html() -> str:
    runs = load_runs()
    by_key = {(r["cases"], r["system"], r["explore"], r["answer"]): r for r in runs}
    runs14 = [r for r in runs if r["cases"] == "cases14"]
    runs_mod = [r for r in runs if r["cases"] == "mod"]
    cases14 = list(read_jsonl(CASES_PATH))
    caselaw = list(read_jsonl(CASES_PATH.parent / "cases_caselaw.jsonl"))
    sample = sample_cases(list(caselaw), 50)
    rulings = list(read_jsonl(DATA_DIR / "raw" / "caselaw" / "mod.jsonl"))
    relevant = sum(1 for r in rulings if r.get("relevant"))
    plans = sum(1 for _ in (DATA_DIR / "plans.jsonl").open(encoding="utf-8")) if (DATA_DIR / "plans.jsonl").exists() else 0
    plans_n = f"{plans:,}" if LANG == "en" else f"{plans:,}".replace(",", " ")
    cases_label = {"cases14": tr("14 cas", "14 cases"), "mod": "MÖD"}

    colors = ["#2563eb", "#f59e0b", "#10b981", "#8b5cf6", "#ef4444", "#0891b2"]
    quality_chart = ""
    if runs:
        configs = [r for r in runs_mod if r["system"] == "agent"] or runs14
        quality_chart = bar_chart(
            [(m, [(short(r), r[k]) for r in configs]) for m, k in
             [("Verdict", "verdict"), (tr("Points clés", "Key points"), "points"),
              (tr("Preuves", "Evidence"), "evidence"), (tr("Ancrage", "Grounding"), "grounded")]],
            ["exploration " + short(r) for r in configs], colors)
    agents = [r for r in runs if r["system"] == "agent"]
    tradeoff = cost_chart = ""
    if agents:
        names = [f"{cases_label[r['cases']]} – {short(r)}" for r in agents]
        tradeoff = scatter([(names[i], r["seconds"], r["points"], colors[i % len(colors)]) for i, r in enumerate(agents)],
                           tr("latence moyenne par question (s)", "mean latency per question (s)"),
                           tr("points clés", "key points"), x_max=60)
        cost_chart = scatter([(names[i], r["cost"], r["points"], colors[i % len(colors)]) for i, r in enumerate(agents)],
                             tr("coût moyen par question ($)", "mean cost per question ($)"),
                             tr("points clés", "key points"), x_max=0.012)

    # Per-case wins of medium exploration over low, on the MÖD cases
    low, med = by_key.get(("mod", "agent", "low", "medium")), by_key.get(("mod", "agent", "medium", "medium"))
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

    def rows_for(case, cases_key):
        out = []
        for run in runs:
            if run["cases"] != cases_key:
                continue
            row = next((r for r in run["rows"] if r["case"] == case["id"]), None)
            out.append((label(run), row))
        return out

    examples = (''.join(example_case(c, rows_for(c, 'cases14')) for c in examples14)
                + ''.join(example_case(c, rows_for(c, 'mod')) for c in examples_mod))
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
        f"<tr><td>{esc(tr(*n))}</td><td>{fmt(p)}</td><td>{fmt(e)}</td><td>{fmt(g)}</td><td>{s} s</td>"
        f"<td>{'–' if f is None else str(f) + ' s'}</td><td>{money(c)}</td></tr>" for n, p, e, g, s, f, c in HISTORY)
    table14 = runs_table(runs14) if runs14 else "<p>–</p>"
    table_mod = runs_table(runs_mod) if runs_mod else "<p>–</p>"
    verdicts_mod = verdict_table([r for r in runs_mod if r["system"] == "agent"], {c["id"]: c for c in caselaw})
    files = ", ".join(sorted({esc(r["file"]) for r in runs})) or "–"
    today = date.today()

    if LANG == "en":
        body = f"""
<h1>Pyrmit – feasibility agent: benchmark report</h1>
<div class="sub">Feasibility assistant for building projects in Sweden (planning law, PBL, Environmental Code,
detailed development plans). Model: GPT-6 Luna via OpenRouter. Report generated on {today:%Y-%m-%d}.</div>

<div class="box"><b>Summary</b>
<ul>
<li>The system under test is a <b>tool-using agent</b> that explores a local corpus by itself: 15 Swedish statutes, the
websites of all 290 municipalities (kommuner), {plans_n} indexed detailed plans (detaljplaner). It answers with cited,
clickable sources.</li>
<li>Two benchmarks: <b>14 hand-written case studies</b> (real projects in the corpus municipalities) and <b>{len(sample)}
cases drawn from real rulings of the Land and Environment Court of Appeal (MÖD)</b>, out of {len(caselaw)} generated from
{len(rulings)} rulings.</li>
<li>Each answer is scored on the verdict, the expected key points, the evidence actually consulted, how well its claims
are grounded in the cited sources, latency and cost.</li>
<li><b>Main result</b>: the reasoning effort of the exploration turns is the setting that matters. Raising exploration
from <i>low</i> to <i>medium</i> makes the agent see much more of the expected evidence (0.53 → 0.70 on the MÖD cases),
improves grounding (0.69 → 0.79) and key-point coverage (0.43 → 0.48), at the cost of ~17 s and 2.4× the price
(≈ $0.009 per question). A <i>high</i>-effort final answer brings nothing measurable.</li>
<li><b>Weak spot</b>: on projects the court refused, the agent concludes “not feasible” in only 40–60 % of cases; it leans
towards “feasible with conditions”. This is the first prompt fix to make.</li>
<li>The MÖD cases are much harder than the 14 case studies, which saturate (verdict ≈ 1): they are the benchmark to use
for the next decisions.</li>
<li>Cost of the agent answers in this report: about ${fmt(total_cost, 2)} (excluding the judge and case generation).</li>
</ul></div>

<h2>1. The system under test</h2>
<h3>1.1 Offline corpus</h3>
<table>
<tr><th>Source</th><th>Content</th><th>Processing</th></tr>
<tr><td>Statutes (Riksdagen open data)</td><td>15 consolidated texts: Planning and Building Act (PBL) and Ordinance (PBF),
Environmental Code (MB), Land Code (JB), Real Property Formation Act, Joint Facilities Act, water and sewage (LAV, FMH),
Cultural Environment Act…</td><td>One chunk per section (§), chapters and lettered sections handled</td></tr>
<tr><td>Websites of the 290 municipalities (Wikidata)</td><td>Pages on building permits, sewage, fees, plan requests,
comprehensive plans, detailed plans + linked PDFs (plan descriptions, plan maps, fee schedules)</td><td>Crawl honouring
robots.txt (1 request/s), PyMuPDF text, local OCR (EasyOCR) for scanned PDFs</td></tr>
<tr><td>Detailed plan registry</td><td>{plans_n} plans: status, date of legal force, plan map / plan description,
extracted plan provisions (building area, ridge height, plot size…)</td><td>Rule-based, no LLM</td></tr>
</table>
<p>In total 344,199 passages (chunks) in 31,497 documents, 275 municipalities represented. Retrieval: local embeddings
<code>snowflake-arctic-embed-l-v2</code> (chosen on a retrieval benchmark: 0.92 recall@5) + BM25 on Swedish stems
(SQLite FTS5), RRF fusion, municipality filter; all on disk (SQLite + vectors on the GPU, ~0.1 s per search).</p>

<h3>1.2 Agent loop</h3>
<div class="flow"><span>Question (English)</span><b>→</b><span>Exploration turns (<i>explore</i> effort): tools in
parallel</span><b>→</b><span>answer_ready</span><b>→</b><span>Final answer (<i>answer</i> effort),
streamed</span><b>→</b><span>Clickable [n] citations</span></div>
<table>
<tr><th>Tool</th><th>Role</th></tr>
<tr><td><code>find_kommun</code></td><td>Place → municipality, and what the corpus holds for it</td></tr>
<tr><td><code>search</code></td><td>Hybrid search (semantic + Swedish BM25) over the statutes and/or a municipality</td></tr>
<tr><td><code>grep</code></td><td>Exact search: plan numbers, property designations, “nockhöjd”, amounts</td></tr>
<tr><td><code>list_documents</code> / <code>read</code></td><td>List a municipality's documents, read a passage or a document</td></tr>
<tr><td><code>law_section</code></td><td>Exact text of a section (“PBL 9 kap. 4 §”)</td></tr>
<tr><td><code>plans</code> / <code>plan_rules</code></td><td>Detailed plan registry and each plan's provisions as a table</td></tr>
<tr><td><code>view_pdf_page</code></td><td>Image of a PDF page for the model (plan map)</td></tr>
</table>
<p>Every tool output carries passage identifiers (<code>[c:id]</code>); the answer must cite them for every rule, number
or deadline. Two reasoning-effort settings: <b>explore</b> for the turns where the agent searches, <b>answer</b> for the
final answer. They are the main subject of this benchmark.</p>

<h2>2. How the benchmark was built</h2>
<h3>2.1 The 14 case studies</h3>
<p>Written by hand from corpus documents and user feedback (questions such as “building permit procedure in
Vallentuna”, “maximum height in Veda”, sewage, infrastructure). Three families: real projects on detailed plans
(Kumla-Stensta, Mörby backe, Kristineberg), national + local rules (Attefall houses, shoreline protection, eco-village on
farmland, private sewage, plot subdivision, demolition…), procedures (advance rulings, förhandsbesked). Each case has
accepted verdicts, 3–5 key points, and <b>expected evidence</b> (a statute section or an exact excerpt of a municipal
document) that the agent must have consulted.</p>

<h3>2.2 Cases drawn from real rulings (MÖD)</h3>
<ol>
<li><b>Collection</b>: {len(rulings)} rulings of Mark- och miljööverdomstolen since 2011 (lagen.nu, whose robots.txt allows
the ruling pages); {relevant} on our topics (building permits, detailed plans, shoreline protection, advance rulings,
sewage…).</li>
<li><b>Transformation</b> by the LLM: the facts become the question, asked as the applicant would <i>before</i> the
decision (without the outcome or the reasoning); the actual outcome gives the accepted verdicts; the court's reasons give
the key points; the statutes applied give the expected evidence.</li>
<li><b>Checks</b>: purely procedural rulings dropped (standing, sanctions); questions that mention the court dropped;
evidence = an exact phrase of at least 5 words of the <b>current</b> statute text (PBL chapter 9 was renumbered by SFS
2025:974 and some wording changed); rulings with no current provision kept without expected evidence (scored on verdict
and key points).</li>
<li><b>Sample</b>: {len(sample)} cases drawn at random (fixed seed), balanced between negative, positive and open
outcomes, all with expected evidence.</li>
</ol>
<p>Split of the {len(caselaw)} generated cases by accepted verdicts: {verdict_split}. Generation cost: ~$0.55.</p>

<h3>2.3 Example cases</h3>
{examples}

<h2>3. How answers are scored</h2>
<table>
<tr><th>Measure</th><th>Definition</th><th>How</th></tr>
<tr><td>Verdict</td><td>The answer's verdict (feasible / with conditions / not feasible / unclear) is among the accepted
verdicts</td><td>LLM judge</td></tr>
<tr><td>Key points</td><td>Each expected point scored 0 (missing or contradicted), 1 (partial), 2 (clear); scaled to 0–1</td>
<td>LLM judge</td></tr>
<tr><td>Evidence</td><td>Share of the expected evidence (statute section, document excerpt) that the agent <i>actually saw</i>
in its tool outputs</td><td>Automatic, no LLM</td></tr>
<tr><td>Grounding</td><td>Share of the answer's factual claims supported by the text of the sources it cites</td>
<td>Second LLM judge, with the full source text</td></tr>
<tr><td>Unsupported claims</td><td>Rules or numbers found neither in the reference nor in the cited sources</td><td>LLM judge</td></tr>
<tr><td>Latency, 1st token, cost</td><td>Total time, time to the first word of the streamed answer, OpenRouter cost</td>
<td>Measured</td></tr>
</table>
<div class="warn"><b>Limits of the evaluation.</b> The judge is the same model as the agent (GPT-6 Luna, medium effort):
cheap but possibly lenient; its scores are for <i>comparing</i> settings, not absolute values. The key points of the MÖD
cases are written by the LLM from the ruling: a point can be finer than what a good advisor would say. The judge gets the
text of the cited sources so that a correct fact missing from the reference is not penalised. Each configuration was run
2 to 4 times: the pass-to-pass variance is given below. Cases run 3 in parallel: latencies include some contention.</div>

<h2>4. Results</h2>
<h3>4.1 History on the 14 cases (5-municipality sub-corpus, successive versions)</h3>
<table><tr><th>Version</th><th>Key points</th><th>Evidence</th><th>Grounding</th><th>Latency</th><th>1st token</th>
<th>Cost</th></tr>
{history}
</table>
<p>v1 → v2: citeable identifiers in every tool output and a “no claim without a source read” rule (grounding 0.68 →
0.86). v2 → v3/v4: parallel tools, <code>answer_ready</code>, streamed answer and <i>low</i> exploration effort: latency
halved, but lower quality. Hence the matrix below.</p>

<h3>4.2 Effort matrix (full corpus on disk)</h3>
<h3>14 case studies</h3>
{table14}
<h3>{len(sample)} MÖD cases</h3>
{table_mod}
<p>Best value of each column in green. n = number of answers (cases × passes).</p>
{quality_chart and '<h3>4.3 Quality on the MÖD cases</h3>' + quality_chart}
<h3>4.4 Quality / speed / cost trade-off</h3>
{tradeoff}
{cost_chart}
{duel}
<h3>4.5 Verdict by actual outcome (MÖD cases)</h3>
{verdicts_mod}
<p>In brackets: number of answers. “Open outcome” = remitted or fact-dependent decision (accepted verdicts: with
conditions / unclear).</p>
{'<h3>4.6 Variance between passes</h3><ul>' + spread + '</ul><p>Typical gap between two identical passes: a few hundredths; a difference below ~0.05 between configurations is not significant.</p>' if spread else ''}

{answer_excerpt}

<h2>5. Reading the results</h2>
<ul>
<li><b>Exploration effort matters, answer effort does not.</b> At <i>low</i>, the agent makes ~12 tool calls per question;
at <i>medium</i>, ~20 (14 cases) to ~26 (MÖD), better targeted: it more often reads the decisive statute section and the
relevant municipal document. Evidence seen: 0.84 → 0.88 on the 14 cases, 0.53 → 0.70 on the MÖD cases; grounding 0.69 →
0.79 on the MÖD cases; key points +0.05 to +0.07, beyond the pass-to-pass spread (~0.04). A <i>high</i> final answer
changes neither key points nor evidence, and adds 7 s.</li>
<li><b>The price</b>: on the MÖD cases, latency 26 s → 43 s (first word of the answer: 19 s → 35 s), cost $0.0036 →
$0.0086 per question. On the 14 cases, only +3 s. At 1,000 questions a month: ~$9 instead of ~$4.</li>
<li><b>Verdict calibration</b>: on the MÖD cases, the verdict is right for 90 % of open outcomes and ~75 % of granted
projects, but only 40–60 % of refused projects: the agent answers “feasible with conditions” where the court said no
(often: productive farmland, shoreline protection without a special reason, need for a detailed plan). More exploration
reinforces this caution (more conditions found → “with conditions”), hence a slightly lower overall verdict score at
<i>medium</i> (0.75 → 0.70) despite better evidence.</li>
<li><b>The MÖD cases are harder</b> than the 14 case studies: fine legal facts (“productive” land, “substantial” change of
use, LIS conditions…) and key points written from the Court's full reasoning. The 14 cases saturate (verdict ≥ 0.96
everywhere) and no longer separate the settings.</li>
<li><b>Grounding</b>: 79–89 % of claims are supported by the cited sources; the rest is mostly general legal knowledge
of the model, not re-read in the corpus.</li>
</ul>

<h2>6. Recommendations and next steps</h2>
<ul>
<li><b>Default app setting</b>: <i>medium</i> exploration, <i>medium</i> answer; keep <i>low</i> exploration as a “fast”
mode (≈ 25 s). A <i>high</i> answer is not worth its cost.</li>
<li><b>Verdict prompt</b>: state explicitly that an unmet substantive condition (productive farmland without an essential
public interest, shoreline protection without a special reason, a project that requires a detailed plan) makes the
project “not feasible as described”, and do not turn every procedural requirement into “with conditions”. Measure the
effect on the refused MÖD cases.</li>
<li><b>Benchmark</b>: use the {len(caselaw)} MÖD cases (samples of 50, 2 passes) for every prompt or model change; add
“plan map only” cases now that the scanned PDFs are OCR'd, once map reading is in place.</li>
<li><b>Corpus</b>: the OCR of the 769 scanned PDFs is done (their text enters the index at the next rebuild); next, link
each plan code to its area on the map (vision model) and each property to its applicable plan (municipal WMS /
Lantmäteriet).</li>
<li><b>Judge</b>: have a domain expert review a sample of scores to calibrate the LLM judge.</li>
</ul>

<h2>Appendix: reproduce</h2>
<p><code>python -m corpus.caselaw</code> (MÖD rulings) · <code>python -m agentic.cases_from_caselaw</code> (cases) ·
<code>python -m agentic.bench --systems agent --store disk --explore-effort medium --effort medium --cases-file
cases_caselaw.jsonl --sample 50 --repeats 2 --workers 3</code> · <code>python -m agentic.grounding &lt;results&gt;</code> ·
<code>python -m agentic.report --lang en</code>. Result files used: {files}.</p>"""
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
<p>Au total 344 199 passages (chunks) dans 31 497 documents, 275 communes représentées. Recherche : embeddings locaux
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
<table><tr><th>Version</th><th>Points clés</th><th>Preuves</th><th>Ancrage</th><th>Latence</th><th>1er token</th>
<th>Coût</th></tr>
{history}
</table>
<p>v1 → v2 : identifiants citables dans toutes les sorties d'outils et règle « pas d'affirmation sans source lue »
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
<li><b>Corpus</b> : l'OCR des 769 PDF scannés est fait (leur texte entre dans l'index à la prochaine reconstruction) ;
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


def main() -> None:
    import argparse

    global LANG
    parser = argparse.ArgumentParser(description="PDF report of the agent benchmark")
    parser.add_argument("--lang", choices=["en", "fr", "both"], default="en")
    args = parser.parse_args()
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    browser = next((b for b in BROWSERS if Path(b).exists()), None) or shutil.which("chrome") or shutil.which("msedge")
    for LANG in (["fr", "en"] if args.lang == "both" else [args.lang]):
        out_html = DOC_DIR / f"{OUTPUT_NAMES[LANG]}.html"
        out_pdf = DOC_DIR / f"{OUTPUT_NAMES[LANG]}.pdf"
        out_html.write_text(build_html(), encoding="utf-8")
        if browser is None:
            print(f"No Chrome/Edge found: open {out_html} and print it to PDF")
            continue
        subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                        f"--print-to-pdf={out_pdf}", out_html.as_uri()], check=True, capture_output=True, timeout=180)
        print(f"{out_pdf} ({out_pdf.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()

"""
What the benchmark tested and how well each solution did, for the Benchmark tab (issue #116): the result files of
agentic.bench (data/agentic/bench-*.json and the missing-info baseline, versioned, so staging and production have
them) grouped into studies, each a question with the configurations it compared and their success rate per benchmark
set. Written for a reader without the project's context; the PDF reports of 2026-10-25 (agentic.report) give the full
analysis.

    study       a comparison run at one time under one protocol (same prompt generation, same judge)
    config      one solution in it: classic RAG or the agent, its reasoning efforts, a tool left out, a model, a prompt
    cell        a config on a set: answers, success rate, key points, evidence, grounding, time, cost

Success rate: the share of answers whose verdict is right on the verdict sets; the key-point score on the explain /
propose / develop sets, which have no verdict; on the missing-information sets, the share of questions where the agent
asked when it had to and answered when it could. No LLM call, no corpus needed: only the stored rows.
"""

import json
import re
from collections import defaultdict
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from statistics import mean

from corpus.common import RESULTS_ROOT

RESULTS_DIR = RESULTS_ROOT / "agentic"  # agentic.bench.RESULTS_DIR (not imported: it loads the corpus modules)

FILE = re.compile(r"bench-(?P<stamp>\d{8}-\d{6})-(?P<systems>[a-z-]+?)-(?P<answer>low|medium|high)"
                  r"(?:-explore-(?P<explore>low|medium|high|same))?(?:-cases_(?P<set>[a-z_]+?))?"
                  r"(?:-no-(?P<off>[a-z_-]+?))?(?:-x-(?P<label>[\w.-]+))?\.json$")
# The missing-info eval's reference run on `dev`, before the agent asked (#93): bench --baseline writes it
BASELINE = re.compile(r"missing-info-baseline-[a-z-]*?-(?P<answer>low|medium|high)-(?P<day>\d{8})\.json$")

# The benchmark sets: name, what they test, and the measure their success rate uses
SETS = {
    "cases14": ("14 case studies", ("Hand-written feasibility questions on real projects in 5 municipalities: can I "
                                    "build this here? The reference is the accepted verdict and 3-5 key points."),
                "verdict"),
    "caselaw": ("Court rulings (MÖD)", ("Real appeals decided by the Land and Environment Court of Appeal, asked as "
                                        "the applicant would have before the decision. The reference is the court's "
                                        "outcome."), "verdict"),
    "plans": ("Plan-map questions", ("Questions about one property whose answer is only on the detailed plan's map "
                                     "(zone codes and values read by a vision model)."), "verdict"),
    "tasks": ("Explain / propose / develop", ("Hand-written questions beyond yes or no: explain a procedure, propose "
                                              "where a project could go, develop a project idea. No verdict: scored "
                                              "on key points."), "points"),
    "generated": ("Explain / propose / develop (generated)", ("The same three kinds of question, drafted from corpus "
                                                              "documents by another model family and checked against "
                                                              "their sources."), "points"),
    "missing_ask": ("Questions missing a fact", ("The answer turns on something only the user knows (where, how big, "
                                                 "what for): the right move is to ask."), "ask"),
    "missing_answer": ("Complete questions", "Nothing is missing: the right move is to answer, not to ask.", "ask"),
}
SET_ORDER = list(SETS)

MEASURES = [
    {"key": "success", "name": "Success rate",
     "text": "Verdict sets: share of answers whose verdict (feasible, feasible with conditions, not feasible, unclear) "
             "is one the reference accepts. Explain / propose / develop: the key-point score. Missing information: "
             "share of questions where the agent asked when it had to and answered when it could."},
    {"key": "points", "name": "Key points",
     "text": "Each expected point scored 0 (missing or wrong), 1 (partly) or 2 (clearly made), scaled to 0-100 %. "
             "Scored by an LLM judge."},
    {"key": "evidence", "name": "Evidence seen",
     "text": "Share of the deciding sources (statute section, plan map, municipal page) the system actually read. "
             "Measured automatically."},
    {"key": "grounded", "name": "Grounding",
     "text": "Share of the answer's claims supported by the sources it cites, checked by a second judge."},
    {"key": "seconds", "name": "Time", "text": "Seconds until the whole answer is written; first word in brackets."},
    {"key": "cost", "name": "Cost", "text": "Model cost of one answer on OpenRouter (the judges excluded)."},
]

SYSTEMS = {
    "rag": ("Classic RAG", ("One search on the question, then one answer from the 20 passages found. It cannot "
                            "open a document, list plans or look at a map.")),
    "agent": ("Tool-using agent", ("Works in turns: searches, reads documents and statute sections, lists plans, "
                                   "looks at a crop of the plan map, then writes the answer with citations.")),
}
OFF = {"view_map_area": "without the map crop tool",
       "view_map_area-view_pdf_page": "without any map reading"}
LABELS = {  # the labelled runs, in the order they were made
    "base": "Starting prompt",
    "v2": "+ a recipe per kind of question and a site checklist",
    "mimo-flash": "MiMo v2.6 Flash as the model instead of GPT-6 Luna",
    "v3": "+ the “complete answer” instruction",
    "toolfix": "+ tool and data fixes",
    "filters": "+ document filters in search and grep",
    "baseline": "Before: the agent always answered",
    "run6": "After: the agent asks with a question card",
}
MISSING = ("missing_ask", "missing_answer")

STUDIES = [
    {"key": "rag-vs-agent", "start": "20261007-211220", "end": "20261019-000000", "labels": False,
     "sets": ("cases14", "caselaw", "plans"), "in_use": "agent-medium-medium",
     "title": "Classic RAG or a tool-using agent, and how much should the model think?",
     "about": "Same model (GPT-6 Luna) and same corpus for every system; each answer judged by GPT-6 Luna. The agent "
              "was tried with more or less reasoning while it explores (searching, reading) and while it writes the "
              "answer, and on the plan-map questions without its map tools.",
     "reading": "The agent wins wherever the deciding rule has to be found: on the court rulings and the plan maps "
                "the classic RAG's single search rarely reaches the statute section or the map that decides. The "
                "RAG is about twice as fast and four times cheaper. Exploring with medium rather than low effort "
                "covers more key points; a high-effort final answer adds nothing measurable. Without map reading "
                "the agent loses most of its edge on plan-map questions."},
    {"key": "beyond-verdict", "start": "20261019-000000", "end": "20261021-000000", "labels": False,
     "sets": ("tasks", "generated", "cases14", "caselaw"), "in_use": "agent-medium-medium",
     "title": "Beyond yes or no: explaining, proposing, developing",
     "about": "Questions without a verdict: explain a procedure, propose where a project could go, develop a project "
              "idea. Judged by MiMo v2.6 Flash, another model family, on key points that each quote a source. The "
              "agent's new prompt was also re-run on two verdict sets to check it did not lose ground there.",
     "reading": "The agent covers more of the expected points than the classic RAG on all three kinds of question, "
                "most clearly when developing a project idea; on the verdict sets it scores as before."},
    {"key": "optimisation", "start": "20261021-000000", "end": "20261101-000000", "labels": True,
     "sets": ("cases14", "tasks", "generated"), "in_use": "x-filters",
     "title": "Improving the agent: prompt, model, tools",
     "about": "The agent (exploration and answer at medium effort) on the same development cases after each change, "
              "in order. Judged by MiMo v2.6 Flash, so the MiMo run is judged by its own model family.",
     "reading": "The “complete answer” instruction, the tool fixes and the document filters each raised the key "
                "points a little; differences under ~5 points are within the run-to-run noise. MiMo Flash scored "
                "highest, but it is judged by its own family and took two to four times longer: the app kept GPT-6 "
                "Luna with the latest prompt and tools."},
    {"key": "missing-info", "start": "20261101-000000", "end": "99999999", "labels": True,
     "sets": MISSING, "in_use": "x-run6",
     "title": "Does the agent ask when the question leaves out what the answer depends on?",
     "about": "50 questions missing a fact only the user knows and 50 complete ones, half in Swedish, half in English, "
              "run twice. GPT-6 Luna at medium effort, judged by GPT-6 Luna.",
     "reading": "Before, the agent guessed: it answered half of the questions it should have asked about. With the "
                "question card it asks when a fact is missing and still answers complete questions directly."},
]


def _mean(values) -> float | None:
    values = [v for v in values if v is not None]
    return round(mean(values), 4) if values else None


def _day(stamp: str) -> str:
    """20261007-211220 -> 2026-10-07"""
    return f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}"


def parse_name(name: str) -> dict | None:
    """What a result file's name says: stamp, answer and explore effort, set, tool left out, label. None for any other
    file."""
    if match := FILE.search(name):
        return {"stamp": match["stamp"], "answer": match["answer"], "explore": match["explore"] or match["answer"],
                "set": match["set"] or "cases14", "off": match["off"] or "", "label": match["label"] or ""}
    if match := BASELINE.search(name):
        return {"stamp": f"{match['day']}-000000", "answer": match["answer"], "explore": match["answer"],
                "set": "missing_info", "off": "", "label": "baseline"}
    return None


def _config(run: dict, row: dict, study: dict) -> tuple[str, str, str, str]:
    """(key, name, settings, description) of the configuration a row belongs to."""
    system = row.get("system") or "agent"
    name, description = SYSTEMS.get(system, (system, ""))
    settings = f"exploration {run['explore']} · answer {run['answer']}"
    if study["labels"]:
        model = (row.get("model") or "").split("/")[-1]
        return (f"x-{run['label']}", LABELS.get(run["label"], f"Run “{run['label']}”"),
                settings + (f" · {model}" if model else ""), description)
    if system == "rag":
        return f"rag-{run['answer']}", name, f"answer effort {run['answer']}", description
    off = run["off"]
    return (f"agent-{run['explore']}-{run['answer']}" + (f"-no-{off}" if off else ""), name,
            settings + (f" · {OFF.get(off, 'without ' + off)}" if off else ""), description)


def _cell(rows: list[dict], measure: str, files: list[str]) -> dict:
    verdicts = [float(r["verdict_ok"]) for r in rows if r.get("verdict_ok") is not None]
    asks = [float(r["ask_ok"]) for r in rows if r.get("ask_ok") is not None]
    points = _mean(r.get("points") for r in rows)
    verdict = round(mean(verdicts), 4) if verdicts else None
    success = {"verdict": verdict, "ask": round(mean(asks), 4) if asks else None}.get(measure, points)
    return {
        "n": len(rows), "success": success, "verdict": verdict, "points": points,
        "evidence": _mean(r.get("evidence") for r in rows), "grounded": _mean(r.get("grounded") for r in rows),
        "unsupported": _mean(r.get("unsupported") for r in rows), "tools": _mean(r.get("tool_calls") for r in rows),
        "seconds": _mean(r.get("seconds") for r in rows), "first": _mean(r.get("first_token_s") for r in rows),
        "cost": _mean(r.get("cost") for r in rows), "files": sorted(set(files)),
    }


def _rank(cell: dict) -> tuple:
    """Better first: success rate, then key points, then the lower cost."""
    return (cell.get("success") or 0, cell.get("points") or 0, -(cell.get("cost") or 0))


def _best(candidates: list[tuple[str, dict]]) -> str | None:
    best = None
    for key, cell in candidates:
        if best is None or _rank(cell) > _rank(best[1]):
            best = (key, cell)
    return best[0] if best else None


def summarise(files: list[tuple[str, list[dict]]]) -> dict:
    """The studies from (file name, rows) pairs. Files that match no study or no name pattern are left out; so are
    rows with an error (a provider failure, not an answer)."""
    studies = []
    for study in STUDIES:
        rows_by: dict[tuple[str, str], list[dict]] = defaultdict(list)
        files_by: dict[tuple[str, str], list[str]] = defaultdict(list)
        configs: dict[str, dict] = {}
        stamps: list[str] = []
        for name, rows in files:
            run = parse_name(name)
            if not run or not study["start"] <= run["stamp"] < study["end"] or bool(run["label"]) != study["labels"]:
                continue
            for row in rows:
                if row.get("error"):
                    continue
                set_key = f"missing_{row.get('expect')}" if run["set"] == "missing_info" else run["set"]
                if set_key not in study["sets"]:
                    continue
                key, title, settings, description = _config(run, row, study)
                config = configs.setdefault(key, {"key": key, "name": title, "settings": settings,
                                                  "about": description, "system": row.get("system") or "agent",
                                                  "first_run": run["stamp"]})
                config["first_run"] = min(config["first_run"], run["stamp"])
                rows_by[(key, set_key)].append(row)
                files_by[(key, set_key)].append(name)
                stamps.append(run["stamp"])
        if not configs:
            continue
        sets = [s for s in study["sets"] if any(k[1] == s for k in rows_by)]
        ordered = sorted(configs.values(), key=lambda c: (c["first_run"] if study["labels"] else "",
                                                          c["system"] != "rag", "-no-" in c["key"], c["settings"]))
        for config in ordered:
            config["results"] = {
                set_key: _cell(rows_by[(config["key"], set_key)], SETS[set_key][2], files_by[(config["key"], set_key)])
                for set_key in sets if (config["key"], set_key) in rows_by}
            del config["first_run"]
        best_by_set = {set_key: best for set_key in sets
                       if (best := _best([(c["key"], c["results"][set_key]) for c in ordered
                                          if set_key in c["results"]]))}
        # The best configuration: among those run on every set of the study, the best mean success rate
        for config in ordered:
            if len(config["results"]) == len(sets):
                cells = list(config["results"].values())
                config["overall"] = {key: _mean(c[key] for c in cells) for key in ("success", "points", "cost")}
        best = _best([(c["key"], c["overall"]) for c in ordered if "overall" in c])
        studies.append({
            "key": study["key"], "title": study["title"], "about": study["about"], "reading": study["reading"],
            "period": [_day(min(stamps)), _day(max(stamps))], "sets": sets, "configs": ordered,
            "best_by_set": best_by_set, "best": best,
            "in_use": study["in_use"] if study["in_use"] in configs else None,
        })
    used = {s for study in studies for s in study["sets"]}
    return {
        "sets": [{"key": key, "name": SETS[key][0], "about": SETS[key][1], "measure": SETS[key][2]}
                 for key in SET_ORDER if key in used],
        "measures": MEASURES,
        "studies": studies,
    }


@lru_cache(maxsize=4)
def _cached(stamp: tuple[tuple[str, float], ...], directory: str) -> dict:
    files = [(name, json.loads((Path(directory) / name).read_text(encoding="utf-8"))) for name, _ in stamp]
    return {**summarise(files), "built": datetime.now(UTC).isoformat(timespec="seconds"), "files": len(files)}


def summary(directory: Path = RESULTS_DIR) -> dict:
    """summarise() over the result files on disk, recomputed only when one is added or changed (< 1 s for all)."""
    paths = (sorted([*directory.glob("bench-*.json"), *directory.glob("missing-info-baseline-*.json")])
             if directory.is_dir() else [])
    return _cached(tuple((path.name, path.stat().st_mtime) for path in paths), str(directory))

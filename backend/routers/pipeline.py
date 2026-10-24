"""
Pipeline view: how the searchable corpus is built and how well each step works, written for a reader without the
project's context (each step says what it does and how it is measured, then its numbers, then details on demand).
Only reads the files the steps write. Separate from the Benchmark view, which grades the agent's answers end to end.

- GET /api/pipeline   {corpus, steps: [{id, step, title, what, measure, status, flow, tiles, sections}]}
  sections: {title, summary, text?, table?: {columns, rows, highlight?, limit?, search?}, bars?: [{label, value,
  hint?}], meter?: {value, total, label}, checks?: [{section, level, message, examples, count}], examples?: [...]}

Sources: data/corpus/check.json (corpus.check), raw/web/*/manifest.jsonl done lines (corpus.crawl),
data/agentic/coverage-*.json (agentic.coverage), data/corpus/pdf_filter/ + corpus/pdf_filter_eval.jsonl
(corpus.pdf_filter), data/eval/ocr-*.json (corpus.ocr_bench), raw/web/*/ocr/ + ocr_jobs.jsonl (corpus.ocr),
data/eval/<date>.json (localrag.eval), data/agentic/replay-*.json (agentic.replay), plans.jsonl via check.json.
"""

import json
import random
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import median

from fastapi import APIRouter, Depends

from corpus.common import DATA_DIR, MUNICIPALITIES_PATH, RESULTS_ROOT, WEB_DIR, read_jsonl
from corpus.ocr import ENGINE_FAMILY as OCR_ENGINE
from dependencies import get_current_user
import models

router = APIRouter()

AGENTIC_DIR = RESULTS_ROOT / "agentic"
EVAL_DIR = RESULTS_ROOT / "eval"

DOC_TYPES = {
    "detaljplan": "Detaljplan: detailed development plan (plan map, description, consultation documents, studies)",
    "oversiktsplan": "Översiktsplan: comprehensive plan of the whole kommun",
    "bygglov": "Bygglov: building permits (how to apply, rules, forms)",
    "strandskydd": "Strandskydd: shore protection (building near water)",
    "avlopp": "Avlopp: water and sewage (private sewage permits)",
    "taxa": "Taxa: fee schedules",
    "other": "Other: decisions, investigations, guidance kept by the filter",
}
FILTER_PATHS = {
    ("rule", True): "Kept: the title or file name names a planning document",
    ("model", True): "Kept: the classifier is sure it is about planning or building",
    ("rule+llm", False): "Removed: a keyword rule flagged it and the LLM agreed",
    ("rule+llm", True): "Kept: a keyword rule flagged it, the LLM disagreed",
    ("model+llm", False): "Removed: the classifier flagged it and the LLM agreed",
    ("model+llm", True): "Kept: the classifier flagged it, the LLM disagreed",
    ("uncertain+llm", False): "Removed: the classifier was unsure, the LLM said off topic",
    ("uncertain+llm", True): "Kept: the classifier was unsure, the LLM said relevant",
    ("review", False): "Removed after reading by hand",
    ("review", True): "Kept after reading by hand",
}
PLAN_STATUS = {
    "in_force": "In force (laga kraft)", "in_progress": "Being drawn up", "consultation": "In consultation (samråd)",
    "review": "In review (granskning)", "adopted": "Adopted, not yet in force", "unknown": "Status not found",
}
TOOLS = {
    "search": "finds passages by meaning and by keywords",
    "grep": "finds an exact word or pattern in a kommun's documents or in the laws",
    "read": "opens a passage or a whole document",
    "list_documents": "lists a kommun's documents by title",
    "law_section": "opens a law section, e.g. PBL 9 kap. 31 §",
    "find_kommun": "tells which kommun a place name belongs to",
    "plans": "lists a kommun's plans from the plan registry",
    "plan_rules": "gives the coded rules of one plan",
}


def _load(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _date(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")


def _pct(value, digits: int = 0) -> str:
    return "–" if value is None else f"{100 * value:.{digits}f} %"


def _s(value) -> str:
    return "–" if value is None else f"{value:.2f}" if value < 10 else f"{value:.0f}"


def _last_line(path: Path) -> str:
    """The done line of a manifest without reading the file (some have 10k lines)."""
    with path.open("rb") as handle:
        handle.seek(0, 2)
        handle.seek(max(0, handle.tell() - 4096))
        return handle.read().decode("utf-8", errors="replace").strip().splitlines()[-1]


def _section(title: str, summary: str = "", **content) -> dict:
    return {"title": title, "summary": summary, **content}


CHECK_ORDER = {"ERROR": 0, "WARN": 1, "INFO": 2, "OK": 3}


def _checks(check: dict, *sections: str) -> tuple[dict, int]:
    """corpus.check lines of some of its sections ("Crawl", "Documents"...) -> (a detail section, errors)."""
    lines = sorted((line for line in check.get("lines") or [] if line["section"].split(" (")[0] in sections),
                   key=lambda line: CHECK_ORDER[line["level"]])
    counts = Counter(line["level"] for line in lines)
    run = (datetime.fromisoformat(check["checked_at"]).astimezone().strftime("%Y-%m-%d %H:%M")
           if check.get("checked_at") else "never")
    section = _section("Automatic checks", f"{counts['ERROR']} error(s), {counts['WARN']} warning(s), "
                       f"{counts['OK']} passed (corpus.check, {run})",
                       text="Each line states what should hold; the icon says whether it does (error, warning, "
                            "information, passed). Click a line to see the cases behind it.",
                       checks=lines)
    return section, counts["ERROR"]


def crawl_step(check: dict) -> dict:
    names = {m["code"]: m["short_name"] for m in json.loads(MUNICIPALITIES_PATH.read_text(encoding="utf-8"))}
    done = {}
    for manifest in WEB_DIR.glob("*/manifest.jsonl"):
        line = _last_line(manifest)
        if '"done": true' in line:
            done[manifest.parent.name] = json.loads(line)
    pages = sum(d.get("pages", 0) for d in done.values())
    pdfs = sum(d.get("pdfs", 0) for d in done.values())
    empty = sorted(names.get(c, c) for c, d in done.items() if not d.get("pages") and not d.get("pdfs"))
    at_cap = sorted(names.get(c, c) for c, d in done.items() if d.get("pdfs", 0) >= (d.get("max_pdfs") or 1e9))
    rows = []
    for code, d in sorted(done.items(), key=lambda kv: -kv[1].get("pdfs", 0)):
        notes = []
        if not d.get("pages") and not d.get("pdfs"):
            notes.append("site answered nothing")
        if d.get("pdfs", 0) >= (d.get("max_pdfs") or 1e9):
            notes.append(f"PDF limit reached ({d['max_pdfs']:,})")
        if d.get("max_pdfs") == 30:
            notes.append("old crawl kept: site unreachable on the last one")
        if (d.get("revisit") or {}).get("pdfs_added"):
            notes.append(f"+{d['revisit']['pdfs_added']} PDFs on the revisit")
        rows.append([names.get(code, code), d.get("pages", 0), d.get("pdfs", 0), f"{d.get('pdf_mb', 0) / 1000:.1f}",
                     d.get("requests", 0), "; ".join(notes)])
    skipped = sum((d.get("skipped") or {}).get("off_topic", 0) for d in done.values())

    coverage_runs = sorted(AGENTIC_DIR.glob("coverage-*.json"))
    history = []
    for path in coverage_runs:
        total = (_load(path) or {}).get("total", {})
        history.append([path.stem.removeprefix("coverage-"), total.get("plans"), total.get("municipalities"),
                        _pct(total.get("plans_with_a_pdf")), _pct(total.get("plans_complete"))])
    latest = _load(coverage_runs[-1]) if coverage_runs else None
    total = (latest or {}).get("total", {})
    by_kommun = [[name, k["plans"], _pct(k["plans_with_a_pdf"] / max(k["plans"], 1)),
                  _pct(k["pdfs_found"] / max(k["pdfs"], 1))]
                 for name, k in sorted(((latest or {}).get("by_kommun") or {}).items())]
    unmeasured = [f"{name}: {why}" for name, why in sorted(((latest or {}).get("unmeasured") or {}).items())]

    problems = len(empty) + len(at_cap)
    checks, _ = _checks(check, "Crawl")
    return {
        "id": "crawl", "step": 1, "title": "Collect: crawl the kommun websites",
        "what": "A crawler visits the website of each of Sweden's 290 kommuner, one request per second, and keeps "
                "the pages about planning and building plus the PDFs they link to (plans, permit guidance, fees...). "
                "Limits per kommun: 1,000 pages, 3,000 PDFs, 40 MB per PDF, 15,000 requests.",
        "measure": "Coverage: for a sample of kommuner we fetch the list of plans in force that the kommun publishes "
                   "and count how many of those plans have their PDFs in our corpus. It shows what the crawl misses, "
                   "which no other test can see.",
        "status": {"level": "warning" if problems else "good",
                   "label": "Mostly complete" if problems else "Complete",
                   "note": f"{len(empty)} kommuner without data, {len(at_cap)} at the PDF limit"},
        "flow": {"value": pdfs, "caption": f"PDFs and {pages:,} web pages from {len(done) - len(empty)} kommuner"},
        "tiles": [
            {"label": "Kommun websites with data", "value": f"{len(done) - len(empty)} / {len(names)}"},
            {"label": "Web pages kept", "value": pages},
            {"label": "PDFs downloaded", "value": pdfs},
            {"label": "Published plans found", "value": _pct(total.get("plans_with_a_pdf")),
             "hint": f"plans with at least one PDF in the corpus, {total.get('plans', 0)} plans of "
                     f"{total.get('municipalities', 0)} kommuner checked"},
        ],
        "sections": [
            _section("Coverage of the plans the kommuner publish",
                     f"{_pct(total.get('plans_with_a_pdf'))} of the checked plans have at least one PDF in the corpus, "
                     f"{_pct(total.get('plans_complete'))} have all of them",
                     text="Before the large crawl of October 2026 the crawler stopped at 30 PDFs per kommun: a quarter "
                          "of the plans were found. Kommuner whose plans sit in a map or search application cannot be "
                          "checked this way (listed below the table).",
                     table={"columns": ["Run", "Plans checked", "Kommuner", "At least one PDF", "All PDFs"],
                            "rows": history, "highlight": len(history) - 1}),
            _section("Coverage per kommun (latest run)", f"{len(by_kommun)} kommuner measurable, {len(unmeasured)} not",
                     table={"columns": ["Kommun", "Plans checked", "At least one PDF", "PDFs found"], "rows": by_kommun},
                     examples=unmeasured),
            _section("Every kommun crawled", f"{len(rows)} kommuner; problems: "
                     + (", ".join(empty + at_cap) if problems else "none"),
                     table={"columns": ["Kommun", "Web pages", "PDFs", "GB of PDFs", "Requests", "Notes"],
                            "rows": rows, "limit": 10, "search": True}),
            _section("Links skipped as obvious noise", f"{skipped:,} PDF links",
                     text="Only unmistakable noise is skipped at this stage (annual reports, alcohol licences, estate "
                          "notices, school health...). Everything else is downloaded and judged by the filter (step 2), "
                          "which never removes a document without a second opinion."),
            checks,
        ],
    }


def filter_step() -> dict:
    from corpus.pdf_filter import DECISIONS_PATH, FEATURES_PATH, evaluate

    base = {"id": "filter", "step": 2, "title": "Filter: remove the PDFs that are not about building",
            "what": "A kommun website also links documents unrelated to building: HR policies, school menus, alcohol "
                    "licences, meeting minutes on other topics. Each PDF is judged in up to three stages: keyword "
                    "rules on its title and file name, a small classifier trained on those rules, and for every "
                    "proposed removal a second opinion from an LLM (MiMo Flash, about $0.0001 per PDF). Some were read "
                    "by hand. No PDF is removed on a rule or the classifier alone: losing a useful document is worse "
                    "than keeping noise.",
            "measure": "Removed PDFs drawn at random and read by hand: how many were useful after all.",
            "sections": []}
    if not DECISIONS_PATH.exists():
        return {**base, "status": {"level": "info", "label": "Not run", "note": ""}, "flow": None, "tiles": []}
    features = {row["doc_id"]: row for row in read_jsonl(FEATURES_PATH)}
    decisions = list(read_jsonl(DECISIONS_PATH))
    counts = Counter()
    for d in decisions:
        by = d["by"] if d.get("keep") is not None else "pending"
        counts[(by, d.get("keep"))] += 1
    judged = len(decisions)
    removed = [d for d in decisions if d.get("keep") is False]
    pending = sum(1 for d in decisions if d.get("keep") is None)
    labels = evaluate(verbose=False)
    lost = labels.get("all drops")
    rows = [[FILTER_PATHS.get(key, f"Kept for now: waiting for the LLM ({key[0]})"), n]
            for key, n in sorted(counts.items(), key=lambda kv: (kv[0][1] is False, -kv[1]))]
    rng = random.Random(len(removed))
    examples = []
    for d in rng.sample(removed, min(12, len(removed))):
        f = features.get(d["doc_id"], {})
        examples.append(f"{f.get('kommun', '')}: {(f.get('title') or f.get('file') or d['doc_id'])[:80]} "
                        f"(why: {d.get('why') or d['by']})")
    good = lost and lost["high"] <= 0.1 and pending <= 20
    return {
        **base,
        "status": {"level": "good" if good else "warning", "label": "Works" if good else "Check",
                   "note": f"at most {_pct(lost['high'])} of the removed PDFs may be useful" if lost else "not measured"},
        "flow": {"value": -len(removed), "caption": f"{len(removed):,} off-topic PDFs removed"},
        "tiles": [
            {"label": "PDFs judged", "value": judged},
            {"label": "Removed as off topic", "value": len(removed), "hint": _pct(len(removed) / max(judged, 1))},
            {"label": "Useful among removed (hand check)", "value": f"{lost['useful']} / {lost['labelled']}" if lost else "–",
             "hint": f"95 % confidence: {_pct(lost['low'])} to {_pct(lost['high'])}" if lost else ""},
            {"label": "Waiting for the LLM", "value": pending, "hint": "kept meanwhile"},
        ],
        "sections": [
            _section("How each PDF was decided", f"{judged - len(removed):,} kept, {len(removed):,} removed",
                     bars=[{"label": label, "value": n} for label, n in rows]),
            _section("Examples of removed PDFs", "12 drawn at random, with the reason given",
                     examples=examples),
            _section("Errors: useful documents among the removed ones",
                     f"{lost['useful']} useful in {lost['labelled']} read by hand" if lost else "not measured",
                     text="Removed PDFs are drawn at random and read by hand (corpus/pdf_filter_eval.jsonl). The two "
                          "useful ones were fee schedules under the Environmental Code, which give the permit fee for "
                          "a private sewage system: that type of document is now always kept.",
                     table={"columns": ["Which drops", "Read by hand", "Useful", "95 % confidence"],
                            "rows": [["All removed PDFs" if by == "all drops" else
                                      "Removed then, kept by the current rules" if by == "kept now" else by,
                                      r["labelled"], r["useful"], f"{_pct(r['low'])} to {_pct(r['high'])}"]
                                     for by, r in labels.items()]}),
        ],
    }


def ocr_step(check: dict) -> dict:
    documents = check.get("summary", {}).get("documents", {})
    waiting = documents.get("needs_ocr") or 0
    jobs_path = DATA_DIR / "ocr_jobs.jsonl"
    jobs = sum(1 for _ in jobs_path.open(encoding="utf-8")) if jobs_path.exists() else 0
    done = 0
    for path in WEB_DIR.glob("*/ocr/*.json"):
        with path.open("rb") as handle:
            done += OCR_ENGINE.encode() in handle.read(200)
    runs = sorted(EVAL_DIR.glob("ocr-*.json"))
    bench = _load(runs[-1]) if runs else {}
    engines = [("easyocr-gpu", "EasyOCR (used before)"), ("rapid-v6-small-gpu", "PP-OCRv6 small"),
               ("rapid-v6-medium-gpu", "PP-OCRv6 medium (chosen)")]
    rows = []
    for key, name in engines:
        sets = (bench or {}).get(key)
        if not sets:
            continue

        def share(name: str) -> str:
            t = sets.get(name)
            return _pct(t["exact"] / max(t["ref_words"], 1)) if t else "–"

        real = sets.get("real/map", {})
        rows.append([name, share("real/map"), f"{real.get('labels_found', '–')} of {real.get('labels', '–')}",
                     share("synthetic/map"), share("synthetic/text"), share("real/text")])
    types = documents.get("needs_ocr_types") or {}
    finished = done >= jobs if jobs else waiting == 0
    return {
        "id": "ocr", "step": 3, "title": "Read: extract the text, OCR the scans",
        "what": "Web pages and PDFs with a text layer are read directly. Scanned PDFs, mostly old plans from the "
                "1950s to the 1990s, are images: they need OCR (optical character recognition) before their text can "
                "be searched. The OCR also records where each word sits on the page, so that a property number can "
                "be found on a scanned plan map.",
        "measure": "OCR engines compared on plan pages: crops of real old scans typed out by hand, and recent plans "
                   "rendered as images and degraded like a scan (their text layer is the answer key). Score = share of "
                   "the words read exactly; property numbers like 3:204 are counted apart, they identify a plot.",
        "status": {"level": "good" if finished else "info",
                   "label": "Done" if finished else "In progress",
                   "note": f"{done:,} of {jobs:,} scanned PDFs read; then the corpus is rebuilt" if jobs else ""},
        "flow": {"value": waiting, "caption": f"{waiting:,} scanned PDFs waiting for OCR"},
        "tiles": [
            {"label": "Scanned PDFs (no text yet)", "value": waiting, "hint": "invisible to search until OCR"},
            {"label": "Of which detaljplaner", "value": types.get("detaljplan", 0)},
            {"label": "Read by the OCR so far", "value": done, "hint": f"of {jobs:,} queued" if jobs else ""},
            {"label": "Words read on real scanned maps", "value": rows[-1][1] if rows else "–",
             "hint": "PP-OCRv6 medium; EasyOCR, used before: " + (rows[0][1] if rows else "–")},
        ],
        "sections": [
            _section("Progress", f"{done:,} of {jobs:,} scanned PDFs", meter={"value": done, "total": jobs or 1,
                                                                              "label": "scanned PDFs read"}),
            _section("Scanned PDFs by document type", f"{waiting:,} in total",
                     bars=[{"label": DOC_TYPES.get(t, t).split(":")[0], "value": n, "hint": DOC_TYPES.get(t)}
                           for t, n in sorted(types.items(), key=lambda kv: -kv[1])]),
            _section("Which OCR engine", f"benchmark {runs[-1].stem.removeprefix('ocr-') if runs else '–'}",
                     text="PP-OCRv6 medium reads 87 % of the words of real scanned plan maps (EasyOCR 69 %) and 8 of "
                          "13 property numbers (EasyOCR none: it reads the colon of 3:204 as a dot). It runs free on "
                          "the laptop's GPU, 5 to 35 s per plan map in the full run. Small text under 12 pixels (zone "
                          "codes such as e1, b1) stays hard for every engine. Columns: share of the words read "
                          "exactly, except property numbers.",
                     table={"columns": ["Engine", "Real scanned maps", "Property numbers", "Rendered maps",
                                        "Rendered text pages", "Real typed page"],
                            "rows": rows, "highlight": len(rows) - 1}),
        ],
    }


def documents_step(check: dict) -> dict:
    summary = check.get("summary", {})
    documents, index, laws = summary.get("documents", {}), summary.get("index", {}), summary.get("laws", {})
    kinds = documents.get("kinds", {})
    types = documents.get("types", {})
    by_type = Counter()
    for key, n in types.items():
        kind, _, doc_type = key.partition(":")
        if kind != "law":
            by_type[(doc_type, kind)] += n
    type_rows = []
    for doc_type in DOC_TYPES:
        pdf, page = by_type.get((doc_type, "pdf"), 0), by_type.get((doc_type, "page"), 0)
        if pdf + page:
            type_rows.append({"label": DOC_TYPES[doc_type].split(":")[0], "value": pdf + page,
                              "hint": f"{DOC_TYPES[doc_type]} - {pdf:,} PDFs, {page:,} web pages"})
    names = {m["code"]: m["short_name"] for m in json.loads(MUNICIPALITIES_PATH.read_text(encoding="utf-8"))}
    per_kommun = {names.get(c, c): n for c, n in (documents.get("per_kommun") or {}).items() if c != "law"}
    typical = median(per_kommun.values()) if per_kommun else 0
    checks, errors = _checks(check, "Documents", "Statutes", "Index and store")
    return {
        "id": "documents", "step": 4, "title": "Index: cut into passages, make them searchable",
        "what": "Each document is cut into passages of about 1,500 characters (a law: one section per passage), "
                "with a header naming the kommun and the document. Each passage gets a vector, a numeric fingerprint "
                "of its meaning, so that a question finds passages by meaning; a keyword index finds exact words. "
                "Passages repeated across the corpus (standard plan wording) are kept once.",
        "measure": "Automatic checks after every rebuild: garbled text, missing law chapters, documents filed under "
                   "the wrong kommun, passages without a vector, a search store behind the corpus.",
        "status": {"level": "warning" if errors else "good", "label": "Checks pass" if not errors else "To check",
                   "note": checks["summary"]},
        "flow": {"value": index.get("chunks"), "caption": f"{documents.get('count', 0):,} documents, "
                                                          f"{index.get('chunks', 0):,} passages"},
        "tiles": [
            {"label": "Documents", "value": documents.get("count"),
             "hint": f"{kinds.get('pdf', 0):,} PDFs, {kinds.get('page', 0):,} web pages, {kinds.get('law', 0)} laws"},
            {"label": "Passages (chunks)", "value": index.get("chunks")},
            {"label": "Documents per kommun", "value": f"{typical:,.0f}", "hint": "median, scanned PDFs included; the "
             "largest: " + ", ".join(f"{k} {v:,}" for k, v in sorted(per_kommun.items(), key=lambda kv: -kv[1])[:3])},
            {"label": "Law sections", "value": laws.get("chunks"), "hint": f"{laws.get('statutes', 0)} laws"},
        ],
        "sections": [
            _section("Why so many documents", f"{len(per_kommun)} kommuner × a median of {typical:,.0f} documents",
                     text="Plans dominate: a detaljplan is published as a plan map, a description and, for recent "
                          "plans, consultation reports and studies (noise, traffic, soil...), and many kommun sites "
                          "also have a web page per plan. Web pages are short (permit guidance, sewage, shore "
                          "protection); PDFs carry most of the text. Scanned PDFs count as documents but have no "
                          "passages until the OCR.",
                     bars=type_rows),
            _section("Documents per kommun", f"median {typical:,.0f}",
                     table={"columns": ["Kommun", "Documents"],
                            "rows": [[k, v] for k, v in sorted(per_kommun.items(), key=lambda kv: -kv[1])],
                            "limit": 10, "search": True}),
            checks,
        ],
    }


def plans_step(check: dict) -> dict:
    plans = check.get("summary", {}).get("plans", {})
    status = plans.get("status") or {}
    per_plan = plans.get("documents_per_plan") or {}
    total = plans.get("plans") or 0
    return {
        "id": "plans", "step": 5, "title": "Plan registry: one record per detaljplan, with its rules",
        "what": "Groups the documents of each detaljplan into one plan (name, number, status, documents) and extracts "
                "the coded rules printed on the plan (for example e1 = largest building area, h1 = highest building "
                "height), so the agent can answer what a plan allows on a plot.",
        "measure": "Counts only for now: plans found, plans with their rules extracted. Rules printed only as a map "
                   "(which zone carries which code) are read by the agent with the image tools.",
        "status": {"level": "info", "label": "Counts only",
                   "note": f"rules extracted for {_pct(plans.get('with_provisions', 0) / max(total, 1))} of the plans"},
        "flow": {"value": total, "caption": f"{total:,} plans"},
        "tiles": [
            {"label": "Plans", "value": total},
            {"label": "In force", "value": status.get("in_force", 0)},
            {"label": "With rules extracted", "value": plans.get("with_provisions"),
             "hint": f"{plans.get('provisions', 0):,} rules in total" if plans.get("provisions") else ""},
            {"label": "Known only from a web page", "value": plans.get("without_documents"),
             "hint": "no document of the plan in the corpus"},
        ],
        "sections": [
            _section("Plan status", f"{status.get('in_force', 0):,} in force",
                     bars=[{"label": PLAN_STATUS.get(s, s), "value": n} for s, n in sorted(status.items(), key=lambda kv: -kv[1])]),
            _section("Documents per plan", "most plans have a single document in the corpus",
                     bars=[{"label": f"{k if k != '5' else '5 or more'} document{'s' if k != '1' else ''}", "value": n}
                           for k, n in sorted(per_plan.items(), key=lambda kv: int(kv[0]))]),
            _checks(check, "Plan registry")[0],
        ],
    }


def tools_step() -> dict:
    runs = sorted(AGENTIC_DIR.glob("replay-*.json"), key=lambda p: p.stat().st_mtime)
    latest = _load(runs[-1]) if runs else {}
    latency = (latest or {}).get("latency") or {}
    calls = (latest or {}).get("calls") or {}
    violations = sum(len(v) if isinstance(v, list) else (v or 0) for v in ((latest or {}).get("violations") or {}).values())
    rows = [[tool, TOOLS.get(tool, ""), calls.get(tool), _s(latency[tool].get("p50")), _s(latency[tool].get("p95")),
             _s(latency[tool].get("max"))] for tool in sorted(latency, key=lambda t: -(calls.get(t) or 0))]
    history = []
    for path in runs[-4:]:
        replay = _load(path) or {}
        lat = replay.get("latency") or {}
        history.append([path.stem.removeprefix("replay-"), *[f"{_s(lat.get(t, {}).get('p50'))} / {_s(lat.get(t, {}).get('p95'))}"
                                                             for t in ("search", "grep", "read")]])
    search, grep = latency.get("search", {}), latency.get("grep", {})
    eval_runs = sorted(EVAL_DIR.glob("2*.json"))
    eval_rows = []
    if eval_runs:
        for setup, s in list(((_load(eval_runs[-1]) or {}).get("summary") or {}).items())[:8]:
            eval_rows.append([setup, _pct(s.get("recall@1")), _pct(s.get("recall@5")), _pct(s.get("recall@10"))])
    return {
        "id": "tools", "step": 6, "title": "Search: the agent's tools on the corpus",
        "what": "The agent answers by exploring the corpus with tools: search by meaning, grep for exact words, read a "
                "document, open a law section, list a kommun's documents or plans (each tool in the table below). "
                "Their speed sets most of the waiting time outside the model.",
        "measure": "Every tool call stored from past benchmark runs is replayed on the current corpus: a call must not "
                   "fail on something the corpus has, and its time is measured. Times: median (typical call) and "
                   "95th percentile (the slow ones).",
        "status": {"level": "good" if not violations else "warning", "label": "Works" if not violations else "Failures",
                   "note": f"search {_s(search.get('p50'))} s, grep {_s(grep.get('p50'))} s typical"},
        "flow": {"value": f"{_s(search.get('p50'))} s", "caption": f"typical search time; grep {_s(grep.get('p50'))} s"},
        "tiles": [
            {"label": "Search, typical time", "value": f"{_s(search.get('p50'))} s", "hint": f"slow calls {_s(search.get('p95'))} s"},
            {"label": "Grep, typical time", "value": f"{_s(grep.get('p50'))} s", "hint": f"slow calls {_s(grep.get('p95'))} s"},
            {"label": "Calls replayed", "value": sum(c or 0 for c in calls.values())},
            {"label": "Failures on data the corpus has", "value": violations},
        ],
        "sections": [
            _section("Time per tool (seconds)", f"replay {runs[-1].stem.removeprefix('replay-') if runs else '–'}",
                     table={"columns": ["Tool", "What it does", "Calls", "Typical", "Slow (95 %)", "Slowest"], "rows": rows}),
            _section("Earlier runs (typical / slow, seconds)", "the corpus grew 5x between the small runs and 20261024",
                     table={"columns": ["Run", "search", "grep", "read"], "rows": history,
                            "highlight": len(history) - 1}),
            _section("Search quality (retrieval evaluation)",
                     f"last run {eval_runs[-1].stem if eval_runs else 'never'}: on the corpus of that date, rerun needed",
                     text="Questions written for real use cases, each labelled with the passages that answer it: "
                          "recall@5 = share of questions whose answering passage is in the first 5 results. This "
                          "run predates the large crawl (349k passages, 1.9 M now).",
                     table={"columns": ["Model | setup", "Recall@1", "Recall@5", "Recall@10"], "rows": eval_rows}),
        ],
    }


_cache: dict = {}


def _signature() -> tuple:
    """Modification times of the source files, plus the OCR output count: the page is rebuilt only when a step wrote
    new results (reading the filter's 70k rows takes seconds)."""
    from corpus.pdf_filter import DECISIONS_PATH, EVAL_PATH

    paths = [DATA_DIR / "check.json", DECISIONS_PATH, EVAL_PATH, DATA_DIR / "ocr_jobs.jsonl",
             *AGENTIC_DIR.glob("coverage-*.json"), *AGENTIC_DIR.glob("replay-*.json"), *EVAL_DIR.glob("*.json")]
    ocr_outputs = sum(1 for _ in WEB_DIR.glob("*/ocr/*.json"))
    return tuple(sorted((str(p), p.stat().st_mtime) for p in paths if p.exists())) + (ocr_outputs,)


@router.get("/pipeline")
def pipeline(_: models.User = Depends(get_current_user)) -> dict:
    signature = _signature()
    if _cache.get("signature") != signature:
        check = _load(DATA_DIR / "check.json") or {}
        _cache.update(signature=signature, result={"corpus": DATA_DIR.parent.name, "steps": [
            crawl_step(check), filter_step(), ocr_step(check), documents_step(check), plans_step(check), tools_step(),
        ]})
    return _cache["result"]

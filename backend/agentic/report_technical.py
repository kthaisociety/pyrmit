"""
Detailed technical report (English; French with --lang fr): the Swedish planning system and where Pyrmit fits, where every piece
of data comes from and how to keep it current, the pipeline with code references, and exactly how retrieval and the
agent are evaluated. Companion to agentic.report (the benchmark summary); figures are read from the data.

    cd backend && python -m agentic.report_technical             # English
    python -m agentic.report_technical --lang fr   # or --lang both
    -> ../pyrmit_doc/pyrmit_rapport_technique.pdf (fr), ../pyrmit_doc/pyrmit_technical_report.pdf (en)
"""

import argparse
import base64
import html
import json
import re
import shutil
import sqlite3
import subprocess
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from agentic import report
from agentic.bench import CASES_PATH, JUDGE_INSTRUCTIONS, sample_cases
from agentic.cases_from_caselaw import INSTRUCTIONS as CASE_INSTRUCTIONS
from agentic.grounding import INSTRUCTIONS as GROUNDING_INSTRUCTIONS
from corpus.common import DATA_DIR, LAWS_DIR, WEB_DIR, read_jsonl

OUTPUT_NAMES = {"fr": "pyrmit_rapport_technique", "en": "pyrmit_technical_report"}
STORE = DATA_DIR.parent / "index" / "store" / "st-arctic-l-v2" / "corpus.sqlite"
EVAL_DIR = DATA_DIR.parent / "eval"
LANG = "en"


def tr(fr: str, en: str) -> str:
    return en if LANG == "en" else fr


def esc(value) -> str:
    return html.escape(str(value))


def num(value: int) -> str:
    return f"{value:,}" if LANG == "en" else f"{value:,}".replace(",", " ")


def code(path: str) -> str:
    return f"<code>{esc(path)}</code>"


# --- figures read from the data ---------------------------------------------------------------------------------------

def corpus_stats() -> dict:
    stats: dict = {}
    if STORE.exists():
        db = sqlite3.connect(STORE)
        stats["chunks"] = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        stats["docs"] = db.execute("SELECT COUNT(DISTINCT doc_id) FROM chunks").fetchone()[0]
        stats["kommuner"] = db.execute("SELECT COUNT(DISTINCT kommun_code) FROM chunks WHERE kommun_code IS NOT NULL").fetchone()[0]
        stats["law_chunks"] = db.execute("SELECT COUNT(*) FROM chunks WHERE kind = 'law'").fetchone()[0]
        stats["doc_types"] = dict(db.execute("SELECT doc_type, COUNT(DISTINCT doc_id) FROM chunks WHERE kind != 'law' "
                                             "GROUP BY doc_type ORDER BY 2 DESC").fetchall())
        stats["kinds"] = dict(db.execute("SELECT kind, COUNT(DISTINCT doc_id) FROM chunks GROUP BY kind").fetchall())
    laws = []
    for path in sorted(LAWS_DIR.glob("*.txt")):
        text = path.read_text(encoding="utf-8")
        title = text.splitlines()[0].strip()
        version = re.search(r"t\.o\.m\. SFS (\d{4}:\d+)", text)
        laws.append((title, version.group(1) if version else "?",
                     datetime.fromtimestamp(path.stat().st_mtime).date().isoformat()))
    stats["laws"] = laws
    manifests = list(WEB_DIR.glob("*/manifest.jsonl"))
    dates = sorted(datetime.fromtimestamp(p.stat().st_mtime).date().isoformat() for p in manifests)
    stats["crawl"] = {"kommuner": len(manifests), "first": dates[0] if dates else "?", "last": dates[-1] if dates else "?"}
    done = [json.loads(p.read_text(encoding="utf-8").strip().splitlines()[-1]) for p in manifests]
    done = [d for d in done if d.get("done")]
    stats["crawl"].update(pages=sum(d.get("pages", 0) for d in done), pdfs=sum(d.get("pdfs", 0) for d in done),
                          pdf_gb=round(sum(d.get("pdf_mb", 0) for d in done) / 1024, 1),
                          requests=sum(d.get("requests", 0) for d in done))
    stats["ocr"] = len(list(WEB_DIR.glob("*/ocr/*.json")))
    plans_path = DATA_DIR / "plans.jsonl"
    plans = [json.loads(line) for line in plans_path.open(encoding="utf-8")] if plans_path.exists() else []
    stats["plans"] = len(plans)
    stats["plans_with_rules"] = sum(1 for p in plans if p["provisions"])
    stats["provisions"] = sum(len(p["provisions"]) for p in plans)
    stats["plan_status"] = Counter(p["status"] for p in plans).most_common()
    rulings = list(read_jsonl(DATA_DIR / "raw" / "caselaw" / "mod.jsonl"))
    stats["rulings"], stats["rulings_relevant"] = len(rulings), sum(1 for r in rulings if r.get("relevant"))
    caselaw = list(read_jsonl(CASES_PATH.parent / "cases_caselaw.jsonl"))
    stats["caselaw_cases"] = len(caselaw)
    stats["caselaw_evidence"] = sum(1 for case in caselaw if case["evidence"])
    stats["caselaw_kommuner"] = len({code for case in caselaw for code in case["kommun"]})
    candidates = report.DATA_DIR.parent / "agentic" / "plan_cases" / "candidates.json"
    stats["plan_candidates"] = len(json.loads(candidates.read_text(encoding="utf-8"))) if candidates.exists() else 0
    stats["municipalities"] = len(json.loads((DATA_DIR / "municipalities.json").read_text(encoding="utf-8")))
    return stats


RETRIEVAL_ROWS = [  # (model | setup) rows of localrag.eval worth showing, in this order
    "st-arctic-l-v2 | dense-sv", "st-bge-m3 | dense-sv", "or-qwen3-8b | dense-sv", "st-kblab-swedish | dense-sv",
    "st-bge-m3 | dense-en", "or-qwen3-8b | dense-en", "st-arctic-l-v2 | hybrid-sv", "st-arctic-l-v2 | dense-sv +rerank",
    "- | bm25-sv", "- | bm25-sv-stem", "- | bm25-en",
]


def retrieval_table() -> str:
    latest: dict[str, dict] = {}
    for path in sorted(EVAL_DIR.glob("*.json")):
        summary = json.loads(path.read_text(encoding="utf-8")).get("summary", {})
        latest.update(summary)
    rows = []
    for key in RETRIEVAL_ROWS:
        if key not in latest:
            continue
        m = latest[key]
        model, setup = key.split(" | ")
        rows.append(f"<tr><td>{esc(model if model != '-' else 'BM25')}</td><td>{esc(setup)}</td>"
                    + "".join(f"<td>{report.fmt(m[k])}</td>" for k in ("recall@1", "recall@5", "recall@10", "complete@5", "mrr"))
                    + "</tr>")
    head = tr("<tr><th>Modèle</th><th>Réglage</th><th>R@1</th><th>R@5</th><th>R@10</th><th>Complet@5</th><th>MRR</th></tr>",
              "<tr><th>Model</th><th>Setup</th><th>R@1</th><th>R@5</th><th>R@10</th><th>Complete@5</th><th>MRR</th></tr>")
    return f"<table>{head}{''.join(rows)}</table>"


def prompt_block(text: str) -> str:
    return f"<pre class='prompt'>{esc(text.strip())}</pre>"


# --- page ----------------------------------------------------------------------------------------------------------

EXTRA_STYLE = """<style>
pre.prompt { white-space: pre-wrap; font-family: Consolas, monospace; font-size: 7.6pt; background: #f8fafc;
  border: 1px solid #e5e7eb; border-radius: 4pt; padding: 6pt 8pt; margin: 4pt 0 8pt; break-inside: avoid; }
td code, li code, p code { white-space: nowrap; }
.toc { columns: 2; font-size: 9pt; margin: 6pt 0 10pt; } .toc div { margin: 1pt 0; }
.case { break-inside: auto; }
img.crop { max-width: 60%; max-height: 300px; border: 1px solid #e5e7eb; border-radius: 4pt; margin: 6pt 0 2pt; }
</style>"""


def build_html() -> str:
    report.LANG = LANG  # the shared table helpers follow the same language
    s = corpus_stats()
    runs = report.load_runs()
    runs_mod = [r for r in runs if r["cases"] == "mod"]
    caselaw = list(read_jsonl(CASES_PATH.parent / "cases_caselaw.jsonl"))
    sample = sample_cases(list(caselaw), 50)
    table_mod = report.runs_table(runs_mod) if runs_mod else "<p>–</p>"
    verdicts_mod = report.verdict_table([r for r in runs_mod if r["system"] == "agent"], {c["id"]: c for c in caselaw})
    laws_rows = "".join(f"<tr><td>{esc(t)}</td><td>SFS {esc(v)}</td><td>{esc(d)}</td></tr>" for t, v, d in s["laws"])
    doc_types = ", ".join(f"{esc(k)} {num(v)}" for k, v in s.get("doc_types", {}).items())
    plan_status = ", ".join(f"{esc(k)} {num(v)}" for k, v in s["plan_status"])
    c = s["crawl"]
    today = date.today()
    judge_prompt, grounding_prompt = prompt_block(JUDGE_INSTRUCTIONS), prompt_block(GROUNDING_INSTRUCTIONS)
    case_prompt = prompt_block(CASE_INSTRUCTIONS)
    retrieval = retrieval_table()
    by_key = {(r["cases"], r["system"], r["explore"], r["answer"], r["ablation"]): r for r in runs}
    overview = report.overview_table([
        (name, [by_key.get((key, "rag", "–", "medium", "")), by_key.get((key, "agent", "medium", "medium", ""))])
        for key, name in (("cases14", tr("14 cas", "14 cases")), ("mod", "MÖD"), ("plans", "plankarta"))])
    results_text = report.NARRATIVE_RESULTS.get(LANG, "")

    # Section 7: how each benchmark set is built, with the cases themselves
    cases14 = list(read_jsonl(CASES_PATH))
    plan_cases = list(read_jsonl(CASES_PATH.parent / "cases_plans.jsonl"))
    colon = tr(" : ", ": ")
    verdict_split = ", ".join(f"{esc(k)}{colon}{v}"
                              for k, v in Counter(" / ".join(c["verdicts"]) for c in caselaw).most_common(5))
    caselaw_topics = ", ".join(f"{esc(t)} {n}" for t, n in Counter(
        t for c in caselaw for t in c.get("tags", []) if t != "caselaw").most_common(8))
    refused = sum(1 for c in plan_cases if "not_feasible" in c["verdicts"])
    plan_verdicts = tr(f"« non faisable » accepté pour {refused}, pas pour les {len(plan_cases) - refused} autres",
                       f"“not feasible” accepted for {refused}, not for the other {len(plan_cases) - refused}")
    cases14_table = (tr("<table><tr><th>Cas</th><th>Question</th><th>Documents sources</th><th>Verdicts acceptés</th></tr>",
                        "<table><tr><th>Case</th><th>Question</th><th>Source documents</th><th>Accepted verdicts</th></tr>")
                     + "".join(f"<tr><td><code>{esc(c['id'])}</code>{' ★' if 'real-project' in c.get('tags', []) else ''}"
                               f"</td><td>{esc(c['question'])}</td><td>{esc(c.get('source', ''))}</td>"
                               f"<td>{esc(', '.join(c['verdicts']))}</td></tr>" for c in cases14)
                     + "</table>" + tr("<p class='n'>★ projet réel sur un plan détaillé réel</p>",
                                       "<p class='n'>★ real project on a real detailed plan</p>"))
    examples14 = [c for c in cases14 if c["id"] in ("kumla-200m2", "ydre-lake-house")]
    examples_mod = [c for c in sample if c["id"] in ("mod-2026-13", "mod-2026-17")] or sample[:2]
    examples = report.examples_html(runs, "cases14", examples14) + report.examples_html(runs, "mod", examples_mod)
    plan_example = ""
    if plan_cases:
        case = plan_cases[0]
        image = report.DATA_DIR.parent / "agentic" / "plan_cases" / case.get("image", "")
        figure = (f"<img class='crop' src='data:image/png;base64,{base64.b64encode(image.read_bytes()).decode()}' "
                  f"alt='plan map crop'><p class='n'>{esc(case.get('source', ''))}</p>") if image.is_file() else ""
        plan_example = figure + report.examples_html(runs, "plans", [case])

    if LANG == "en":
        body = f"""
<h1>Pyrmit – technical report</h1>
<div class="sub">Data, Swedish legal context, pipeline and evaluation methodology. Companion to the benchmark report.
Generated on {today:%Y-%m-%d}; figures are read from the data and result files at generation time.</div>
<div class="toc">
<div>1. Purpose of the system</div><div>2. The Swedish planning system and where Pyrmit fits</div>
<div>3. Data sources: what, why, how</div><div>4. Keeping the data current</div>
<div>5. Pipeline, with code references</div><div>6. Retrieval evaluation</div>
<div>7. Evaluation: how the benchmarks are built and scored</div><div>8. Results summary</div>
<div>9. Limitations and roadmap</div><div>Appendix: commands and files</div>
</div>

<h2>1. Purpose of the system</h2>
<p>Pyrmit answers, in English, whether a building or land project is feasible in a given Swedish municipality and how
to get it approved: which rules decide the case (national law, the municipality's plans and local guidance), what
permits are needed, and what remains uncertain. Every rule, number or deadline in an answer must cite a passage the
system actually read; citations open the original document at that passage. It is a <b>pre-application screening</b>
tool: it does not replace the municipality's decision, and the answers say what must be checked.</p>

<h2>2. The Swedish planning system and where Pyrmit fits</h2>
<h3>2.1 Who decides what</h3>
<ul>
<li><b>Municipal planning monopoly.</b> Planning the use of land and water is a municipal matter (PBL 1 kap. 2 §). The
municipality's building committee (byggnadsnämnd) decides on permits; its planning bodies adopt plans.</li>
<li><b>Comprehensive plan (översiktsplan, PBL 3 kap.)</b>: covers the whole municipality, states intentions (where to
build, what to protect). Not binding, but it guides permit and planning decisions.</li>
<li><b>Detailed plan (detaljplan, PBL 4 kap.)</b>: binding for an area: land use (residential, roads, nature…) and
property provisions (building area, ridge height, storeys, minimum plot size, land that may not be built on, design,
implementation period). It consists of a <i>plankarta</i> (map with codes and provisions) and a <i>planbeskrivning</i>
(explanatory description). Plans go through consultation (samråd), review (granskning), adoption (antagande) and gain
legal force (laga kraft). Area regulations (områdesbestämmelser) are a lighter binding instrument.</li>
<li><b>Permits (PBL 9 kap.)</b>: building permit (bygglov), demolition permit (rivningslov), site permit (marklov);
some measures only need a notification (anmälan) or are exempt (e.g. Attefall measures). Inside a detailed plan the
project must comply with the plan (small deviations can be accepted); outside, the site is assessed against the general
suitability requirements of PBL 2 kap. An advance ruling (förhandsbesked) can settle the location question first.
<b>Note</b>: PBL chapter 9 was renumbered by SFS 2025:974 (bygglov conditions now 9 kap. 56–57 §, small deviations
60–61 §, advance ruling 74 §); case law and most guidance still use the old numbers.</li>
<li><b>Environmental Code (miljöbalken)</b> constraints that often decide feasibility: shoreline protection
(strandskydd, MB 7 kap.; building needs an exemption with a special reason), productive agricultural land
(MB 3 kap. 4 §: only for essential public interests), areas of national interest (MB 3–4 kap.).</li>
<li><b>Water and sewage</b>: municipal water and sewage areas (LAV); a private sewage system needs a permit or
notification to the municipal environmental committee (förordningen om miljöfarlig verksamhet och hälsoskydd, 13–14 §§).</li>
<li><b>Property formation</b> (fastighetsbildning) is decided by Lantmäteriet under the Real Property Formation Act;
detailed plans can set minimum plot sizes.</li>
<li><b>Appeals</b>: building committee decisions are appealed to the county administrative board (länsstyrelsen), then
to a Land and Environment Court (mark- och miljödomstol), then to the Land and Environment Court of Appeal
(Mark- och miljööverdomstolen, MÖD), which needs leave to appeal and sets precedents. Decisions to adopt a detailed plan
are appealed directly to the Land and Environment Court.</li>
</ul>
<h3>2.2 Where Pyrmit fits</h3>
<table>
<tr><th>Question in a project</th><th>Legal basis</th><th>What Pyrmit reads</th></tr>
<tr><td>Is my site inside a detailed plan, and what does it allow?</td><td>PBL 4 kap., plan provisions</td>
<td>Plan registry, plan maps and descriptions crawled from the municipality (tools <code>plans</code>,
<code>plan_rules</code>, <code>read</code>)</td></tr>
<tr><td>Do I need a permit, a notification, or nothing?</td><td>PBL 9 kap., PBF</td><td>Statute text
(<code>law_section</code>), municipal permit pages</td></tr>
<tr><td>Can I build outside a plan / get an advance ruling?</td><td>PBL 2 kap., 9 kap.</td><td>Statute text, comprehensive
plan, municipal guidance</td></tr>
<tr><td>Shoreline, farmland, national interests?</td><td>MB 3, 4, 7 kap.</td><td>Statute text, comprehensive plan, municipal
pages on strandskydd</td></tr>
<tr><td>Water and sewage, fees, timelines?</td><td>LAV, FMH, municipal fee schedules (taxa)</td><td>Municipal pages and
PDFs (sewage guidance, taxa)</td></tr>
</table>
<p>The system mirrors how a planning officer screens a case: identify the municipality and the site, check the plan
situation, find the national rules that apply, then the local documents. It stops before what needs official data it
does not have yet (which plan covers a given property, maps of protected areas) and says so in the answer.</p>

<h2>3. Data sources: what, why, how</h2>
<table>
<tr><th>Source</th><th>What we take</th><th>Why this source</th><th>How (code)</th><th>Terms</th></tr>
<tr><td>Riksdagen open data (data.riksdagen.se)</td><td>{len(s['laws'])} consolidated statutes (PBL, PBF, MB, JB, FBL,
LAV, FMH…)</td><td>Official consolidated text with amendment markers; free API</td><td>{code('corpus/laws.py')}
(<code>LAWS</code>, <code>main</code>)</td><td>Open data, cite Riksdagen</td></tr>
<tr><td>Wikidata (SPARQL)</td><td>{s['municipalities']} municipalities: official code, county, website; ~10k localities</td>
<td>Stable identifiers and official websites; localities for place → municipality</td><td>{code('corpus/municipalities.py')}
(<code>sparql</code>, <code>pick_site</code>)</td><td>CC0</td></tr>
<tr><td>Municipal websites</td><td>{num(c['pages'])} pages, {num(c['pdfs'])} PDFs ({c['pdf_gb']} GB): permits, sewage,
fees, plans, comprehensive plans</td><td>Local rules and detailed plans are published by each municipality; no national
full-text source</td><td>{code('corpus/crawl.py')} (<code>content_relevance</code>, <code>crawl</code>)</td><td>Public
web pages; robots.txt honoured, 1 request/s per host</td></tr>
<tr><td>Local OCR (EasyOCR, GPU)</td><td>Text of {num(s['ocr'])} scanned PDFs (old plan maps)</td><td>Old plans have no
text layer</td><td>{code('corpus/ocr.py')}</td><td>Local processing</td></tr>
<tr><td>Plan registry (derived)</td><td>{num(s['plans'])} plans, {num(s['plans_with_rules'])} with
{num(s['provisions'])} extracted provisions</td><td>Agent needs plans as entities with status and rules</td>
<td>{code('corpus/plans.py')} (<code>plan_key</code>, <code>provisions_of</code>, <code>status_of</code>)</td><td>Derived</td></tr>
<tr><td>Case law: MÖD via lagen.nu</td><td>{s['rulings']} rulings since 2011, {s['rulings_relevant']} on our topics</td>
<td>Real decisions with facts, outcome and reasons: ground truth for the benchmark</td><td>{code('corpus/caselaw.py')}
(<code>parse_case</code>, <code>relevant</code>)</td><td>Court rulings are public documents without copyright
protection; lagen.nu allows the ruling pages in robots.txt</td></tr>
</table>
<h3>3.1 Statute versions in the corpus</h3>
<table><tr><th>Statute</th><th>Consolidated up to</th><th>Downloaded</th></tr>{laws_rows}</table>
<h3>3.2 Crawl</h3>
<p>{c['kommuner']} municipalities crawled between {c['first']} and {c['last']} ({num(c['requests'])} requests). The
crawler starts from each official website, follows links scored by topic keywords (building permits, plans, sewage,
fees; negative keywords for unrelated sections), keeps pages with a relevance score ≥ 4 (<code>KEEP_SCORE</code>), PDFs
linked from relevant pages, and caps each municipality (300 pages, 150 PDFs, 40 MB per PDF, 1,500 requests, depth 4,
per-section quotas). Text is extracted with PyMuPDF block by block, repeated headers and footers removed
({code('corpus/extract.py')} <code>page_blocks</code>, <code>strip_boilerplate</code>), each document classified
(<code>doc_type</code>: {doc_types}).</p>
<p>Corpus served by the app: {num(s.get('chunks', 0))} chunks in {num(s.get('docs', 0))} documents,
{s.get('kommuner', 0)} municipalities, {num(s.get('law_chunks', 0))} statute sections. Plan statuses in the registry:
{plan_status}.</p>
<h3>3.3 Sources not used yet (and why they matter)</h3>
<ul>
<li><b>Lantmäteriet</b>: the property register (property designations, boundaries) and national access to digital
detailed plans. Needed to answer “which plan covers my property” reliably. Access terms and APIs to be confirmed
(some are paid).</li>
<li><b>Svensk författningssamling</b> (svenskforfattningssamling.se): the official publication of new acts; useful to
detect amendments before the consolidated text is updated.</li>
<li><b>County boards and national agencies</b>: GIS layers for shoreline protection, national interests, protected
nature; Boverket's guidance (PBL kunskapsbanken). Would turn spatial questions (“is my plot within 100 m of the
shore?”) into data lookups.</li>
<li><b>Municipal plan services</b> (WMS / plan registers): many municipalities publish plan boundaries as map services;
combined with an address or property, they give the applicable plan.</li>
</ul>

<h2>4. Keeping the data current</h2>
<h3>4.1 Current state (honest picture)</h3>
<ul>
<li>Statutes: the consolidated version is visible in the raw text (“t.o.m. SFS …”, table 3.1) but not stored as
metadata; texts with two versions of a section (in force now / from a future date) are both indexed.</li>
<li>Municipal documents: <b>no fetch date or HTTP validators are stored per page or PDF</b> (the crawl manifest keeps id,
URL, title, score); the only date is the crawl itself ({c['first']}–{c['last']}). Fee schedules change yearly; plan
pages change when plans move through the process.</li>
<li>Plans: status is inferred from page URLs and document text (laga kraft date, “antagandehandling”…); superseded or
repealed plans are not tracked.</li>
<li>Rebuilds are manual: extract → chunk → embed (incremental) → store → plan registry. Chunk ids include a text hash,
so unchanged chunks keep their vectors.</li>
</ul>
<h3>4.2 How to guarantee freshness</h3>
<ol>
<li><b>Provenance on every document</b>: fetched_at, HTTP ETag / Last-Modified, content hash, source URL, and for
statutes the “t.o.m. SFS” version and the date of entry into force of each section version. Shown in the source panel
and in the answer (“municipal page fetched on …”).</li>
<li><b>Scheduled refresh by volatility</b>: statutes weekly (Riksdagen API, compare the version marker; check
svenskforfattningssamling.se for new acts); municipal plan and permit pages weekly, the rest of the crawl monthly, with
conditional requests (If-None-Match / If-Modified-Since) and sitemaps so unchanged pages cost one cheap request; case
law monthly.</li>
<li><b>Incremental pipeline</b>: re-extract and re-chunk only changed documents, embed only new chunk ids, update the
store in place (insert / delete rows and vectors) instead of rebuilding; rebuild the plan registry for touched
municipalities.</li>
<li><b>Legal validity</b>: index each statute section with its validity interval (the consolidated text marks future
versions “Träder i kraft I:…” and expiring ones “Upphör att gälla U:…”), answer with the version in force on the
question date; track plan status changes (adopted → legal force → amended / repealed).</li>
<li><b>Prefer authoritative sources</b> where they exist (Lantmäteriet's digital plans and property data) over crawled
copies, and keep the crawl for what has no national source (local guidance, fees).</li>
<li><b>Monitoring and regression</b>: after each refresh, a report of changed / failed sources per municipality, and a
benchmark run (MÖD sample) to catch quality regressions; alert when a municipality's site structure changes (crawl
yields drop).</li>
</ol>

<h2>5. Pipeline, with code references</h2>
<table>
<tr><th>Stage</th><th>What it does</th><th>Code</th></tr>
<tr><td>Municipalities</td><td>Wikidata SPARQL → codes, websites, localities</td><td>{code('corpus/municipalities.py')}</td></tr>
<tr><td>Statutes</td><td>Riksdagen API → raw text per SFS</td><td>{code('corpus/laws.py')}</td></tr>
<tr><td>Crawl</td><td>Async, robots.txt, 1 req/s/host, topic scoring, caps, resumable manifests</td><td>{code('corpus/crawl.py')}</td></tr>
<tr><td>OCR</td><td>EasyOCR sv+en on GPU, tiled pages, plans first</td><td>{code('corpus/ocr.py')}</td></tr>
<tr><td>Extraction</td><td>PyMuPDF blocks, boilerplate removal, doc types, OCR text when needed</td><td>{code('corpus/extract.py')}</td></tr>
<tr><td>Chunking</td><td>One chunk per statute section (chapters only on their own line, lettered §, transitional
provisions dropped); ~1,500-char document chunks; corpus-wide dedup; ids = hash(doc, index, text)</td>
<td>{code('corpus/chunk.py')} (<code>law_chunks</code>, <code>document_chunks</code>)</td></tr>
<tr><td>Embeddings</td><td>Snowflake arctic-embed-l-v2 (1024 dim) on the GPU, incremental</td><td>{code('localrag/index.py')},
{code('embeddings.py')}</td></tr>
<tr><td>Disk store</td><td>SQLite (chunks, FTS5 BM25 on Swedish stems with pool / municipality filter tokens) + float16
vectors (memmap → GPU)</td><td>{code('localrag/store.py')} (<code>build</code>, <code>DiskStore</code>, <code>DiskRetriever</code>)</td></tr>
<tr><td>Plan registry</td><td>Plans, status, provisions tied to chunks</td><td>{code('corpus/plans.py')}</td></tr>
<tr><td>Place → municipality</td><td>Wikidata names and localities ∪ corpus place names</td><td>{code('localrag/gazetteer.py')}</td></tr>
<tr><td>Agent tools</td><td>find_kommun, search (hybrid RRF), grep, list_documents, read, law_section, plans, plan_rules,
view_pdf_page; every output tagged with [c:chunk_id]</td><td>{code('agentic/tools.py')} (<code>CorpusTools</code>,
<code>TOOL_SCHEMAS</code>)</td></tr>
<tr><td>Agent loop</td><td>Responses API tool loop: exploration turns at <code>explore_effort</code>, parallel tool
calls, <code>answer_ready</code>, streamed final answer at <code>effort</code>, step budget</td><td>{code('agentic/agent.py')}
(<code>run_agent</code>, <code>SYSTEM_PROMPT</code>)</td></tr>
<tr><td>Chat integration</td><td>Background thread, SSE events, live citation numbering, saved trace</td>
<td>{code('agentic/service.py')} (<code>stream_agent</code>, <code>CitationNumberer</code>), {code('routers/chat.py')}</td></tr>
<tr><td>Source viewer</td><td>Cited chunk → PDF page with highlight, or URL text fragment</td><td>{code('routers/docs.py')},
{code('frontend/components/SourceViewer.tsx')}</td></tr>
</table>
<p><b>Grounding by construction.</b> Tool outputs carry chunk ids; the answer format requires a [c:id] for every rule,
number, fee or deadline, and forbids stating what was not read in a tool result. The chat replaces ids by numbers while
streaming and attaches, for each number, the cited chunks (pipeline event <code>citations</code>).</p>

<h2>6. Retrieval evaluation</h2>
<p>{code('localrag/eval.py')} on {code('localrag/questions.jsonl')}: 45 use-case questions (permits, plans, sewage, fees,
heights…), each labelled with the passages that answer it (exact excerpts of municipal documents or statute sections).
Metrics per question: recall@k = share of the expected passages found in the top k; complete@5 = all expected
passages in the top 5; MRR = 1 / rank of the first expected passage. The municipality filter is detected from the
question. Setups: <i>dense-en</i> / <i>dense-sv</i> = embedding of the English question / of a Swedish rewrite;
<i>bm25</i> = BM25 on Swedish tokens; <i>hybrid</i> = reciprocal-rank fusion; <i>+rerank</i> = cross-encoder
bge-reranker-v2-m3.</p>
{retrieval}
<p><b>Findings</b>: querying in Swedish is decisive (+13 to +28 points of recall@5 over the English query, depending on the model); local open models match
API models (arctic-embed-l-v2: 0.92 recall@5); BM25 on English queries is useless on a Swedish corpus; neither BM25
fusion nor the reranker beat dense retrieval on the Swedish query. The agent still uses hybrid search because exact
wording (plan names, “20 meter”) matters inside its tool calls.</p>

<h2>7. Evaluation: how the benchmarks are built and scored</h2>
<p>Three benchmark sets, each built to answer a different question. All cases share one format (one JSON line per case):
the <code>question</code> as a user would ask it, in English; the <code>kommun</code> codes it concerns; the accepted
<code>verdicts</code> (feasible / conditional / not_feasible / unclear); 3–5 <code>key_points</code> an expert answer must
make; the <code>evidence</code> the system should have read (matchers, section 7.5); and the <code>source</code>. They
differ in where the scenario comes from and who wrote the reference.</p>
<table>
<tr><th>Set</th><th>Scenario</th><th>Documents it is built from</th><th>Reference written by</th><th>Size</th></tr>
<tr><td><b>14 case studies</b><br>{code('agentic/cases.jsonl')}</td><td>Realistic questions (user feedback, typical
projects); 3 are real development projects</td><td>Detailed plans, municipal guidance pages and statutes of 5
municipalities</td><td>Hand, from those documents</td><td>14</td></tr>
<tr><td><b>MÖD rulings</b><br>{code('agentic/cases_caselaw.jsonl')}</td><td><b>Real</b> applications that were refused or
granted and appealed to the highest planning court</td><td>The rulings of Mark- och miljööverdomstolen (lagen.nu), current
statute text for the evidence</td><td>LLM, from the ruling (facts, outcome, reasons)</td><td>{s['caselaw_cases']}
generated, 50 sampled</td></tr>
<tr><td><b>Plankarta</b><br>{code('agentic/cases_plans.jsonl')}</td><td><b>Real</b> plan maps and property numbers;
the project is designed</td><td>Plan maps (plankartor) in force or adopted, and the plan legend from the plan
registry</td><td>Vision LLM, from a crop of the map + the legend; only confident labels kept</td><td>{len(plan_cases)}</td></tr>
</table>

<h3>7.1 The 14 case studies (hand-written)</h3>
<p><b>Where they come from.</b> The questions started from the feedback on the first version of Pyrmit (questions on
Vallentuna such as “what is the building permit procedure”, “what is the maximum height in Veda”) and were extended to
the project types the tool is meant for: building on a detailed plan, Attefall houses, shoreline protection, an
eco-village on farmland, private sewage, plot subdivision, rezoning requests, demolition, advance rulings. Five
municipalities were chosen because the corpus covers them well: Vallentuna, Uppsala, Norrtälje, Ydre and Gotland.</p>
<p><b>Real or constructed.</b> Three cases are real development projects on real detailed plans (Kumla-Stensta,
Mörby backe and Kristineberg in Vallentuna): the question asks about a project slightly beyond, or within, what the
adopted plan allows, and the plan's own provisions decide. The others are realistic scenarios built on the
municipality's real pages and the statutes. None is an application with a known decision: the reference is what the
documents say, written by hand, and every key point is backed by an <b>exact excerpt</b> of the document or a statute
section (the expected evidence).</p>
{cases14_table}

<h3>7.2 The MÖD cases (real rulings)</h3>
<p><b>Why real rulings.</b> A ruling of Mark- och miljööverdomstolen is a real application (a building permit, an advance
ruling, a shoreline exemption, a detailed plan…) that the municipality decided, that was appealed, and on which the
highest court in planning matters gave the final answer with its reasons. It gives what hand-written cases cannot: a
real outcome to check the verdict against, decided on the law, and a variety of situations ({s['caselaw_kommuner']}
municipalities).</p>
<ol>
<li><b>Collection</b> ({code('corpus/caselaw.py')}): {s['rulings']} rulings since 2011 from lagen.nu (robots.txt allows
the ruling pages; 1 request/s), with headnote, keywords, statutes cited and full text; {s['rulings_relevant']} are on our
topics (building permits, detailed plans, shoreline protection, advance rulings, sewage…).</li>
<li><b>Transformation</b> ({code('agentic/cases_from_caselaw.py')}, one LLM call per ruling, prompt below): the facts of
the ruling become the question, written as the applicant would ask it <i>before</i> the decision, with neither the
outcome nor the reasoning; the actual outcome gives the accepted verdicts (a remittal or a fact-dependent decision gives
“conditional” / “unclear”); the court's reasons give the key points; the statutes it applied give the expected
evidence.</li>
<li><b>Checks</b>: purely procedural rulings dropped (standing, sanctions); questions that mention the
court dropped (<code>LEAK</code> regex); municipality names mapped to codes. Evidence = the longest run of
≥ 5 words of the statute wording quoted in the ruling that is found in the <b>current</b> statute text, so it survives
the 2025 renumbering of PBL chapter 9 and small amendments; {s['caselaw_evidence']} of the {s['caselaw_cases']} cases
have such a label, the others (rulings under the old PBL) are scored on verdict and key points only.</li>
<li><b>Sample</b>: the benchmark runs on 50 cases drawn with a fixed seed, round-robin over the three outcomes (refused,
granted, open), labelled cases first (<code>sample_cases</code> in {code('agentic/bench.py')}).</li>
</ol>
<p>Split of the {s['caselaw_cases']} cases by accepted verdicts: {verdict_split}. Topics (ruling keywords): {caselaw_topics}.
Case-generation prompt ({code('agentic/cases_from_caselaw.py')} <code>INSTRUCTIONS</code>):</p>
{case_prompt}

<h3>7.3 The plankarta cases (real plan maps, designed projects)</h3>
<p><b>Why.</b> In the two other sets the map is never needed (2 map views in 576 agent answers): their answers are in the
text of plans and statutes. But a detailed plan's rules often differ by zone (a height or a building area per block), and
only the map shows which zone a property is in. This set asks about a specific property where that matters.</p>
<ol>
<li><b>Candidates</b> ({code('agentic/cases_from_plans.py')} <code>candidates</code>, rule-based, free): plans in force or
adopted from the plan registry, whose plan map has a text layer and at least two coded height or building-area rules (so
the rules differ by zone); on the map, a property number (e.g. “5:125”) printed at most twice, whose surroundings carry
one of those codes; scale labels, legend and title-block areas and unconfirmed tract names are filtered; at most two per
municipality. The crop around the property is saved. {s['plan_candidates']} candidates.</li>
<li><b>Reference</b> (<code>label</code>, one vision call per candidate, high effort): the model gets the crop and the
meaning of the codes from the plan legend, decides which zone the property is in and which codes apply, and designs a
realistic project (house, extension, garage) <b>within</b> the limits for half of the cases and <b>slightly above</b>
one limit for the other half, so that “not feasible” is not a free win. It writes the question in the owner's words,
without plan codes, and the key points with each code and value. Only high-confidence labels are kept:
{len(plan_cases)} cases in {len({c['kommun'][0] for c in plan_cases})} municipalities ({plan_verdicts}).</li>
<li><b>Evidence</b> = the plan map document (<code>doc_id</code>): the system must have had it in front of it.</li>
</ol>
<p><b>Real or constructed.</b> The plan, the map, the property and its codes are real; the project and the question are
constructed, and the reference is a model's reading of the map. The crops are kept in
<code>data/agentic/plan_cases/</code> for a manual check; a sample should be reviewed by a person.</p>

<h3>7.4 Example cases</h3>
{examples}
{plan_example}

<h3>7.5 Evidence labels and matching</h3>
<p>A matcher is a dict checked against every chunk the agent was shown ({code('localrag/eval.py')} <code>matches</code>):
<code>law</code> (substring of the statute title) + <code>section</code> or <code>contains</code> (verbatim phrase,
whitespace- and case-normalised), <code>kommun_code</code> + <code>contains</code> / <code>title</code>, or
<code>any</code> (alternatives). For MÖD cases, the generator asks for 5–12 words of the statute as quoted in the ruling,
then keeps the <b>longest run of ≥ 5 consecutive words found in the current statute text</b>
(<code>longest_phrase</code>): this survives renumbering and small amendments (“tas i anspråk” → “tas i anspråk eller
inreds”). Without a match, a section number is used only outside the renumbered PBL 9 kap.; otherwise the case has no
evidence label. <code>check_labels</code> refuses to run a benchmark whose labels match no chunk.</p>
<h3>7.6 Metrics</h3>
<table>
<tr><th>Metric</th><th>Formula</th><th>Code</th></tr>
<tr><td>verdict_ok</td><td>judge's verdict ∈ accepted verdicts</td><td><code>judge</code>, <code>run_case</code></td></tr>
<tr><td>points</td><td>Σ judge scores (0/1/2 per key point) / (2 × number of key points)</td><td><code>run_case</code></td></tr>
<tr><td>evidence (seen)</td><td>share of matchers satisfied by at least one chunk the system saw (agent: tool outputs;
RAG: retrieved chunks), no LLM</td><td><code>evidence_recall</code></td></tr>
<tr><td>evidence cited</td><td>share of matchers satisfied by at least one chunk the answer cites ([c:id], truncated ids
resolved by unique prefix), no LLM</td><td>{code('agentic/report.py')} <code>reading_metrics</code></td></tr>
<tr><td>passages seen</td><td>distinct chunk ids in the tool outputs (agent) or retrieved (RAG). A precision “relevant /
read” is not computed: the evidence labels list the decisive passages (1–3 per case), not every useful one, so most
useful passages would count as irrelevant, and more so for the agent, which reads 3–4 times more</td>
<td><code>reading_metrics</code></td></tr>
<tr><td>grounded</td><td>supported claims / claims, second judge with the full text of the cited chunks</td>
<td>{code('agentic/grounding.py')}</td></tr>
<tr><td>unsupported</td><td>claims in neither the reference nor the cited sources (first judge)</td><td><code>judge</code></td></tr>
<tr><td>seconds, first_token_s, cost</td><td>wall time; time to the first streamed answer token; OpenRouter
<code>usage.cost</code> summed over calls</td><td>{code('agentic/agent.py')} <code>AgentRun</code></td></tr>
</table>
<p>The judge receives the question, the key points, the accepted verdicts, the answer and up to 15 cited chunks
(1,500 characters each). Prompt ({code('agentic/bench.py')} <code>JUDGE_INSTRUCTIONS</code>):</p>
{judge_prompt}
<p>Grounding prompt ({code('agentic/grounding.py')} <code>INSTRUCTIONS</code>):</p>
{grounding_prompt}
<h3>7.7 Protocol</h3>
<ul>
<li>Systems: the agent (<code>run_agent</code>, efforts set per run) and a classic RAG baseline (<code>run_rag</code> in
{code('agentic/bench.py')}: the chat's local pipeline, i.e. a rewrite call that also writes a Swedish search query, one
dense search on it with the municipality filter, the top 10 statute sections + top 10 municipal passages, one streamed
answer in the same format). Evidence for the RAG = the passages it retrieved.</li>
<li>Corpus: the full disk store (<code>--store disk</code>), so cases from any municipality are answerable.</li>
<li>Same model for agent and judges (GPT-6 Luna via OpenRouter); judge effort medium.</li>
<li>Repeats (<code>--repeats</code>) and merged files give 2–4 passes per configuration; per-pass means measure noise.</li>
<li>Cases run in parallel (<code>--workers 3</code>): latencies include some contention.</li>
<li>Results are written after every case (<code>data/agentic/bench-*.json</code>, one row per answer with the full
answer, tool steps and judge comment); <code>--resume</code> completes an interrupted run.</li>
<li>Reports: {code('agentic/report.py')} (summary) and this file, {code('agentic/report_technical.py')}.</li>
</ul>
<h3>7.8 Scope: which questions these benchmarks represent</h3>
<p>The three sets ask one kind of question: <b>a defined project at a known place: is it feasible, under which rules,
and how to get it approved?</b> This is pre-application screening. Within it, the sets are skewed in known ways:</p>
<ul>
<li>The place is always given (municipality, often the plan or the property) and the project is specified (use, size,
height); the question is single-turn, in English.</li>
<li>The 14 case studies come from 5 municipalities that the corpus covers well: coverage is better than for an
average municipality.</li>
<li>Appealed rulings are contested cases by selection: more borderline situations and more refusals than ordinary
applications, so the MÖD set is harder than typical traffic and refusal-heavy.</li>
<li>The plankarta cases are designed so that about half the projects slightly exceed a limit.</li>
</ul>
<p><b>Not measured</b>, although plausible uses of the tool:</p>
<ul>
<li><b>Shaping a project from a vague idea</b> (“I have land near Stockholm and want to build a small eco-village: what
could I build, where, and in which order?”): proposing options, the constraints that decide between them, the questions
to ask the municipality, over several turns. No set rewards a good design conversation; the verdict / key-point scoring
does not fit it.</li>
<li>Process guidance beyond the key points (documents to submit, sequencing of permits, timelines), and follow-up
turns.</li>
<li>Finding where a project is possible (which municipality, plan or site allows it) and comparing rules across
municipalities.</li>
<li>Questions where the user does not know the property or the plan, and arguments addressed to the municipality or
the neighbours.</li>
</ul>
<p>The scores therefore say how well Pyrmit <i>checks</i> a defined project, not how well it helps <i>build</i> one.
The target use cases, and so the next benchmark, should come from the product vision defined with the project team
and the client, for example real project briefs, written as the users would bring them.</p>

<h2>8. Results summary</h2>
<p>Classic RAG and the agent at its default setting (exploration medium, answer medium) on the three sets; all
configurations, charts and the reading of the results are in the benchmark report.</p>
{overview}
{results_text}

<h2>9. Limitations and roadmap</h2>
<ul>
<li><b>Evaluation</b>: LLM judge = agent model (possible leniency); key points written by an LLM; no human review yet.
Next: expert review of a sample, a second judge model, inter-judge agreement.</li>
<li><b>Scope of the benchmarks</b>: only feasibility checks of a defined project at a known place (section 7.8); helping
shape a project from a vague idea, multi-turn guidance and site search are not measured. The use cases to evaluate
next come from the product vision (project team and client).</li>
<li><b>Data</b>: coverage depends on each municipality's website; no property → plan link; no spatial layers; no
provenance dates (section 4). Next: provenance metadata, scheduled incremental refresh, Lantmäteriet and county GIS data.</li>
<li><b>Plans</b>: provisions are extracted as text; which map area carries which code needs a vision model on the plan
map.</li>
<li><b>Agent</b>: verdict calibration on refusals (prompt), default exploration effort medium, a fast low-effort mode.</li>
</ul>

<h2>Appendix: commands and files</h2>
<pre class="prompt">cd backend
python -m corpus.municipalities && python -m corpus.laws && python -m corpus.crawl
python -m corpus.ocr && python -m corpus.extract && python -m corpus.chunk
python -m localrag.index --model st-arctic-l-v2 && python -m localrag.store --model st-arctic-l-v2 && python -m corpus.plans
python -m localrag.eval --models st-arctic-l-v2
python -m corpus.caselaw && python -m agentic.cases_from_caselaw
python -m agentic.bench --systems agent --store disk --explore-effort medium --effort medium \\
    --cases-file cases_caselaw.jsonl --sample 50 --repeats 2 --workers 3
python -m agentic.grounding data/agentic/bench-....json
python -m agentic.report && python -m agentic.report_technical</pre>"""
    else:
        body = f"""
<h1>Pyrmit – rapport technique</h1>
<div class="sub">Données, contexte juridique suédois, pipeline et méthodologie d'évaluation. Complément du rapport de
benchmark. Généré le {today:%d/%m/%Y} ; les chiffres sont lus dans les données et fichiers de résultats à la génération.</div>
<div class="toc">
<div>1. À quoi sert le système</div><div>2. Le système d'urbanisme suédois et la place de Pyrmit</div>
<div>3. Sources de données : quoi, pourquoi, comment</div><div>4. Garder les données à jour</div>
<div>5. Pipeline, avec références dans le code</div><div>6. Évaluation de la recherche</div>
<div>7. Évaluation de l'agent : méthodologie détaillée</div><div>8. Synthèse des résultats</div>
<div>9. Limites et feuille de route</div><div>Annexe : commandes et fichiers</div>
</div>

<h2>1. À quoi sert le système</h2>
<p>Pyrmit répond, en anglais, à la question : ce projet de construction ou d'aménagement est-il faisable dans telle
commune suédoise, et comment le faire autoriser ? Il identifie les règles qui décident (loi nationale, plans et
consignes de la commune), les autorisations nécessaires et ce qui reste incertain. Toute règle, chiffre ou délai doit
citer un passage que le système a réellement lu ; les citations ouvrent le document original à ce passage. C'est un
outil de <b>pré-instruction</b> : il ne remplace pas la décision de la commune, et ses réponses disent ce qu'il faut
vérifier.</p>

<h2>2. Le système d'urbanisme suédois et la place de Pyrmit</h2>
<h3>2.1 Qui décide quoi</h3>
<ul>
<li><b>Monopole communal de la planification.</b> Planifier l'usage du sol et de l'eau est une affaire communale
(PBL 1 kap. 2 §). La commission de la construction (byggnadsnämnd) délivre les autorisations ; les organes de la
commune adoptent les plans.</li>
<li><b>Plan d'ensemble (översiktsplan, PBL 3 kap.)</b> : couvre toute la commune, fixe des intentions (où construire, quoi
protéger). Non contraignant, mais il oriente les décisions d'autorisation et de planification.</li>
<li><b>Plan détaillé (detaljplan, PBL 4 kap.)</b> : contraignant sur une zone : usage du sol (habitat, voirie, nature…) et
prescriptions (emprise au sol, hauteur de faîtage, nombre d'étages, taille minimale des parcelles, terrain non
constructible, aspect, durée de mise en œuvre). Il comprend une <i>plankarta</i> (carte avec codes et prescriptions) et
une <i>planbeskrivning</i> (notice). Il passe par la concertation (samråd), l'examen (granskning), l'adoption
(antagande) puis devient exécutoire (laga kraft). Les områdesbestämmelser sont un outil contraignant plus léger.</li>
<li><b>Autorisations (PBL 9 kap.)</b> : permis de construire (bygglov), de démolir (rivningslov), d'aménager (marklov) ;
certains travaux demandent seulement une déclaration (anmälan) ou en sont dispensés (ex. travaux « Attefall »). Dans un
plan détaillé, le projet doit être conforme au plan (de petits écarts peuvent être admis) ; hors plan, le site est jugé
sur les exigences générales d'aptitude du PBL 2 kap. Un avis préalable (förhandsbesked) peut trancher d'abord la question
de l'implantation. <b>Attention</b> : le PBL 9 kap. a été renuméroté par la SFS 2025:974 (conditions du bygglov
désormais 9 kap. 56–57 §, petits écarts 60–61 §, förhandsbesked 74 §) ; la jurisprudence et la plupart des guides
utilisent encore les anciens numéros.</li>
<li><b>Contraintes du Code de l'environnement (miljöbalken)</b> qui décident souvent : protection du rivage (strandskydd,
MB 7 kap. ; construire exige une dérogation avec un motif particulier), terres agricoles productives (MB 3 kap. 4 § :
seulement pour un intérêt public essentiel), zones d'intérêt national (MB 3–4 kap.).</li>
<li><b>Eau et assainissement</b> : zones de service public (LAV) ; un assainissement individuel exige une autorisation ou
une déclaration auprès de la commission de l'environnement de la commune (förordningen om miljöfarlig verksamhet och
hälsoskydd, 13–14 §§).</li>
<li><b>Division foncière</b> (fastighetsbildning) : décidée par Lantmäteriet selon la fastighetsbildningslag ; le plan
détaillé peut fixer une taille minimale de parcelle.</li>
<li><b>Recours</b> : les décisions de la commission de la construction vont devant la préfecture (länsstyrelsen), puis le
tribunal foncier et environnemental (mark- och miljödomstol), puis la Cour d'appel foncière et environnementale
(Mark- och miljööverdomstolen, MÖD), sur autorisation, qui fait jurisprudence. Les décisions d'adoption d'un plan
détaillé vont directement devant le tribunal foncier et environnemental.</li>
</ul>
<h3>2.2 La place de Pyrmit</h3>
<table>
<tr><th>Question dans un projet</th><th>Base juridique</th><th>Ce que Pyrmit lit</th></tr>
<tr><td>Mon terrain est-il dans un plan détaillé, et que permet-il ?</td><td>PBL 4 kap., prescriptions du plan</td>
<td>Registre des plans, plankartor et notices récupérées sur le site de la commune (outils <code>plans</code>,
<code>plan_rules</code>, <code>read</code>)</td></tr>
<tr><td>Faut-il un permis, une déclaration, ou rien ?</td><td>PBL 9 kap., PBF</td><td>Texte de loi (<code>law_section</code>),
pages permis de la commune</td></tr>
<tr><td>Puis-je construire hors plan / obtenir un avis préalable ?</td><td>PBL 2 kap., 9 kap.</td><td>Texte de loi, plan
d'ensemble, consignes communales</td></tr>
<tr><td>Rivage, terres agricoles, intérêts nationaux ?</td><td>MB 3, 4, 7 kap.</td><td>Texte de loi, plan d'ensemble, pages
communales sur le strandskydd</td></tr>
<tr><td>Eau et assainissement, taxes, délais ?</td><td>LAV, FMH, barèmes communaux (taxa)</td><td>Pages et PDF communaux
(assainissement, taxa)</td></tr>
</table>
<p>Le système reproduit la démarche d'un instructeur : identifier la commune et le site, vérifier la situation au regard
des plans, trouver les règles nationales applicables, puis les documents locaux. Il s'arrête là où il faudrait des
données officielles qu'il n'a pas encore (quel plan couvre telle parcelle, cartes des zones protégées) et le dit dans la
réponse.</p>

<h2>3. Sources de données : quoi, pourquoi, comment</h2>
<table>
<tr><th>Source</th><th>Ce qu'on prend</th><th>Pourquoi cette source</th><th>Comment (code)</th><th>Conditions</th></tr>
<tr><td>Données ouvertes du Riksdag (data.riksdagen.se)</td><td>{len(s['laws'])} lois et règlements consolidés (PBL, PBF,
MB, JB, FBL, LAV, FMH…)</td><td>Texte consolidé officiel avec marqueurs de modification ; API gratuite</td>
<td>{code('corpus/laws.py')} (<code>LAWS</code>, <code>main</code>)</td><td>Données ouvertes, citer le Riksdag</td></tr>
<tr><td>Wikidata (SPARQL)</td><td>{s['municipalities']} communes : code officiel, comté, site web ; ~10 000 localités</td>
<td>Identifiants stables et sites officiels ; localités pour lieu → commune</td><td>{code('corpus/municipalities.py')}
(<code>sparql</code>, <code>pick_site</code>)</td><td>CC0</td></tr>
<tr><td>Sites des communes</td><td>{num(c['pages'])} pages, {num(c['pdfs'])} PDF ({c['pdf_gb']} Go) : permis,
assainissement, taxes, plans, plans d'ensemble</td><td>Les règles locales et les plans détaillés sont publiés par chaque
commune ; pas de source nationale en texte intégral</td><td>{code('corpus/crawl.py')} (<code>content_relevance</code>,
<code>crawl</code>)</td><td>Pages publiques ; robots.txt respecté, 1 requête/s par site</td></tr>
<tr><td>OCR local (EasyOCR, GPU)</td><td>Texte de {num(s['ocr'])} PDF scannés (anciennes plankartor)</td><td>Les vieux plans
n'ont pas de couche texte</td><td>{code('corpus/ocr.py')}</td><td>Traitement local</td></tr>
<tr><td>Registre des plans (dérivé)</td><td>{num(s['plans'])} plans, dont {num(s['plans_with_rules'])} avec
{num(s['provisions'])} prescriptions extraites</td><td>L'agent a besoin des plans comme entités, avec statut et règles</td>
<td>{code('corpus/plans.py')} (<code>plan_key</code>, <code>provisions_of</code>, <code>status_of</code>)</td><td>Dérivé</td></tr>
<tr><td>Jurisprudence MÖD via lagen.nu</td><td>{s['rulings']} arrêts depuis 2011, dont {s['rulings_relevant']} sur nos
sujets</td><td>Vraies décisions avec faits, issue et motifs : vérité terrain du benchmark</td><td>{code('corpus/caselaw.py')}
(<code>parse_case</code>, <code>relevant</code>)</td><td>Les décisions de justice sont des documents publics non protégés
par le droit d'auteur ; le robots.txt de lagen.nu autorise les pages d'arrêts</td></tr>
</table>
<h3>3.1 Versions des lois dans le corpus</h3>
<table><tr><th>Texte</th><th>Consolidé jusqu'à</th><th>Téléchargé le</th></tr>{laws_rows}</table>
<h3>3.2 Crawl</h3>
<p>{c['kommuner']} communes crawlées entre le {c['first']} et le {c['last']} ({num(c['requests'])} requêtes). Le crawler
part du site officiel, suit les liens notés par mots-clés thématiques (permis, plans, assainissement, taxes ; mots-clés
négatifs pour les rubriques hors sujet), garde les pages de score ≥ 4 (<code>KEEP_SCORE</code>), les PDF liés depuis des
pages pertinentes, et plafonne chaque commune (300 pages, 150 PDF, 40 Mo par PDF, 1 500 requêtes, profondeur 4, quotas
par rubrique). Le texte est extrait par blocs avec PyMuPDF, en-têtes et pieds de page répétés retirés
({code('corpus/extract.py')} <code>page_blocks</code>, <code>strip_boilerplate</code>), et chaque document est classé
(<code>doc_type</code> : {doc_types}).</p>
<p>Corpus servi par l'app : {num(s.get('chunks', 0))} passages dans {num(s.get('docs', 0))} documents,
{s.get('kommuner', 0)} communes, {num(s.get('law_chunks', 0))} articles de loi. Statuts des plans du registre :
{plan_status}.</p>
<h3>3.3 Sources pas encore utilisées (et pourquoi elles comptent)</h3>
<ul>
<li><b>Lantmäteriet</b> : registre foncier (désignations cadastrales, limites) et accès national aux plans détaillés
numériques. Indispensable pour répondre de façon fiable à « quel plan couvre ma parcelle ». Conditions d'accès et API à
confirmer (certaines sont payantes).</li>
<li><b>Svensk författningssamling</b> (svenskforfattningssamling.se) : publication officielle des nouveaux textes ; utile
pour détecter une modification avant la mise à jour du texte consolidé.</li>
<li><b>Préfectures et agences nationales</b> : couches SIG du strandskydd, des intérêts nationaux, des espaces protégés ;
guides de Boverket (PBL kunskapsbanken). Elles transformeraient les questions spatiales (« ma parcelle est-elle à moins de
100 m du rivage ? ») en simples consultations de données.</li>
<li><b>Services de plans des communes</b> (WMS / registres de plans) : beaucoup de communes publient les périmètres des plans
en service cartographique ; avec une adresse ou une parcelle, on obtient le plan applicable.</li>
</ul>

<h2>4. Garder les données à jour</h2>
<h3>4.1 Situation actuelle (sans fard)</h3>
<ul>
<li>Lois : la version consolidée est visible dans le texte brut (« t.o.m. SFS … », tableau 3.1) mais pas stockée en
métadonnée ; les articles qui ont deux versions (en vigueur / à une date future) sont indexés toutes les deux.</li>
<li>Documents communaux : <b>aucune date de récupération ni en-tête HTTP de validation n'est stocké par page ou PDF</b>
(le manifeste du crawl garde id, URL, titre, score) ; la seule date est celle du crawl ({c['first']}–{c['last']}). Les
barèmes de taxes changent chaque année ; les pages de plans changent au fil de la procédure.</li>
<li>Plans : le statut est déduit des URL et du texte (date de laga kraft, « antagandehandling »…) ; les plans remplacés
ou abrogés ne sont pas suivis.</li>
<li>Les reconstructions sont manuelles : extraction → découpage → embeddings (incrémental) → store → registre des plans.
Les identifiants de passages incluent un hash du texte : les passages inchangés gardent leurs vecteurs.</li>
</ul>
<h3>4.2 Comment garantir la fraîcheur</h3>
<ol>
<li><b>Provenance sur chaque document</b> : date de récupération, ETag / Last-Modified HTTP, hash du contenu, URL source, et
pour les lois la version « t.o.m. SFS » et la date d'entrée en vigueur de chaque version d'article. Affichées dans le
panneau des sources et dans la réponse (« page communale récupérée le … »).</li>
<li><b>Rafraîchissement planifié selon la volatilité</b> : lois chaque semaine (API du Riksdag, comparaison du marqueur de
version ; svenskforfattningssamling.se pour les nouveaux textes) ; pages plans et permis chaque semaine, le reste du
crawl chaque mois, avec requêtes conditionnelles (If-None-Match / If-Modified-Since) et sitemaps pour qu'une page
inchangée ne coûte qu'une requête légère ; jurisprudence chaque mois.</li>
<li><b>Pipeline incrémental</b> : réextraire et redécouper seulement les documents modifiés, n'embedder que les nouveaux
identifiants, mettre le store à jour en place (ajout / suppression de lignes et de vecteurs) au lieu de tout
reconstruire ; reconstruire le registre des plans des seules communes touchées.</li>
<li><b>Validité juridique</b> : indexer chaque version d'article avec son intervalle de validité (le texte consolidé marque
les versions futures « Träder i kraft I:… » et celles qui expirent « Upphör att gälla U:… »), répondre avec la version en
vigueur à la date de la question ; suivre les changements de statut des plans (adopté → exécutoire → modifié / abrogé).</li>
<li><b>Préférer les sources officielles</b> quand elles existent (plans numériques et données foncières de Lantmäteriet)
aux copies crawlées, et garder le crawl pour ce qui n'a pas de source nationale (consignes locales, taxes).</li>
<li><b>Surveillance et non-régression</b> : après chaque rafraîchissement, un rapport des sources modifiées / en échec par
commune, et un passage du benchmark (échantillon MÖD) pour détecter une régression ; alerte quand la structure d'un site
change (chute du nombre de pages récupérées).</li>
</ol>

<h2>5. Pipeline, avec références dans le code</h2>
<table>
<tr><th>Étape</th><th>Rôle</th><th>Code</th></tr>
<tr><td>Communes</td><td>SPARQL Wikidata → codes, sites, localités</td><td>{code('corpus/municipalities.py')}</td></tr>
<tr><td>Lois</td><td>API du Riksdag → texte brut par SFS</td><td>{code('corpus/laws.py')}</td></tr>
<tr><td>Crawl</td><td>Asynchrone, robots.txt, 1 req/s/site, score thématique, plafonds, manifestes reprenables</td><td>{code('corpus/crawl.py')}</td></tr>
<tr><td>OCR</td><td>EasyOCR sv+en sur GPU, pages en tuiles, plans d'abord</td><td>{code('corpus/ocr.py')}</td></tr>
<tr><td>Extraction</td><td>Blocs PyMuPDF, retrait des en-têtes, types de documents, texte OCR si besoin</td><td>{code('corpus/extract.py')}</td></tr>
<tr><td>Découpage</td><td>Un passage par article de loi (chapitre seulement sur sa propre ligne, § à lettre, dispositions
transitoires retirées) ; passages de ~1 500 caractères pour les documents ; dédoublonnage global ; id = hash(doc, rang,
texte)</td><td>{code('corpus/chunk.py')} (<code>law_chunks</code>, <code>document_chunks</code>)</td></tr>
<tr><td>Embeddings</td><td>Snowflake arctic-embed-l-v2 (1024 dim) sur GPU, incrémental</td><td>{code('localrag/index.py')},
{code('embeddings.py')}</td></tr>
<tr><td>Store disque</td><td>SQLite (passages, BM25 FTS5 sur racines suédoises avec jetons de filtre bassin / commune) +
vecteurs float16 (memmap → GPU)</td><td>{code('localrag/store.py')} (<code>build</code>, <code>DiskStore</code>,
<code>DiskRetriever</code>)</td></tr>
<tr><td>Registre des plans</td><td>Plans, statut, prescriptions reliées aux passages</td><td>{code('corpus/plans.py')}</td></tr>
<tr><td>Lieu → commune</td><td>Noms et localités Wikidata ∪ noms de lieux du corpus</td><td>{code('localrag/gazetteer.py')}</td></tr>
<tr><td>Outils de l'agent</td><td>find_kommun, search (hybride RRF), grep, list_documents, read, law_section, plans,
plan_rules, view_pdf_page ; chaque sortie marquée [c:chunk_id]</td><td>{code('agentic/tools.py')} (<code>CorpusTools</code>,
<code>TOOL_SCHEMAS</code>)</td></tr>
<tr><td>Boucle de l'agent</td><td>Boucle d'outils (Responses API) : tours d'exploration à <code>explore_effort</code>, appels
en parallèle, <code>answer_ready</code>, réponse finale streamée à <code>effort</code>, budget de tours</td>
<td>{code('agentic/agent.py')} (<code>run_agent</code>, <code>SYSTEM_PROMPT</code>)</td></tr>
<tr><td>Intégration au chat</td><td>Thread de fond, événements SSE, numérotation des citations à la volée, trace sauvegardée</td>
<td>{code('agentic/service.py')} (<code>stream_agent</code>, <code>CitationNumberer</code>), {code('routers/chat.py')}</td></tr>
<tr><td>Visionneuse de sources</td><td>Passage cité → page du PDF surlignée, ou fragment de texte d'URL</td>
<td>{code('routers/docs.py')}, {code('frontend/components/SourceViewer.tsx')}</td></tr>
</table>
<p><b>Ancrage par construction.</b> Les sorties d'outils portent les identifiants de passages ; le format de réponse exige
un [c:id] pour chaque règle, chiffre, taxe ou délai, et interdit d'affirmer ce qui n'a pas été lu dans un outil. Le chat
remplace les identifiants par des numéros pendant le streaming et associe à chaque numéro les passages cités
(événement <code>citations</code>).</p>

<h2>6. Évaluation de la recherche</h2>
<p>{code('localrag/eval.py')} sur {code('localrag/questions.jsonl')} : 45 questions d'usage (permis, plans, assainissement,
taxes, hauteurs…), chacune étiquetée par les passages qui y répondent (extraits exacts de documents communaux ou
articles de loi). Mesures par question : rappel@k = part des passages attendus présents dans les k premiers ;
complet@5 = tous les passages attendus dans les 5 premiers ; MRR = 1 / rang du premier passage attendu. Le filtre
communal est détecté dans la question. Réglages : <i>dense-en</i> / <i>dense-sv</i> = embedding de la question anglaise /
d'une reformulation suédoise ; <i>bm25</i> = BM25 sur les mots suédois ; <i>hybrid</i> = fusion par rang réciproque ;
<i>+rerank</i> = cross-encoder bge-reranker-v2-m3.</p>
{retrieval}
<p><b>Constats</b> : interroger en suédois est décisif (+13 à +28 points de rappel@5 par rapport à la question anglaise, selon le modèle) ; les
modèles ouverts locaux égalent les modèles d'API (arctic-embed-l-v2 : 0,92 de rappel@5) ; BM25 sur une question anglaise
ne sert à rien sur un corpus suédois ; ni la fusion BM25 ni le reranker ne battent la recherche dense sur la question
suédoise. L'agent garde la recherche hybride, car la formulation exacte (noms de plans, « 20 meter ») compte dans ses
appels d'outils.</p>

<h2>7. Évaluation de l'agent : méthodologie détaillée</h2>
<h3>7.1 Jeux de cas</h3>
<ul>
<li><b>14 études de cas</b> ({code('agentic/cases.jsonl')}), écrites à la main. Champs : <code>question</code>,
<code>kommun</code> (codes), <code>verdicts</code> (acceptés), <code>key_points</code>, <code>evidence</code> (matchers),
<code>source</code>.</li>
<li><b>{s['caselaw_cases']} cas MÖD</b> ({code('agentic/cases_caselaw.jsonl')}) générés par
{code('agentic/cases_from_caselaw.py')} à partir de {s['rulings_relevant']} arrêts thématiques : un appel LLM par arrêt
avec le prompt ci-dessous ; brouillons en cache dans <code>data/corpus/raw/caselaw/case_drafts.jsonl</code> ; rejet si
non utilisable (procédure, sanctions, qualité pour agir) ou si la question mentionne le tribunal (regex <code>LEAK</code>) ;
nom de commune → code (<code>kommun_codes</code>, formes au génitif) ; articles → matchers de preuve
(<code>evidence_for</code>).</li>
<li><b>Échantillonnage</b> : <code>sample_cases</code> dans {code('agentic/bench.py')} tire N cas avec une graine fixe, à tour
de rôle dans trois strates (négative = refusé, positive = accepté, ouverte = renvoi / dépend des faits), cas étiquetés
d'abord. Le rapport utilise N = {len(sample)}.</li>
</ul>
<p>Prompt de génération des cas ({code('agentic/cases_from_caselaw.py')} <code>INSTRUCTIONS</code>) :</p>
{case_prompt}
<h3>7.2 Étiquettes de preuve et correspondance</h3>
<p>Un matcher est un dictionnaire testé sur chaque passage montré à l'agent ({code('localrag/eval.py')} <code>matches</code>) :
<code>law</code> (sous-chaîne du titre de la loi) + <code>section</code> ou <code>contains</code> (phrase exacte, casse et
espaces normalisés), <code>kommun_code</code> + <code>contains</code> / <code>title</code>, ou <code>any</code>
(alternatives). Pour les cas MÖD, le générateur demande 5 à 12 mots de l'article tel que l'arrêt le cite, puis garde la
<b>plus longue suite d'au moins 5 mots consécutifs présente dans le texte de loi actuel</b> (<code>longest_phrase</code>) :
cela résiste à la renumérotation et aux petites modifications (« tas i anspråk » → « tas i anspråk eller inreds »). Sans
correspondance, un numéro d'article n'est utilisé qu'en dehors du PBL 9 kap. renuméroté ; sinon le cas n'a pas
d'étiquette de preuve. <code>check_labels</code> refuse de lancer un benchmark dont une étiquette ne correspond à aucun
passage.</p>
<h3>7.3 Mesures</h3>
<table>
<tr><th>Mesure</th><th>Formule</th><th>Code</th></tr>
<tr><td>verdict_ok</td><td>verdict du juge ∈ verdicts acceptés</td><td><code>judge</code>, <code>run_case</code></td></tr>
<tr><td>points</td><td>Σ notes du juge (0/1/2 par point clé) / (2 × nombre de points clés)</td><td><code>run_case</code></td></tr>
<tr><td>evidence</td><td>part des matchers satisfaits par au moins un passage vu par l'agent (sorties d'outils), sans LLM</td>
<td><code>evidence_recall</code></td></tr>
<tr><td>grounded</td><td>affirmations soutenues / affirmations, second juge avec le texte complet des passages cités</td>
<td>{code('agentic/grounding.py')}</td></tr>
<tr><td>unsupported</td><td>affirmations ni dans la référence ni dans les sources citées (premier juge)</td><td><code>judge</code></td></tr>
<tr><td>seconds, first_token_s, cost</td><td>temps total ; temps jusqu'au premier token de la réponse streamée ;
<code>usage.cost</code> d'OpenRouter sommé sur les appels</td><td>{code('agentic/agent.py')} <code>AgentRun</code></td></tr>
</table>
<p>Le juge reçoit la question, les points clés, les verdicts acceptés, la réponse et jusqu'à 15 passages cités
(1 500 caractères chacun). Prompt ({code('agentic/bench.py')} <code>JUDGE_INSTRUCTIONS</code>) :</p>
{judge_prompt}
<p>Prompt d'ancrage ({code('agentic/grounding.py')} <code>INSTRUCTIONS</code>) :</p>
{grounding_prompt}
<h3>7.4 Protocole</h3>
<ul>
<li>Corpus : le store disque complet (<code>--store disk</code>), pour que les cas de toute commune aient une réponse
possible.</li>
<li>Même modèle pour l'agent et les juges (GPT-6 Luna via OpenRouter) ; juge en effort medium.</li>
<li>Répétitions (<code>--repeats</code>) et fichiers fusionnés : 2 à 4 passages par configuration ; les moyennes par
passage mesurent le bruit.</li>
<li>Cas en parallèle (<code>--workers 3</code>) : les latences incluent un peu de contention.</li>
<li>Résultats écrits après chaque cas (<code>data/agentic/bench-*.json</code>, une ligne par réponse avec la réponse
complète, les étapes d'outils et le commentaire du juge) ; <code>--resume</code> complète un run interrompu.</li>
<li>Rapports : {code('agentic/report.py')} (synthèse) et ce document, {code('agentic/report_technical.py')}.</li>
</ul>

<h2>8. Synthèse des résultats</h2>
<p>Échantillon MÖD ({len(sample)} cas) ; détails et graphiques dans le rapport de benchmark.</p>
{table_mod}
{verdicts_mod}
<p>L'effort d'exploration est le réglage qui compte (preuves 0,53 → 0,70, ancrage 0,69 → 0,79) ; une réponse en effort
high n'apporte rien ; l'agent sous-utilise « non faisable » sur les projets refusés (40 à 60 %).</p>

<h2>9. Limites et feuille de route</h2>
<ul>
<li><b>Évaluation</b> : juge LLM = modèle de l'agent (complaisance possible) ; points clés rédigés par un LLM ; pas encore de
relecture humaine. Suite : relecture d'un échantillon par un expert, second modèle juge, accord entre juges.</li>
<li><b>Données</b> : couverture dépendante du site de chaque commune ; pas de lien parcelle → plan ; pas de couches
spatiales ; pas de dates de provenance (section 4). Suite : métadonnées de provenance, rafraîchissement incrémental
planifié, données Lantmäteriet et SIG des préfectures.</li>
<li><b>Plans</b> : les prescriptions sont extraites en texte ; savoir quelle zone de la carte porte quel code demande un
modèle de vision sur la plankarta.</li>
<li><b>Agent</b> : calibrage du verdict sur les refus (prompt), exploration medium par défaut, mode rapide en low.</li>
</ul>

<h2>Annexe : commandes et fichiers</h2>
<pre class="prompt">cd backend
python -m corpus.municipalities && python -m corpus.laws && python -m corpus.crawl
python -m corpus.ocr && python -m corpus.extract && python -m corpus.chunk
python -m localrag.index --model st-arctic-l-v2 && python -m localrag.store --model st-arctic-l-v2 && python -m corpus.plans
python -m localrag.eval --models st-arctic-l-v2
python -m corpus.caselaw && python -m agentic.cases_from_caselaw
python -m agentic.bench --systems agent --store disk --explore-effort medium --effort medium \\
    --cases-file cases_caselaw.jsonl --sample 50 --repeats 2 --workers 3
python -m agentic.grounding data/agentic/bench-....json
python -m agentic.report && python -m agentic.report_technical</pre>"""

    title = tr("Pyrmit – rapport technique", "Pyrmit – technical report")
    return (f'<!doctype html><html lang="{LANG}"><head><meta charset="utf-8"><title>{title}</title>{report.STYLE}'
            f"{EXTRA_STYLE}</head><body>{body}\n</body></html>")


def main() -> None:
    global LANG
    parser = argparse.ArgumentParser(description="Detailed technical report (data, legal context, pipeline, evaluation)")
    parser.add_argument("--lang", choices=["en", "fr", "both"], default="en")
    args = parser.parse_args()
    report.DOC_DIR.mkdir(parents=True, exist_ok=True)
    browser = report.find_browser()
    for LANG in (["fr", "en"] if args.lang == "both" else [args.lang]):
        report.write_pdf(build_html(), OUTPUT_NAMES[LANG], browser)


if __name__ == "__main__":
    main()

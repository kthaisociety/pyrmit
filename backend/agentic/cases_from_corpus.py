"""
Benchmark cases beyond the verdict, drafted from corpus documents (agentic/cases_tasks.jsonl holds the hand-written
seeds of the same kinds):

  explain   one kommun guidance page (bygglov, avlopp, taxa, strandskydd, planbesked...) -> a question in the user's
            words, key points each backed by a verbatim quote of the page
  propose   the kommun's översiktsplan passages that name places for growth -> "where in <kommun> could we build X?"
            (no place inside the kommun named), the places the plan designates as anchors, constraints as key points
  develop   a project idea (IDEAS) + the kommun's rural-development / VA passages + core statutes -> obstacles, levers
            and the facts to ask the user for

Quotes are checked against the source texts (longest run of >= 5 words found, as for the MÖD cases); a point or
anchor whose quote is not found is dropped, and a case needs 3 key points (propose: 2 key points and 3 anchors) left.
The drafting model defaults to another model family than the agent (MiMo v2.6 Flash), so the reference is not
written by the model under test. Seed kommuner (SEED_KOMMUNER) are skipped.

Spends API credits (one call per case, ~$0.002 with MiMo Flash); drafts are cached in data/agentic/task_drafts.jsonl
(rebuilding costs nothing, --regenerate pays again):

    cd backend
    python -m agentic.cases_from_corpus --per-task 2       # a few, then inspect agentic/cases_generated.jsonl
    python -m agentic.cases_from_corpus --per-task 10
    CUDA_VISIBLE_DEVICES= python -m agentic.bench --cases-file cases_generated.jsonl --store disk --leakage
"""

import argparse
import json
import os
import random
import re
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agentic.cases_from_caselaw import longest_phrase
from corpus.common import read_jsonl, stable_id, write_jsonl
from localrag.eval import normalize
from localrag.index import INDEX_DIR
from localrag.store import store_dir
from llm import get_openai_client, get_response_output_text, resolve_model_name

OUTPUT_PATH = Path(__file__).resolve().parent / "cases_generated.jsonl"
DRAFTS_PATH = INDEX_DIR.parent / "agentic" / "task_drafts.jsonl"
DEFAULT_MODEL = "xiaomi/mimo-v2.6-flash"
SEED_KOMMUNER = {"0115", "0188", "0380", "0980"}  # cases_tasks.jsonl
MAX_SOURCE_CHARS = 1800

EXPLAIN_TITLE = re.compile(r"bygglov|ansök|anmäl|förhandsbesked|planbesked|detaljplan|strandskydd|avlopp|taxa|avgift|"
                           r"attefall|rivningslov|marklov|nybyggnadskarta|bygga nytt|enskilt vatten", re.I)
GROWTH = re.compile(r"utvecklingsområde|utbyggnadsområde|nya bostäder|ny bostadsbebyggelse|prioriterade (?:tät)?orter|"
                    r"serviceort|landsbygdsnod|kommundelscentrum|stationssamhälle|LIS-område|tätortsutveckling|"
                    r"ny bebyggelse ska", re.I)
RURAL = re.compile(r"landsbygd|utanför tätort|sammanhållen bebyggelse|komplettering|enskild[at]? avlopp|"
                   r"gemensamhetsanläggning|gemensamt avlopp|förhandsbesked|jordbruksmark", re.I)
STATUTES = [("Plan- och bygglag", "4 kap. 2 §"), ("Plan- och bygglag", "5 kap. 3 §"), ("Plan- och bygglag", "9 kap. 74 §"),
            ("Miljöbalk", "3 kap. 4 §"), ("Miljöbalk", "7 kap. 15 §"), ("Miljöbalk", "7 kap. 18 c §"),
            ("miljöfarlig verksamhet och hälsoskydd", "13 §"), ("Anläggningslag", "1 §")]
IDEAS = [
    "an eco-village of 15-25 homes with shared gardens and one shared wastewater system, on farmland outside a village",
    "a cluster of 6-10 tiny houses on a working farm, rented to young families",
    "turning an old barn or a closed village school into 4-8 co-housing apartments",
    "6-8 guest cabins for farm stays on a working farm, with a shared well and wastewater system",
    "a market garden with a large greenhouse, a farm shop and two homes for the growers, on the edge of a village",
    "a small co-housing community (8-12 households) with a shared house and workshops on a former farm near a lake",
]

# Manual review of the generated cases (2026-10-21), applied on every rebuild. Per case id: key points to drop or
# relabel (matched by a substring of the drafted point), and the anchors of propose cases replaced by the places the
# source passage actually designates (the draft missed some or kept roads / lakes).
REVIEW = {
    "gen-develop-1715-2d6d81": {"drop": ["not a toilet-related installation"]},  # Kil: misleading for cabins with WC
    "gen-develop-2062-e2573c": {"relabel": {"one new coherent settlement": "Obstacle"}},  # Mora: detaljplan needed
    "gen-develop-0360-8f7076": {"relabel": {"to be changed or preserved": "Obstacle"}},  # Tierp: PBL 4:2 p. 2
    "gen-propose-1880-53410c": {"anchors": ["Garphyttan", "Vintrosa", "Glanshammar", "Hampetorp", "Kilsmo",
                                            "Brevens Bruk", "Järle"]},  # Örebro: villa plots + LIS study places
    "gen-propose-0127-6f52e4": {"anchors": ["Grödinge", "Vårsta", "Tegelvreten", "Eldtomta"]},  # Botkyrka ÖP no. 25
    "gen-propose-2482-86070d": {"anchors": ["Skelleftedalen", "Myckle", "Jörn", "Byske"]},  # Burträsket: a lake (risk)
    # 2026-10-21 audit: points the asker does not need (the question asks how to apply / where to build)
    "gen-explain-0186-38f1a9": {"drop": ["New Boverket building rules", "Applications are public documents"]},
    "gen-propose-1881-7b1660": {"drop": ["roughly 3,000-4,000 new homes"]},
}

COMMON = """You build test cases for Pyrmit, an assistant on Swedish planning and land law used by landowners, farmers,
architects, developers and eco-village groups. You get numbered sources [S1], [S2]... (Swedish municipal documents and
statutes). Everything in the reference must come from these sources: each item carries a quote of 6-15 consecutive
words copied exactly from one source (Swedish, as written there, no ellipsis) and that source's number.
Return JSON only."""

INSTRUCTIONS = {
    "explain": COMMON + """
{"usable": true|false,   // false if the page gives no concrete procedure, rule, fee, deadline or requirement
 "question": "<English, 1-3 sentences, as a resident would ask without having read the page: name the kommun, use
               everyday words, not the page's terms or headings>",
 "key_points": [{"point": "<English: what an expert answer must say>", "quote": "<exact words>", "source": "S1"}]
                // 3-5 points, the most useful facts for the asker (steps, requirements, fees, deadlines, who decides)
}""",
    "propose": COMMON + """
{"usable": true|false,   // false unless the sources name at least 3 places where the kommun wants new housing or growth
 "project": "<a project that fits what the plan wants in those places, e.g. 'a group of 15-20 small houses'>",
 "question": "<English, 2-3 sentences: a group or developer asking where in <kommun> they could build the project and
               what it would take. Name the kommun but NO place inside it and none of the plan's own terms.>",
 "anchors": [{"name": "<ONE place name exactly as written in the source, without area codes or numbers>", "quote":
              "<exact words containing the name, saying what the plan wants there>", "source": "S2"}],
              // 3-8 places the plan designates for this kind of project, one place per anchor
 "min_anchors": 2,       // how many of the anchors a good answer should name (2 or 3)
 "key_points": [{"point": "<a constraint or the approval route an expert answer must state>", "quote": "...", "source": "..."}]
                         // 2-4 points
}""",
    "develop": COMMON + """
The user's idea: {idea}.
{"usable": true|false,   // false if the sources say too little that applies to this idea in this kommun
 "question": "<English, 2-4 sentences in the first person ('We want to...'): the user describes the idea in <kommun>
               (a rough location type, no property, no plan or area names) and asks what they are missing and how to
               make it work. Do NOT mention any rule, permit, plan type or constraint (no detaljplan, strandskydd,
               farmland protection, sewage permit...): finding them is the assistant's job.>",
 "key_points": [{"kind": "Obstacle"|"Lever"|"Ask", "point": "<English>", "quote": "...", "source": "..."}]
   // 4-6 points: 1-3 Obstacles (a rule or plan statement that could block the idea), 1-3 Levers (a way to make it
   // work: location, scale, plan route, shared facilities... that a source allows), and exactly one Ask (a fact the
   // assistant must ask the user for; an Ask has quote "" and source "")
}""",
}


class Corpus:
    def __init__(self, path: Path):
        self.db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
        self.db.row_factory = sqlite3.Row

    def rows(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self.db.execute(sql, params).fetchall()

    def statutes(self) -> list[dict]:
        out = []
        for law, section in STATUTES:
            row = self.db.execute("SELECT * FROM chunks WHERE kind = 'law' AND title LIKE ? AND section = ? LIMIT 1",
                                  (f"%{law}%", section)).fetchone()
            if row:
                out.append(dict(row))
        return out


def source_block(sources: list[dict]) -> str:
    return "\n\n".join(f"[S{i + 1}] {s['title'] if s['kind'] == 'law' else s['kommun'] + ' – ' + s['title']}"
                       f"{' ' + s['section'] if s['kind'] == 'law' and s.get('section') else ''}\n"
                       f"{s['text'][:MAX_SOURCE_CHARS]}" for i, s in enumerate(sources))


def verified(item: dict, sources: list[dict]) -> tuple[dict | None, str | None]:
    """The evidence matcher of an item's quote, and the phrase found (None when the quote is not in its source)."""
    match = re.fullmatch(r"S(\d+)", str(item.get("source", "")).strip())
    if not match or not 1 <= int(match.group(1)) <= len(sources):
        return None, None
    source = sources[int(match.group(1)) - 1]
    phrase = longest_phrase(str(item.get("quote", "")), [normalize(source["header"] + " " + source["text"])])
    if not phrase:
        return None, None
    if source["kind"] == "law":
        law = next(law for law, _ in STATUTES if law.lower() in source["title"].lower())
        return {"law": law, "contains": phrase}, phrase
    return {"kommun_code": source["kommun_code"], "contains": phrase}, phrase


def pick_jobs(corpus: Corpus, per_task: int, seed: int) -> list[dict]:
    """Source documents per task, one kommun per case, kommuner not reused across tasks."""
    rng = random.Random(seed)
    used: set[str] = set(SEED_KOMMUNER)
    jobs: list[dict] = []

    # explain: short guidance pages, round-robin over their types
    pages = [dict(r) for r in corpus.rows(
        "SELECT doc_id, kommun_code, kommun, doc_type, title, count(*) AS n, sum(length(text)) AS size FROM chunks "
        "WHERE doc_id LIKE 'page:%' AND doc_type IN ('bygglov', 'avlopp', 'taxa', 'strandskydd', 'other', 'oversiktsplan') "
        "GROUP BY doc_id HAVING n <= 6 AND size >= 1200")]
    pages = [p for p in pages if EXPLAIN_TITLE.search(p["title"])]
    rng.shuffle(pages)
    by_type: dict[str, list[dict]] = {}
    for page in pages:
        by_type.setdefault(page["doc_type"], []).append(page)
    while len([j for j in jobs if j["task"] == "explain"]) < per_task and any(by_type.values()):
        for members in by_type.values():
            while members and members[0]["kommun_code"] in used:
                members.pop(0)
            if members and len([j for j in jobs if j["task"] == "explain"]) < per_task:
                page = members.pop(0)
                used.add(page["kommun_code"])
                sources = [dict(r) for r in corpus.rows("SELECT * FROM chunks WHERE doc_id = ? ORDER BY chunk_index", (page["doc_id"],))]
                jobs.append({"task": "explain", "kommun_code": page["kommun_code"], "kommun": page["kommun"],
                             "sources": sources, "label": page["title"]})

    # propose / develop: the kommuner's översiktsplan passages on growth / rural building
    growth: dict[str, list[dict]] = {}
    rural: dict[str, list[dict]] = {}
    for row in corpus.rows("SELECT * FROM chunks WHERE doc_type = 'oversiktsplan'"):
        chunk = dict(row)
        if GROWTH.search(chunk["text"]):
            growth.setdefault(chunk["kommun_code"], []).append(chunk)
        if RURAL.search(chunk["text"]):
            rural.setdefault(chunk["kommun_code"], []).append(chunk)
    def strongest(chunks: list[dict], pattern: re.Pattern, n: int) -> list[dict]:
        return sorted(chunks, key=lambda c: -len(pattern.findall(c["text"])))[:n]

    candidates = [code for code, chunks in growth.items() if len(chunks) >= 6 and code not in used]
    rng.shuffle(candidates)
    for code in candidates[:per_task]:
        used.add(code)
        sources = strongest(growth[code], GROWTH, 12)
        jobs.append({"task": "propose", "kommun_code": code, "kommun": sources[0]["kommun"], "sources": sources,
                     "label": "översiktsplan growth passages"})

    candidates = [code for code, chunks in rural.items() if len(chunks) >= 4 and code not in used]
    rng.shuffle(candidates)
    statutes = corpus.statutes()
    for i, code in enumerate(candidates[:per_task]):
        used.add(code)
        avlopp = [dict(r) for r in corpus.rows(
            "SELECT * FROM chunks WHERE kommun_code = ? AND doc_type = 'avlopp' AND doc_id LIKE 'page:%' LIMIT 4", (code,))]
        sources = strongest(rural[code], RURAL, 8) + avlopp + statutes
        jobs.append({"task": "develop", "kommun_code": code, "kommun": sources[0]["kommun"], "sources": sources,
                     "idea": IDEAS[i % len(IDEAS)], "label": "rural / VA passages + statutes"})
    return jobs


def job_key(job: dict) -> str:
    return stable_id(job["task"], job["kommun_code"], job.get("idea", ""), *[s["chunk_id"] for s in job["sources"]])


def draft(client, model: str, job: dict, effort: str) -> dict:
    instructions = INSTRUCTIONS[job["task"]].replace("{idea}", job.get("idea", ""))
    response = client.responses.create(
        model=model, reasoning={"effort": effort}, instructions=instructions,
        input=f"Kommun: {job['kommun']}\n\nSources:\n\n{source_block(job['sources'])}",
    )
    raw = get_response_output_text(response).strip()
    result = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
    result["_cost"] = float(getattr(response.usage, "cost", 0) or 0)
    return result


def build_case(job: dict, draft_: dict) -> tuple[dict | None, str]:
    if not draft_.get("usable"):
        return None, "not usable"
    task, sources = job["task"], job["sources"]
    case_id = f"gen-{task}-{job['kommun_code']}-{job_key(job)[:6]}"
    review = REVIEW.get(case_id, {})
    points, evidence = [], []
    for item in draft_.get("key_points") or []:
        text = str(item.get("point", ""))
        if any(part in text for part in review.get("drop", [])):
            continue
        kind = next((k for part, k in review.get("relabel", {}).items() if part in text), item.get("kind"))
        if task == "develop" and kind == "Ask":  # no quote: a fact to ask the user
            points.append(f"Ask: {item.get('point', '').strip()}")
            continue
        matcher, _ = verified(item, sources)
        if matcher is None:
            continue
        points.append(f"{kind}: {item['point'].strip()}" if task == "develop" else item["point"].strip())
        if matcher not in evidence:
            evidence.append(matcher)
    case = {"id": case_id, "task": task, "kommun": [job["kommun_code"]],
            "question": str(draft_.get("question", "")).strip()}
    if task == "propose":
        anchors = []
        for item in draft_.get("anchors") or []:
            name = str(item.get("name", "")).strip()
            matcher, phrase = verified(item, sources)
            # "05A Melltorp och 05B Hyssna" -> Melltorp, Hyssna: one place per anchor, as an answer would name it
            for part in re.split(r"\s+och\s+|\s*[,/&]\s*", re.sub(r"\b\d+[A-Z]?\b", " ", name)):
                part = part.strip(" -–")
                if (matcher and len(part) > 2 and normalize(part) in normalize(phrase)
                        and normalize(part) != normalize(job["kommun"])  # the kommun itself is not an option
                        and not re.search(r"(vägen?|gatan?|detaljplan\w*)$", part, re.I)  # streets / plans, not places
                        and part not in [a["name"] for a in anchors]):
                    anchors.append({"name": part})
        if "anchors" in review:
            anchors = [{"name": name} for name in review["anchors"]]
        leaked = [a["name"] for a in anchors if re.search(rf"(?<!\w){re.escape(a['name'])}(?!\w)", case["question"], re.I)]
        if leaked:
            return None, f"question names the places {leaked}"
        if len(anchors) < 3 or len(points) < 2:
            return None, f"{len(anchors)} anchors / {len(points)} points verified"
        case["anchors"] = anchors
        case["min_anchors"] = max(1, min(int(draft_.get("min_anchors") or 2), 3, len(anchors)))
    elif len([p for p in points if not p.startswith("Ask:")]) < 3:
        return None, f"{len(points)} points verified"
    if task == "develop" and not (any(p.startswith("Obstacle:") for p in points) and any(p.startswith("Lever:") for p in points)):
        return None, "no verified obstacle or lever"
    case.update({"key_points": points, "evidence": evidence,
                 "source": f"{job['kommun']}: {job['label']}" + (f"; idea: {job['idea']}" if job.get("idea") else ""),
                 "tags": ["generated", task]})
    return case, "ok"


def main() -> None:
    parser = argparse.ArgumentParser(description="Explain / propose / develop cases drafted from corpus documents")
    parser.add_argument("--per-task", type=int, default=10, help="cases drafted per task (before filtering)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--effort", default="medium")
    parser.add_argument("--tasks", nargs="+", default=["explain", "propose", "develop"])
    parser.add_argument("--regenerate", action="store_true", help="ignore cached drafts of the selected jobs")
    args = parser.parse_args()
    os.environ.setdefault("LLM_PROVIDER", "openrouter")

    corpus = Corpus(store_dir("st-arctic-l-v2") / "corpus.sqlite")
    jobs = [job for job in pick_jobs(corpus, args.per_task, args.seed) if job["task"] in args.tasks]
    client, model = get_openai_client(), resolve_model_name(args.model)
    print(f"{len(jobs)} jobs -> cases with {model} ({args.effort})")

    drafts = {d["key"]: d for d in read_jsonl(DRAFTS_PATH)} if DRAFTS_PATH.exists() else {}
    if args.regenerate:
        drafts = {k: v for k, v in drafts.items() if k not in {job_key(job) for job in jobs}}
        write_jsonl(DRAFTS_PATH, drafts.values())
    lock = threading.Lock()

    def run(job: dict) -> tuple[dict, dict | None, str, float]:
        key = job_key(job)
        cached = drafts.get(key)
        cost = 0.0
        if cached is None:
            try:
                cached = draft(client, model, job, args.effort)
            except Exception as exc:
                return job, None, f"error: {exc}", 0.0
            cost = cached["_cost"]
            cached.update({"key": key, "model": model})
            with lock:  # appended at once: an interrupted run keeps every draft it paid for
                drafts[key] = cached
                DRAFTS_PATH.parent.mkdir(parents=True, exist_ok=True)
                with DRAFTS_PATH.open("a", encoding="utf-8") as file:
                    file.write(json.dumps(cached, ensure_ascii=False) + "\n")
        case, status = build_case(job, cached)
        return job, case, status, cost

    cases, total = [], 0.0
    with ThreadPoolExecutor(max_workers=4) as pool:
        for job, case, status, cost in pool.map(run, jobs):
            total += cost
            print(f"  {job['task']:<8} {job['kommun']:<16} {status[:100]}")
            if case:
                cases.append(case)
    written = write_jsonl(OUTPUT_PATH, cases)
    print(f"{written} cases -> {OUTPUT_PATH} (${total:.3f})")


if __name__ == "__main__":
    main()

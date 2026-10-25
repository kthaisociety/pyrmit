"""
Which crawled PDFs stay in the corpus. The 2026-10-23 crawl brought 60k PDFs (7.8k before); most are planning
documents, but a kommun's "riktlinjer" / "taxa" / "program" links also give flag policies, chimney-sweep fees,
dementia guidelines... Three stages, each decision kept with its origin:

1. rules: plan words in the title / file name / link text keep a PDF (`KEEP`), off-topic words propose a drop (`DROP`)
2. model: a logistic regression on arctic vectors of the same fields + the first page, trained on the rule
   labels, keeps the rest when it is confident (p >= HIGH) and proposes a drop when p <= LOW
3. review: the biggest uncertain ones are read by hand (`corpus/pdf_review.jsonl`, versioned); every other proposed
   drop and uncertain PDF goes to an LLM (`llm`, ~$0.0001 per PDF with MiMo Flash), which keeps it in doubt.
   Losing a useful document costs more than keeping noise: no PDF is dropped on a rule or the model alone.

    cd backend
    python -m corpus.pdf_filter features   # from documents.jsonl + manifests (new doc_ids are added)
    python -m corpus.pdf_filter classify   # rules + model -> data/corpus/pdf_filter/decisions.jsonl
    python -m corpus.pdf_filter review --limit 200   # print uncertain PDFs not reviewed yet
    python -m corpus.pdf_filter llm --limit 100000   # proposed drops + uncertain ones not answered yet, MiMo Flash
    python -m corpus.pdf_filter classify   # again, with the answers
    python -m corpus.pdf_filter apply      # drop them from documents.jsonl (or rerun corpus.extract)
    python -m corpus.pdf_filter stats
    python -m corpus.pdf_filter eval-sample --limit 50   # random drops to label in corpus/pdf_filter_eval.jsonl
    python -m corpus.pdf_filter eval       # share of useful documents among the drops (the error that matters)

`corpus.extract` skips the PDFs whose decision is "drop" (PDFs without a decision are kept).
"""

import argparse
import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import unquote, urlparse

import numpy as np

from corpus.common import DATA_DIR, DOCUMENTS_PATH, WEB_DIR, read_jsonl, write_jsonl
from corpus.crawl import fold

FILTER_DIR = DATA_DIR / "pdf_filter"
FEATURES_PATH = FILTER_DIR / "features.jsonl"
DECISIONS_PATH = FILTER_DIR / "decisions.jsonl"
REVIEW_PATH = Path(__file__).resolve().parent / "pdf_review.jsonl"
LLM_PATH = FILTER_DIR / "llm.jsonl"
EVAL_PATH = Path(__file__).resolve().parent / "pdf_filter_eval.jsonl"  # hand labels of random drops (versioned)
MODEL = "st-arctic-l-v2"
HIGH, LOW = 0.85, 0.15
HEAD_CHARS = 700

# Planning and building documents, their investigations, and the plans / programmes that steer land use
KEEP = re.compile(
    r"detaljplan|plankarta|planbeskrivning|genomforandebeskrivning|planbestammelse|samradsredogorelse"
    r"|granskningsutlatande|granskningshandling|samradshandling|antagandehandling|utstallningshandling|planprogram"
    r"|omradesbestammelse|oversiktsplan|fordjupad oversikt|\bfop\b|\bop ?20\d\d|planbesked|startpromemoria|planuppdrag"
    r"|bygglov|forhandsbesked|strandskydd|attefall|bygganmalan|kontrollplan|rivningslov|marklov|lovplikt|bygglovsbefri"
    r"|nybyggnadskarta|situationsplan|dagvatten|geotekni|buller|miljokonsekvens|\bmkb\b|betydande miljopaverkan"
    r"|naturvarde|naturinventering|arkeolog|fornlamning|skyfall|solstudie|skuggstudie|dagsljus|markmiljo|markundersok"
    r"|markteknisk|gestaltning|kvalitetsprogram|exploatering|markanvisning|bostadsforsorjning|bostadsbyggnad"
    r"|gronplan|gronstruktur|gronytefaktor|kulturmiljo|bevarandeprogram|byggnadsinventering|kulturhistorisk"
    r"|arkitektur|va-plan|va-utbyggnad|vatten- och avloppsplan|vattenforsorjningsplan|enskilt avlopp|enskilda avlopp"
    r"|avloppsanlaggning|fastighetsbildning|fastighetsforteckning|grundkarta|illustrationskarta|plan- och bygg"
    r"|byggnadsordning|landsbygdsutveckling i strandnara|\blis\b|vindkraft|planeringsstrategi|utbyggnadsstrategi"
    r"|utvecklingsstrategi|trafikstrategi|trafikutredning|trafikplan|parkeringsnorm|parkeringstal|parkeringspolicy"
    r"|mobilitetsplan|cykelplan|vattenskyddsomrade|riksintresse|tomtindelning|fastighetsplan|planavgift"
    r"|bygglovstaxa|plan- och bygglovstaxa|taxa for plan|lantmateri"
    r"|ekosystemtjanst|tradinventering|tillganglighet.*(bygg|tomt)|bullerplank|riskutredning|riskbedomning.*(plan|detalj)"
    r"|luftutredning|luftkvalitet|vibration|radonundersok|stadsplan|byggplan|programhandling|sektionsritning|fasadritning"
    r"|planskiss|illustrationsplan|landskapsplan|strukturplan|utvecklingsplan|tematiskt tillagg|klimatanpassning"
    r"|havsplan|kustzon|vatten\w*plan|tomt|villatomt|bostadsomrade|byggratt|bygglovsansokan|markanvandning|mobilitet"
    r"|samradsmote|kontrollansvarig|olovligt byggande|vattentjanstplan"
    # site constraints (from the manual review of the biggest uncertain PDFs, 2026-10-23)
    r"|miljoteknisk|fororenad|fororening|\bmifo\b|riskbedomning|farligt gods|artskydd|naturvardsprogram"
    r"|naturvardsstrategi|naturvardsplan|friluftsplan|gronbla|blaplan|planeringsunderlag|planeringsforutsattning"
    r"|skotselplan|naturreservat|bebyggelse|stadsutveckling|hallbarhetsprogram|jordprov|funktionsutredning"
    r"|bygga varsamt|varsam|vindbruk|va-oversikt|va-program|va-riktlinje|\babva\b|pbl-taxa|parkeringsstrategi"
    r"|parkeringsplan|ortsanalys|masterplan|miljobedomning|samradsunderlag|stadsbyggnadsprogram|stadsbyggnadside"
    r"|plan for tillvaxt|fotgangarplan|stadsmiljo|deponi"
    # Environmental Code fee schedules carry the fee of an enskilt avlopp permit: the only useful documents found
    # among 120 random drops (corpus.pdf_filter eval, 2026-10-23), 120 such PDFs had been dropped
    r"|taxa.*miljobalk|miljobalk.*taxa|miljobalktaxa")
# On the first page, when the name says nothing ("Minnesanteckningar samrådsmöte" of a planprogram)
KEEP_HEAD = re.compile(r"detaljplan|planprogram|oversiktsplan|planbeskrivning|plankarta|planbestammelse"
                       r"|omradesbestammelse|bygglov|strandskydd|plan- och bygglag")
# Kommun administration outside planning and building
DROP = re.compile(
    r"avfall|renhallning|sophamtning|kompost|bibliotek|\blss\b|fardtjanst|hemtjanst|omsorg|forskol|skolgard|elevhalsa"
    r"|skolskjuts|grundskol|gymnasie|vuxenutbildning|socialtjanst|ekonomiskt bistand|bostadsanpassning|demens"
    r"|verksamhetsplan|verksamhetsberattelse|namndplan|budget|arsredovisning|delarsrapport|bokslut|internkontroll"
    r"|planeringsdirektiv|ekonomisk styrning|ekonomisk-styrning|minoritet|felparkering|parkeringsovervakning|dodsbo"
    r"|kopiering|allmanna? handling|hygienisk|gardsforsaljning|alkohol|tobak|livsmedel|serveringstillstand"
    r"|sim- och sporthall|sporthall|idrottsanlaggning|kallelse|dagordning|medelvarden for vatten|flaggning|flagg"
    r"|diskriminering|jamstalldhet|krisberedskap|kontinuitet|risk- och sarbarhet|sarbarhetsanalys|revisionsrapport"
    r"|revisorerna|revisor|missiv|lonepolicy|personalpolicy|arbetsmiljopolicy|arvode|reglemente|delegationsordning"
    r"|motion |medborgarforslag|interpellation|valnamnd|folkhalsa|integration|kulturskola|fritidsgard|turism"
    r"|evenemang|matsedel|maltid|sotning|brandskyddskontroll|hundar|djurhallning|smittskydd|rokfri|narkotika"
    r"|upphandlingspolicy|inkopspolicy|lediga jobb|rekrytering|anstallning|nyhetsbrev|pressmeddelande|informationsblad"
    r"|personuppgift|gdpr|dataskydd|kommunikationspolicy|varumarke|grafisk profil|bidrag till foreningar"
    r"|foreningsbidrag|stipendi|naringslivsprogram|naringslivsstrategi|digitaliseringsstrategi|it-strategi"
    r"|e-tjanst|klagomal|synpunkt|offentlig plats|torghandel|uteservering|skyltpolicy"
    r"|cookies|tillganglighetsredogorelse|vattenprov|dricksvattenkvalitet|badvatten"
    r"|hyresgast|hyreslagenhet|uthyrning|lokalbokning|felanmalan|snorojning|vintervaghallning|vinterunderhall"
    r"|halsoskydd|namnden - handlingar|namnden - kompletterande"
    r"|informationshanteringsplan|dokumenthanteringsplan|energiplan|klimatplan|energi- och klimat|kretsloppsplan"
    r"|miljoprogram|flerarsplan|fiskeplan|handlingsplan for radon"
    r"|atgardsprogram for|vattenvardsprogram|planeringdirektiv|kommunplan|teknisk handbok|teknisk standard"
    r"|material och arbetsbeskrivning|klimatstrategi|miljorapport|skydd mot olyckor|lekplatsplan|resvaneundersokning")


def _file_name(url: str | None) -> str:
    return unquote(urlparse(url or "").path.rsplit("/", 1)[-1])


def anchors() -> dict[str, str]:
    """doc_id -> link text of the PDF (the manifests; documents.jsonl keeps the metadata title)."""
    result = {}
    for manifest in WEB_DIR.glob("*/manifest.jsonl"):
        code = manifest.parent.name
        for entry in read_jsonl(manifest):
            if entry.get("type") == "pdf":
                result[f"pdf:{code}:{entry['id']}"] = entry.get("anchor") or ""
    return result


def features() -> None:
    """Adds the PDFs of documents.jsonl not seen yet (decisions survive a re-extract that drops them)."""
    FILTER_DIR.mkdir(parents=True, exist_ok=True)
    known = {row["doc_id"] for row in read_jsonl(FEATURES_PATH)} if FEATURES_PATH.exists() else set()
    links = anchors()
    added = 0
    with FEATURES_PATH.open("a", encoding="utf-8") as file:
        for doc in read_jsonl(DOCUMENTS_PATH):
            if not doc["doc_id"].startswith("pdf:") or doc["doc_id"] in known:
                continue
            row = {"doc_id": doc["doc_id"], "kommun": doc.get("kommun"), "title": doc.get("title") or "",
                   "file": _file_name(doc.get("url")), "anchor": links.get(doc["doc_id"], ""),
                   "source": urlparse(doc.get("source_page") or "").path, "chars": len(doc.get("text") or ""),
                   "head": " ".join((doc.get("text") or "")[:HEAD_CHARS].split())}
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
            added += 1
    print(f"{added} PDFs added, {len(known) + added} in {FEATURES_PATH}")


def name_text(row: dict) -> str:
    return fold(f"{row['title']} {row['file']} {row['anchor']}")


def rule(row: dict) -> tuple[bool | None, str]:
    """Plan words win over off-topic words ("Detaljplan för förskola"); the first page counts only when the name
    says nothing."""
    name = name_text(row)
    if match := KEEP.search(name):
        return True, match.group(0)
    if match := DROP.search(name):
        return False, match.group(0)
    if match := KEEP_HEAD.search(fold(row["head"])):
        return True, "head: " + match.group(0)
    return None, ""


def model_text(row: dict) -> str:
    return f"{row['title']}\n{row['file']}\n{row['anchor']}\n{row['source']}\n{row['head']}"


def vectors(rows: list[dict]) -> np.ndarray:
    """arctic vectors of model_text, cached by doc_id."""
    from embeddings import Embedder
    from localrag.index import load_model_config

    cache_ids, cache = FILTER_DIR / "vector_ids.json", FILTER_DIR / "vectors.npy"
    ids = json.loads(cache_ids.read_text()) if cache_ids.exists() else []
    matrix = np.load(cache) if cache.exists() else np.zeros((0, 1024), dtype=np.float16)
    position = {doc_id: i for i, doc_id in enumerate(ids)}
    todo = [row for row in rows if row["doc_id"] not in position]
    if todo:
        print(f"embedding {len(todo)} PDFs with {MODEL}", flush=True)
        embedder = Embedder(load_model_config(MODEL))
        new = np.asarray(embedder.embed_documents([model_text(row) for row in todo]), dtype=np.float16)
        matrix = np.vstack([matrix, new]) if len(matrix) else new
        ids += [row["doc_id"] for row in todo]
        np.save(cache, matrix)
        cache_ids.write_text(json.dumps(ids))
        position = {doc_id: i for i, doc_id in enumerate(ids)}
    return np.asarray(matrix[[position[row["doc_id"]] for row in rows]], dtype=np.float32)


def load_reviews() -> dict[str, dict]:
    return {row["doc_id"]: row for row in read_jsonl(REVIEW_PATH)} if REVIEW_PATH.exists() else {}


def load_llm() -> dict[str, dict]:
    return {row["doc_id"]: row for row in read_jsonl(LLM_PATH)} if LLM_PATH.exists() else {}


def decide(rule_keep: bool | None, why: str, p: float, review: dict | None, answer: dict | None) -> dict:
    """keep True / False, or None while an LLM answer is pending (corpus.extract keeps those)."""
    if review:
        return {"keep": review["keep"], "by": "review", "why": review.get("why", "")}
    if rule_keep is True:
        return {"keep": True, "by": "rule", "why": why}
    if rule_keep is None and p >= HIGH:
        return {"keep": True, "by": "model", "why": ""}
    # Losing a useful document costs more than keeping noise: a rule or the model only proposes a drop, the LLM
    # decides (and keeps in doubt)
    proposed = "rule" if rule_keep is False else "model" if p <= LOW else "uncertain"
    if answer is None:
        return {"keep": None, "by": f"{proposed}+pending", "why": why}
    return {"keep": answer["keep"], "by": f"{proposed}+llm", "why": answer.get("why", "")}


def classify() -> None:
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import cross_val_score

    rows = list(read_jsonl(FEATURES_PATH))
    labels = [rule(row) for row in rows]
    X = vectors(rows)
    train = [i for i, (keep, _) in enumerate(labels) if keep is not None]
    y = np.array([labels[i][0] for i in train])
    classifier = LogisticRegression(C=2.0, max_iter=2000, class_weight="balanced")
    print(f"rules: {int(y.sum())} keep, {int((~y).sum())} drop, {len(rows) - len(train)} undecided")
    print("cross-validated accuracy on the rule labels:",
          round(float(cross_val_score(classifier, X[train], y, cv=5).mean()), 3), flush=True)
    classifier.fit(X[train], y)
    proba = classifier.predict_proba(X)[:, list(classifier.classes_).index(True)]
    reviews, answers = load_reviews(), load_llm()
    decisions = [{"doc_id": row["doc_id"], **decide(keep, why, float(p), reviews.get(row["doc_id"]),
                                                    answers.get(row["doc_id"])),
                  "p": round(float(p), 3), "rule": keep}
                 for row, (keep, why), p in zip(rows, labels, proba)]
    write_jsonl(DECISIONS_PATH, decisions)
    stats()


def stats() -> None:
    rows = {row["doc_id"]: row for row in read_jsonl(FEATURES_PATH)}
    counts, chars = Counter(), Counter()
    for decision in read_jsonl(DECISIONS_PATH):
        key = (decision["by"], decision["keep"])
        counts[key] += 1
        chars[key] += rows[decision["doc_id"]]["chars"]
    total = sum(chars.values()) or 1
    for key in sorted(counts, key=str):
        print(f"  {key[0]:10} {str(key[1]):5} {counts[key]:6} PDFs  {100 * chars[key] / total:5.1f} % of the text")
    # The model against the rules where both exist: how often would it have overruled them
    disagree = [d for d in read_jsonl(DECISIONS_PATH) if d["rule"] is not None and (d["p"] >= 0.5) != d["rule"]]
    print(f"  model disagrees with the rules on {len(disagree)} PDFs")


def uncertain(limit: int, offset: int = 0) -> list[dict]:
    rows = {row["doc_id"]: row for row in read_jsonl(FEATURES_PATH)}
    pending = [d for d in read_jsonl(DECISIONS_PATH) if d["keep"] is None]
    pending.sort(key=lambda d: -rows[d["doc_id"]]["chars"])  # the biggest weigh most on the index
    return [{**rows[d["doc_id"]], "p": d["p"]} for d in pending[offset:offset + limit]]


def review(limit: int, offset: int) -> None:
    for i, row in enumerate(uncertain(limit, offset), offset):
        name = " | ".join(part for part in (row["title"][:80], row["file"][:60], row["anchor"][:60]) if part)
        print(f"{i} {row['doc_id']} p={row['p']} {row['chars'] // 1000}k [{row['kommun']}] {name} :: {row['head'][:160]}")


LLM_PROMPT = """You sort documents crawled from a Swedish kommun's website for a search engine about land use,
detailed plans (detaljplaner), comprehensive plans (översiktsplaner), building permits (bygglov) and the rules and
investigations behind them (noise, stormwater, nature, heritage, roads and parking, water and sewage for properties,
housing supply, plot sales...).
Keep a document if someone asking what may be built where, or how a plan or permit works in this kommun, could need it.
When in doubt, keep it: losing a useful document is worse than keeping noise.
Drop only kommun administration clearly outside that scope: schools, social care, culture and leisure, budgets and audits, HR,
internal policies, waste collection, fees outside planning/building, crisis management, meeting logistics...
Answer with JSON only: {"keep": true|false, "why": "<5 words>"}"""


def llm(model: str, workers: int, limit: int | None, check_model: int = 0) -> None:
    """The uncertain PDFs, or with check_model a random sample of the model's decisions (-> llm-check.jsonl, not
    used as decisions) to measure how often the LLM agrees with them."""
    from llm import get_openai_client, get_response_output_text, resolve_model_name

    client, model = get_openai_client(), resolve_model_name(model)
    cost = 0.0
    out_path = FILTER_DIR / "llm-check.jsonl" if check_model else LLM_PATH
    done = {row["doc_id"] for row in read_jsonl(out_path)} if out_path.exists() else set()
    reviews = load_reviews()
    if check_model:
        import random
        rows = {row["doc_id"]: row for row in read_jsonl(FEATURES_PATH)}
        decided = [d for d in read_jsonl(DECISIONS_PATH) if d["by"] == "model" and d["doc_id"] not in done]
        todo = [{**rows[d["doc_id"]], "p": d["p"]} for d in random.Random(0).sample(decided, check_model)]
    else:
        todo = [row for row in uncertain(10**9) if row["doc_id"] not in done and row["doc_id"] not in reviews][:limit]
    print(f"{len(todo)} PDFs to {model}", flush=True)

    def ask(row: dict) -> dict | None:
        content = (f"Kommun: {row['kommun']}\nTitle: {row['title']}\nFile: {row['file']}\nLink text: {row['anchor']}\n"
                   f"Found on: {row['source']}\nStart of the text: {row['head'][:500]}")
        try:
            response = client.responses.create(model=model, reasoning={"effort": "low"}, instructions=LLM_PROMPT,
                                               input=content)
            raw = get_response_output_text(response)
            answer = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
            return {"doc_id": row["doc_id"], "keep": bool(answer["keep"]), "by": "llm", "why": answer.get("why", ""),
                    "p": row["p"], "cost": float(getattr(response.usage, "cost", 0) or 0)}
        except Exception as exc:
            print(f"  {row['doc_id']}: {exc!r}", flush=True)
            return None

    with ThreadPoolExecutor(workers) as pool, out_path.open("a", encoding="utf-8") as file:
        for i, result in enumerate(pool.map(ask, todo), 1):
            if result:
                cost += result["cost"]
                file.write(json.dumps(result, ensure_ascii=False) + "\n")
                file.flush()
            if i % 500 == 0:
                print(f"  {i}/{len(todo)} (${cost:.2f})", flush=True)
    print(f"done, ${cost:.2f}")
    if check_model:
        checked = list(read_jsonl(out_path))
        agree = sum((row["p"] >= 0.5) == row["keep"] for row in checked)
        print(f"LLM agrees with the model on {agree}/{len(checked)}; disagreements:")
        for row in checked:
            if (row["p"] >= 0.5) != row["keep"]:
                print(f"  model {'keep' if row['p'] >= 0.5 else 'drop'} p={row['p']} llm: {row['why']} {row['doc_id']}")


def apply() -> None:
    """Removes the dropped PDFs from documents.jsonl (decided after the extract: new PDFs of a crawl get their
    features from documents.jsonl), instead of a 20-min re-extract."""
    dropped = dropped_ids()
    kept = removed = 0
    temporary = DOCUMENTS_PATH.with_suffix(".filtered.jsonl")
    with DOCUMENTS_PATH.open(encoding="utf-8") as source, temporary.open("w", encoding="utf-8") as target:
        for line in source:
            if json.loads(line)["doc_id"] in dropped:
                removed += 1
            else:
                target.write(line)
                kept += 1
    temporary.replace(DOCUMENTS_PATH)
    print(f"{removed} dropped PDFs removed, {kept} documents left")


def eval_sample(limit: int) -> None:
    """A random sample of the drops (not the hand-reviewed ones) to label in EVAL_PATH: was a useful document lost?"""
    import random

    rows = {row["doc_id"]: row for row in read_jsonl(FEATURES_PATH)}
    labelled = {row["doc_id"] for row in read_jsonl(EVAL_PATH)} if EVAL_PATH.exists() else set()
    drops = sorted(d["doc_id"] for d in read_jsonl(DECISIONS_PATH) if d["keep"] is False and d["by"] != "review")
    for doc_id in [d for d in random.Random(1).sample(drops, len(drops)) if d not in labelled][:limit]:
        row = rows[doc_id]
        name = " | ".join(part for part in (row["title"][:80], row["file"][:60], row["anchor"][:60]) if part)
        print(f"{doc_id} [{row['kommun']}] {name} :: {' '.join(row['head'].split())[:300]}")


def evaluate(verbose: bool = True) -> dict:
    """Share of the drops that were useful documents, per decision path, from the hand labels of a random sample
    (95 % Wilson interval: with ~100 labels, a 0 % estimate still allows ~4 %). Labels of PDFs a later rule change
    keeps are counted under their new path."""
    from math import sqrt

    if not EVAL_PATH.exists() or not DECISIONS_PATH.exists():
        return {}
    paths = {d["doc_id"]: d["by"] if d["keep"] is False else "kept now" for d in read_jsonl(DECISIONS_PATH)}
    groups: dict[str, list[bool]] = {}
    for label in read_jsonl(EVAL_PATH):
        by = paths.get(label["doc_id"], "gone")
        groups.setdefault(by, []).append(label["useful"])
        groups.setdefault("all drops", []).append(label["useful"])
    result = {}
    for by, labels in sorted(groups.items()):
        n, k, z = len(labels), sum(labels), 1.96
        centre, half = (k + z * z / 2) / (n + z * z), z * sqrt(k * (n - k) / n + z * z / 4) / (n + z * z)
        result[by] = {"labelled": n, "useful": k, "rate": k / n, "low": max(0.0, centre - half), "high": centre + half}
        if verbose:
            print(f"  {by:16} {k:3}/{n:<3} useful ({k / n:.1%}, 95 % interval {result[by]['low']:.1%}-"
                  f"{result[by]['high']:.1%})")
    for label in read_jsonl(EVAL_PATH):
        if label["useful"] and verbose:
            print(f"  lost: {label['doc_id']} {label.get('why', '')}")
    return result


def dropped_ids() -> set[str]:
    """For corpus.extract: the PDFs to leave out."""
    if not DECISIONS_PATH.exists():
        return set()
    return {d["doc_id"] for d in read_jsonl(DECISIONS_PATH) if d["keep"] is False}


def main() -> None:
    parser = argparse.ArgumentParser(description="Relevance filter of the crawled PDFs")
    parser.add_argument("step", choices=["features", "classify", "review", "llm", "apply", "stats", "eval-sample",
                                         "eval"])
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--model", default="xiaomi/mimo-v2.6-flash")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--check-model", type=int, default=0, help="llm: judge a sample of the model's decisions")
    args = parser.parse_args()
    if args.step == "features":
        features()
    elif args.step == "classify":
        classify()
    elif args.step == "review":
        review(args.limit, args.offset)
    elif args.step == "llm":
        llm(args.model, args.workers, args.limit, args.check_model)
    elif args.step == "apply":
        apply()
    elif args.step == "eval-sample":
        eval_sample(args.limit)
    elif args.step == "eval":
        evaluate()
    else:
        stats()


if __name__ == "__main__":
    main()

"""
Detaljplan registry: groups the crawled detaljplan documents into plans and extracts their planbestämmelser,
so the agent can list a kommun's plans and read a plan's rules as a table (agentic tools `plans` and
`plan_rules`) instead of guessing from document titles.

    cd backend && python -m corpus.plans          # after corpus.extract + localrag.store -> data/corpus/plans.jsonl

Rule-based, no LLM:
- a plan = the detaljplan PDFs of one kommun whose file names reduce to the same key once role words
  (plankarta, planbeskrivning...), dates and versions are removed; PDFs without a usable key take the plan
  page that links them. Plan pages without PDFs are plans too (often the page holds the description).
- status from the linking page (gällande / pågående / upphävda) and the documents ("laga kraft 2019-05-02",
  ANTAGANDEHANDLING, GRANSKNINGSHANDLING, SAMRÅDSHANDLING).
- provisions = lines of the plankarta / planbestämmelser with a Boverket code (e1, f2, h1, B, GATA, +0.0...) or a
  sentence with a measure (byggnadsarea, nockhöjd, våningar...), each tied to the chunk that contains it so the
  agent can cite it. What zone a code applies to is on the map: that needs the vision model.
"""

import json
import re
import sqlite3
from collections import Counter, defaultdict
from urllib.parse import unquote, urlparse

from corpus.common import DATA_DIR, DOCUMENTS_PATH, read_jsonl, stable_id, write_jsonl

PLANS_PATH = DATA_DIR / "plans.jsonl"
STORE_PATH = DATA_DIR.parent / "index" / "store" / "st-arctic-l-v2" / "corpus.sqlite"

ROLES = [  # first match wins
    ("plankarta", r"plankarta|plankort|karta|_best\b|bestämmelser|bestammelser"),
    ("planbeskrivning", r"planbeskrivning|beskrivning"),
    ("genomförande", r"genomförande|genomforande"),
    ("granskningsutlåtande", r"granskningsutlåtande|granskningsutlatande|utlåtande|utlatande"),
    ("samrådsredogörelse", r"samrådsredogörelse|samradsredogorelse|samrådsredog"),
    ("illustration", r"illustration"),
    ("utredning", r"utredning|pm\b|bullerutredning|dagvatten|geotekni|naturvärdes|trafik"),
]
NOISE_WORDS = (r"plankarta|plankort|karta|planbeskrivning|beskrivning|bestämmelser|bestammelser|best|"
               r"genomförandebeskrivning|granskningsutlåtande|granskningsutlatande|utlåtande|samrådsredogörelse|"
               r"antagandehandling|granskningshandling|samrådshandling|samradshandling|antagande|granskning|samråd|"
               r"samrad|laga|kraft|lagakraft|detaljplan|detaljplanen|för|for|del|av|rev|reviderad|uppdaterad|"
               r"version|ver|final|slutlig|pdf|tillgänglig|tillganglig|webb|web|a\d|a\d-l|layout\d*|sv|ny|mfl|m\.?fl")

STATUS_PAGE = [("in_force", r"gallande|gällande|antagna|laga-?kraft|vunnit"), ("in_progress", r"pagaende|pågående|samrad|granskning"),
               ("repealed", r"upphavd|upphävd")]
LAGA_KRAFT = re.compile(r"laga\s*kraft\s*(?:den\s*)?[:\-–]?\s*(\d{4}-\d{2}-\d{2}|\d{1,2}\s+\w+\s+\d{4})", re.I)
ANTAGEN = re.compile(r"antag(?:en|ande|ningsbeslut)[^\n]{0,40}?(\d{4}-\d{2}-\d{2})", re.I)
STAGES = [("in_force", r"laga\s*kraft"), ("adopted", r"antagandehandling"), ("review", r"granskningshandling"),
          ("consultation", r"samrådshandling|samradshandling")]
PLAN_NUMBER = re.compile(r"\b(?:Dp|DP|Detaljplan nr\.?|Plan nr\.?|Akt(?:nr)?\.?)\s*([0-9][0-9A-Za-z:/\-.]{0,14})")

CODE = r"(?:[a-zåäö]{1,2}\d{1,2}|[A-ZÅÄÖ]{1,2}\d{0,2}|GATA|LOKALGATA|HUVUDGATA|NATUR|PARK|TORG|VÄG|GÅNG|PARKERING|\+\d{1,3}[.,]\d)"
PROVISION_LINE = re.compile(rf"^\s*({CODE})\s+([A-ZÅÄÖ0-9].{{8,400}})$")
MEASURE = re.compile(r"(byggnadsarea|bruttoarea|nockhöjd|byggnadshöjd|totalhöjd|takvinkel|våning|fastighetsstorlek|"
                     r"fastighet(?:er)? får|genomförandetid|får inte förses med byggnad|komplementbyggnad|exploatering)", re.I)
NUMBER = re.compile(r"(\d{1,3}(?:[  ]\d{3})+|\d+(?:[.,]\d+)?)\s*(kvadratmeter|kvm|m2|m²|meter|m\b|procent|%|våningar|grader|år)", re.I)
# "4 kap 11 § 1", "4 kap. 16 § 1 st 1 p.", "4 kap. 5 § första stycket 2 och 3"
LAW_REF = re.compile(r",?\s*(\d+\s*kap\.?\s*\d+\s*[a-z]?\s*§(?:[\s,]*(?:\d+|st|p|stycket|punkt|första|andra|tredje|och|§)\.?)*)\s*$")
NOT_A_RULE = re.compile(r"^[\d\s.,:/\-NE]+$|\b\d{4}-\d{3,5}\b|^(?:[A-ZÅÄÖ]{1,2}\s)?\d{5,}")  # coordinates, case numbers
TOPICS = {
    "building_area": r"byggnadsarea|exploatering|bruttoarea|\be\d\b",
    "height": r"nockhöjd|byggnadshöjd|totalhöjd|höjd|\+\d",
    "storeys": r"våning",
    "plot_size": r"fastighetsstorlek|fastighet(?:er)? får|minsta tomt",
    "no_building": r"får inte förses med byggnad|prickmark",
    "ancillary": r"komplementbyggnad|uthus|garage|förråd",
    "roof": r"takvinkel|tak",
    "implementation": r"genomförandetid",
    "use": r"^(?:[A-ZÅÄÖ]{1,2}\d{0,2}|GATA|LOKALGATA|HUVUDGATA|NATUR|PARK|TORG)$",
    "shoreline": r"strandskydd",
    "noise": r"buller|\bdB\b",
    "design": r"utformning|fasad|material|kulör",
}


def file_stem(url: str) -> str:
    return unquote(urlparse(url or "").path.rsplit("/", 1)[-1]).rsplit(".", 1)[0]


def role_of(document: dict) -> str:
    haystack = f"{file_stem(document.get('url'))} {document.get('title') or ''}".lower()
    for role, pattern in ROLES:
        if re.search(pattern, haystack):
            return role
    return "other"


def plan_key(stem: str) -> str:
    key = stem.lower().replace("_", " ").replace("-", " ").replace("+", " ")
    key = re.sub(r"(\d)([a-zåäö])", r"\1 \2", key)                     # "1.1plankartaa3" -> "1.1 plankartaa3"
    key = re.sub(r"^\s*(?:\d{1,2}(?:\.\d{1,2})*\.?\s+)+", " ", key)     # agenda / document numbering "17. ", "1.2 "
    key = re.sub(r"\d{6,8}|\b\d{4}[ .]?\d{2}[ .]?\d{2}\b|\b\d{6}\b|\b20\d\d\b|\(\d+\)|\bv\d+\b|\b1 \d{3,5}\b", " ", key)
    key = re.sub(r"\b(?:plankart|planbeskriv|bestämmels|granskningsutl|samrådsredog)\w*", " ", key)
    key = re.sub(rf"\b(?:{NOISE_WORDS}|tmp|kf|ks|bn|beslut|om|remiss|bilaga|handlingar|handling|gällande|"
                 rf"kopplat|till|exploateringsavtal|avtal|a\d[ls]?)\b", " ", key)
    key = re.sub(r"[^\wåäö:.]+", " ", key)
    return " ".join(key.split()).strip(" .")


LISTING_PAGE = re.compile(r"^\W*(?:gällande|pågående|antagna|aktuella|nya|äldre)?\s*detaljplaner\b", re.I)
PLAN_TITLE = re.compile(r"(?:Detaljplan|Ändring av detaljplan|Ändring av detaljplanen|Upphävande av detaljplan)"
                        r"\s+(?:för|över)\s+([^\n]{4,90})", re.I)


def title_from_text(texts: list[str]) -> str | None:
    """'Detaljplan för Kumla-Stensta, Vallentuna kommun' on the first page of a plankarta / planbeskrivning."""
    for text in texts:
        match = PLAN_TITLE.search(text[:2500])
        if match:
            return " ".join(match.group(0).split()).rstrip(" ,.")
    return None


def status_of(page_url: str, texts: list[str]) -> tuple[str, str | None, str | None]:
    """(status, laga kraft date, adoption date) from the linking page and the documents' text."""
    joined = "\n".join(texts)
    laga = LAGA_KRAFT.search(joined)
    adopted = ANTAGEN.search(joined)
    if laga:
        return "in_force", laga.group(1), adopted.group(1) if adopted else None
    for status, pattern in STATUS_PAGE:
        if re.search(pattern, (page_url or "").lower()):
            if status == "in_progress":
                for stage, stage_pattern in STAGES[1:]:
                    if re.search(stage_pattern, joined, re.I):
                        return stage, None, adopted.group(1) if adopted else None
            return status, None, adopted.group(1) if adopted else None
    for stage, pattern in STAGES:
        if re.search(pattern, joined, re.I):
            return stage, None, adopted.group(1) if adopted else None
    return "unknown", None, adopted.group(1) if adopted else None


def provisions_of(text: str, is_map: bool) -> list[dict]:
    """Planbestämmelser lines after the PLANBESTÄMMELSER heading. On a plankarta: coded lines and measure sentences.
    In a planbeskrivning (prose): only lowercase-coded lines and short sentences with a measure and a number."""
    start = re.search(r"planbestämmelser", text, re.I)
    if start is None:
        return []
    found, seen = [], set()
    for line in text[start.start():].splitlines():
        line = " ".join(line.split())
        if not line or len(line) > 420 or NOT_A_RULE.search(line):
            continue
        match = PROVISION_LINE.match(line)
        code, body = (match.group(1), match.group(2)) if match else (None, line)
        if code and code[0].isupper() and not code.startswith("+") and (not is_map or len(body) > 150):
            code, body = None, line  # "I Norrköping ..." is a sentence, not use code I
        if code is None:
            if not MEASURE.search(line) or (not is_map and (len(line) > 200 or not NUMBER.search(line))):
                continue
        law = LAW_REF.search(body)
        rule = body[:law.start()].rstrip(" ,.") if law else body
        if len(rule) < 8 or (code is None and len(rule.split()) <= 2) or (code, rule) in seen:  # headings
            continue
        seen.add((code, rule))
        topics = [t for t, pattern in TOPICS.items()
                  if re.search(pattern, (code or "") if t == "use" else f"{code or ''} {rule}", re.I if t != "use" else 0)]
        if code and topics == ["use"] and len(rule) > 120:  # a sentence starting with a capital is not a use code
            topics = []
        found.append({"code": code, "text": rule, "law_ref": law.group(1) if law else None, "topics": topics,
                      "numbers": [f"{n} {u}" for n, u in NUMBER.findall(rule)][:6]})
    return found


def chunk_for(provision_text: str, chunks: list[tuple[str, str]]) -> str | None:
    """The chunk that contains the provision (a shorter prefix when chunking cut the line)."""
    words = provision_text.lower().split()
    flat = [(chunk_id, " ".join(text.lower().split())) for chunk_id, text in chunks]
    for size in (10, 5, 3):
        needle = " ".join(words[:size])
        hits = [chunk_id for chunk_id, text in flat if needle in text]
        if hits and (len(hits) == 1 or size == 3):
            return hits[0]
    return None


def main() -> None:
    documents = [d for d in read_jsonl(DOCUMENTS_PATH) if d["doc_type"] == "detaljplan" and d["kind"] != "law"]
    pages = {d["url"]: d for d in documents if d["doc_id"].startswith("page")}
    store = sqlite3.connect(STORE_PATH)

    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    keys_by_page: dict[str, set[str]] = defaultdict(set)
    for document in documents:
        if document["doc_id"].startswith("page"):
            continue
        key = plan_key(file_stem(document.get("url")))
        if len(key) < 3:  # "A1-L", "Plankarta": the linking page names the plan
            source = pages.get(document.get("source_page"))
            key = "page:" + document["source_page"] if source else "doc:" + document["doc_id"]
        groups[(document["kommun_code"], key)].append(document)
        keys_by_page[document.get("source_page")].add(key)

    plans = []
    for (code, key), docs in groups.items():
        page_urls = [d.get("source_page") for d in docs if d.get("source_page")]
        page = pages.get(max(set(page_urls), key=page_urls.count)) if page_urls else None
        # A page that links only this plan's documents names it; a listing page of many plans does not
        own_page = page is not None and keys_by_page[page["url"]] == {key}
        fallback = key if not key.startswith(("page:", "doc:")) else (docs[0]["title"] or key)
        name = page["title"] if own_page else (title_from_text([d.get("text") or "" for d in docs]) or fallback)
        plans.append(build_plan(code, name, docs, page if own_page else None, page_urls, store))
    for url, page in pages.items():  # plan pages with no PDFs of their own
        if url not in keys_by_page and not LISTING_PAGE.search(page["title"] or "") and re.search(r"detaljplan|planområde|planförslag", page.get("text") or "", re.I):
            plans.append(build_plan(page["kommun_code"], page["title"], [], page, [url], store))

    written = write_jsonl(PLANS_PATH, sorted(plans, key=lambda p: (p["kommun_code"], p["name"])))
    with_rules = [p for p in plans if p["provisions"]]
    cited = sum(1 for p in with_rules for r in p["provisions"] if r["chunk_id"])
    print(f"{written} plans -> {PLANS_PATH}\n  {len(with_rules)} with provisions "
          f"({sum(len(p['provisions']) for p in with_rules)} provisions, {cited} tied to a chunk)\n"
          f"  status: {dict(Counter(p['status'] for p in plans).most_common())}\n"
          f"  with PDFs: {sum(1 for p in plans if p['documents'])}, kommuner: {len({p['kommun_code'] for p in plans})}")


def build_plan(code: str, name: str, docs: list[dict], page: dict | None, page_urls: list[str],
               store: sqlite3.Connection) -> dict:
    texts = [d.get("text") or "" for d in docs] + ([page.get("text") or ""] if page else [])
    status, laga_kraft, adopted = status_of(page_urls[0] if page_urls else "", texts)
    number = next((m.group(1) for t in [name, *texts] for m in [PLAN_NUMBER.search(t[:3000])] if m), None)
    provisions = []
    for document in sorted(docs, key=lambda d: role_of(d) != "plankarta"):
        found = provisions_of(document.get("text") or "", is_map=role_of(document) == "plankarta")
        if not found:
            continue
        chunks = store.execute("SELECT chunk_id, text FROM chunks WHERE doc_id = ?", (document["doc_id"],)).fetchall()
        for provision in found:
            # corpus.chunk drops paragraphs repeated across the corpus (standard plan wording), so a provision may
            # have no chunk of its own: it is then cited through a chunk of its plankarta (exact=False)
            chunk_id = chunk_for(provision["text"], chunks)
            provision.update(doc_id=document["doc_id"], chunk_id=chunk_id or (chunks[0][0] if chunks else None),
                             exact=chunk_id is not None)
        provisions = found
        break  # the plankarta first; a planbeskrivning only when no map text exists
    kommun = (docs[0] if docs else page)["kommun"]
    return {
        "plan_id": stable_id(code, name, *(d["doc_id"] for d in docs)),
        "kommun_code": code, "kommun": kommun, "name": " ".join(name.split()), "plan_number": number,
        "status": status, "laga_kraft": laga_kraft, "adopted": adopted,
        "page": {"doc_id": page["doc_id"], "url": page["url"]} if page else None,
        "documents": [{"doc_id": d["doc_id"], "role": role_of(d), "title": d.get("title"), "url": d.get("url"),
                       "pages": d.get("pages"), "scanned": bool(d.get("needs_ocr"))} for d in docs],
        "provisions": provisions,
    }


if __name__ == "__main__":
    main()

"""
Match every plan polygon in the snapshots to its documents in the document store (data/corpus/documents.jsonl, the
detaljplan documents corpus.extract wrote), so a pin leads to the text of the plans at the point without a search:

    cd backend && python -m place.plan_links                     # every kommun with a snapshot
    python -m place.plan_links --kommun 0182 --kommun 0380       # some of them
    python -m place.plan_links --kommun 0380 --hosted            # against the hosted corpus (CORPUS_DATABASE_URL)

-> data/geo/<code>/plan_links.jsonl (the link table), data/geo/plan_fetch_list.json (the links of the polygons no
document matched, for the scraper) and data/geo/plan_match_report.md (one line per kommun). Three match levels per
polygon, tried in order, the first with a hit wins: LINK (a polygon link equals a document's address), AKT (the
normalised aktbeteckning equals one read from the title, the file name or the front of the text of a document of the
same kommun) and NAME (the kommun and the plan name agree, marked for review). Restart the backend after a run.

--hosted matches against the PDFs of the hosted corpus instead, where a polygon also hits the documents of the registry
plan (data/corpus/plans.jsonl) with its page, and writes the kommun's link table and its text report
(data/geo/<code>/plan_text_report.md: the share of polygons with text, and why the others have none). The last run
decides what a kommun's table holds, so a run against the local document store replaces a hosted one's links.
"""

import argparse
import json
import os
import re
from collections.abc import Callable
from pathlib import Path
from urllib.parse import unquote, urlsplit

from corpus.common import BACKEND_DIR, DATA_DIR, DOCUMENTS_PATH
from place import plan_layers
from place.sources import PILOTS, plan_layer_definitions, today
from place.sources import feature as pilot_feature
from place.store import GEO_DIR, PlaceStore

LINKS_FILE = "plan_links.jsonl"
FETCH_LIST = "plan_fetch_list.json"
MATCH_REPORT = "plan_match_report.md"
TEXT_REPORT = "plan_text_report.md"  # beside a kommun's snapshot: the polygons with and without text in the corpus
LEVELS = ("link", "akt", "name")
NO_PUBLIC_LINK = "no public link"
# Why a polygon has no documents in the hosted corpus, for the text report
NO_LINK = "the polygon has no link"
NOT_IN_REGISTRY = "its plan page is not in the plan registry"
NOT_IN_CORPUS = "its plan has no documents in the hosted corpus"
DOCUMENT_TYPE = "detaljplan"
HOSTED_FRONT_CHUNKS = 3  # chunks read per hosted document: more than AKT_FRONT_CHARS of text
# How far into a document's text an aktbeteckning says the document is about that plan, about its first page. Further
# in it is most often a mention: a new plan's description lists the plans it replaces and the plans around it
AKT_FRONT_CHARS = 3000

KOMMUN_PREFIX = re.compile(r"^\d{4}K?-")
# An aktbeteckning in running text: with its kommun prefix ("0182K-93/62", "0182-P 2015/3", "2280-DP-193") or a
# letter prefix ("P2015-12", "DP 2015/3"); a bare "2015-06" would be a date, so one of the two is required
AKT_IN_TEXT = re.compile(r"(?<![\w/])(?:(\d{4})K?\s?-\s?([A-ZÅÄÖ]{0,3}\s?\d{1,4}(?:\s?[/\-.]\s?\d{1,4}){0,2})"
                         r"|([A-ZÅÄÖ]{1,3}\s?\d{2,4}\s?[/\-.]\s?\d{1,4}(?:[/\-]\d{1,3})?))(?![\w/])")
PLAN_WORDS = re.compile(r"^(?:(?:ändring|upphävande|tillägg) (?:av|till) )?(?:detaljplan(?:en)?|stadsplan(?:en)?|"
                        r"byggnadsplan(?:en)?|områdesbestämmelser) (?:för|över) ", re.IGNORECASE)


class DocumentStoreUnavailable(RuntimeError):
    """The document store cannot be read (its file is missing or unreadable)."""


def normalise_akt(text: str | None) -> str | None:
    """One key for the spellings of an aktbeteckning: the kommun code prefix ("0380-", "0380K-") dropped, upper
    case, no whitespace, "-" and "." read as "/", so "0380-P2015/12", "0380-P 2015/12" and "P2015-12" give
    "P2015/12". None for None, an empty string or a value without a digit."""
    if text is None:
        return None
    key = KOMMUN_PREFIX.sub("", re.sub(r"\s+", "", str(text).upper()))
    key = key.replace("-", "/").replace(".", "/")
    return key if re.search(r"\d", key) else None


def polygon_key(plan: dict) -> str | None:
    """The key a link table row and a profile plan row share: the plan's aktbeteckning ("ref"), else its page or
    first document link ("url"), else its name; None when the plan has none of them."""
    return plan.get("ref") or plan.get("url") or plan.get("name") or None


def load_documents(path: Path = DOCUMENTS_PATH) -> dict[str, list[dict]]:
    """The document store's detaljplan documents by kommun code: {"0182": [{"doc_id", "kommun_code", "title",
    "url", "text"}, ...]}, laws and other document types left out. Raises DocumentStoreUnavailable when `path` is
    missing or not readable."""
    by_kommun: dict[str, list[dict]] = {}
    try:
        with Path(path).open(encoding="utf-8") as lines:
            for line in lines:
                if not line.strip():
                    continue
                document = json.loads(line)
                if document.get("kind") != "law" and document.get("doc_type") == DOCUMENT_TYPE and document.get("kommun_code"):
                    by_kommun.setdefault(document["kommun_code"], []).append(document)
    except (OSError, ValueError) as exc:
        raise DocumentStoreUnavailable(f"The document store {path} cannot be read: {exc}") from exc
    return by_kommun


def load_hosted_documents(codes: list[str], store, plans: Callable[[str], list[dict]]) -> dict[str, list[dict]]:
    """The hosted corpus's detaljplan PDFs of the kommuner in `codes`, by kommun code, in load_documents' shape: {"doc_id",
    "kommun_code", "title", "url", "text" (the document's first chunks)} plus "plan_pages" (the page urls of the
    registry plans holding the document, [] when none) and "role" (the registry's role, "plankarta",
    "planbeskrivning", ..., None for a document in no plan). `store` answers query(sql, params) on the chunks view
    (localrag.pg_store.PgStore); `plans` gives a kommun's registry plans. Raises DocumentStoreUnavailable when the
    store cannot be read."""
    by_kommun: dict[str, list[dict]] = {}
    try:
        for code in codes:
            of_plans: dict[str, dict] = {}
            for plan in plans(code):
                page = (plan.get("page") or {}).get("url")
                for held in plan.get("documents") or []:
                    entry = of_plans.setdefault(held["doc_id"], {"role": held.get("role"), "plan_pages": []})
                    if page:
                        entry["plan_pages"].append(page)
            documents: dict[str, dict] = {}
            for row in store.query("SELECT doc_id, title, url, kommun_code, text FROM chunks WHERE kind = 'pdf' "
                                   "AND doc_type = ? AND kommun_code = ? AND CAST(chunk_index AS INTEGER) < ? "
                                   "ORDER BY doc_id, CAST(chunk_index AS INTEGER)",
                                   (DOCUMENT_TYPE, code, HOSTED_FRONT_CHUNKS)):
                known = of_plans.get(row["doc_id"], {})
                document = documents.setdefault(row["doc_id"], {
                    "doc_id": row["doc_id"], "kommun_code": row["kommun_code"], "title": row["title"], "url": row["url"],
                    "text": "", "role": known.get("role"), "plan_pages": known.get("plan_pages", [])})
                document["text"] += (row["text"] or "") + "\n"
            by_kommun[code] = list(documents.values())
    except Exception as exc:  # the driver's own errors: psycopg2 is only imported with the hosted store
        raise DocumentStoreUnavailable(f"The hosted corpus cannot be read: {exc}") from exc
    return by_kommun


# --- the polygons and the keys ----------------------------------------------------------------------------------

def _polygons(code: str, geo_dir: Path) -> list[dict]:
    """The snapshot's plans as {"ref", "name", "url", "page", "documents", "dropped_links"}, in file order. A pilot
    kommun's plans are those of its plan layers (plans, additions, area regulations), each with the page its document
    link leads to (plan_pages.json, place.plan_documents) when known."""
    if code not in PILOTS:
        polygons = []
        for item in _features(geo_dir / code / f"{plan_layers.LAYER_ID}.geojson"):
            props = item.get("properties") or {}
            row = plan_layers.feature(props)
            polygons.append({"ref": row["ref"], "name": row["name"], "url": row["url"], "page": row["page"],
                             "documents": row["documents"],
                             "dropped_links": (props.get(plan_layers.PLAN_KEY) or {}).get("dropped_links", 0)})
        return polygons
    pages = PlaceStore(geo_dir).plan_pages(code)
    polygons = []
    for layer in plan_layer_definitions(code):
        for item in _features(geo_dir / code / f"{layer.id}.geojson"):
            row = pilot_feature(layer, item.get("properties") or {})
            polygons.append({"ref": row["ref"], "name": row["name"], "url": row["url"],
                             "page": pages.get(row["ref"]) or row["url"],
                             "documents": [row["url"]] if pages.get(row["ref"]) and row["url"] else [],
                             "dropped_links": 0})
    return polygons


def _features(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["features"] if path.exists() else []


def _url_key(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(str(url).strip())
    key = parts.netloc.lower() + parts.path.rstrip("/")
    return key + (f"?{parts.query}" if parts.query else "") if key else None


def _name_key(text: str | None, kommun: str | None) -> str:
    key = " ".join(str(text or "").lower().split())
    key = PLAN_WORDS.sub("", key)
    if kommun:
        key = re.sub(rf"\s*[-–|]\s*{re.escape(kommun.lower())} kommun\s*$", "", key)
    return " ".join(re.findall(r"[0-9a-zåäöé:]+", key))


def _akt_keys_in(text: str, code: str) -> set[str]:
    """The normalised aktbeteckningar a document's text names, those with another kommun's prefix left out."""
    keys = set()
    for prefix, with_prefix, bare in AKT_IN_TEXT.findall(text or ""):
        if prefix and prefix != code:
            continue
        key = normalise_akt(with_prefix or bare)
        if key:
            keys.add(key)
    return keys


def _own_akt_keys(document: dict, code: str) -> set[str]:
    """The aktbeteckningar a document presents as its own: in its title, its file name (read in upper case, as file
    names are often lower case) or the first AKT_FRONT_CHARS of its text. One named further in is only a mention."""
    file_name = unquote(urlsplit(str(document.get("url") or "")).path.rstrip("/").rsplit("/", 1)[-1]).upper()
    places = (document.get("title"), file_name, (document.get("text") or "")[:AKT_FRONT_CHARS])
    return set().union(*(_akt_keys_in(place, code) for place in places))


def _links_of(polygon: dict) -> list[str]:
    return [link for link in [polygon["page"], *polygon["documents"]] if link]


# --- the match ----------------------------------------------------------------------------------------------------

class _Index:
    """The kommun's documents indexed by the three levels' keys."""

    def __init__(self, documents: list[dict], code: str, kommun: str | None):
        self.by_url: dict[str, list[dict]] = {}
        self.by_akt: dict[str, list[dict]] = {}
        self.by_name: dict[str, list[dict]] = {}
        for document in documents:
            for url in map(_url_key, [document.get("url"), *document.get("plan_pages", [])]):
                if url:
                    self.by_url.setdefault(url, []).append(document)
            if document.get("plan_pages"):
                continue  # the registry knows its plan: an aktbeteckning or a name in it is only a mention of another
            for key in _own_akt_keys(document, code):
                self.by_akt.setdefault(key, []).append(document)
            name = _name_key(document.get("title"), kommun)
            if name:
                self.by_name.setdefault(name, []).append(document)

    def hits(self, polygon: dict, kommun: str | None) -> tuple[str | None, list[dict]]:
        """(level, documents) of the first level with a hit, (None, []) when none."""
        urls = {key for key in map(_url_key, _links_of(polygon)) if key}
        link = _unique(document for url in urls for document in self.by_url.get(url, []))
        if link:
            return "link", link
        akt = normalise_akt(polygon["ref"])
        if akt and self.by_akt.get(akt):
            return "akt", _unique(self.by_akt[akt])
        name = _name_key(polygon["name"], kommun)
        if name and self.by_name.get(name):
            return "name", _unique(self.by_name[name])
        return None, []


def _unique(documents) -> list[dict]:
    seen, unique = set(), []
    for document in documents:
        if document["doc_id"] not in seen:
            seen.add(document["doc_id"])
            unique.append(document)
    return unique


def _kommun_name(code: str, geo_dir: Path) -> str | None:
    path = geo_dir / code / "manifest.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get("kommun", {}).get("name")


def match_kommun(code: str, documents: list[dict], *, geo_dir: Path = GEO_DIR) -> dict:
    """Match the plan polygons of the kommun's snapshot (a plan-layer kommun's `geo_dir`/<code>/plans.geojson through
    place.plan_layers.feature, a pilot kommun's plan layers through place.sources.feature) to `documents`, the store's
    documents of that kommun only.

    Per polygon the levels run in order and stop at the first with a hit; every document hitting at that level is
    linked, and a document may be linked from several polygons. "link": a polygon's page or document link equals a
    document's url (scheme, trailing slash and case of the host ignored). "akt": the polygon's normalised
    aktbeteckning equals one in a document's title, file name or first AKT_FRONT_CHARS of text, unless the plan
    registry places the document under a plan page ("plan_pages"), which makes that page's plan its plan. "name": the polygon's name and a document's title agree
    once "Detaljplan för", the kommun suffix, case and punctuation are dropped; such a link carries "review" True.

    Returns {"code", "links": [{"key" (polygon_key), "ref", "doc_id", "level", "review", "role" (the document's, None
    when it has none), "date"}], "fetch":
    [{"key", "ref", "name", "links" (the polygon's page and document links), "reason" (NO_PUBLIC_LINK when the
    polygon had links dropped as internal paths and none left, else None)}] for the polygons no document matched,
    "report": {"code", "polygons", "link", "akt", "name", "unmatched", "documents", "unclaimed_share" (the share
    of `documents` no polygon claimed, None without documents)}}. Nothing is written."""
    kommun = _kommun_name(code, geo_dir)
    own = [document for document in documents if document.get("kommun_code") == code]
    index = _Index(own, code, kommun)
    date = today()
    links, fetch, claimed = [], [], set()
    counts = dict.fromkeys(LEVELS, 0)
    for polygon in _polygons(code, geo_dir):
        level, hits = index.hits(polygon, kommun)
        if level is None:
            no_link = not _links_of(polygon) and polygon["dropped_links"] > 0
            fetch.append({"key": polygon_key(polygon), "ref": polygon["ref"], "name": polygon["name"],
                          "links": _links_of(polygon), "reason": NO_PUBLIC_LINK if no_link else None})
            continue
        counts[level] += 1
        for document in hits:
            claimed.add(document["doc_id"])
            links.append({"key": polygon_key(polygon), "ref": polygon["ref"], "doc_id": document["doc_id"],
                          "level": level, "review": level == "name", "role": document.get("role"), "date": date})
    polygons = sum(counts.values()) + len(fetch)
    report = {"code": code, "polygons": polygons, **counts, "unmatched": len(fetch), "documents": len(own),
              "unclaimed_share": (1 - len(claimed) / len(own)) if own else None}
    return {"code": code, "links": links, "fetch": fetch, "report": report}


def write_links(code: str, links: list[dict], geo_dir: Path = GEO_DIR) -> None:
    """Write the kommun's link table to `geo_dir`/<code>/LINKS_FILE, one JSON row per line, replacing the earlier
    table."""
    (geo_dir / code / LINKS_FILE).write_text("".join(json.dumps(link, ensure_ascii=False) + "\n" for link in links),
                                             encoding="utf-8")


def _share(value: float | None) -> str:
    return "–" if value is None else f"{round(value * 100)} %"


def match_report(rows: list[dict]) -> str:
    """The report rows of match_kommun as Markdown: a heading with the date, then one table row per kommun: code,
    polygons, matched at each level, unmatched, store documents, share unclaimed."""
    matched, polygons = sum(row["polygons"] - row["unmatched"] for row in rows), sum(row["polygons"] for row in rows)
    lines = [f"# Plan documents matched, {today()}", "", f"{matched} of {polygons} polygons matched in {len(rows)} kommuner.", "",
             "| Kod | Polygons | Link | Akt | Name (review) | Unmatched | Documents | Unclaimed |",
             "|---|---|---|---|---|---|---|---|"]
    for row in rows:
        lines.append(f"| {row['code']} | {row['polygons']} | {row['link']} | {row['akt']} | {row['name']} | "
                     f"{row['unmatched']} | {row['documents']} | {_share(row['unclaimed_share'])} |")
    return "\n".join(lines) + "\n"


def run(codes: list[str], documents: Callable[[], dict[str, list[dict]]] = load_documents, *,
        geo_dir: Path = GEO_DIR) -> list[dict]:
    """match_kommun for every kommun in `codes` (those with a snapshot under `geo_dir`), then write each kommun's link
    table, the fetch list ({code: fetch items}) to `geo_dir`/FETCH_LIST and the report to `geo_dir`/MATCH_REPORT.
    Returns the report rows. `documents` is read once before anything is written: a DocumentStoreUnavailable it
    raises stops the run with nothing written."""
    by_kommun = documents()
    results = [match_kommun(code, by_kommun.get(code, []), geo_dir=geo_dir) for code in codes]
    for result in results:
        write_links(result["code"], result["links"], geo_dir)
    fetch = {result["code"]: result["fetch"] for result in results if result["fetch"]}
    (geo_dir / FETCH_LIST).write_text(json.dumps(fetch, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    rows = [result["report"] for result in results]
    (geo_dir / MATCH_REPORT).write_text(match_report(rows), encoding="utf-8")
    return rows


def text_report(code: str, result: dict, plans: list[dict]) -> str:
    """The text report of one kommun as Markdown, from match_kommun's `result`: the share of polygons with documents
    in the hosted corpus, the counts per match level, and a table of the polygons without documents (aktbeteckning,
    name, reason: NO_LINK when the polygon has no link, NOT_IN_REGISTRY when no plan of `plans` has its page,
    NOT_IN_CORPUS when one has but none of its documents is in the corpus)."""
    pages = {_url_key((plan.get("page") or {}).get("url")) for plan in plans} - {None}

    def reason(item: dict) -> str:
        if not item["links"]:
            return NO_LINK
        return NOT_IN_CORPUS if pages & set(map(_url_key, item["links"])) else NOT_IN_REGISTRY

    row = result["report"]
    matched = row["polygons"] - row["unmatched"]
    share = _share(matched / row["polygons"] if row["polygons"] else None)
    reasons = [(item, reason(item)) for item in result["fetch"]]
    lines = [f"# Plan text in the hosted corpus, kommun {code}, {today()}", "",
             f"{matched} of {row['polygons']} polygons have documents in the hosted corpus ({share}): "
             f"{row['link']} by link, {row['akt']} by aktbeteckning, {row['name']} by name (for review).", ""]
    if reasons:
        lines += [f"- {text}: {sum(1 for _, why in reasons if why == text)}"
                  for text in (NO_LINK, NOT_IN_REGISTRY, NOT_IN_CORPUS)]
        lines += ["", "| Aktbeteckning | Name | Reason |", "|---|---|---|"]
        lines += [f"| {item['ref'] or '–'} | {item['name'] or '–'} | {why} |" for item, why in reasons]
    return "\n".join(lines) + "\n"


def run_hosted(code: str, store, plans: Callable[[str], list[dict]], *, geo_dir: Path = GEO_DIR) -> dict:
    """Match one kommun's polygons against the hosted corpus: a polygon's page or document link hits a document when it
    equals the document's address or the page of a registry plan holding it, then the akt and name levels as in
    match_kommun. Writes `geo_dir`/<code>/LINKS_FILE, each row also carrying the document's "role", and
    `geo_dir`/<code>/TEXT_REPORT; the national fetch list and match report are left alone. Returns match_kommun's
    report row. A DocumentStoreUnavailable stops the run with nothing written."""
    result = match_kommun(code, load_hosted_documents([code], store, plans).get(code, []), geo_dir=geo_dir)
    report = text_report(code, result, plans(code))
    write_links(code, result["links"], geo_dir)
    (geo_dir / code / TEXT_REPORT).write_text(report, encoding="utf-8")
    return result["report"]


def _registry_plans(code: str) -> list[dict]:
    """The plan registry's plans of a kommun (data/corpus/plans.jsonl), [] without the file."""
    path = DATA_DIR / "plans.jsonl"
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as lines:
        return [plan for plan in map(json.loads, lines) if plan["kommun_code"] == code]


def _main_hosted(codes: list[str]) -> None:
    from dotenv import load_dotenv

    from localrag.pg_store import PgStore

    load_dotenv(BACKEND_DIR / ".env")
    if not os.getenv("CORPUS_DATABASE_URL"):
        raise SystemExit("Nothing written: --hosted needs CORPUS_DATABASE_URL")
    try:
        store = PgStore(os.environ["CORPUS_DATABASE_URL"])
        for code in codes:
            row = run_hosted(code, store, _registry_plans)
            print(f"{code}: {row['polygons'] - row['unmatched']} of {row['polygons']} polygons have documents -> "
                  f"{GEO_DIR / code / TEXT_REPORT}")
    except DocumentStoreUnavailable as exc:
        raise SystemExit(f"Nothing written: {exc}") from exc
    except Exception as exc:  # opening the store: the driver's own errors, without the address in the message
        raise SystemExit(f"Nothing written: the hosted corpus cannot be reached ({type(exc).__name__})") from exc


def main() -> None:
    """CLI: --kommun <code> (repeatable, default every kommun with a snapshot); --hosted matches against the hosted
    corpus at CORPUS_DATABASE_URL (one or more --kommun required)."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--kommun", action="append", help="kommun code (default: every kommun with a snapshot)")
    parser.add_argument("--hosted", action="store_true", help="match against the hosted corpus (needs --kommun)")
    args = parser.parse_args()
    if args.hosted:
        if not args.kommun:
            parser.error("--hosted needs --kommun")
        _main_hosted(args.kommun)
        return
    codes = args.kommun or [kommun["code"] for kommun in PlaceStore().kommuner()]
    try:
        rows = run(codes)
    except DocumentStoreUnavailable as exc:
        raise SystemExit(f"Nothing written: {exc}") from exc
    matched = sum(row["polygons"] - row["unmatched"] for row in rows)
    print(f"{matched} of {sum(row['polygons'] for row in rows)} polygons matched in {len(rows)} kommuner -> "
          f"{GEO_DIR / MATCH_REPORT}")


if __name__ == "__main__":
    main()

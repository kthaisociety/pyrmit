"""
Match every plan polygon in the snapshots to its documents in the document store (data/corpus/documents.jsonl, the
detaljplan documents corpus.extract wrote), so a pin leads to the text of the plans at the point without a search:

    cd backend && python -m place.plan_links                     # every kommun with a snapshot
    python -m place.plan_links --kommun 0182 --kommun 0380       # some of them

-> data/geo/<code>/plan_links.jsonl (the link table), data/geo/plan_fetch_list.json (the links of the polygons no
document matched, for the scraper) and data/geo/plan_match_report.md (one line per kommun). Three match levels per
polygon, tried in order, the first with a hit wins: LINK (a polygon link equals a document's address), AKT (the
normalised aktbeteckning equals one read from a document's text of the same kommun) and NAME (the kommun and the
plan name agree, marked for review). Restart the backend after a run.
"""

import argparse
import json
import re
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

from corpus.common import DOCUMENTS_PATH
from place import plan_layers
from place.sources import PILOTS, layer_by_id, today
from place.sources import feature as pilot_feature
from place.store import GEO_DIR, PlaceStore

LINKS_FILE = "plan_links.jsonl"
FETCH_LIST = "plan_fetch_list.json"
MATCH_REPORT = "plan_match_report.md"
LEVELS = ("link", "akt", "name")
NO_PUBLIC_LINK = "no public link"
DOCUMENT_TYPE = "detaljplan"

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


# --- the polygons and the keys ----------------------------------------------------------------------------------

def _polygons(code: str, geo_dir: Path) -> list[dict]:
    """The snapshot's plans as {"ref", "name", "url", "page", "documents", "dropped_links"}, in file order. A pilot
    kommun's page is the one its document link leads to (plan_pages.json, place.plan_documents) when known."""
    path = geo_dir / code / f"{plan_layers.LAYER_ID}.geojson"
    layer = layer_by_id(code, plan_layers.LAYER_ID) if code in PILOTS else None
    pages = PlaceStore(geo_dir).plan_pages(code) if layer else {}
    polygons = []
    for item in json.loads(path.read_text(encoding="utf-8"))["features"]:
        props = item.get("properties") or {}
        if plan_layers.PLAN_KEY in props or layer is None:
            row = plan_layers.feature(props)
            polygons.append({"ref": row["ref"], "name": row["name"], "url": row["url"], "page": row["page"],
                             "documents": row["documents"],
                             "dropped_links": (props.get(plan_layers.PLAN_KEY) or {}).get("dropped_links", 0)})
        else:
            row = pilot_feature(layer, props)
            polygons.append({"ref": row["ref"], "name": row["name"], "url": row["url"],
                             "page": pages.get(row["ref"]) or row["url"],
                             "documents": [row["url"]] if pages.get(row["ref"]) and row["url"] else [],
                             "dropped_links": 0})
    return polygons


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
            url = _url_key(document.get("url"))
            if url:
                self.by_url.setdefault(url, []).append(document)
            for key in _akt_keys_in(document.get("text") or "", code):
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
    """Match the plan polygons of the kommun's snapshot (`geo_dir`/<code>/plans.geojson, a pilot kommun's plans read
    through place.sources.feature, a plan-layer kommun's through place.plan_layers.feature) to `documents`, the
    store's documents of that kommun only.

    Per polygon the levels run in order and stop at the first with a hit; every document hitting at that level is
    linked, and a document may be linked from several polygons. "link": a polygon's page or document link equals a
    document's url (scheme, trailing slash and case of the host ignored). "akt": the polygon's normalised
    aktbeteckning equals one found in a document's text. "name": the polygon's name and a document's title agree
    once "Detaljplan för", the kommun suffix, case and punctuation are dropped; such a link carries "review" True.

    Returns {"code", "links": [{"key" (polygon_key), "ref", "doc_id", "level", "review", "date"}], "fetch":
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
                          "level": level, "review": level == "name", "date": date})
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


def main() -> None:
    """CLI: --kommun <code> (repeatable, default every kommun with a snapshot)."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--kommun", action="append", help="kommun code (default: every kommun with a snapshot)")
    args = parser.parse_args()
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

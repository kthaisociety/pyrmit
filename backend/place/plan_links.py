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

from collections.abc import Callable
from pathlib import Path

from corpus.common import DOCUMENTS_PATH
from place.store import GEO_DIR

LINKS_FILE = "plan_links.jsonl"
FETCH_LIST = "plan_fetch_list.json"
MATCH_REPORT = "plan_match_report.md"
LEVELS = ("link", "akt", "name")
NO_PUBLIC_LINK = "no public link"


class DocumentStoreUnavailable(RuntimeError):
    """The document store cannot be read (its file is missing or unreadable)."""


def normalise_akt(text: str | None) -> str | None:
    """One key for the spellings of an aktbeteckning: the kommun code prefix ("0380-", "0380K-") dropped, upper
    case, no whitespace, "-" and "." read as "/", so "0380-P2015/12", "0380-P 2015/12" and "P2015-12" give
    "P2015/12". None for None, an empty string or a value without a digit."""
    raise NotImplementedError


def polygon_key(plan: dict) -> str | None:
    """The key a link table row and a profile plan row share: the plan's aktbeteckning ("ref"), else its page or
    first document link ("url"), else its name; None when the plan has none of them."""
    raise NotImplementedError


def load_documents(path: Path = DOCUMENTS_PATH) -> dict[str, list[dict]]:
    """The document store's detaljplan documents by kommun code: {"0182": [{"doc_id", "kommun_code", "title",
    "url", "text"}, ...]}, laws and other document types left out. Raises DocumentStoreUnavailable when `path` is
    missing or not readable."""
    raise NotImplementedError


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
    raise NotImplementedError


def write_links(code: str, links: list[dict], geo_dir: Path = GEO_DIR) -> None:
    """Write the kommun's link table to `geo_dir`/<code>/LINKS_FILE, one JSON row per line, replacing the earlier
    table."""
    raise NotImplementedError


def match_report(rows: list[dict]) -> str:
    """The report rows of match_kommun as Markdown: a heading with the date, then one table row per kommun: code,
    polygons, matched at each level, unmatched, store documents, share unclaimed."""
    raise NotImplementedError


def run(codes: list[str], documents: Callable[[], dict[str, list[dict]]] = load_documents, *,
        geo_dir: Path = GEO_DIR) -> list[dict]:
    """match_kommun for every kommun in `codes` (those with a snapshot under `geo_dir`), then write each kommun's link
    table, the fetch list ({code: fetch items}) to `geo_dir`/FETCH_LIST and the report to `geo_dir`/MATCH_REPORT.
    Returns the report rows. `documents` is read once before anything is written: a DocumentStoreUnavailable it
    raises stops the run with nothing written."""
    raise NotImplementedError


def main() -> None:
    """CLI: --kommun <code> (repeatable, default every kommun with a snapshot)."""
    raise NotImplementedError


if __name__ == "__main__":
    main()

"""
Snapshot the plan layers of the kommun plan sources (place.registry) for the place profile, in the format
place.fetch writes for the pilot kommuner, and report the coverage:

    cd backend && python -m place.plan_layers                      # every kommun in place/plan_sources.json
    python -m place.plan_layers --kommun 0182 --kommun 0120        # some of them

-> data/geo/<code>/kommun.geojson, plans.geojson, manifest.json per kommun, and data/geo/plan_coverage.md.
Restart the backend after fetching.
"""

from collections.abc import Iterable
from pathlib import Path

import httpx

from place.registry import PlanSource
from place.store import GEO_DIR

PLAN_KEY = "_plan"                  # the block plan_properties adds to a snapshot feature's properties
LAYER_ID = "plans"                  # the snapshot file and manifest key, as for the pilot kommuner
LAYER_TITLE = "Gällande detaljplaner"
MIN_SHARE_OF_SURVEY = 0.5           # fewer polygons than this share of the survey's count flags the fetch
COVERAGE_REPORT = "plan_coverage.md"


def feature(props: dict) -> dict:
    """The profile row of a snapshot plan from its properties, read from their PLAN_KEY block: {"layer": LAYER_ID,
    "kind": "plan", "layer_title": LAYER_TITLE, "name", "ref" (aktbeteckning), "type", "date" (ISO), "url" (the
    plan page, else the first document link, else None), "page", "documents" (absolute links, in the layer's
    order), "status", "authority", "law", "text", "note" (all None)}."""
    raise NotImplementedError


def fetch_plan_layer(source: PlanSource, *, client: httpx.Client | None = None, out_dir: Path = GEO_DIR) -> dict:
    """Snapshot the plan layer of `source` into `out_dir`/<code>/, the format place.store.PlaceStore reads:

    - `kommun.geojson`: the kommun boundary from OpenStreetMap (place.fetch.kommun_boundary), fetched when the file
      is missing and kept otherwise
    - `plans.geojson`: every polygon of the layer that meets the boundary (a shared server's other kommuner are
      left out), with the provider's raw attributes plus a PLAN_KEY block: {"ref" (aktbeteckning), "name", "date"
      (ISO), "type" (when the layer states it, else None), "page" (the first link that is not a file), "documents"
      (the file links, absolute, each once), "dropped_links"}. A link that is only a file name becomes absolute
      through the source's base_url ("{file}" replaced, or the name joined to the pattern); a link wrapped in HTML
      keeps the addresses of its anchors; an internal path (a UNC path, a drive letter, file:) and a bare name
      without a base_url are dropped and counted; a "www." address gets https.
    - `manifest.json`: "kommun" {"code", "name", "fetched", "source", "licence"} and "layers" {"plans": {"title",
      "provider" ("<name> kommun"), "licence", "url", "layer_id" None, "type_name", "count", "fetched" (today),
      "complete" False, "service", "status", "ref_share", "link_share", "dropped_links"}}

    Returns the coverage row: {"code", "name", "fetched" (True when the snapshot was written), "reason" (why it
    was not, else None), "count" (polygons kept), "survey_count", "ref_share" (share of the kept polygons with an
    aktbeteckning), "link_share" (share with a page or document link), "dropped_links", "date" (today)}. The
    shares are None when nothing was fetched.

    No snapshot is written, and an earlier one is left as it is, when the service fails, answers with no polygon,
    or with fewer than MIN_SHARE_OF_SURVEY of the survey's count for a source that is not shared; the row then
    carries the reason. A failing service never raises."""
    raise NotImplementedError


def fetch_registry(sources: Iterable[PlanSource], *, client: httpx.Client | None = None,
                   out_dir: Path = GEO_DIR) -> list[dict]:
    """fetch_plan_layer for every source, in the order given, going on after a kommun that fails, then
    coverage_report of the rows written to `out_dir`/COVERAGE_REPORT. Returns the coverage rows."""
    raise NotImplementedError


def coverage_report(rows: list[dict]) -> str:
    """The coverage rows as Markdown: a heading with the date and how many kommuner were fetched, then a table with
    one row per kommun: code, name, fetched or not with the reason, polygons, the survey's count, share with an
    aktbeteckning, share with a link, dropped links."""
    raise NotImplementedError


def main() -> None:
    """CLI: --kommun <code> (repeatable, default every kommun in the registry) and --registry <json>."""
    raise NotImplementedError


if __name__ == "__main__":
    main()

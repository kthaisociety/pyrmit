"""
Snapshot the area layers of pilot kommuner (place.sources.PILOTS) for the place profile:

    cd backend && python -m place.fetch --kommun 0380            # all layers, ~1-2 min
    python -m place.fetch --kommun 0380 --only plans,natura2000  # some layers again

-> data/geo/<code>/kommun.geojson (boundary: OpenStreetMap via Nominatim, ODbL), <layer>.geojson (raw attributes,
WGS84) and manifest.json (fetch date, source, licence and count per layer), the format place.store.PlaceStore
reads. Restart the backend after fetching.
"""

from pathlib import Path

import httpx

from place.store import GEO_DIR


def fetch_kommun(code: str, only: set[str] | None = None, *, client: httpx.Client | None = None,
                 out_dir: Path = GEO_DIR) -> dict:
    """Snapshot pilot kommun `code` (every layer, or the layer ids in `only`) into `out_dir`/<code>/ and return
    its manifest. National layers keep only the features that meet the kommun boundary. A layer whose fetch fails
    keeps its previous snapshot and gets "last_error" in the manifest; the others are still written.
    Raises KeyError for a kommun that is not a pilot."""
    raise NotImplementedError


def main() -> None:
    """CLI: --kommun <code> (repeatable, default every pilot kommun) and --only <layer ids, comma-separated>."""
    raise NotImplementedError


if __name__ == "__main__":
    main()

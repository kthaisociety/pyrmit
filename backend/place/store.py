"""The place snapshots (data/geo/<code>/, written by place.fetch): which kommun a point lies in and which
features of a layer cover a geometry."""

from pathlib import Path

GEO_DIR = Path(__file__).resolve().parent.parent / "data" / "geo"


class PlaceStore:
    """The snapshots of every pilot kommun under `root`, read on first use.

    Snapshot format, one folder per kommun code:
    - `manifest.json`: {"kommun": {"code", "name", "fetched", "source", "licence"}, "layers": {<layer id>:
      {"title", "provider", "licence", "count", "fetched", "complete", ...}}}. Layer ids are those of
      `place.sources`; "complete" (plans only) means the layer holds every plan in force.
    - `kommun.geojson`: one Feature, the kommun boundary.
    - `<layer id>.geojson`: a FeatureCollection in WGS84 with the provider's raw attributes.

    A layer listed in the manifest without its file is reported as unavailable, never as empty."""

    def __init__(self, root: Path = GEO_DIR):
        raise NotImplementedError

    def kommuner(self) -> list[dict]:
        """The pilot kommuner that have a snapshot: [{"code", "name", "bbox": [west, south, east, north],
        "fetched"}], in code order."""
        raise NotImplementedError

    def kommun_at(self, lon: float, lat: float) -> str | None:
        """Code of the pilot kommun whose boundary contains the point, or None outside every snapshot."""
        raise NotImplementedError

    def layers(self, code: str) -> list[dict]:
        """The kommun's layers from its manifest: [{"id", "title", "provider", "licence", "fetched", "complete",
        "status"}], status "ok" when the snapshot file exists, else "unavailable"."""
        raise NotImplementedError

    def features(self, code: str, layer_id: str, geometry) -> list[tuple[dict, object]]:
        """(raw properties, shapely geometry) of the layer's features that intersect `geometry` (a shapely
        geometry in WGS84). Empty for a layer without a snapshot file."""
        raise NotImplementedError

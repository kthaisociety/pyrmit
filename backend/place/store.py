"""The place snapshots (data/geo/<code>/, written by place.fetch): which kommun a point lies in and which
features of a layer cover a geometry."""

import json
import threading
from pathlib import Path

from shapely import STRtree
from shapely.geometry import Point, shape

GEO_DIR = Path(__file__).resolve().parent.parent / "data" / "geo"


class _Layer:
    """One snapshot file: its features and a spatial index over their geometries."""

    def __init__(self, path: Path):
        data = json.loads(path.read_text(encoding="utf-8"))
        self.properties = [feature.get("properties") or {} for feature in data["features"]]
        self.geometries = [shape(feature["geometry"]) for feature in data["features"]]
        self.index = STRtree(self.geometries)

    def intersecting(self, geometry) -> list[tuple[dict, object]]:
        hits = self.index.query(geometry, predicate="intersects")
        return [(self.properties[i], self.geometries[i]) for i in sorted(hits)]


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
        self.root = Path(root)
        self._lock = threading.Lock()
        self._manifests: dict[str, dict] | None = None
        self._boundaries: dict[str, object] = {}
        self._layers: dict[tuple[str, str], _Layer] = {}

    def _kommun_manifests(self) -> dict[str, dict]:
        with self._lock:
            if self._manifests is None:
                self._manifests = {}
                for manifest_path in sorted(self.root.glob("*/manifest.json")):
                    code = manifest_path.parent.name
                    self._manifests[code] = json.loads(manifest_path.read_text(encoding="utf-8"))
                    boundary = json.loads((manifest_path.parent / "kommun.geojson").read_text(encoding="utf-8"))
                    self._boundaries[code] = shape(boundary["geometry"])
            return self._manifests

    def kommuner(self) -> list[dict]:
        """The pilot kommuner that have a snapshot: [{"code", "name", "bbox": [west, south, east, north],
        "fetched"}], in code order."""
        return [{"code": code, "name": manifest["kommun"]["name"], "bbox": list(self._boundaries[code].bounds),
                 "fetched": manifest["kommun"].get("fetched")}
                for code, manifest in self._kommun_manifests().items()]

    def kommun_at(self, lon: float, lat: float) -> str | None:
        """Code of the pilot kommun whose boundary contains the point, or None outside every snapshot."""
        point = Point(lon, lat)
        self._kommun_manifests()
        return next((code for code, boundary in self._boundaries.items() if boundary.covers(point)), None)

    def layers(self, code: str) -> list[dict]:
        """The kommun's layers from its manifest: [{"id", "title", "provider", "licence", "fetched", "complete",
        "status"}], status "ok" when the snapshot file exists, else "unavailable"."""
        entries = self._kommun_manifests()[code]["layers"]
        return [{"id": layer_id, "title": entry.get("title"), "provider": entry.get("provider"),
                 "licence": entry.get("licence"), "fetched": entry.get("fetched"),
                 "complete": bool(entry.get("complete")),
                 "status": "ok" if self._path(code, layer_id).exists() else "unavailable"}
                for layer_id, entry in entries.items()]

    def _path(self, code: str, layer_id: str) -> Path:
        return self.root / code / f"{layer_id}.geojson"

    def _layer(self, code: str, layer_id: str) -> _Layer | None:
        key = (code, layer_id)
        with self._lock:
            if key not in self._layers:
                path = self._path(code, layer_id)
                if not path.exists():
                    return None
                self._layers[key] = _Layer(path)
            return self._layers[key]

    def features(self, code: str, layer_id: str, geometry) -> list[tuple[dict, object]]:
        """(raw properties, shapely geometry) of the layer's features that intersect `geometry` (a shapely
        geometry in WGS84). Empty for a layer without a snapshot file."""
        layer = self._layer(code, layer_id)
        return layer.intersecting(geometry) if layer else []

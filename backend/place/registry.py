"""
The registry of kommun plan sources: which open map layer holds each kommun's plans in force, and which of its
attributes carry the aktbeteckning, the document links, the plan name, the date and the plan type. It is built from
the survey of all 290 kommuner (docs/research/kommun-planlager.csv: the status A and B rows served by ArcGIS or WFS,
the pilot kommuner of place.sources left out since they have their own layers) and kept as place/plan_sources.json.
An operator edits that file for what the survey could not tell: the base pattern of links that are bare file names,
and the licence of a layer that states one.

    cd backend && python -m place.registry                 # rebuild plan_sources.json from the survey
    python -m place.registry --survey ../docs/research/kommun-planlager.csv --out place/plan_sources.json
"""

from dataclasses import dataclass
from pathlib import Path

REGISTRY_PATH = Path(__file__).resolve().parent / "plan_sources.json"
SURVEY_PATH = Path(__file__).resolve().parents[2] / "docs" / "research" / "kommun-planlager.csv"
UNKNOWN_LICENCE = "unknown"


@dataclass(frozen=True)
class PlanSource:
    """One kommun's plan layer and how to read a plan out of it."""

    code: str                         # kommun code, "0182"
    name: str                         # kommun name, "Nacka"
    status: str                       # survey status: "A" (the layer links the documents) or "B" (it does not)
    service: str                      # "arcgis" (a MapServer or FeatureServer layer) or "wfs"
    url: str                          # arcgis: the layer's url (.../MapServer/0); wfs: the service endpoint, a
                                      # query string with the service's own parameters (version, typename, ...) allowed
    layer: str                        # arcgis: the layer's title; wfs: the feature type name
    akt_fields: tuple[str, ...]       # attributes holding the aktbeteckning, first non-empty wins (case-insensitive)
    url_fields: tuple[str, ...]       # attributes holding document or plan page links
    name_fields: tuple[str, ...]      # attributes holding the plan name
    date_fields: tuple[str, ...]      # attributes holding the date, laga kraft first
    type_fields: tuple[str, ...]      # attributes holding the plan type (detaljplan, stadsplan, byggnadsplan, ...)
    base_url: str | None = None       # pattern for links that are bare file names: "{file}" marks the name, a
                                      # pattern without it is a prefix the name is joined to
    licence: str = UNKNOWN_LICENCE    # the licence the layer states, else "unknown"
    survey_count: int | None = None   # polygons the survey counted in the layer
    shared: bool = False              # the server serves several kommuner, so the survey's count is not this kommun's
    note: str | None = None           # the survey's note on the layer


def build_registry(survey: Path = SURVEY_PATH, previous: Path | None = REGISTRY_PATH) -> list[PlanSource]:
    """The plan sources of the survey's status A and B rows whose endpoint is ArcGIS or WFS, in kommun code order,
    the pilot kommuner (place.sources.PILOTS) left out. Each carries the survey's endpoint, layer (a WFS type name
    without the " (title)" the survey appends), aktbeteckning, link and date attributes (laga kraft attributes
    first), the survey's count and note, and the usual attribute names for the plan name and type. `shared` is
    True when the survey lists the endpoint's host for more than one kommun. The licence is "unknown" and base_url
    None unless `previous`, an earlier registry file, holds a value for the kommun: an operator's edits survive a
    rebuild. Raises FileNotFoundError when `survey` is missing."""
    raise NotImplementedError


def save_registry(sources: list[PlanSource], path: Path = REGISTRY_PATH) -> None:
    """Write the sources to `path` as a JSON list, one object per source, in the order given."""
    raise NotImplementedError


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, PlanSource]:
    """The registry file as {kommun code: PlanSource}, in file order. Raises FileNotFoundError when `path` is
    missing."""
    raise NotImplementedError


def main() -> None:
    """CLI: --survey <csv> (default the survey in docs/research) and --out <json> (default plan_sources.json)."""
    raise NotImplementedError


if __name__ == "__main__":
    main()

"""
The registry of kommun plan sources: which open map layer holds each kommun's plans in force, and which of its
attributes carry the aktbeteckning, the document links, the plan name, the date and the plan type. It is built from
the survey of all 290 kommuner (docs/research/kommun-planlager.csv: the status A and B rows served by ArcGIS or WFS,
the pilot kommuner of place.sources left out since they have their own layers) and kept as place/plan_sources.json
(ADR-0006). An operator edits that file for what the survey could not tell: the base pattern of links that are bare
file names, and the licence of a layer that states one.

    cd backend && python -m place.registry                 # rebuild plan_sources.json from the survey
    python -m place.registry --survey ../docs/research/kommun-planlager.csv --out place/plan_sources.json
"""

import argparse
import csv
import json
from collections import Counter
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import get_origin
from urllib.parse import urlsplit

from place.sources import PILOTS

REGISTRY_PATH = Path(__file__).resolve().parent / "plan_sources.json"
SURVEY_PATH = Path(__file__).resolve().parents[2] / "docs" / "research" / "kommun-planlager.csv"
UNKNOWN_LICENCE = "unknown"

OPEN_STATUSES = ("A", "B")
SERVICES = ("arcgis", "wfs")
SURVEY_LIST_SEPARATOR = "|"

# The attribute names the kommuner use, matched case-insensitively, after the survey's own for the same thing
USUAL_AKT_FIELDS = ("aktbeteckning", "aktbet", "aktbet_lok", "lmakt", "akt", "planbeteckning", "planbet", "plannr",
                    "plan_nr", "planid", "plan_id", "externid", "dp_aktnummer", "dp_akt", "dp_plannummer",
                    "dp_planid", "idnr")
USUAL_NAME_FIELDS = ("plannamn", "plnamn", "planname", "plan_namn", "dp_plannamn", "namn", "name", "beskr",
                     "beskrivning", "rubrik", "titel", "title")
USUAL_DATE_FIELDS = ("lagakraftdatum", "laga_kraft_datum", "laga_kraft", "lagakraft", "lagakraft_datum",
                     "legallybindingdate", "ldat", "dp_laga_kraft_datum", "laga_kraft_d", "antagandedatum",
                     "adoptiondate", "ant_datum", "adat", "beslutsdatum", "approvaldate", "constitutiondate",
                     "bdat", "datum")
USUAL_TYPE_FIELDS = ("plantyp", "plantyp_tx", "plantype", "dp_plantyp", "planform", "planf", "typ", "type",
                     "kategori")
LAGA_KRAFT_MARKS = ("laga", "legally", "ldat", "lk_")


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


def _survey_list(value: str) -> tuple[str, ...]:
    return tuple(part for part in value.split(SURVEY_LIST_SEPARATOR) if part) if value else ()


def _or_usual(surveyed: tuple[str, ...], usual: tuple[str, ...]) -> tuple[str, ...]:
    """The survey's attribute names, or the usual ones where the survey found none."""
    return surveyed or usual


def _laga_kraft_first(names: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted(names, key=lambda name: not any(mark in name.lower() for mark in LAGA_KRAFT_MARKS)))


def _wfs_type_name(layer: str) -> str:
    """The survey writes a WFS layer as 'type (title)': the type alone."""
    return layer.split(" (")[0].strip()


def _count(value: str) -> int | None:
    return int(value) if value.strip().isdigit() else None


def _source(row: dict, shared_hosts: set[str], previous: dict[str, PlanSource]) -> PlanSource:
    earlier = previous.get(row["kod"])
    layer = _wfs_type_name(row["layer_name"]) if row["endpoint_kind"] == "wfs" else row["layer_name"]
    return PlanSource(
        code=row["kod"], name=row["kommun"], status=row["status"], service=row["endpoint_kind"],
        url=row["endpoint_url"], layer=layer,
        akt_fields=_or_usual(_survey_list(row["akt_fields"]), USUAL_AKT_FIELDS),
        url_fields=_survey_list(row["url_fields"]),
        name_fields=USUAL_NAME_FIELDS,
        date_fields=_or_usual(_laga_kraft_first(_survey_list(row["date_fields"])), USUAL_DATE_FIELDS),
        type_fields=USUAL_TYPE_FIELDS,
        base_url=earlier.base_url if earlier else None,
        licence=earlier.licence if earlier and earlier.licence != UNKNOWN_LICENCE else UNKNOWN_LICENCE,
        survey_count=_count(row["count"]), shared=urlsplit(row["endpoint_url"]).netloc in shared_hosts,
        note=row["notes"].strip() or None)


def build_registry(survey: Path = SURVEY_PATH, previous: Path | None = REGISTRY_PATH) -> list[PlanSource]:
    """The plan sources of the survey's status A and B rows whose endpoint is ArcGIS or WFS, in kommun code order,
    the pilot kommuner (place.sources.PILOTS) left out. Each carries the survey's endpoint, layer (a WFS type name
    without the " (title)" the survey appends), aktbeteckning, link and date attributes (laga kraft attributes
    first; the usual aktbeteckning and date names where the survey found none), the survey's count and note, and
    the usual attribute names for the plan name and type. `shared` is
    True when the survey lists the endpoint's host for more than one kommun. The licence is "unknown" and base_url
    None unless `previous`, an earlier registry file, holds a value for the kommun: an operator's edits survive a
    rebuild. Raises FileNotFoundError when `survey` is missing."""
    with Path(survey).open(encoding="utf-8", newline="") as lines:
        rows = [row for row in csv.DictReader(lines)
                if row["status"] in OPEN_STATUSES and row["endpoint_kind"] in SERVICES]
    hosts = Counter(urlsplit(row["endpoint_url"]).netloc for row in rows)
    shared_hosts = {host for host, count in hosts.items() if count > 1}
    earlier = load_registry(previous) if previous and Path(previous).exists() else {}
    return sorted((_source(row, shared_hosts, earlier) for row in rows if row["kod"] not in PILOTS),
                  key=lambda source: source.code)


def save_registry(sources: list[PlanSource], path: Path = REGISTRY_PATH) -> None:
    """Write the sources to `path` as a JSON list, one object per source, in the order given."""
    Path(path).write_text(json.dumps([asdict(source) for source in sources], ensure_ascii=False, indent=1) + "\n",
                          encoding="utf-8")


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, PlanSource]:
    """The registry file as {kommun code: PlanSource}, in file order. Raises FileNotFoundError when `path` is
    missing."""
    tuple_fields = {field.name for field in fields(PlanSource) if get_origin(field.type) is tuple}
    sources = []
    for entry in json.loads(Path(path).read_text(encoding="utf-8")):
        sources.append(PlanSource(**{key: tuple(value) if key in tuple_fields else value for key, value in entry.items()}))
    return {source.code: source for source in sources}


def main() -> None:
    """CLI: --survey <csv> (default the survey in docs/research) and --out <json> (default plan_sources.json)."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--survey", type=Path, default=SURVEY_PATH)
    parser.add_argument("--out", type=Path, default=REGISTRY_PATH)
    args = parser.parse_args()
    sources = build_registry(args.survey, previous=args.out)
    save_registry(sources, args.out)
    print(f"{len(sources)} plan sources -> {args.out}")


if __name__ == "__main__":
    main()

"""
The place-lookup benchmark: how often the place profile gets each layer right, against a facit made by hand. No
model calls (ADR-0003); the lookup's own live sources (property, ancient remains) are called as in the app.

    cd backend && python -m place.bench candidates --kommun 0380 --n 30   # proposals for the facit, to check by hand
    python -m place.bench run [--set dev|test|all] [--label name]       # -> data/agentic/place-bench-<time>[-label].json
    python -m place.bench compare <run a.json> <run b.json>             # per-layer change between two runs

Facit (place/cases.jsonl, one JSON object per line):
    {"id", "kommun", "set": "dev" | "test" (held out, e.g. Norrtälje), "pin": {"lat", "lon"}, "tags": [hard cases],
     "expected": {"property", "detaljplan", "plans": [aktbeteckning], "zones": [code], "protected_areas": [NVRID],
                  "natura2000": [site code], "national_interests": [name], "ancient_remains": [RAÄ number],
                  "permits": [permit key]},
     "checked": {"by", "where": [sources checked], "second_check": {"by", "date"} | null},
     "locked": "YYYY-MM-DD" | null, "corrections": [{"date", "field", "from", "to", "why"}]}
Only locked entries are run: the facit is written before the lookup sees those properties.
"""

from collections.abc import Callable
from pathlib import Path

from place.store import PlaceStore

CASES_PATH = Path(__file__).resolve().parent / "cases.jsonl"
RESULTS_DIR = Path(__file__).resolve().parent.parent / "data" / "agentic"
SET_LAYERS = ("plans", "zones", "protected_areas", "natura2000", "national_interests", "ancient_remains", "permits")
EXACT_LAYERS = ("property", "detaljplan")
HARD_CASES = ("outside_detaljplan", "several_plans", "plan_boundary", "plan_in_progress", "protected_area",
              "natura2000", "ancient_remains", "near_water", "street_or_park")


def load_cases(path: Path = CASES_PATH) -> list[dict]:
    """The facit entries of a cases file, in file order. Raises ValueError naming the line of an entry that lacks
    "id", "pin" or "expected"."""
    raise NotImplementedError


def observed(profile: dict) -> dict:
    """What a place profile says, in the facit's terms: {"property": designation | None, "detaljplan", "plans":
    aktbeteckningar, "zones": codes, "protected_areas": NVRIDs, "natura2000": site codes, "national_interests": names,
    "ancient_remains": RAÄ numbers, "permits": permit keys}."""
    raise NotImplementedError


def hard_case_tags(profile: dict) -> list[str]:
    """The HARD_CASES a place profile shows: outside_detaljplan, several_plans (more than one plan in force),
    plan_boundary (a plan or zone covering only part of the property), plan_in_progress, protected_area,
    natura2000, ancient_remains, near_water (a water zone on or next to the property), street_or_park (no property,
    or a property that is mostly street or park)."""
    raise NotImplementedError


def score_case(case: dict, profile: dict) -> dict:
    """One facit entry against the lookup's profile: {"id", "set", "layers": {layer: {"expected", "observed",
    "missing", "extra", "ok"}}, "ok": every layer right, "corrections": the entry's corrections}. Set layers compare
    as sets (missing = expected but not found, extra = found but not expected); property and detaljplan exactly."""
    raise NotImplementedError


def run_bench(cases: list[dict], *, build: Callable[[float, float], dict] | None = None, which: str = "dev",
              label: str | None = None, out_dir: Path = RESULTS_DIR) -> dict:
    """Run the lookup on the locked entries of `cases` in set `which` ("dev", "test" or "all") and save the result to
    `out_dir`/place-bench-<YYYYmmdd-HHMMSS>[-<label>].json. `build` (lat, lon -> profile) defaults to
    place.profile.build_profile. Returns {"date", "label", "set", "cases": [score_case ...], "skipped": [ids of
    unlocked entries], "layers": {layer: {"precision", "recall", "tp", "fp", "fn"} for set layers, {"accuracy",
    "right", "total"} for exact layers}, "path"}."""
    raise NotImplementedError


def compare_runs(before: dict, after: dict) -> dict:
    """Per-layer change between two saved runs: {layer: {"before", "after", "change"}} on recall for set layers and
    accuracy for exact layers, and "fixed" / "broken": the case ids that went from wrong to right and back."""
    raise NotImplementedError


def candidates(code: str, n: int = 30, *, seed: int = 31, build: Callable[[float, float], dict] | None = None,
               store: PlaceStore | None = None) -> list[dict]:
    """Up to `n` proposed facit entries for kommun `code`, unlocked and with an empty "expected": random points of
    the kommun's boundary in `store` (seeded) whose profiles together cover every HARD_CASES tag, tagged with
    hard_case_tags. `build` and `store` default to build_profile and the snapshot store. Proposals only: a person
    checks each place and writes its facit."""
    raise NotImplementedError


def main() -> None:
    """CLI: candidates / run / compare (see the module docstring)."""
    raise NotImplementedError


if __name__ == "__main__":
    main()

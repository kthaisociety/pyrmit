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

import argparse
import json
import random
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from shapely.geometry import Point, box

from place.sources import PILOTS, SWEDEN_TZ
from place.store import PlaceStore

CASES_PATH = Path(__file__).resolve().parent / "cases.jsonl"
RESULTS_DIR = Path(__file__).resolve().parent.parent / "data" / "agentic"
SET_LAYERS = ("plans", "zones", "protected_areas", "natura2000", "national_interests", "ancient_remains", "permits")
EXACT_LAYERS = ("property", "detaljplan")
HELD_OUT = {"0188"}  # Norrtälje: the test kommun, never tuned on
REQUIRED_FIELDS = ("id", "pin", "expected")
SAMPLES_PER_CANDIDATE = 6
FULL_SHARE = 0.95      # a zone covering less of the property means a boundary runs through it
OPEN_GROUND = ("GATA", "PARK", "TORG", "NATUR")
HARD_CASES = ("outside_detaljplan", "several_plans", "plan_boundary", "plan_in_progress", "protected_area",
              "natura2000", "ancient_remains", "near_water", "street_or_park")


def load_cases(path: Path = CASES_PATH) -> list[dict]:
    """The facit entries of a cases file, in file order. Raises ValueError naming the line of an entry that lacks
    "id", "pin" or "expected"."""
    cases = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        entry = json.loads(line)
        missing = [field for field in REQUIRED_FIELDS if field not in entry]
        if missing:
            raise ValueError(f"{path}, line {number}: the entry lacks {', '.join(missing)}")
        cases.append(entry)
    return cases


def _refs(rows: list[dict], field: str = "ref") -> list[str]:
    return list(dict.fromkeys(row[field] for row in rows if row.get(field)))


def observed(profile: dict) -> dict:
    """What a place profile says, in the facit's terms: {"property": designation | None, "detaljplan", "plans":
    aktbeteckningar, "zones": codes, "protected_areas": NVRIDs, "natura2000": site codes, "national_interests": names,
    "ancient_remains": RAÄ numbers, "permits": permit keys}."""
    return {"property": (profile.get("property") or {}).get("designation"), "detaljplan": profile["detaljplan"],
            "plans": _refs(profile["plans"]), "zones": _refs(profile["zones"]),
            "protected_areas": _refs(profile.get("protected_areas", [])),
            "natura2000": _refs(profile.get("natura2000", [])),
            "national_interests": _refs(profile.get("national_interests", []), "name"),
            "ancient_remains": _refs(profile.get("ancient_remains", [])),
            "permits": [permit["key"] for permit in profile.get("permits", [])]}


def _mostly_open_ground(profile: dict) -> bool:
    zones = profile.get("zones") or []
    if profile.get("property_status") == "none":
        return True
    largest = max(zones, key=lambda zone: zone.get("share") or 0, default=None)
    return bool(largest and (largest.get("ref") or "").upper().startswith(OPEN_GROUND) and (largest["share"] or 0) >= 0.5)


def hard_case_tags(profile: dict) -> list[str]:
    """The HARD_CASES a place profile shows: outside_detaljplan, several_plans (more than one plan in force),
    plan_boundary (a plan or zone covering only part of the property), plan_in_progress, protected_area,
    natura2000, ancient_remains, near_water (a water zone on or next to the property), street_or_park (no property,
    or a property that is mostly street or park)."""
    zones = profile.get("zones") or []
    shows = {
        "outside_detaljplan": profile.get("detaljplan") == "outside",
        "several_plans": sum(plan["kind"] == "plan" for plan in profile.get("plans", [])) > 1,
        "plan_boundary": bool(profile.get("property")) and any((zone.get("share") or 1) < FULL_SHARE for zone in zones),
        "plan_in_progress": bool(profile.get("pending_plans")),
        "protected_area": bool(profile.get("protected_areas")),
        "natura2000": bool(profile.get("natura2000")),
        "ancient_remains": bool(profile.get("ancient_remains")),
        "near_water": any(zone.get("layer") == "zones_vatten" for zone in zones),
        "street_or_park": profile.get("covered", False) and _mostly_open_ground(profile),
    }
    return [tag for tag in HARD_CASES if shows[tag]]


def score_case(case: dict, profile: dict) -> dict:
    """One facit entry against the lookup's profile: {"id", "set", "layers": {layer: {"expected", "observed",
    "missing", "extra", "ok"}}, "ok": every layer right, "corrections": the entry's corrections}. Set layers compare
    as sets (missing = expected but not found, extra = found but not expected); property and detaljplan exactly."""
    seen, expected = observed(profile), case["expected"]
    layers = {}
    for layer in EXACT_LAYERS:
        layers[layer] = {"expected": expected.get(layer), "observed": seen[layer], "missing": [], "extra": [],
                         "ok": expected.get(layer) == seen[layer]}
    for layer in SET_LAYERS:
        want, got = set(expected.get(layer) or []), set(seen[layer])
        missing, extra = sorted(want - got), sorted(got - want)
        layers[layer] = {"expected": sorted(want), "observed": sorted(got), "missing": missing, "extra": extra,
                         "ok": not missing and not extra}
    return {"id": case["id"], "set": case.get("set", "dev"), "layers": layers,
            "ok": all(layer["ok"] for layer in layers.values()), "corrections": case.get("corrections", [])}


def _ratio(part: int, whole: int) -> float | None:
    return part / whole if whole else None


def _summary(scores: list[dict]) -> dict:
    summary = {}
    for layer in EXACT_LAYERS:
        right = sum(score["layers"][layer]["ok"] for score in scores)
        summary[layer] = {"accuracy": _ratio(right, len(scores)), "right": right, "total": len(scores)}
    for layer in SET_LAYERS:
        found = [score["layers"][layer] for score in scores]
        fp = sum(len(row["extra"]) for row in found)
        fn = sum(len(row["missing"]) for row in found)
        tp = sum(len(row["observed"]) for row in found) - fp
        summary[layer] = {"precision": _ratio(tp, tp + fp), "recall": _ratio(tp, tp + fn), "tp": tp, "fp": fp,
                          "fn": fn}
    return summary


def _result_path(out_dir: Path, label: str | None) -> Path:
    stamp = datetime.now(SWEDEN_TZ).strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"place-bench-{stamp}{'-' + label if label else ''}.json"
    suffix = 2
    while path.exists():  # two runs in the same second keep both files
        path = out_dir / f"place-bench-{stamp}-{suffix}{'-' + label if label else ''}.json"
        suffix += 1
    return path


def run_bench(cases: list[dict], *, build: Callable[[float, float], dict] | None = None, which: str = "dev",
              label: str | None = None, out_dir: Path = RESULTS_DIR) -> dict:
    """Run the lookup on the locked entries of `cases` in set `which` ("dev", "test" or "all") and save the result to
    `out_dir`/place-bench-<YYYYmmdd-HHMMSS>[-<label>].json. `build` (lat, lon -> profile) defaults to
    place.profile.build_profile. Returns {"date", "label", "set", "cases": [score_case ...], "skipped": [ids of
    unlocked entries], "layers": {layer: {"precision", "recall", "tp", "fp", "fn"} for set layers, {"accuracy",
    "right", "total"} for exact layers}, "path"}."""
    if build is None:
        from place.profile import build_profile as build
    chosen = [case for case in cases if which == "all" or case.get("set", "dev") == which]
    scores = [score_case(case, build(case["pin"]["lat"], case["pin"]["lon"])) for case in chosen if case.get("locked")]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = _result_path(out_dir, label)
    result = {"date": datetime.now(SWEDEN_TZ).isoformat(timespec="seconds"), "label": label, "set": which,
              "cases": scores, "skipped": [case["id"] for case in chosen if not case.get("locked")],
              "layers": _summary(scores), "path": str(path)}
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def _headline(layer: str, stats: dict) -> float | None:
    return stats["accuracy"] if layer in EXACT_LAYERS else stats["recall"]


def compare_runs(before: dict, after: dict) -> dict:
    """Per-layer change between two saved runs: {layer: {"before", "after", "change"}} on recall for set layers and
    accuracy for exact layers, and "fixed" / "broken": the case ids that went from wrong to right and back."""
    diff = {}
    for layer in (*EXACT_LAYERS, *SET_LAYERS):
        old, new = _headline(layer, before["layers"][layer]), _headline(layer, after["layers"][layer])
        diff[layer] = {"before": old, "after": new,
                       "change": None if old is None or new is None else new - old}
    was = {case["id"]: case["ok"] for case in before["cases"]}
    now = {case["id"]: case["ok"] for case in after["cases"]}
    both = [case_id for case_id in now if case_id in was]
    diff["fixed"] = [case_id for case_id in both if now[case_id] and not was[case_id]]
    diff["broken"] = [case_id for case_id in both if was[case_id] and not now[case_id]]
    return diff


def sample_points(store: PlaceStore, code: str, count: int, rng: random.Random) -> list[tuple[float, float]]:
    """(lat, lon) points of the kommun: half inside its plans (where most cases are), half anywhere in it."""
    west, south, east, north = next(k["bbox"] for k in store.kommuner() if k["code"] == code)
    plans = [geometry for _, geometry in store.features(code, "plans", box(west, south, east, north))]
    points = []
    while len(points) < count:
        if plans and len(points) % 2 == 0:
            plan = rng.choice(plans)
            px, py = _point_in(plan, rng)
        else:
            px, py = rng.uniform(west, east), rng.uniform(south, north)
        if store.kommun_at(px, py) == code:
            points.append((round(py, 6), round(px, 6)))
    return points


def _point_in(polygon, rng: random.Random) -> tuple[float, float]:
    """A random (lon, lat) inside the polygon, else its representative point."""
    west, south, east, north = polygon.bounds
    for _ in range(20):
        x, y = rng.uniform(west, east), rng.uniform(south, north)
        if polygon.contains(Point(x, y)):
            return x, y
    point = polygon.representative_point()
    return point.x, point.y


def _empty_facit() -> dict:
    return {"property": None, "detaljplan": None, **{layer: [] for layer in SET_LAYERS}}


def candidates(code: str, n: int = 30, *, seed: int = 31, build: Callable[[float, float], dict] | None = None,
               store: PlaceStore | None = None) -> list[dict]:
    """Up to `n` proposed facit entries for kommun `code`, unlocked and with an empty "expected": random points of
    the kommun's boundary in `store` (seeded) whose profiles together cover every HARD_CASES tag, tagged with
    hard_case_tags. `build` and `store` default to build_profile and the snapshot store. Proposals only: a person
    checks each place and writes its facit."""
    from place.profile import build_profile, default_store

    build, store = build or build_profile, store or default_store()
    sampled = [({"lat": lat, "lon": lon}, hard_case_tags(build(lat, lon)))
               for lat, lon in sample_points(store, code, n * SAMPLES_PER_CANDIDATE, random.Random(seed))]
    chosen, covered = [], set()
    for tag in HARD_CASES:  # first one place per hard case, then the most-tagged places
        hit = next((s for s in sampled if tag in s[1] and tag not in covered and s not in chosen), None)
        if hit and len(chosen) < n:
            chosen.append(hit)
            covered.update(hit[1])
    chosen += sorted((s for s in sampled if s not in chosen), key=lambda s: -len(s[1]))[:n - len(chosen)]
    name = PILOTS.get(code, {}).get("name", code).lower()
    return [{"id": f"{name}-{number:03d}", "kommun": code, "set": "test" if code in HELD_OUT else "dev", "pin": pin,
             "tags": tags, "expected": _empty_facit(), "checked": {"by": None, "where": [], "second_check": None},
             "locked": None, "corrections": []} for number, (pin, tags) in enumerate(chosen, start=1)]


def _print_run(result: dict) -> None:
    print(f"{len(result['cases'])} entries ({result['set']}), {len(result['skipped'])} unlocked skipped -> {result['path']}")
    for layer, stats in result["layers"].items():
        if layer in EXACT_LAYERS:
            print(f"  {layer:20} accuracy {stats['accuracy']}")
        else:
            print(f"  {layer:20} precision {stats['precision']}  recall {stats['recall']}")
    for case in result["cases"]:
        for layer, row in case["layers"].items():
            if not row["ok"]:
                print(f"  {case['id']} {layer}: missing {row['missing'] or '-'}, extra {row['extra'] or '-'}"
                      + ("" if layer not in EXACT_LAYERS else f" (expected {row['expected']}, got {row['observed']})"))


def main() -> None:
    """CLI: candidates / run / compare (see the module docstring)."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    propose = commands.add_parser("candidates")
    propose.add_argument("--kommun", default="0380")
    propose.add_argument("--n", type=int, default=30)
    propose.add_argument("--out", type=Path)
    run = commands.add_parser("run")
    run.add_argument("--cases", type=Path, default=CASES_PATH)
    run.add_argument("--set", default="dev", choices=("dev", "test", "all"))
    run.add_argument("--label")
    compare = commands.add_parser("compare")
    compare.add_argument("before", type=Path)
    compare.add_argument("after", type=Path)
    args = parser.parse_args()
    if args.command == "candidates":
        out = args.out or CASES_PATH.with_name(f"cases_draft_{args.kommun}.jsonl")
        proposals = candidates(args.kommun, args.n)
        out.write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in proposals), encoding="utf-8")
        print(f"{len(proposals)} proposals -> {out}: check each place by hand, fill in 'expected', then lock it")
    elif args.command == "run":
        _print_run(run_bench(load_cases(args.cases), which=args.set, label=args.label))
    else:
        before, after = (json.loads(path.read_text(encoding="utf-8")) for path in (args.before, args.after))
        print(json.dumps(compare_runs(before, after), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

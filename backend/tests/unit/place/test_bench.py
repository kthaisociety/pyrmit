"""place.bench: the place-lookup benchmark on profiles of the fake snapshot, and the permits' stable keys. No
network, no model (PCR-0011)."""

import json

import pytest

from place.bench import (
    HARD_CASES,
    candidates,
    compare_runs,
    hard_case_tags,
    load_cases,
    observed,
    run_bench,
    score_case,
)
from place.profile import build_profile
from tests.unit.place.snapshot import (
    fake_property,
    registry,
    remains_at,
    write_national_snapshot,
)

PERFECT = {"property": "Uppsala Kungsängen 7:8", "detaljplan": "inside",
           "plans": ["0380-P2012/9", "0380-O2005/1", "0380-P2002/5", "0380-P1990/3"], "zones": ["BCK", "P"],
           "protected_areas": ["2001234"], "natura2000": ["SE0210071"], "national_interests": ["Fyrisån", "Uppsala stad"],
           "ancient_remains": ["Uppsala 123:1", "Uppsala 586:1", "L1941:4000"],
           "permits": ["bygglov", "dispens:2001234", "natura2000:SE0210071", "fornlamning:Uppsala 123:1",
                       "contact:Uppsala 586:1", "riksintresse:Fyrisån", "riksintresse:Uppsala stad"]}


def case(id="uppsala-001", expected=None, locked="2026-10-26", which="dev", corrections=()):
    return {"id": id, "kommun": "0380", "set": which, "pin": {"lat": 59.8505, "lon": 17.641}, "tags": [],
            "expected": dict(PERFECT if expected is None else expected),
            "checked": {"by": "anna", "where": ["Uppsala kommun's map", "plan documents"], "second_check": None},
            "locked": locked, "corrections": list(corrections)}


@pytest.fixture
def store(tmp_path):
    return write_national_snapshot(tmp_path)


@pytest.fixture
def build(store):
    """The fake lookup: build_profile on the fake snapshot with fake live sources."""
    def profile_of(lat, lon):
        return build_profile(lat, lon, store=store, property_at=fake_property, plan_registry=registry,
                             ancient_remains_at=remains_at)
    return profile_of


# --- scoring ---------------------------------------------------------------------------------------------------

def test_the_permits_have_stable_keys(build):
    """Every likely permit carries a key that stays the same between runs."""
    keys = [permit["key"] for permit in build(59.8505, 17.641)["permits"]]
    assert keys == ["bygglov", "dispens:2001234", "natura2000:SE0210071", "fornlamning:Uppsala 123:1",
                    "contact:Uppsala 586:1", "riksintresse:Fyrisån", "riksintresse:Uppsala stad"]


def test_a_profile_is_read_in_the_facit_terms(build):
    """The lookup's profile reads as the facit's layers."""
    seen = observed(build(59.8505, 17.641))
    assert seen["property"] == "Uppsala Kungsängen 7:8"
    assert sorted(seen["plans"]) == sorted(PERFECT["plans"])
    assert sorted(seen["ancient_remains"]) == sorted(PERFECT["ancient_remains"])


def test_a_perfect_lookup_scores_every_layer_right(build):
    """A profile matching the facit is right on every layer."""
    result = score_case(case(), build(59.8505, 17.641))
    assert result["ok"] is True
    assert all(layer["ok"] for layer in result["layers"].values())


def test_a_missing_plan_is_listed_and_lowers_recall(build, tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("runs")
    """A plan in the facit that the lookup misses is listed as missing and counts against recall."""
    expected = PERFECT | {"plans": PERFECT["plans"] + ["0380-P1999/9"]}
    result = score_case(case(expected=expected), build(59.8505, 17.641))
    assert result["layers"]["plans"]["missing"] == ["0380-P1999/9"]
    run = run_bench([case(expected=expected)], build=build, out_dir=tmp_path)
    assert run["layers"]["plans"]["recall"] == pytest.approx(4 / 5)


def test_an_extra_protected_area_is_listed_and_lowers_precision(build, tmp_path):
    """A protected area the lookup finds but the facit does not have is listed as extra and counts against
    precision."""
    expected = PERFECT | {"protected_areas": []}
    result = score_case(case(expected=expected), build(59.8505, 17.641))
    assert result["layers"]["protected_areas"]["extra"] == ["2001234"]
    run = run_bench([case(expected=expected)], build=build, out_dir=tmp_path)
    assert run["layers"]["protected_areas"]["precision"] == 0.0


def test_property_and_detaljplan_are_exact_matches(build):
    """The property and the detaljplan status are right only when equal to the facit."""
    result = score_case(case(expected=PERFECT | {"detaljplan": "outside"}), build(59.8505, 17.641))
    assert result["layers"]["detaljplan"]["ok"] is False
    assert result["layers"]["property"]["ok"] is True


# --- running ---------------------------------------------------------------------------------------------------

def test_unlocked_entries_are_not_run(build, tmp_path):
    """An entry without a lock date is skipped and reported, never scored."""
    run = run_bench([case(), case(id="draft", locked=None)], build=build, out_dir=tmp_path)
    assert [c["id"] for c in run["cases"]] == ["uppsala-001"]
    assert run["skipped"] == ["draft"]


def test_held_out_entries_run_only_when_asked(build, tmp_path):
    """Test-set entries (e.g. Norrtälje) are left out of a dev run and run on their own."""
    cases = [case(), case(id="norrtalje-001", which="test")]
    assert [c["id"] for c in run_bench(cases, build=build, out_dir=tmp_path)["cases"]] == ["uppsala-001"]
    assert [c["id"] for c in run_bench(cases, build=build, which="test", out_dir=tmp_path)["cases"]] == ["norrtalje-001"]


def test_a_run_is_saved_with_its_date_and_label(build, tmp_path):
    """The result file sits in the results folder, named by date and label, and holds the per-layer report."""
    run = run_bench([case()], build=build, label="baseline", out_dir=tmp_path)
    [path] = list(tmp_path.glob("place-bench-*-baseline.json"))
    saved = json.loads(path.read_text())
    assert saved["label"] == "baseline"
    assert saved["layers"]["plans"]["recall"] == 1.0
    assert run["path"] == str(path)


def test_corrections_to_the_facit_show_in_the_result(build, tmp_path):
    """A corrected entry carries its corrections into the result."""
    correction = {"date": "2026-10-30", "field": "plans", "from": [], "to": ["0380-P2002/5"], "why": "missed"}
    run = run_bench([case(corrections=[correction])], build=build, out_dir=tmp_path)
    assert run["cases"][0]["corrections"] == [correction]


def test_two_runs_compare_per_layer(build, tmp_path):
    """Comparing two runs gives each layer's change and the cases that were fixed."""
    worse = run_bench([case(expected=PERFECT | {"plans": PERFECT["plans"] + ["0380-P1999/9"]})], build=build,
                      out_dir=tmp_path)
    better = run_bench([case()], build=build, out_dir=tmp_path)
    diff = compare_runs(worse, better)
    assert diff["plans"]["change"] == pytest.approx(1 - 4 / 5)
    assert diff["fixed"] == ["uppsala-001"]


# --- the facit file and the candidates -------------------------------------------------------------------------

def test_a_facit_file_is_read_line_by_line(tmp_path):
    """The cases file holds one entry per line."""
    path = tmp_path / "cases.jsonl"
    path.write_text("\n".join(json.dumps(c) for c in (case(), case(id="uppsala-002"))) + "\n")
    assert [c["id"] for c in load_cases(path)] == ["uppsala-001", "uppsala-002"]


def test_a_broken_facit_entry_names_its_line(tmp_path):
    """An entry without its expected layers is an error naming the line."""
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps(case()) + "\n" + json.dumps({"id": "x", "pin": {"lat": 1, "lon": 2}}) + "\n")
    with pytest.raises(ValueError, match="line 2"):
        load_cases(path)


def test_hard_cases_are_recognised_on_a_profile(build):
    """The fake property shows several plans, a plan boundary, a plan in progress, a protected area, Natura 2000 and
    ancient remains."""
    tags = hard_case_tags(build(59.8505, 17.641))
    for tag in ("several_plans", "plan_boundary", "plan_in_progress", "protected_area", "natura2000",
                "ancient_remains"):
        assert tag in tags
    assert set(tags) <= set(HARD_CASES)


def test_a_place_outside_any_plan_is_a_hard_case(build):
    """A property outside a detaljplan is tagged so."""
    assert "outside_detaljplan" in hard_case_tags(build(59.88, 17.68))


def test_candidates_are_unlocked_proposals_covering_the_hard_cases(build, store):
    """Candidates have no facit and no lock, and each carries the hard cases its place shows."""
    proposals = candidates("0380", n=4, build=build, store=store)
    assert 0 < len(proposals) <= 4
    assert all(p["locked"] is None and not any(p["expected"].values()) for p in proposals)
    assert all(set(p["tags"]) <= set(HARD_CASES) for p in proposals)

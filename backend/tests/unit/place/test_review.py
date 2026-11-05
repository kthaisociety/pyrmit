"""place.review: the coverage of every kommun and the plan polygons of a map view with their match level, on the fake
Uppsala and Nacka snapshots and the fake services (PCR-0011)."""

import pytest

from place import review
from place.plan_layers import fetch_plan_layer, fetch_registry
from place.plan_links import write_links
from place.review import NOT_FETCHED_YET, coverage, plans_in_view
from place.sources import today
from place.store import PlaceStore
from tests.unit.place.plan_layer import (
    NACKA_FEATURES,
    fake_services,
    nacka_store,
    source,
)

VARMDO = source(code="0120", name="Värmdö", url="https://karta.varmdo.se/arcgis/rest/services/P/MapServer/1")
NACKA_BOX = (18.0, 59.25, 18.4, 59.40)
KVARNHOLMEN_BOX = (18.14, 59.29, 18.18, 59.33)      # NEWER and OLDER, not ELSEWHERE
UPPSALA_AND_NACKA_BOX = (17.5, 59.25, 18.4, 60.0)
SWEDEN_BOX = (10.5, 55.0, 24.5, 69.5)


def link(ref, doc_id, level="akt"):
    return {"key": ref, "ref": ref, "doc_id": doc_id, "level": level, "review": level == "name", "date": today()}


def properties(collection):
    return [feature["properties"] for feature in collection["features"]]


def by_code(collection):
    return {feature["properties"]["code"]: feature for feature in collection["features"]}


def failed_varmdo(tmp_path):
    """Värmdö's feature in the coverage, after a run where its layer failed and Nacka's did not."""
    fetch_registry([VARMDO, source()], client=fake_services(fail_host="varmdo"), out_dir=tmp_path)
    return by_code(coverage(PlaceStore(tmp_path), [source(), VARMDO]))["0120"]


# --- the coverage of every kommun -------------------------------------------------------------------------------

def test_coverage_lists_every_registry_kommun_in_code_order(tmp_path):
    """Every kommun of the registry gets one feature, fetched or not, in kommun code order."""
    store = nacka_store(tmp_path)
    assert [row["code"] for row in properties(coverage(store, [source(), VARMDO]))] == ["0120", "0182", "0380"]


def test_coverage_marks_a_kommun_with_a_snapshot_covered_with_its_polygons(tmp_path):
    """A kommun whose plan layer was snapshotted is covered, with its polygon count and snapshot date."""
    nacka = by_code(coverage(nacka_store(tmp_path), [source()]))["0182"]
    assert nacka["properties"] == {"code": "0182", "name": "Nacka", "covered": True, "polygons": 3, "matched": 0,
                                   "fetched": today(), "reason": None}


def test_coverage_outlines_a_covered_kommun(tmp_path):
    """A covered kommun's feature is its outline, to colour."""
    assert by_code(coverage(nacka_store(tmp_path), [source()]))["0182"]["geometry"]["type"] in ("Polygon", "MultiPolygon")


def test_coverage_marks_a_failed_kommun_not_covered(tmp_path):
    """A kommun whose fetch failed is not covered and has no polygons."""
    row = failed_varmdo(tmp_path)["properties"]
    assert (row["covered"], row["polygons"]) == (False, 0)


def test_coverage_gives_the_reason_a_kommun_failed(tmp_path):
    """A kommun whose fetch failed carries the coverage row's reason."""
    assert "500" in failed_varmdo(tmp_path)["properties"]["reason"]


def test_coverage_outlines_a_failed_kommun(tmp_path):
    """A kommun whose layer failed after its boundary was fetched still has its outline to colour."""
    assert failed_varmdo(tmp_path)["geometry"]["type"] in ("Polygon", "MultiPolygon")


def test_coverage_has_no_outline_for_a_kommun_never_fetched(tmp_path):
    """A registry kommun no run has reached has no outline."""
    assert by_code(coverage(nacka_store(tmp_path), [source(), VARMDO]))["0120"]["geometry"] is None


def test_coverage_says_when_a_kommun_was_never_fetched(tmp_path):
    """A registry kommun no run has reached says so."""
    varmdo = by_code(coverage(nacka_store(tmp_path), [source(), VARMDO]))["0120"]
    assert varmdo["properties"]["reason"] == NOT_FETCHED_YET


def test_coverage_counts_the_plans_with_a_matched_document(tmp_path):
    """The plans with at least one plan-document link are counted, a plan once however many its documents."""
    store = nacka_store(tmp_path)
    write_links("0182", [link("0182-P2015/3", "pdf:0182:a1"), link("0182-P2015/3", "pdf:0182:a2"),
                         link("0182-P1988/12", "page:0182:b2", "name")], tmp_path)
    assert by_code(coverage(store, [source()]))["0182"]["properties"]["matched"] == 2


def test_coverage_includes_a_pilot_kommun_beside_the_registry(tmp_path):
    """Uppsala, which has a snapshot but no plan source, is covered, its plan layers counted together."""
    row = by_code(coverage(nacka_store(tmp_path), [source()]))["0380"]["properties"]
    assert (row["covered"], row["polygons"]) == (True, 5)


def test_coverage_keeps_a_doubtful_layer_like_any_other(tmp_path):
    """A snapshot the report flags (no aktbeteckning or link on any polygon) is covered; nothing is filtered."""
    bare = [(geometry, props | {"aktbeteckning": None, "url": None}) for geometry, props in NACKA_FEATURES]
    fetch_plan_layer(source(), client=fake_services(bare), out_dir=tmp_path)
    row = by_code(coverage(PlaceStore(tmp_path), [source()]))["0182"]["properties"]
    assert (row["covered"], row["polygons"]) == (True, 5)


# --- the plans in a map view --------------------------------------------------------------------------------------

def test_plans_in_view_returns_the_polygons_meeting_the_box_with_their_match_level(tmp_path):
    """The polygons in the box come with kommun, aktbeteckning, name, date and the level their documents matched at."""
    store = nacka_store(tmp_path)
    write_links("0182", [link("0182-P2015/3", "pdf:0182:a1", "link")], tmp_path)
    assert properties(plans_in_view(store, KVARNHOLMEN_BOX)) == [
        {"code": "0182", "kommun": "Nacka", "ref": "0182-P2015/3", "name": "Kvarnholmen etapp 4", "date": "2015-06-01",
         "match": "link"},
        {"code": "0182", "kommun": "Nacka", "ref": "0182-P1988/12", "name": "Sicklaön", "date": "1988-03-09",
         "match": None},
    ]


def test_plans_in_view_leaves_out_the_polygons_outside_the_box(tmp_path):
    """A polygon that does not meet the box is not served."""
    names = [row["name"] for row in properties(plans_in_view(nacka_store(tmp_path), KVARNHOLMEN_BOX))]
    assert "Utan akt" not in names  # ELSEWHERE lies east of the box


def test_plans_in_view_spans_several_kommuner(tmp_path):
    """A box over two kommuner gets the polygons of both."""
    rows = properties(plans_in_view(nacka_store(tmp_path), UPPSALA_AND_NACKA_BOX))
    assert {row["code"] for row in rows} == {"0182", "0380"}


def test_plans_in_view_reads_a_pilot_kommuns_plans_from_its_own_layer(tmp_path):
    """Uppsala's raw attributes give the same fields as a plan-layer kommun's normalised block."""
    rows = properties(plans_in_view(nacka_store(tmp_path), UPPSALA_AND_NACKA_BOX))
    assert {row["ref"] for row in rows if row["code"] == "0380"} == {"0380-P1990/3", "0380-P2002/5", "0380-P2010/1"}


def test_plans_in_view_carries_the_polygon(tmp_path):
    """Each feature has the polygon to draw."""
    [first, *_] = plans_in_view(nacka_store(tmp_path), KVARNHOLMEN_BOX)["features"]
    assert first["geometry"]["type"] in ("Polygon", "MultiPolygon")


def test_plans_in_view_is_not_truncated_within_the_cap(tmp_path):
    """Fewer polygons than the cap are served whole."""
    assert plans_in_view(nacka_store(tmp_path), NACKA_BOX)["truncated"] is False


def test_plans_in_view_caps_the_polygons_and_says_so(tmp_path, monkeypatch):
    """More polygons than the cap are cut to it, and the collection says it was truncated."""
    monkeypatch.setattr(review, "MAX_PLANS", 2)
    collection = plans_in_view(nacka_store(tmp_path), NACKA_BOX)
    assert (len(collection["features"]), collection["truncated"]) == (2, True)


def test_plans_in_view_is_not_truncated_at_exactly_the_cap(tmp_path, monkeypatch):
    """As many polygons as the cap is everything: nothing was cut."""
    monkeypatch.setattr(review, "MAX_PLANS", 3)
    collection = plans_in_view(nacka_store(tmp_path), NACKA_BOX)
    assert (len(collection["features"]), collection["truncated"]) == (3, False)


@pytest.mark.parametrize("bad_box", [
    SWEDEN_BOX,                                 # wider than a kommun: the country is never loaded at once
    (18.4, 59.25, 18.0, 59.40),                 # west right of east
    (18.0, 59.40, 18.4, 59.25),                 # south above north
    (18.0, 95.0, 18.4, 95.5),                   # not a coordinate
    (18.0, float("nan"), 18.4, 59.40),          # not a number
], ids=["country", "west-east", "south-north", "latitude", "nan"])
def test_plans_in_view_refuses_a_box(tmp_path, bad_box):
    """A box wider than a kommun, the wrong way round or off the globe is refused."""
    with pytest.raises(ValueError):
        plans_in_view(nacka_store(tmp_path), bad_box)


def test_plans_in_view_is_empty_where_no_snapshot_is(tmp_path):
    """A box over no snapshot gets an empty collection, not an error."""
    collection = plans_in_view(nacka_store(tmp_path), (11.9, 57.6, 12.1, 57.8))
    assert (collection["features"], collection["truncated"]) == ([], False)

"""Acceptance tests for #55: see plan polygons for every registry kommun on the map. The coverage of every kommun,
the plan polygons of a map view with their match level, the coverage rows kept across runs, and the review endpoints,
on the fake Uppsala and Nacka snapshots and the fake services (PCR-0011). Folded into the module tests by
unit-test-ticket."""

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dependencies import get_current_user
from place import review
from place.plan_layers import (
    COVERAGE_REPORT,
    COVERAGE_ROWS,
    fetch_plan_layer,
    fetch_registry,
    load_coverage,
)
from place.plan_links import write_links
from place.review import NOT_FETCHED_YET, coverage, plans_in_view
from place.sources import today
from place.store import PlaceStore
from routers import place as place_router
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


# --- the coverage of every kommun -------------------------------------------------------------------------------

def test_coverage_lists_every_registry_kommun_in_code_order(tmp_path):
    """Every kommun of the registry gets one feature, fetched or not, in kommun code order."""
    store = nacka_store(tmp_path)
    codes = [row["code"] for row in properties(coverage(store, [source(), VARMDO]))]
    assert codes == ["0120", "0182", "0380"]


def test_coverage_marks_a_kommun_with_a_snapshot_covered_with_its_polygons(tmp_path):
    """A kommun whose plan layer was snapshotted is covered, with its polygon count and snapshot date."""
    nacka = by_code(coverage(nacka_store(tmp_path), [source()]))["0182"]
    assert nacka["properties"] == {"code": "0182", "name": "Nacka", "covered": True, "polygons": 3, "matched": 0,
                                   "fetched": today(), "reason": None}
    assert nacka["geometry"]["type"] in ("Polygon", "MultiPolygon")


def test_coverage_marks_a_failed_kommun_not_covered_with_the_reason(tmp_path):
    """A kommun whose fetch failed is not covered, and carries the coverage row's reason."""
    fetch_registry([VARMDO, source()], client=fake_services(fail_host="varmdo"), out_dir=tmp_path)
    varmdo = by_code(coverage(PlaceStore(tmp_path), [source(), VARMDO]))["0120"]
    assert varmdo["properties"]["covered"] is False
    assert varmdo["properties"]["polygons"] == 0
    assert "500" in varmdo["properties"]["reason"]


def test_coverage_outlines_a_failed_kommun(tmp_path):
    """A kommun whose layer failed after its boundary was fetched still has its outline to colour."""
    fetch_registry([VARMDO, source()], client=fake_services(fail_host="varmdo"), out_dir=tmp_path)
    varmdo = by_code(coverage(PlaceStore(tmp_path), [source(), VARMDO]))["0120"]
    assert varmdo["geometry"]["type"] in ("Polygon", "MultiPolygon")


def test_coverage_says_when_a_kommun_was_never_fetched(tmp_path):
    """A registry kommun no run has reached is not covered, without an outline, and says so."""
    varmdo = by_code(coverage(nacka_store(tmp_path), [source(), VARMDO]))["0120"]
    assert varmdo["geometry"] is None
    assert varmdo["properties"]["reason"] == NOT_FETCHED_YET


def test_coverage_counts_the_polygons_with_a_matched_document(tmp_path):
    """The polygons with at least one plan-document link are counted, a polygon once however many its documents."""
    store = nacka_store(tmp_path)
    write_links("0182", [link("0182-P2015/3", "pdf:0182:a1"), link("0182-P2015/3", "pdf:0182:a2"),
                         link("0182-P1988/12", "page:0182:b2", "name")], tmp_path)
    assert by_code(coverage(store, [source()]))["0182"]["properties"]["matched"] == 2


def test_coverage_includes_a_pilot_kommun_beside_the_registry(tmp_path):
    """Uppsala, which has a snapshot but no plan source, is covered like a registry kommun."""
    uppsala = by_code(coverage(nacka_store(tmp_path), [source()]))["0380"]
    assert uppsala["properties"]["covered"] is True
    assert uppsala["properties"]["polygons"] == 3


def test_coverage_keeps_a_doubtful_layer_like_any_other(tmp_path):
    """A snapshot the report flags (no aktbeteckning or link on any polygon) is covered; nothing is filtered."""
    bare = [(geometry, props | {"aktbeteckning": None, "url": None}) for geometry, props in NACKA_FEATURES]
    fetch_plan_layer(source(), client=fake_services(bare), out_dir=tmp_path)
    nacka = by_code(coverage(PlaceStore(tmp_path), [source()]))["0182"]
    assert (nacka["properties"]["covered"], nacka["properties"]["polygons"]) == (True, 3)


# --- the fetch keeps what the coverage needs ------------------------------------------------------------------

def test_a_failed_fetch_keeps_the_kommun_outline(tmp_path):
    """The boundary is on disk once fetched, even when the layer then fails, so the next run reuses it."""
    row = fetch_plan_layer(VARMDO, client=fake_services(fail_host="varmdo"), out_dir=tmp_path)
    assert row["fetched"] is False
    assert PlaceStore(tmp_path).outline("0120") is not None
    assert not (tmp_path / "0120" / "manifest.json").exists()


def test_an_outline_alone_does_not_cover_the_kommun(tmp_path):
    """A kommun with only a boundary file (its layer failed) is not a snapshot: a pin there is not covered."""
    fetch_plan_layer(VARMDO, client=fake_services(fail_host="varmdo"), out_dir=tmp_path)
    store = PlaceStore(tmp_path)
    assert store.outline("0120") is not None, "the failed fetch should have kept the outline"
    assert store.kommun_at(18.16, 59.31) is None


def test_fetch_merges_the_coverage_rows_of_earlier_runs(tmp_path):
    """A run of some kommuner replaces their rows and keeps the others', so the report still covers every kommun."""
    fetch_registry([VARMDO, source()], client=fake_services(fail_host="varmdo"), out_dir=tmp_path)
    fetch_registry([VARMDO], client=fake_services(), out_dir=tmp_path)
    rows = load_coverage(tmp_path)
    assert [(code, row["fetched"]) for code, row in sorted(rows.items())] == [("0120", True), ("0182", True)]
    report = (tmp_path / COVERAGE_REPORT).read_text(encoding="utf-8")
    assert "2 of 2 kommuner fetched" in report
    assert "| 0120 | Värmdö | yes |" in report and "| 0182 | Nacka | yes |" in report


def test_the_coverage_rows_are_what_the_fetch_returned(tmp_path):
    """The rows file holds the fetch's own rows, keyed by code, and reads back empty before any run."""
    assert load_coverage(tmp_path) == {}
    rows = fetch_registry([source()], client=fake_services(), out_dir=tmp_path)
    assert load_coverage(tmp_path) == {"0182": rows[0]}
    assert json.loads((tmp_path / COVERAGE_ROWS).read_text(encoding="utf-8"))["0182"]["name"] == "Nacka"


# --- the plans in a map view --------------------------------------------------------------------------------------

def test_plans_in_view_returns_the_polygons_meeting_the_box_with_their_match_level(tmp_path):
    """The polygons in the box come with kommun, aktbeteckning, name, date and the level their documents matched at."""
    store = nacka_store(tmp_path)
    write_links("0182", [link("0182-P2015/3", "pdf:0182:a1", "link")], tmp_path)
    rows = properties(plans_in_view(store, KVARNHOLMEN_BOX))
    assert rows == [
        {"code": "0182", "kommun": "Nacka", "ref": "0182-P2015/3", "name": "Kvarnholmen etapp 4", "date": "2015-06-01",
         "match": "link"},
        {"code": "0182", "kommun": "Nacka", "ref": "0182-P1988/12", "name": "Sicklaön", "date": "1988-03-09",
         "match": None},
    ]


def test_plans_in_view_leaves_out_the_polygons_outside_the_box(tmp_path):
    """A polygon that does not meet the box is not served."""
    refs = [row["ref"] for row in properties(plans_in_view(nacka_store(tmp_path), KVARNHOLMEN_BOX))]
    assert None not in refs  # ELSEWHERE, the plan without an aktbeteckning, lies east of the box


def test_plans_in_view_spans_several_kommuner(tmp_path):
    """A box over two kommuner gets the polygons of both, a pilot kommun's read from its own layer."""
    rows = properties(plans_in_view(nacka_store(tmp_path), UPPSALA_AND_NACKA_BOX))
    assert {row["code"] for row in rows} == {"0182", "0380"}
    assert {row["ref"] for row in rows if row["code"] == "0380"} == {"0380-P1990/3", "0380-P2002/5", "0380-P2010/1"}


def test_plans_in_view_carries_the_geometry(tmp_path):
    """Each feature has the polygon to draw."""
    [first, *_] = plans_in_view(nacka_store(tmp_path), KVARNHOLMEN_BOX)["features"]
    assert first["geometry"]["type"] in ("Polygon", "MultiPolygon")
    assert first["geometry"]["coordinates"]


def test_plans_in_view_is_not_truncated_within_the_cap(tmp_path):
    """Fewer polygons than the cap are served whole."""
    assert plans_in_view(nacka_store(tmp_path), NACKA_BOX)["truncated"] is False


def test_plans_in_view_caps_the_polygons_and_says_so(tmp_path, monkeypatch):
    """More polygons than the cap are cut to it, and the collection says it was truncated."""
    monkeypatch.setattr(review, "MAX_PLANS", 2)
    collection = plans_in_view(nacka_store(tmp_path), NACKA_BOX)
    assert (len(collection["features"]), collection["truncated"]) == (2, True)


def test_plans_in_view_refuses_a_country_sized_box(tmp_path):
    """A box wider than a kommun is refused: the polygons are never loaded for the whole country at once."""
    with pytest.raises(ValueError):
        plans_in_view(nacka_store(tmp_path), SWEDEN_BOX)


def test_plans_in_view_refuses_a_malformed_box(tmp_path):
    """A box whose west is not left of its east, or south not below its north, is refused."""
    with pytest.raises(ValueError):
        plans_in_view(nacka_store(tmp_path), (18.4, 59.25, 18.0, 59.40))


def test_plans_in_view_is_empty_where_no_snapshot_is(tmp_path):
    """A box over no snapshot gets an empty collection, not an error."""
    collection = plans_in_view(nacka_store(tmp_path), (11.9, 57.6, 12.1, 57.8))
    assert (collection["features"], collection["truncated"]) == ([], False)


# --- the endpoints ---------------------------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path):
    app = FastAPI()
    app.include_router(place_router.router, prefix="/api")
    store = nacka_store(tmp_path)
    app.dependency_overrides[place_router.get_place_store] = lambda: store
    app.dependency_overrides[place_router.get_plan_sources] = lambda: {"0182": source(), "0120": VARMDO}
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u1")
    return TestClient(app)


def test_review_coverage_endpoint_serves_every_kommun(client):
    """GET /api/place/review/coverage is the coverage collection of the registry and the snapshots."""
    response = client.get("/api/place/review/coverage")
    assert response.status_code == 200
    assert [row["code"] for row in properties(response.json())] == ["0120", "0182", "0380"]


def test_review_plans_endpoint_serves_the_polygons_in_the_box(client):
    """GET /api/place/review/plans?bbox=w,s,e,n is the plans in that view."""
    response = client.get("/api/place/review/plans", params={"bbox": ",".join(map(str, KVARNHOLMEN_BOX))})
    assert response.status_code == 200
    assert [row["ref"] for row in properties(response.json())] == ["0182-P2015/3", "0182-P1988/12"]
    assert response.json()["truncated"] is False


def test_review_plans_endpoint_rejects_a_country_sized_box(client):
    """A box wider than place.review.MAX_SPAN is a 422 with a message."""
    response = client.get("/api/place/review/plans", params={"bbox": ",".join(map(str, SWEDEN_BOX))})
    assert response.status_code == 422
    assert response.json()["detail"]


def test_review_plans_endpoint_rejects_a_box_that_is_not_four_numbers(client):
    """A bbox that does not parse is a 422."""
    assert client.get("/api/place/review/plans", params={"bbox": "18,59,x"}).status_code == 422


def test_review_endpoints_require_sign_in(tmp_path):
    """Without a token neither review endpoint is served."""
    app = FastAPI()
    app.include_router(place_router.router, prefix="/api")
    store = nacka_store(tmp_path)
    app.dependency_overrides[place_router.get_place_store] = lambda: store
    anonymous = TestClient(app)
    assert anonymous.get("/api/place/review/coverage").status_code == 401
    assert anonymous.get("/api/place/review/plans", params={"bbox": "18,59,18.4,59.4"}).status_code == 401

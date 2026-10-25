"""place.profile.build_profile on a fake snapshot: the property, its plans and zones, and what the card says
when there is no property, no coverage or no answer."""

import json

import pytest

from place.live import PlaceSourceUnavailable
from place.profile import NOT_A_DECISION, build_profile
from tests.unit.place.snapshot import (
    EMPTY_LOT,
    FETCHED,
    OUTSIDE,
    PIN,
    STREET,
    fake_property,
    no_remains,
    registry,
    write_snapshot,
)


def profile(store, at=PIN, **kwargs):
    return build_profile(*at, store=store, property_at=kwargs.pop("property_at", fake_property),
                         plan_registry=kwargs.pop("plan_registry", registry),
                         ancient_remains_at=kwargs.pop("ancient_remains_at", no_remains), **kwargs)


# --- the property and its plans ---------------------------------------------------------------------------------

def test_names_the_property_at_the_pin(store):
    """A pin in Uppsala gives the property's designation and its boundary."""
    result = profile(store)
    assert result["property_status"] == "found"
    assert result["property"]["designation"] == "Uppsala Kungsängen 7:8"
    assert result["property"]["geometry"]["type"] == "Polygon"


def test_lists_plans_in_force_newest_first(store):
    """Plans in force covering the property come newest laga kraft date first."""
    refs = [p["ref"] for p in profile(store)["plans"] if p["kind"] == "plan"]
    assert refs == ["0380-P2002/5", "0380-P1990/3"]


def test_plan_rows_carry_name_date_and_document_link(store):
    """Each plan has its aktbeteckning, name, laga kraft date and a link to the plan documents."""
    atle = next(p for p in profile(store)["plans"] if p["ref"] == "0380-P2002/5")
    assert atle["name"] == "Del av Atle, Kungsängen 7:8"
    assert atle["date"] == "2002-01-09"
    assert atle["url"] == "https://www.uppsala.se/detaljplan/?aktbeteckning=0380-P2002/5"


def test_lists_additions_and_area_regulations_with_the_plans(store):
    """Tillägg and områdesbestämmelser covering the property are listed with the plans."""
    kinds = {p["ref"]: p["kind"] for p in profile(store)["plans"]}
    assert kinds["0380-P2012/9"] == "plan_addition"
    assert kinds["0380-O2005/1"] == "area_regulations"


def test_lists_land_use_zones_with_code_and_wording(store):
    """Land-use zones on the property come with their code, wording and the interpreted-boundary caveat."""
    zones = {z["ref"]: z for z in profile(store)["zones"]}
    assert zones["BCK"]["name"] == "Bostäder, Centrumfunktion, Kontor"
    assert "Tolkad" in zones["BCK"]["note"]


def test_points_to_corpus_provisions_when_indexed(store):
    """A plan whose provisions the corpus holds points to that corpus plan."""
    atle = next(p for p in profile(store)["plans"] if p["ref"] == "0380-P2002/5")
    assert atle["corpus_plan_id"] == "f41489"
    assert atle["provisions_indexed"] is True


def test_matches_a_plan_to_the_corpus_through_its_plan_page(store, tmp_path):
    """The plan's document link leads to its page; the corpus plan of that page is the match, whatever its name."""
    page = "https://www.uppsala.se/detaljplan/kungsangen-stadsplan/"
    (tmp_path / "0380" / "plan_pages.json").write_text(json.dumps({"0380-P1990/3": page}))
    def registry_with_page(code):
        return [{"plan_id": "b70001", "kommun_code": "0380", "name": "Stadsplan Kungsängen (Kv Atle m.fl.)",
                 "page": {"doc_id": "page:0380:x", "url": page}, "provisions": [{"code": "e1", "text": "..."}]}]
    old = next(p for p in profile(store, plan_registry=registry_with_page)["plans"] if p["ref"] == "0380-P1990/3")
    assert old["corpus_plan_id"] == "b70001" and old["provisions_indexed"] is True


def test_says_provisions_not_indexed_otherwise(store):
    """A plan without provisions in the corpus is marked as not indexed."""
    old = next(p for p in profile(store)["plans"] if p["ref"] == "0380-P1990/3")
    assert old["provisions_indexed"] is False


def test_lists_pending_plans_separately(store):
    """Plans in progress are listed apart from the plans in force, with their stage."""
    result = profile(store)
    assert [p["name"] for p in result["pending_plans"]] == ["Kungsängen 7:8 m.fl."]
    assert result["pending_plans"][0]["status"] == "Samråd"
    assert all(p["kind"] != "plan_pending" for p in result["plans"])


def test_says_inside_detaljplan(store):
    """A property covered by a plan in force is inside a detaljplan."""
    assert profile(store)["detaljplan"] == "inside"


def test_says_outside_detaljplan_when_the_plan_layer_is_complete(store):
    """No plan found and a complete plan layer means outside a detaljplan."""
    assert profile(store, at=EMPTY_LOT)["detaljplan"] == "outside"


def test_says_unknown_when_the_plan_layer_is_incomplete(tmp_path):
    """No plan found in an incomplete plan layer is not proof of being outside one."""
    store = write_snapshot(tmp_path, complete=False)
    assert profile(store, at=EMPTY_LOT)["detaljplan"] == "unknown"


def test_lists_every_plan_and_zone_the_property_spans(store):
    """A property spanning several zones gets each one, with the share of the property it covers."""
    shares = {z["ref"]: z["share"] for z in profile(store)["zones"]}
    assert set(shares) == {"BCK", "P"}
    assert shares["BCK"] == pytest.approx(0.75, abs=0.02)


def test_leaves_out_a_neighbour_that_only_touches_the_property(store):
    """A plan touching the property's boundary is not listed."""
    assert "0380-P2010/1" not in [p["ref"] for p in profile(store)["plans"]]


def test_rows_carry_geometry_for_the_map(store):
    """Plans and zones carry their outline so the map can draw them."""
    result = profile(store)
    assert all(row["geometry"]["type"] in ("Polygon", "MultiPolygon") for row in result["plans"] + result["zones"])


# --- no property, not covered, failures -------------------------------------------------------------------------

def test_reports_no_property_on_a_street(store):
    """A pin with no property at it says so."""
    result = profile(store, at=STREET)
    assert result["property"] is None
    assert result["property_status"] == "none"


def test_reports_property_service_failure(store):
    """A failing property service is reported as unavailable, not as no property."""
    def broken(code, lon, lat):
        raise PlaceSourceUnavailable("timeout")
    result = profile(store, property_at=broken)
    assert result["property_status"] == "unavailable"


def test_reports_a_place_outside_the_pilot_kommuner(store):
    """A pin outside the pilot kommuner is not covered."""
    result = profile(store, at=OUTSIDE)
    assert result["covered"] is False
    assert result["kommun"] is None
    assert result["property_status"] == "not_covered"
    assert result["plans"] == []


def test_rejects_a_point_that_is_not_a_coordinate(store):
    """A latitude outside -90..90 is an error."""
    with pytest.raises(ValueError):
        profile(store, at=(123.0, 17.6))


# --- sources ---------------------------------------------------------------------------------------------------

def test_every_row_names_its_source_and_date(store):
    """Plans, zones and pending plans each name their source and snapshot date."""
    result = profile(store)
    for row in result["plans"] + result["zones"] + result["pending_plans"]:
        assert row["source"] == "Uppsala kommun"
        assert row["fetched"] == FETCHED


def test_says_registry_data_not_a_decision(store):
    """The first note says the card is registry data, not a decision."""
    assert profile(store)["notes"][0] == NOT_A_DECISION


def test_lists_the_layers_consulted_with_their_status(tmp_path):
    """A layer without its snapshot file is reported as unavailable."""
    store = write_snapshot(tmp_path, missing=("plans_pending",))
    status = {layer["id"]: layer["status"] for layer in profile(store)["layers"]}
    assert status["plans"] == "ok"
    assert status["plans_pending"] == "unavailable"

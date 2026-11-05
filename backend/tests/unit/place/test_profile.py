"""place.profile.build_profile on a fake snapshot: the property, its plans and zones, and what the card says
when there is no property, no coverage or no answer."""

import json
import time

import pytest

from place.live import PlaceSourceUnavailable
from place.plan_layers import fetch_plan_layer
from place.plan_links import run as match_plans
from place.plan_links import run_hosted
from place.profile import (
    NOT_A_DECISION,
    CorpusUnavailable,
    build_profile,
    hosted_documents,
)
from place.sources import today
from place.store import PlaceStore
from tests.unit.place.hosted import (
    ATLE,
    DESCRIPTION_ID,
    MAP_ID,
    STADSPLAN,
    STADSPLAN_ID,
    DownCorpus,
    FakeCorpus,
    hosted_snapshot,
    lookup,
    plans_of,
)
from tests.unit.place.plan_layer import (
    IN_NACKA,
    NO_PLAN_IN_NACKA,
    fake_services,
    nacka_store,
    source,
)
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
                         ancient_remains_at=kwargs.pop("ancient_remains_at", no_remains),
                         corpus_documents=kwargs.pop("corpus_documents", lambda doc_ids: {}), **kwargs)


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


# --- a kommun with an open plan layer (#52) ---------------------------------------------------------------------

def test_a_pin_in_a_plan_layer_kommun_names_it_and_lists_every_plan_at_the_point_newest_first(tmp_path):
    """A pin in a kommun with a plan snapshot names the kommun and lists every plan whose polygon covers the point,
    newest first."""
    result = profile(nacka_store(tmp_path), at=IN_NACKA)
    assert result["kommun"] == {"code": "0182", "name": "Nacka"} and result["covered"] is True
    assert [p["ref"] for p in result["plans"]] == ["0182-P2015/3", "0182-P1988/12"]
    assert result["detaljplan"] == "inside"


def test_a_plan_layer_row_carries_its_keys(tmp_path):
    """Each plan row has its aktbeteckning, name, date, page link, absolute document links, licence and snapshot date."""
    newer, older = profile(nacka_store(tmp_path), at=IN_NACKA)["plans"]
    assert (newer["ref"], newer["name"], newer["date"], newer["type"]) == ("0182-P2015/3", "Kvarnholmen etapp 4",
                                                                         "2015-06-01", "Detaljplan")
    assert (newer["page"], newer["documents"]) == (None, ["http://infobank.nacka.se/ext/planer/kvarnholmen.pdf"])
    assert newer["url"] == "http://infobank.nacka.se/ext/planer/kvarnholmen.pdf"
    assert (newer["licence"], newer["source"], newer["fetched"]) == ("unknown", "Nacka kommun", today())
    assert (older["date"], older["page"], older["documents"]) == ("1988-03-09", "https://www.nacka.se/planer/sicklaon/", [])
    assert older["url"] == "https://www.nacka.se/planer/sicklaon/"


def test_a_plan_layer_kommun_has_no_property_lookup(tmp_path):
    """Outside Uppsala there is no property: the plans are those at the point and the property is not covered."""
    result = profile(nacka_store(tmp_path), at=IN_NACKA)
    assert (result["property"], result["property_status"]) == (None, "not_covered")
    assert (result["zones"], result["pending_plans"]) == ([], [])


def test_no_plan_in_a_plan_layer_kommun_says_none_was_found_not_outside(tmp_path):
    """Where the layer is not known to hold every plan, a point without a plan is not 'outside': the profile says
    no plan was found in the kommun's layer."""
    result = profile(nacka_store(tmp_path), at=NO_PLAN_IN_NACKA)
    assert result["detaljplan"] == "unknown"
    assert any("no plan was found" in note.lower() and "Nacka" in note for note in result["notes"])


def test_uppsala_plan_rows_carry_page_documents_and_licence(store):
    """Uppsala's plan rows carry the new keys too: the page is the document link, the documents are none."""
    atle = next(p for p in profile(store)["plans"] if p["ref"] == "0380-P2002/5")
    assert atle["page"] == "https://www.uppsala.se/detaljplan/?aktbeteckning=0380-P2002/5"
    assert atle["documents"] == []
    assert atle["licence"] == "open data"

# --- the documents matched to the plans (#53) --------------------------------------------------------------------

KVARNHOLMEN_PDF = "http://infobank.nacka.se/ext/planer/kvarnholmen.pdf"


def document(doc_id, *, code="0182", url="https://www.nacka.se/planer/x/", kommun="Nacka"):
    return {"doc_id": doc_id, "kind": "page", "doc_type": "detaljplan", "kommun_code": code, "kommun": kommun,
            "title": "En sida", "url": url, "text": ""}


def nacka_snapshot(tmp_path):
    fetch_plan_layer(source(), client=fake_services(), out_dir=tmp_path)
    return tmp_path


def test_plan_rows_carry_the_matched_document_ids(tmp_path):
    """After a run, a plan at the pin carries the ids of its matched documents and the level that matched them."""
    geo_dir = nacka_snapshot(tmp_path)
    match_plans(["0182"], lambda: {"0182": [document("pdf:0182:a1", url=KVARNHOLMEN_PDF)]}, geo_dir=geo_dir)
    newer, older = profile(PlaceStore(geo_dir), at=IN_NACKA)["plans"]
    assert (newer["document_ids"], newer["document_match"]) == (["pdf:0182:a1"], "link")
    assert (older["document_ids"], older["document_match"]) == ([], None)


def test_plan_rows_say_no_document_is_matched_before_a_run(tmp_path):
    """Before any run a plan row says no document is matched yet."""
    newer = profile(PlaceStore(nacka_snapshot(tmp_path)), at=IN_NACKA)["plans"][0]
    assert (newer["document_ids"], newer["document_match"]) == ([], None)


def test_uppsala_plan_rows_carry_matched_document_ids(tmp_path):
    """Uppsala's plan rows carry their matched documents too."""
    write_snapshot(tmp_path)
    uppsala = [document("page:0380:h8", code="0380", kommun="Uppsala",
                        url="https://www.uppsala.se/detaljplan/?aktbeteckning=0380-P2002/5")]
    match_plans(["0380"], lambda: {"0380": uppsala}, geo_dir=tmp_path)
    atle = next(p for p in profile(PlaceStore(tmp_path))["plans"] if p["ref"] == "0380-P2002/5")
    assert (atle["document_ids"], atle["document_match"]) == (["page:0380:h8"], "link")


@pytest.fixture
def geo(tmp_path):
    return hosted_snapshot(tmp_path)


def pinned(geo, corpus_documents=lookup):
    return profile(PlaceStore(geo), corpus_documents=corpus_documents)


def plan_row(result, ref):
    return next(plan for plan in result["plans"] if plan["ref"] == ref)


# --- the place profile ------------------------------------------------------------------------------------------

def test_plan_row_lists_its_documents_with_role_title_and_address(geo):
    """A pin on a plan with documents lists each with its role, title and address."""
    run_hosted("0380", FakeCorpus(), plans_of, geo_dir=geo)
    atle = plan_row(pinned(geo), ATLE)
    assert atle["text_status"] == "read"
    assert {"doc_id": MAP_ID, "role": "plankarta", "title": "Plankarta (PDF, 3 MB)",
            "url": "https://www.uppsala.se/atle/plankarta.pdf"} in atle["corpus_documents"]


def test_plan_maps_come_first(geo):
    """A plan's documents are listed plan map first, then plan description."""
    run_hosted("0380", FakeCorpus(), plans_of, geo_dir=geo)
    assert [document["role"] for document in plan_row(pinned(geo), ATLE)["corpus_documents"]] == ["plankarta", "planbeskrivning"]


def test_several_plans_each_list_their_own_documents(geo):
    """A point covered by several plans lists each with its own documents."""
    run_hosted("0380", FakeCorpus(), plans_of, geo_dir=geo)
    profile = pinned(geo)
    assert {document["doc_id"] for document in plan_row(profile, ATLE)["corpus_documents"]} == {MAP_ID, DESCRIPTION_ID}
    assert [document["doc_id"] for document in plan_row(profile, STADSPLAN)["corpus_documents"]] == [STADSPLAN_ID]


def test_plan_without_documents_has_no_text_and_keeps_its_link(geo):
    """A plan with no document shows no text read, with its link to the kommun."""
    run_hosted("0380", FakeCorpus(), plans_of, geo_dir=geo)
    addition = plan_row(pinned(geo), "0380-P2012/9")
    assert (addition["text_status"], addition["corpus_documents"]) == ("none", [])
    assert addition["url"]


def test_unreachable_corpus_keeps_the_plan_rows_without_documents(geo):
    """The corpus being down leaves the plan rows in place, without documents, marked unavailable."""
    run_hosted("0380", FakeCorpus(), plans_of, geo_dir=geo)

    def down(doc_ids):
        raise CorpusUnavailable("down")

    atle = plan_row(pinned(geo, down), ATLE)
    assert (atle["text_status"], atle["corpus_documents"]) == ("unavailable", [])


def test_unreachable_corpus_adds_a_note(geo):
    """The profile says the plan documents could not be read."""
    run_hosted("0380", FakeCorpus(), plans_of, geo_dir=geo)

    def down(doc_ids):
        raise CorpusUnavailable("down")

    assert any("plan documents" in note.lower() for note in pinned(geo, down)["notes"])


def test_no_lookup_for_plans_without_links(geo):
    """A pin with no matched documents never asks the corpus."""
    def refuse(doc_ids):
        raise AssertionError("asked the corpus")

    assert all(plan["text_status"] == "none" for plan in pinned(geo, refuse)["plans"])


def test_a_linked_document_gone_from_the_corpus_is_left_out(geo):
    """A link whose document the corpus no longer holds is not listed."""
    run_hosted("0380", FakeCorpus(), plans_of, geo_dir=geo)
    atle = plan_row(pinned(geo, lambda doc_ids: {}), ATLE)
    assert (atle["text_status"], atle["corpus_documents"]) == ("none", [])


class FakeRetriever:
    def __init__(self, store):
        self.store = store


def serve_corpus(monkeypatch, store):
    monkeypatch.setenv("RETRIEVAL_BACKEND", "local")
    monkeypatch.setattr("localrag.service.get_retriever", lambda: FakeRetriever(store))


def test_hosted_documents_gives_title_and_address_of_those_the_corpus_holds(monkeypatch):
    """The corpus's title and address come back by document id; an id it does not hold is left out."""
    serve_corpus(monkeypatch, FakeCorpus())
    assert hosted_documents([MAP_ID, "pdf:0380:gone"]) == {
        MAP_ID: {"title": "Plankarta (PDF, 3 MB)", "url": "https://www.uppsala.se/atle/plankarta.pdf"}}


def test_hosted_documents_without_a_local_corpus_raises(monkeypatch):
    """An app on the pgvector backend has no corpus to read from."""
    serve_corpus(monkeypatch, FakeCorpus())
    monkeypatch.delenv("RETRIEVAL_BACKEND")
    with pytest.raises(CorpusUnavailable):
        hosted_documents([MAP_ID])


def test_hosted_documents_with_an_unreachable_corpus_raises(monkeypatch):
    """A driver error comes out as CorpusUnavailable."""
    serve_corpus(monkeypatch, DownCorpus())
    with pytest.raises(CorpusUnavailable):
        hosted_documents([MAP_ID])


def test_hosted_documents_gives_up_on_a_corpus_that_does_not_answer(monkeypatch):
    """A corpus still silent after the wait raises instead of holding the pin."""
    class Silent:
        def query(self, sql, params=()):
            time.sleep(0.2)
            return []

    serve_corpus(monkeypatch, Silent())
    monkeypatch.setattr("place.profile.CORPUS_LOOKUP_SECONDS", 0.01)
    with pytest.raises(CorpusUnavailable):
        hosted_documents([MAP_ID])

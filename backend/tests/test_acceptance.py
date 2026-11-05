"""Acceptance tests of #56: a pin on an Uppsala plan shows that plan's documents from the hosted corpus, and a report
says how many of Uppsala's plans have text. No real database (PCR-0011): the corpus is a SQLite chunks table."""

import json
import sqlite3

import pytest

from place.plan_links import (
    FETCH_LIST,
    LINKS_FILE,
    MATCH_REPORT,
    NO_LINK,
    NOT_IN_CORPUS,
    NOT_IN_REGISTRY,
    TEXT_REPORT,
    DocumentStoreUnavailable,
    load_hosted_documents,
    match_kommun,
    run_hosted,
    text_report,
)
from place.profile import CorpusUnavailable, build_profile
from place.store import PlaceStore
from tests.unit.place.snapshot import (
    PIN,
    fake_property,
    no_remains,
    registry,
    write_snapshot,
)

PAGE = "https://www.uppsala.se/detaljplaner/{}/"
ATLE = "0380-P2002/5"
STADSPLAN = "0380-P1990/3"
MAP_ID, DESCRIPTION_ID, STADSPLAN_ID = "pdf:0380:map", "pdf:0380:description", "pdf:0380:stadsplan"
CHUNKS = [
    (MAP_ID, 0, "pdf", "detaljplan", "0380", "Plankarta (PDF, 3 MB)", "https://www.uppsala.se/atle/plankarta.pdf", "Karta"),
    (DESCRIPTION_ID, 0, "pdf", "detaljplan", "0380", "Planbeskrivning (PDF)", "https://www.uppsala.se/atle/beskrivning.pdf",
     "Beskrivning"),
    (DESCRIPTION_ID, 1, "pdf", "detaljplan", "0380", "Planbeskrivning (PDF)", "https://www.uppsala.se/atle/beskrivning.pdf",
     "Fortsättning"),
    (STADSPLAN_ID, 0, "pdf", "detaljplan", "0380", "Stadsplan (PDF)", "https://www.uppsala.se/k/stadsplan.pdf", "Karta"),
    ("pdf:0380:lost", 0, "pdf", "detaljplan", "0380", "Inget plan", "https://www.uppsala.se/x/annat.pdf", "Annat"),
    ("page:0380:atle", 0, "page", "detaljplan", "0380", "Atle", PAGE.format("atle"), "Sidan"),
    ("pdf:0182:other", 0, "pdf", "detaljplan", "0182", "Nacka", "https://www.nacka.se/a.pdf", "Nacka"),
]
PLANS = [
    {"plan_id": "a", "kommun_code": "0380", "name": "Atle", "page": {"url": PAGE.format("atle")},
     "documents": [{"doc_id": DESCRIPTION_ID, "role": "planbeskrivning"}, {"doc_id": MAP_ID, "role": "plankarta"}]},
    {"plan_id": "s", "kommun_code": "0380", "name": "Kungsängen", "page": {"url": PAGE.format("kungsangen")},
     "documents": [{"doc_id": STADSPLAN_ID, "role": "plankarta"}]},
    {"plan_id": "g", "kommun_code": "0380", "name": "Grannplanen", "page": {"url": PAGE.format("granne")},
     "documents": [{"doc_id": "pdf:0380:not-loaded", "role": "plankarta"}]},
]


class FakeCorpus:
    """The hosted corpus's read side (PgStore.query) on a SQLite chunks table."""

    def __init__(self, rows=CHUNKS):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("CREATE TABLE chunks (doc_id, chunk_index, kind, doc_type, kommun_code, title, url, text)")
        self.connection.executemany("INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?)", rows)

    def query(self, sql, params=()):
        return self.connection.execute(sql, tuple(params)).fetchall()


class DownCorpus:
    def query(self, sql, params=()):
        raise OSError("connection refused")


def plans_of(code):
    return [plan for plan in PLANS if plan["kommun_code"] == code]


@pytest.fixture
def geo(tmp_path):
    write_snapshot(tmp_path)
    (tmp_path / "0380" / "plan_pages.json").write_text(json.dumps(
        {ATLE: PAGE.format("atle"), STADSPLAN: PAGE.format("kungsangen"), "0380-P2010/1": PAGE.format("granne"),
         "0380-P2012/9": PAGE.format("not-in-registry")}), encoding="utf-8")
    return tmp_path


def lookup(doc_ids):
    return {row["doc_id"]: {"title": row["title"], "url": row["url"]} for row in FakeCorpus().query(
        f"SELECT DISTINCT doc_id, title, url FROM chunks WHERE doc_id IN ({','.join('?' * len(doc_ids))})", doc_ids)}


def pinned(geo, corpus_documents=lookup):
    return build_profile(*PIN, store=PlaceStore(geo), property_at=fake_property, plan_registry=registry,
                         ancient_remains_at=no_remains, corpus_documents=corpus_documents)


def plan_row(profile, ref):
    return next(plan for plan in profile["plans"] if plan["ref"] == ref)


def link_rows(geo):
    text = (geo / "0380" / LINKS_FILE).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


# --- the hosted corpus's documents ------------------------------------------------------------------------------

def test_hosted_documents_are_the_kommuns_pdfs_with_role_and_plan_page():
    """A document comes back under its kommun with the role and plan page the registry gives it; web pages are left out."""
    documents = load_hosted_documents(["0380"], FakeCorpus(), plans_of)["0380"]
    description = next(document for document in documents if document["doc_id"] == DESCRIPTION_ID)
    assert (description["role"], description["plan_pages"]) == ("planbeskrivning", [PAGE.format("atle")])
    assert {document["doc_id"] for document in documents} == {MAP_ID, DESCRIPTION_ID, STADSPLAN_ID, "pdf:0380:lost"}


def test_hosted_document_in_no_plan_has_no_role():
    """A document no registry plan holds has no role and no plan page."""
    documents = load_hosted_documents(["0380"], FakeCorpus(), plans_of)["0380"]
    lost = next(document for document in documents if document["doc_id"] == "pdf:0380:lost")
    assert (lost["role"], lost["plan_pages"]) == (None, [])


def test_unreachable_hosted_corpus_raises():
    """A corpus that cannot be read raises DocumentStoreUnavailable."""
    with pytest.raises(DocumentStoreUnavailable):
        load_hosted_documents(["0380"], DownCorpus(), plans_of)


# --- the match --------------------------------------------------------------------------------------------------

def test_polygon_links_to_the_documents_of_its_plan_page(geo):
    """A polygon whose page is a registry plan's page is linked to that plan's documents at the link level."""
    run_hosted("0380", FakeCorpus(), plans_of, geo_dir=geo)
    atle = {row["doc_id"]: row["level"] for row in link_rows(geo) if row["ref"] == ATLE}
    assert atle == {MAP_ID: "link", DESCRIPTION_ID: "link"}


def test_a_plan_addition_links_to_the_documents_of_its_plan_page(geo):
    """A tillägg's polygon is linked to its plan's documents like a plan's."""
    (geo / "0380" / "plan_pages.json").write_text(json.dumps({"0380-P2012/9": PAGE.format("atle")}), encoding="utf-8")
    run_hosted("0380", FakeCorpus(), plans_of, geo_dir=geo)
    assert {row["doc_id"] for row in link_rows(geo) if row["ref"] == "0380-P2012/9"} == {MAP_ID, DESCRIPTION_ID}


def test_a_document_of_another_plan_is_not_hit_on_a_mention(geo):
    """A document the registry places under another plan's page is not linked for naming an aktbeteckning."""
    mention = (STADSPLAN_ID, 1, "pdf", "detaljplan", "0380", "Stadsplan (PDF)", "https://www.uppsala.se/k/stadsplan.pdf",
               "Ersätter 0380-P2010/1")
    run_hosted("0380", FakeCorpus([*CHUNKS, mention]), plans_of, geo_dir=geo)
    assert not [row for row in link_rows(geo) if row["ref"] == "0380-P2010/1"]


def test_a_document_in_no_plan_is_hit_on_its_aktbeteckning(geo):
    """A document the registry places under no plan page is linked when its front names the aktbeteckning."""
    own = ("pdf:0380:own", 0, "pdf", "detaljplan", "0380", "Plankarta", "https://www.uppsala.se/z/plankarta.pdf", "0380-P2010/1")
    run_hosted("0380", FakeCorpus([*CHUNKS, own]), plans_of, geo_dir=geo)
    assert [(row["doc_id"], row["level"]) for row in link_rows(geo) if row["ref"] == "0380-P2010/1"] == [("pdf:0380:own", "akt")]


def test_link_rows_carry_the_documents_role(geo):
    """Each link row says the document's role."""
    run_hosted("0380", FakeCorpus(), plans_of, geo_dir=geo)
    assert {row["doc_id"]: row["role"] for row in link_rows(geo) if row["ref"] == ATLE} == {
        MAP_ID: "plankarta", DESCRIPTION_ID: "planbeskrivning"}


def test_hosted_run_leaves_the_national_files_alone(geo):
    """A run for one kommun does not write the national fetch list or match report."""
    run_hosted("0380", FakeCorpus(), plans_of, geo_dir=geo)
    assert not (geo / FETCH_LIST).exists() and not (geo / MATCH_REPORT).exists()


def test_unreachable_corpus_stops_the_run_with_nothing_written(geo):
    """The corpus being down keeps the earlier link table and writes no report."""
    (geo / "0380" / LINKS_FILE).write_text('{"key": "earlier"}\n', encoding="utf-8")
    with pytest.raises(DocumentStoreUnavailable):
        run_hosted("0380", DownCorpus(), plans_of, geo_dir=geo)
    assert (geo / "0380" / LINKS_FILE).read_text(encoding="utf-8") == '{"key": "earlier"}\n'
    assert not (geo / "0380" / TEXT_REPORT).exists()


# --- the report -------------------------------------------------------------------------------------------------

def test_report_states_the_share_of_polygons_with_text(geo):
    """The report says how many of the kommun's polygons have documents."""
    row = run_hosted("0380", FakeCorpus(), plans_of, geo_dir=geo)
    report = (geo / "0380" / TEXT_REPORT).read_text(encoding="utf-8")
    assert f"{row['polygons'] - row['unmatched']} of {row['polygons']} polygons" in report


def test_report_says_a_plan_page_is_missing_from_the_registry(geo):
    """A polygon whose page no registry plan has is listed with that reason."""
    documents = load_hosted_documents(["0380"], FakeCorpus(), plans_of)["0380"]
    without_it = [plan for plan in PLANS if plan["name"] != "Grannplanen"]
    report = text_report("0380", match_kommun("0380", documents, geo_dir=geo), without_it)
    assert any("0380-P2010/1" in line and NOT_IN_REGISTRY in line for line in report.splitlines())


def test_report_says_a_plans_documents_are_not_in_the_corpus(geo):
    """A polygon whose registry plan has no document in the corpus is listed with that reason."""
    documents = load_hosted_documents(["0380"], FakeCorpus(), plans_of)["0380"]
    report = text_report("0380", match_kommun("0380", documents, geo_dir=geo), plans_of("0380"))
    assert any("0380-P2010/1" in line and NOT_IN_CORPUS in line for line in report.splitlines())


def test_report_says_a_polygon_has_no_link(geo):
    """A polygon without any link is listed with that reason."""
    result = {"code": "0380", "links": [], "report": {"polygons": 1, "link": 0, "akt": 0, "name": 0, "unmatched": 1},
              "fetch": [{"key": "0380-P1/1", "ref": "0380-P1/1", "name": "Utan länk", "links": [], "reason": None}]}
    report = text_report("0380", result, PLANS)
    assert any("0380-P1/1" in line and NO_LINK in line for line in report.splitlines())


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

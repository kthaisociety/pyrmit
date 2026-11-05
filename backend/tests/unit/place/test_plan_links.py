"""place.plan_links: the aktbeteckning normaliser, the three match levels, the link table, the fetch list and the
report, on the fake Nacka and Uppsala snapshots with fake store documents (PCR-0011)."""

import json

import pytest

from place.plan_layers import fetch_plan_layer
from place.plan_links import (
    AKT_FRONT_CHARS,
    FETCH_LIST,
    LINKS_FILE,
    MATCH_REPORT,
    NO_LINK,
    NOT_IN_CORPUS,
    NOT_IN_REGISTRY,
    TEXT_REPORT,
    DocumentStoreUnavailable,
    load_documents,
    load_hosted_documents,
    match_kommun,
    normalise_akt,
    run,
    run_hosted,
    text_report,
)
from place.sources import today
from tests.unit.place.hosted import (
    ATLE,
    CHUNKS,
    DESCRIPTION_ID,
    MAP_ID,
    PAGE,
    PLANS,
    STADSPLAN_ID,
    DownCorpus,
    FakeCorpus,
    hosted_snapshot,
    plans_of,
)
from tests.unit.place.plan_layer import (
    NACKA_FEATURES,
    fake_services,
    source,
    with_link,
)
from tests.unit.place.snapshot import (
    write_snapshot,
)

KVARNHOLMEN_PDF = "http://infobank.nacka.se/ext/planer/kvarnholmen.pdf"


def document(doc_id, *, code="0182", url="https://www.nacka.se/planer/x/", title="En sida", text="", kommun="Nacka"):
    return {"doc_id": doc_id, "kind": "pdf" if doc_id.startswith("pdf") else "page", "doc_type": "detaljplan",
            "kommun_code": code, "kommun": kommun, "title": title, "url": url, "text": text}


def nacka_snapshot(tmp_path, features=NACKA_FEATURES):
    fetch_plan_layer(source(), client=fake_services(features), out_dir=tmp_path)
    return tmp_path


def links_of(result, ref):
    return [(link["doc_id"], link["level"], link["review"]) for link in result["links"] if link["ref"] == ref]


# --- the normaliser ---------------------------------------------------------------------------------------------

def test_aktbeteckning_spellings_share_one_key():
    """The same plan written 0380-P2015/12, 0380-P 2015/12 or P2015-12 yields one key."""
    assert normalise_akt("0380-P2015/12") == normalise_akt("0380-P 2015/12") == normalise_akt("P2015-12") == "P2015/12"


def test_normaliser_drops_the_kommun_prefix_with_a_k():
    """0182K-93/62 and 0182-93/62 are the same aktbeteckning."""
    assert normalise_akt("0182K-93/62") == normalise_akt("0182-93/62") == "93/62"


def test_normaliser_gives_none_for_no_aktbeteckning():
    """None, an empty string and a value without digits give no key."""
    assert normalise_akt(None) is None and normalise_akt("") is None and normalise_akt("saknas") is None


# --- the match levels -------------------------------------------------------------------------------------------

def test_link_level_matches_on_the_documents_address(tmp_path):
    """A polygon whose document link equals a document's address is linked at the link level."""
    result = match_kommun("0182", [document("pdf:0182:a1", url=KVARNHOLMEN_PDF)], geo_dir=nacka_snapshot(tmp_path))
    assert links_of(result, "0182-P2015/3") == [("pdf:0182:a1", "link", False)]


def test_link_level_ignores_scheme_and_trailing_slash(tmp_path):
    """https and a trailing slash on either side do not keep a link from matching."""
    result = match_kommun("0182", [document("page:0182:b2", url="http://www.nacka.se/planer/sicklaon")],
                          geo_dir=nacka_snapshot(tmp_path))
    assert links_of(result, "0182-P1988/12") == [("page:0182:b2", "link", False)]


def test_akt_level_matches_on_the_aktbeteckning_in_the_text(tmp_path):
    """A document whose text holds the polygon's aktbeteckning, however spelled, is linked at the akt level."""
    text = "Planbeskrivning\nAktbeteckning: 0182-P 2015/3\nDetaljplanen vann laga kraft 2015-06-01."
    result = match_kommun("0182", [document("pdf:0182:c3", text=text)], geo_dir=nacka_snapshot(tmp_path))
    assert links_of(result, "0182-P2015/3") == [("pdf:0182:c3", "akt", False)]


def test_akt_level_ignores_an_aktbeteckning_past_the_front_of_the_text(tmp_path):
    """A new plan's description naming the plan it replaces, deep in its text, is not that plan's document."""
    text = "Planbeskrivning\n" + "x" * AKT_FRONT_CHARS + "\nPlanen ersätter detaljplan 0182-P2015/3."
    result = match_kommun("0182", [document("pdf:0182:c5", text=text)], geo_dir=nacka_snapshot(tmp_path))
    assert links_of(result, "0182-P2015/3") == []
    assert "0182-P2015/3" in [item["ref"] for item in result["fetch"]]


def test_akt_level_matches_on_the_aktbeteckning_in_the_title(tmp_path):
    """A document titled with the aktbeteckning is linked, wherever its text names it."""
    documents = [document("pdf:0182:c6", title="Gällande plankarta 0182-P2015/3 (PDF, 1 MB)")]
    result = match_kommun("0182", documents, geo_dir=nacka_snapshot(tmp_path))
    assert links_of(result, "0182-P2015/3") == [("pdf:0182:c6", "akt", False)]


@pytest.mark.parametrize("file_name", ["0182-P2015-3.pdf", "0182-P%202015-3.pdf", "0182k-p2015-3.pdf"])
def test_akt_level_matches_on_the_aktbeteckning_in_the_file_name(tmp_path, file_name):
    """A document whose file name holds the aktbeteckning, encoded or in lower case, is linked."""
    documents = [document("pdf:0182:c7", url=f"https://www.nacka.se/planer/{file_name}")]
    result = match_kommun("0182", documents, geo_dir=nacka_snapshot(tmp_path))
    assert links_of(result, "0182-P2015/3") == [("pdf:0182:c7", "akt", False)]


def test_name_level_match_is_marked_for_review(tmp_path):
    """A document whose title names the plan is linked at the name level and marked for review."""
    result = match_kommun("0182", [document("page:0182:d4", title="Detaljplan för Kvarnholmen etapp 4 - Nacka kommun")],
                          geo_dir=nacka_snapshot(tmp_path))
    assert links_of(result, "0182-P2015/3") == [("page:0182:d4", "name", True)]


def test_levels_stop_at_the_first_hit(tmp_path):
    """A polygon matched at the link level takes no akt or name matches."""
    documents = [document("pdf:0182:a1", url=KVARNHOLMEN_PDF),
                 document("pdf:0182:c3", text="Aktbeteckning 0182-P2015/3"),
                 document("page:0182:d4", title="Kvarnholmen etapp 4")]
    result = match_kommun("0182", documents, geo_dir=nacka_snapshot(tmp_path))
    assert links_of(result, "0182-P2015/3") == [("pdf:0182:a1", "link", False)]


def test_every_document_hitting_at_the_level_is_linked(tmp_path):
    """Two documents that both hold the aktbeteckning are both linked."""
    documents = [document("pdf:0182:c3", text="Akt 0182-P2015/3 plankarta"), document("pdf:0182:c4", text="0182-P2015/3")]
    result = match_kommun("0182", documents, geo_dir=nacka_snapshot(tmp_path))
    assert links_of(result, "0182-P2015/3") == [("pdf:0182:c3", "akt", False), ("pdf:0182:c4", "akt", False)]


def test_a_document_covering_two_polygons_links_to_both(tmp_path):
    """An amendment naming two plans' aktbeteckningar is linked from both polygons."""
    text = "Ändring av detaljplanerna 0182-P2015/3 och 0182-P1988/12."
    result = match_kommun("0182", [document("pdf:0182:e5", text=text)], geo_dir=nacka_snapshot(tmp_path))
    assert links_of(result, "0182-P2015/3") == [("pdf:0182:e5", "akt", False)]
    assert links_of(result, "0182-P1988/12") == [("pdf:0182:e5", "akt", False)]


def test_an_aktbeteckning_in_another_kommuns_document_does_not_match(tmp_path):
    """A document of another kommun holding the aktbeteckning is not linked."""
    other = document("pdf:0120:f6", code="0120", kommun="Värmdö", text="Aktbeteckning 0182-P2015/3")
    result = match_kommun("0182", [other], geo_dir=nacka_snapshot(tmp_path))
    assert result["links"] == []


def test_link_rows_carry_the_date(tmp_path):
    """Every link row says when it was made."""
    result = match_kommun("0182", [document("pdf:0182:a1", url=KVARNHOLMEN_PDF)], geo_dir=nacka_snapshot(tmp_path))
    assert result["links"][0]["date"] == today()


# --- the fetch list and the report ------------------------------------------------------------------------------

def test_unmatched_polygons_go_to_the_fetch_list_with_their_links(tmp_path):
    """A polygon no document matched is listed with its links for the scraper."""
    result = match_kommun("0182", [document("pdf:0182:a1", url=KVARNHOLMEN_PDF)], geo_dir=nacka_snapshot(tmp_path))
    sicklaon = next(item for item in result["fetch"] if item["ref"] == "0182-P1988/12")
    assert sicklaon["links"] == ["https://www.nacka.se/planer/sicklaon/"] and sicklaon["reason"] is None
    assert "0182-P2015/3" not in [item["ref"] for item in result["fetch"]]


def test_polygons_with_dropped_internal_links_are_listed_as_no_public_link(tmp_path):
    """A polygon whose links were internal paths goes to the fetch list as 'no public link', with its aktbeteckning."""
    geo_dir = nacka_snapshot(tmp_path, with_link(r"\\server\plan\kvarnholmen.pdf"))
    result = match_kommun("0182", [], geo_dir=geo_dir)
    kvarnholmen = next(item for item in result["fetch"] if item["ref"] == "0182-P2015/3")
    assert (kvarnholmen["links"], kvarnholmen["reason"]) == ([], "no public link")


def test_the_report_counts_levels_unmatched_and_unclaimed_documents(tmp_path):
    """The kommun's report row counts polygons, matches per level, unmatched polygons and the store's unclaimed share."""
    documents = [document("pdf:0182:a1", url=KVARNHOLMEN_PDF), document("page:0182:d4", title="Sicklaön"),
                 document("pdf:0182:g7", title="Något annat")]
    report = match_kommun("0182", documents, geo_dir=nacka_snapshot(tmp_path))["report"]
    assert (report["polygons"], report["link"], report["akt"], report["name"], report["unmatched"]) == (3, 1, 0, 1, 1)
    assert (report["documents"], report["unclaimed_share"]) == (3, pytest.approx(1 / 3))


# --- the run ------------------------------------------------------------------------------------------------------

def test_the_run_writes_the_link_table_the_fetch_list_and_the_report(tmp_path):
    """One run writes each kommun's link table, the fetch list grouped by kommun and the report."""
    geo_dir = nacka_snapshot(tmp_path)
    rows = run(["0182"], lambda: {"0182": [document("pdf:0182:a1", url=KVARNHOLMEN_PDF)]}, geo_dir=geo_dir)
    links = [json.loads(line) for line in (geo_dir / "0182" / LINKS_FILE).read_text(encoding="utf-8").splitlines()]
    assert [(link["ref"], link["doc_id"]) for link in links] == [("0182-P2015/3", "pdf:0182:a1")]
    fetch = json.loads((geo_dir / FETCH_LIST).read_text(encoding="utf-8"))
    assert [item["ref"] for item in fetch["0182"]] == ["0182-P1988/12", None]
    assert [row["code"] for row in rows] == ["0182"]
    assert "| 0182 |" in (geo_dir / MATCH_REPORT).read_text(encoding="utf-8")


def test_the_run_covers_every_kommun_with_a_snapshot(tmp_path):
    """Uppsala's plans are matched too, through their document link."""
    write_snapshot(tmp_path)
    geo_dir = nacka_snapshot(tmp_path)
    uppsala = [document("page:0380:h8", code="0380", kommun="Uppsala",
                        url="https://www.uppsala.se/detaljplan/?aktbeteckning=0380-P2002/5")]
    rows = run(["0182", "0380"], lambda: {"0182": [], "0380": uppsala}, geo_dir=geo_dir)
    assert [(row["code"], row["link"]) for row in rows] == [("0182", 0), ("0380", 1)]


def test_uppsala_polygons_match_the_page_their_document_link_leads_to(tmp_path):
    """A pilot kommun's document link redirects to the plan's page; the page plan_pages.json recorded matches."""
    write_snapshot(tmp_path)
    page = "https://www.uppsala.se/bygga-och-bo/detaljplaner/1991-2000/del-av-atle/"
    (tmp_path / "0380" / "plan_pages.json").write_text(json.dumps({"0380-P2002/5": page}), encoding="utf-8")
    result = match_kommun("0380", [document("page:0380:h8", code="0380", kommun="Uppsala", url=page)], geo_dir=tmp_path)
    assert links_of(result, "0380-P2002/5") == [("page:0380:h8", "link", False)]


def test_an_unreachable_store_stops_the_run_with_nothing_written(tmp_path):
    """When the document store cannot be read the run stops with a message and writes nothing."""
    def unavailable():
        raise DocumentStoreUnavailable("documents.jsonl is missing")
    geo_dir = nacka_snapshot(tmp_path)
    with pytest.raises(DocumentStoreUnavailable):
        run(["0182"], unavailable, geo_dir=geo_dir)
    assert not (geo_dir / "0182" / LINKS_FILE).exists() and not (geo_dir / MATCH_REPORT).exists()


def test_loading_the_store_needs_its_file(tmp_path):
    """A missing documents file is the store being unreachable."""
    with pytest.raises(DocumentStoreUnavailable):
        load_documents(tmp_path / "documents.jsonl")


def test_loading_the_store_keeps_detaljplan_documents_by_kommun(tmp_path):
    """The store's detaljplan documents come grouped by kommun; laws and other types are left out."""
    path = tmp_path / "documents.jsonl"
    rows = [document("pdf:0182:a1"), document("page:0120:b2", code="0120", kommun="Värmdö"),
            {"doc_id": "law:pbl", "kind": "law", "doc_type": "lag", "kommun_code": None, "title": "PBL", "url": "", "text": ""},
            {**document("pdf:0182:z9"), "doc_type": "bygglov"}]
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    assert {code: [d["doc_id"] for d in docs] for code, docs in load_documents(path).items()} == {
        "0182": ["pdf:0182:a1"], "0120": ["page:0120:b2"]}


@pytest.fixture
def geo(tmp_path):
    return hosted_snapshot(tmp_path)


def link_rows(geo):
    text = (geo / "0380" / LINKS_FILE).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


# --- against the hosted corpus: its documents ------------------------------------------------------------------------------

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


# --- against the hosted corpus: the match --------------------------------------------------------------------------------------------------

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


# --- against the hosted corpus: the report -------------------------------------------------------------------------------------------------

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

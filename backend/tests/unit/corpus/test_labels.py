"""The schema labels (docs/source-chunk-schema.md) set at download and text extraction: place, fetch date, content
fingerprint, plan ID and plan stage. No network, no database (PCR-0011)."""

import asyncio
import json
import os
import sqlite3
from datetime import UTC, datetime
from types import SimpleNamespace

import pymupdf

from corpus import crawl, extract, laws, pdf_filter, plans
from corpus.common import fetch_date, missing_labels, text_sha1

MTIME = datetime(2026, 10, 22, 14, 8, 43, tzinfo=UTC)
RECORDED = "2026-10-23T19:16:50.897014+00:00"


def touch(path, when=MTIME):
    os.utime(path, (when.timestamp(), when.timestamp()))


# --- fetch date and required labels ---------------------------------------------------------------------------------

def test_fetch_date_prefers_the_recorded_date(tmp_path):
    path = tmp_path / "file.pdf"
    path.write_bytes(b"%PDF")
    touch(path)
    assert fetch_date(RECORDED, path) == (RECORDED, "recorded")
    assert fetch_date(None, path) == (MTIME.isoformat(), "file_mtime")


def test_missing_labels():
    assert missing_labels({"url": "u", "place": "national", "fetched_at": RECORDED}) == []
    assert missing_labels({"url": "", "place": None}) == ["url", "place", "fetched_at"]


# --- extraction -----------------------------------------------------------------------------------------------------

def test_laws_are_national_and_dated(tmp_path, monkeypatch):
    monkeypatch.setattr(extract, "LAWS_DIR", tmp_path)
    index = [{"slug": "pbl", "title": "Plan- och bygglag (2010:900)", "url": "https://data.riksdagen.se/pbl",
              "fetched_at": RECORDED},
             {"slug": "mb", "title": "Miljöbalk (1998:808)", "url": "https://data.riksdagen.se/mb"}]  # before #106
    (tmp_path / "index.json").write_text(json.dumps(index), encoding="utf-8")
    for slug in ("pbl", "mb"):
        (tmp_path / f"{slug}.txt").write_text(f"{slug} 1 § Text.", encoding="utf-8")
        touch(tmp_path / f"{slug}.txt")
    pbl, mb = extract.law_documents()
    assert (pbl["place"], pbl["kommun"], pbl["kommun_code"]) == ("national", None, None)
    assert (pbl["fetched_at"], pbl["fetched_at_source"]) == (RECORDED, "recorded")
    assert (mb["fetched_at"], mb["fetched_at_source"]) == (MTIME.isoformat(), "file_mtime")
    assert pbl["content_sha1"] == text_sha1("pbl 1 § Text.")
    assert missing_labels(pbl) == missing_labels(mb) == []


def test_pages_copy_the_crawler_fetch_date(tmp_path, monkeypatch):
    monkeypatch.setattr(extract, "WEB_DIR", tmp_path)
    pages = tmp_path / "0115" / "pages"
    pages.mkdir(parents=True)
    page = {"url": "https://www.vallentuna.se/bygga/detaljplaner/kumla", "title": "Detaljplan för Kumla",
            "text": "Detaljplanen för Kumla är på granskning.", "score": 9}
    (pages / "a.json").write_text(json.dumps({**page, "fetched_at": RECORDED}), encoding="utf-8")
    (pages / "b.json").write_text(json.dumps({**page, "text": "Ett äldre crawl utan datum."}), encoding="utf-8")
    touch(pages / "b.json")
    documents = {d["doc_id"]: d for d in extract.page_documents({"0115": "Vallentuna"})}
    recorded, old = documents["page:0115:a"], documents["page:0115:b"]
    assert (recorded["place"], recorded["fetched_at"], recorded["fetched_at_source"]) == ("Vallentuna", RECORDED,
                                                                                          "recorded")
    assert (old["fetched_at"], old["fetched_at_source"]) == (MTIME.isoformat(), "file_mtime")
    assert recorded["content_sha1"] == text_sha1(recorded["text"])


def write_pdf(path, text):
    pdf = pymupdf.open()
    pdf.new_page().insert_textbox(pymupdf.Rect(50, 50, 550, 800), text)
    pdf.save(path)


PLAN_TEXT = ("Detaljplan för Kumla-Stensta, Vallentuna kommun. GRANSKNINGSHANDLING. Syftet med detaljplanen är att "
             "möjliggöra bostäder i form av friliggande villor med en största byggnadsarea om 200 kvadratmeter.")


def test_pdfs_take_the_manifest_date_else_the_file_mtime(tmp_path):
    path = tmp_path / "abc.pdf"
    write_pdf(path, PLAN_TEXT)
    touch(path)
    entry = {"id": "abc", "url": "https://www.vallentuna.se/dp/kumla_plankarta.pdf", "anchor": "Plankarta"}
    old = extract._pdf_document((str(path), "0115", entry, "Vallentuna"))
    new = extract._pdf_document((str(path), "0115", {**entry, "fetched_at": RECORDED}, "Vallentuna"))
    assert (old["place"], old["fetched_at"], old["fetched_at_source"]) == ("Vallentuna", MTIME.isoformat(),
                                                                           "file_mtime")
    assert (new["fetched_at"], new["fetched_at_source"]) == (RECORDED, "recorded")
    assert old["content_sha1"] == text_sha1(old["text"]) and old["text"]


def test_legacy_documents_have_no_fetch_date_and_are_never_guessed():
    # The schema: an unknown date stays empty. corpus.chunk then rejects their chunks
    labels = extract.labels("Vallentuna", (None, None), "text")
    assert labels["fetched_at"] is None and missing_labels({"url": None, **labels}) == ["url", "fetched_at"]


# --- plan ID and plan stage -----------------------------------------------------------------------------------------

def plan_documents():
    def pdf(doc_id, stem, text):
        return {"doc_id": doc_id, "kind": "pdf", "doc_type": "detaljplan", "kommun_code": "0115",
                "kommun": "Vallentuna", "title": stem, "url": f"https://www.vallentuna.se/dp/{stem}.pdf",
                "source_page": None, "text": text}
    return [
        {"doc_id": "law:pbl", "kind": "law", "doc_type": "lag", "kommun": None, "title": "PBL", "url": "u",
         "text": "1 § Text."},
        pdf("pdf:0115:a", "kumla_plankarta", PLAN_TEXT),
        pdf("pdf:0115:b", "kumla_planbeskrivning", "Planbeskrivning. GRANSKNINGSHANDLING."),
        pdf("pdf:0115:c", "ekbacken_plankarta", "Detaljplan för Ekbacken. Laga kraft 2019-05-02."),
        {"doc_id": "page:0115:p", "kind": "page", "doc_type": "bygglov", "kommun_code": "0115",
         "kommun": "Vallentuna", "title": "Bygglov", "url": "https://www.vallentuna.se/bygglov", "text": "Bygglov."},
    ]


def write_documents(path, documents):
    path.write_text("".join(json.dumps(d, ensure_ascii=False) + "\n" for d in documents), encoding="utf-8")


def read_documents(path):
    return {d["doc_id"]: d for d in map(json.loads, path.read_text(encoding="utf-8").splitlines())}


def registry_ids(documents):
    store = sqlite3.connect(":memory:")
    store.execute("CREATE TABLE chunks (chunk_id, doc_id, text)")
    return {doc["doc_id"]: plan["plan_id"] for spec in plans.plan_groups(documents)
            for plan in [plans.build_plan(*spec, store)] for doc in plan["documents"]}


def test_plan_documents_get_the_registry_plan_id_and_stage(tmp_path):
    path = tmp_path / "documents.jsonl"
    write_documents(path, plan_documents())
    stages = plans.add_plan_labels(path)
    documents = read_documents(path)
    assert stages == {"review": 2, "in_force": 1}
    assert documents["pdf:0115:a"]["plan_id"] == documents["pdf:0115:b"]["plan_id"] != documents["pdf:0115:c"]["plan_id"]
    assert [documents[i]["plan_stage"] for i in ("pdf:0115:a", "pdf:0115:b", "pdf:0115:c")] == ["review", "review",
                                                                                                 "in_force"]
    # The same ID as corpus.plans writes to plans.jsonl
    assert {i: documents[i]["plan_id"] for i in registry_ids(plan_documents())} == registry_ids(plan_documents())
    for doc_id in ("law:pbl", "page:0115:p"):
        assert (documents[doc_id]["plan_id"], documents[doc_id]["plan_stage"]) == (None, None)
    assert documents["pdf:0115:a"]["text"] == PLAN_TEXT  # the rest of the document is untouched


def test_pdf_filter_apply_regroups_the_plans(tmp_path, monkeypatch):
    path = tmp_path / "documents.jsonl"
    write_documents(path, plan_documents())
    plans.add_plan_labels(path)
    before = read_documents(path)["pdf:0115:a"]["plan_id"]
    monkeypatch.setattr(pdf_filter, "DOCUMENTS_PATH", path)
    monkeypatch.setattr(pdf_filter, "dropped_ids", lambda: {"pdf:0115:b"})
    pdf_filter.apply()
    after = read_documents(path)
    remaining = [d for d in plan_documents() if d["doc_id"] != "pdf:0115:b"]
    assert "pdf:0115:b" not in after
    assert after["pdf:0115:a"]["plan_id"] == registry_ids(remaining)["pdf:0115:a"] != before


# --- download -------------------------------------------------------------------------------------------------------

def crawler(tmp_path, monkeypatch):
    monkeypatch.setattr(crawl, "WEB_DIR", tmp_path)
    kommun = {"code": "0115", "short_name": "Vallentuna", "website": "https://www.vallentuna.se"}
    return crawl.KommunCrawler(kommun, None, None, SimpleNamespace(max_pdfs=10, max_pdf_mb=50))


def manifest_lines(crawler_):
    return [json.loads(line) for line in crawler_.manifest.read_text(encoding="utf-8").splitlines()]


def test_crawler_records_when_a_pdf_was_downloaded(tmp_path, monkeypatch):
    found = crawler(tmp_path, monkeypatch)
    url = "https://www.vallentuna.se/dp/kumla_plankarta.pdf"
    started = datetime.now(UTC)
    response = SimpleNamespace(status_code=200, content=b"%PDF-1.4 kumla")
    asyncio.run(found.store_pdf(crawl.Task(-5, url, "pdf"), response))
    (line,) = manifest_lines(found)
    assert started <= datetime.fromisoformat(line["fetched_at"]) <= datetime.now(UTC)


def test_crawler_dates_a_pdf_of_an_earlier_pass_by_its_file(tmp_path, monkeypatch):
    found = crawler(tmp_path, monkeypatch)
    url = "https://www.vallentuna.se/dp/kumla_plankarta.pdf"
    path = tmp_path / "0115" / "pdf" / f"{crawl.stable_id(url)}.pdf"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"%PDF-1.4 kumla")
    touch(path)
    asyncio.run(found.store_pdf(crawl.Task(-5, url, "pdf")))
    (line,) = manifest_lines(found)
    assert line["fetched_at"] == MTIME.isoformat()


def test_laws_record_when_they_were_downloaded(tmp_path, monkeypatch):
    class Client:
        def __init__(self, **_):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def get(self, url):
            return SimpleNamespace(text="Plan- och bygglag (2010:900)\n\n1 § Text.")

    monkeypatch.setattr(laws, "LAWS_DIR", tmp_path)
    monkeypatch.setattr(laws, "LAWS", {"2010:900": "plan_och_bygglag"})
    monkeypatch.setattr(laws.httpx, "Client", Client)
    started = datetime.now(UTC)
    laws.main()
    (law,) = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert started <= datetime.fromisoformat(law["fetched_at"]) <= datetime.now(UTC)

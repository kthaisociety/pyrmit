import json

import httpx
import pymupdf
import pytest

from corpus import pdf_files

PDF = b"%PDF-1.7 fake plankarta"


@pytest.fixture
def site(tmp_path, monkeypatch):
    """Empty crawl folder and cache; the kommun's site answers from `site.pages` and counts its requests."""
    monkeypatch.setattr(pdf_files, "WEB_DIR", tmp_path / "web")
    monkeypatch.setattr(pdf_files, "CACHE_DIR", tmp_path / "cache")
    state = type("Site", (), {"pages": {}, "requests": 0})()

    def answer(request: httpx.Request) -> httpx.Response:
        state.requests += 1
        status, body = state.pages.get(str(request.url), (404, b"not found"))
        return httpx.Response(status, content=body)

    monkeypatch.setattr(pdf_files, "_client", httpx.Client(transport=httpx.MockTransport(answer)))
    return state


def _crawled(tmp_path, code: str, pdf_id: str):
    path = tmp_path / "web" / code / "pdf" / f"{pdf_id}.pdf"
    path.parent.mkdir(parents=True)
    path.write_bytes(PDF)
    return path


def test_crawled_copy_is_used(site, tmp_path):
    crawled = _crawled(tmp_path, "0115", "aa")
    assert pdf_files.pdf_path("pdf:0115:aa", "https://vallentuna.se/aa.pdf") == crawled


def test_crawled_copy_is_used_without_a_request(site, tmp_path):
    _crawled(tmp_path, "0115", "aa")
    pdf_files.pdf_path("pdf:0115:aa", "https://vallentuna.se/aa.pdf")
    assert site.requests == 0


def test_missing_pdf_is_downloaded_into_the_cache(site, tmp_path):
    site.pages["https://uppsala.se/plan.pdf"] = (200, PDF)
    path = pdf_files.pdf_path("pdf:0380:bb", "https://uppsala.se/plan.pdf")
    assert path == tmp_path / "cache" / "0380" / "bb.pdf"


def test_downloaded_pdf_holds_the_site_bytes(site):
    site.pages["https://uppsala.se/plan.pdf"] = (200, PDF)
    assert pdf_files.pdf_path("pdf:0380:bb", "https://uppsala.se/plan.pdf").read_bytes() == PDF


def test_missing_pdf_is_downloaded_once(site):
    site.pages["https://uppsala.se/plan.pdf"] = (200, PDF)
    pdf_files.pdf_path("pdf:0380:bb", "https://uppsala.se/plan.pdf")
    pdf_files.pdf_path("pdf:0380:bb", "https://uppsala.se/plan.pdf")
    assert site.requests == 1


FAILED_DOWNLOADS = pytest.mark.parametrize("status, body", [
    (404, b"not found"),                       # link moved
    (200, b"<html>Sidan finns inte</html>"),   # an error page answered 200
])


@FAILED_DOWNLOADS
def test_failed_download_gives_none(site, status, body):
    site.pages["https://uppsala.se/gone.pdf"] = (status, body)
    assert pdf_files.pdf_path("pdf:0380:cc", "https://uppsala.se/gone.pdf") is None


@FAILED_DOWNLOADS
def test_failed_download_caches_nothing(site, tmp_path, status, body):
    site.pages["https://uppsala.se/gone.pdf"] = (status, body)
    pdf_files.pdf_path("pdf:0380:cc", "https://uppsala.se/gone.pdf")
    cache = tmp_path / "cache" / "0380"
    assert not cache.exists() or not any(cache.iterdir())


def test_oversized_pdf_is_refused(site, monkeypatch):
    monkeypatch.setattr(pdf_files, "MAX_BYTES", 10)
    site.pages["https://uppsala.se/huge.pdf"] = (200, PDF)
    assert pdf_files.pdf_path("pdf:0380:dd", "https://uppsala.se/huge.pdf") is None


@pytest.fixture
def remote(monkeypatch):
    """The corpus database holds an OCR output for pdf:0380:scan only; `remote.asked` lists the doc_ids asked."""
    asked = []

    def answer(doc_id):
        asked.append(doc_id)
        return b'{"words": []}' if doc_id == "pdf:0380:scan" else None

    monkeypatch.setattr(pdf_files, "remote_ocr", answer)
    monkeypatch.setattr(pdf_files, "_no_ocr", set())
    return type("Remote", (), {"asked": asked})()


def test_ocr_output_from_the_corpus_database_is_cached(site, remote, tmp_path):
    path = pdf_files.ocr_path("pdf:0380:scan")
    assert path == tmp_path / "cache" / "0380" / "scan.ocr.json"


def test_cached_ocr_output_holds_the_database_bytes(site, remote):
    assert pdf_files.ocr_path("pdf:0380:scan").read_bytes() == b'{"words": []}'


def test_pdf_without_ocr_output_has_no_ocr_path(site, remote):
    assert pdf_files.ocr_path("pdf:0380:text") is None


def test_corpus_database_is_asked_once_per_pdf(site, remote):
    """A cached output and a remembered miss: the database is asked once for each."""
    for _ in range(2):
        pdf_files.ocr_path("pdf:0380:scan")
        pdf_files.ocr_path("pdf:0380:text")
    assert remote.asked == ["pdf:0380:scan", "pdf:0380:text"]


def _ocr_output(tmp_path, monkeypatch, output: dict) -> None:
    """A crawled OCR output for pdf:0380:scan."""
    path = tmp_path / "web" / "0380" / "ocr" / "scan.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(output), encoding="utf-8")


WORDS = [[0, 10, 20, 50, 30, "Plankarta", 0.99], [1, 100, 200, 140, 212, "Nockhöjd", 0.97],
         [1, 145, 200, 160, 212, "8", 0.95], [1, 165, 200, 175, 212, "m", 0.9]]


def test_ocr_words_are_those_of_the_asked_page(site, tmp_path, monkeypatch):
    _ocr_output(tmp_path, monkeypatch, {"pages": ["Plankarta", "Nockhöjd 8 m"], "words": WORDS})
    assert [text for _, text in pdf_files.ocr_words("pdf:0380:scan", 1)] == ["Nockhöjd", "8", "m"]


def test_ocr_words_carry_their_box_in_pdf_points(site, tmp_path, monkeypatch):
    _ocr_output(tmp_path, monkeypatch, {"pages": ["Plankarta", "Nockhöjd 8 m"], "words": WORDS})
    assert pdf_files.ocr_words("pdf:0380:scan", 1)[0][0] == pymupdf.Rect(100, 200, 140, 212)


def test_ocr_output_without_word_boxes_gives_no_words(site, tmp_path, monkeypatch):
    """EasyOCR outputs, from before 2026-10-23, hold page texts only."""
    _ocr_output(tmp_path, monkeypatch, {"engine": "easyocr sv+en", "pages": ["Plankarta"]})
    assert pdf_files.ocr_words("pdf:0380:scan", 0) is None


def test_pdf_without_ocr_output_gives_no_words(site):
    assert pdf_files.ocr_words("pdf:0380:text", 0) is None


@pytest.mark.parametrize("doc_id, url", [
    ("pdf:0380:ii", None),                         # no URL: nothing to download
    ("page:0380:jj", "https://uppsala.se/page"),   # not a crawled PDF
])
def test_nothing_to_download(site, doc_id, url):
    assert not pdf_files.needs_download(doc_id, url)


def test_needs_download_when_neither_crawled_nor_cached(site):
    """What the source viewer asks first, to say "downloading from the kommun's site" before the wait."""
    assert pdf_files.needs_download("pdf:0380:gg", "https://uppsala.se/gg.pdf")


def test_no_download_needed_once_cached(site):
    site.pages["https://uppsala.se/gg.pdf"] = (200, PDF)
    pdf_files.pdf_path("pdf:0380:gg", "https://uppsala.se/gg.pdf")
    assert not pdf_files.needs_download("pdf:0380:gg", "https://uppsala.se/gg.pdf")


def test_no_download_needed_when_crawled(site, tmp_path):
    _crawled(tmp_path, "0115", "hh")
    assert not pdf_files.needs_download("pdf:0115:hh", "https://vallentuna.se/hh.pdf")


@pytest.mark.parametrize("doc_id, url", [
    ("page:0380:ee", "https://uppsala.se/page"),   # a web page
    ("pdf:0380:ff", None),                         # no URL to fetch it from
])
def test_only_crawled_pdfs_have_a_file(site, doc_id, url):
    assert pdf_files.pdf_path(doc_id, url) is None


def test_looking_up_a_file_that_cannot_exist_makes_no_request(site):
    pdf_files.pdf_path("page:0380:ee", "https://uppsala.se/page")
    pdf_files.pdf_path("pdf:0380:ff", None)
    assert site.requests == 0


def test_only_crawled_pdfs_have_an_ocr_output(site):
    assert pdf_files.ocr_path("law:plan_och_bygglag") is None

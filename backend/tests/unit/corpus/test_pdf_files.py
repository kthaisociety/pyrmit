import httpx
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


def test_crawled_copy_is_used_without_a_request(site, tmp_path):
    crawled = tmp_path / "web" / "0115" / "pdf" / "aa.pdf"
    crawled.parent.mkdir(parents=True)
    crawled.write_bytes(PDF)
    assert pdf_files.pdf_path("pdf:0115:aa", "https://vallentuna.se/aa.pdf") == crawled
    assert site.requests == 0


def test_missing_pdf_is_downloaded_once_into_the_cache(site, tmp_path):
    site.pages["https://uppsala.se/plan.pdf"] = (200, PDF)
    path = pdf_files.pdf_path("pdf:0380:bb", "https://uppsala.se/plan.pdf")
    assert path == tmp_path / "cache" / "0380" / "bb.pdf" and path.read_bytes() == PDF
    assert pdf_files.pdf_path("pdf:0380:bb", "https://uppsala.se/plan.pdf") == path
    assert site.requests == 1


@pytest.mark.parametrize("status, body", [
    (404, b"not found"),                       # link moved
    (200, b"<html>Sidan finns inte</html>"),   # an error page answered 200
])
def test_failed_download_gives_none_and_caches_nothing(site, tmp_path, status, body):
    site.pages["https://uppsala.se/gone.pdf"] = (status, body)
    assert pdf_files.pdf_path("pdf:0380:cc", "https://uppsala.se/gone.pdf") is None
    assert not (tmp_path / "cache" / "0380").exists() or not any((tmp_path / "cache" / "0380").iterdir())


def test_oversized_pdf_is_refused(site, monkeypatch):
    monkeypatch.setattr(pdf_files, "MAX_BYTES", 10)
    site.pages["https://uppsala.se/huge.pdf"] = (200, PDF)
    assert pdf_files.pdf_path("pdf:0380:dd", "https://uppsala.se/huge.pdf") is None


def test_ocr_output_from_the_corpus_database_is_cached(site, tmp_path, monkeypatch):
    asked = []

    def remote(doc_id):
        asked.append(doc_id)
        return b'{"words": []}' if doc_id == "pdf:0380:scan" else None

    monkeypatch.setattr(pdf_files, "remote_ocr", remote)
    monkeypatch.setattr(pdf_files, "_no_ocr", set())
    path = pdf_files.ocr_path("pdf:0380:scan")
    assert path == tmp_path / "cache" / "0380" / "scan.ocr.json" and path.read_bytes() == b'{"words": []}'
    assert pdf_files.ocr_path("pdf:0380:scan") == path
    assert pdf_files.ocr_path("pdf:0380:text") is None and pdf_files.ocr_path("pdf:0380:text") is None
    assert asked == ["pdf:0380:scan", "pdf:0380:text"]  # cached output and remembered miss: asked once each


def test_only_crawled_pdfs_have_a_file(site):
    assert pdf_files.pdf_path("page:0380:ee", "https://uppsala.se/page") is None
    assert pdf_files.pdf_path("pdf:0380:ff", None) is None  # no URL to fetch it from
    assert pdf_files.ocr_path("law:plan_och_bygglag") is None
    assert site.requests == 0

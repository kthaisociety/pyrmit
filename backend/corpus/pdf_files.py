"""
Crawled PDFs and their OCR outputs as the serving code reads them (cited-source viewer, view_map_area,
view_pdf_page): the crawl folder's copy (corpus/raw/web), else a local cache filled on first use by downloading the
PDF from its original URL on the kommun's site. An install without the crawl folder (corpus on Neon, see
corpus.snapshot) thus still opens cited PDFs at the passage and lets the agent look at plankartor. OCR outputs exist
only where corpus.ocr ran.

    PDF_CACHE_DIR   cache folder, relative to backend/ (default data/cache/pdf)

OCR outputs come from the crawl folder, else from `remote_ocr` when a store holds them (localrag.pg_store sets it),
cached next to the PDFs.

A check on 65 random PDFs of Uppsala, Vallentuna and Stockholm (2026-10-31, crawl of 2026-10-23..26): all answered
with the crawled bytes, 0.2-1.1 s median, 14 s for the largest. Links will die as kommuner rework their sites: the
caller then gets None (the agent still has the chunk text).
"""

import logging
import os
import re
import ssl
import threading
from collections.abc import Callable
from pathlib import Path

import httpx
import truststore

from corpus.common import BACKEND_DIR, USER_AGENT, WEB_DIR

CACHE_DIR = BACKEND_DIR / os.getenv("PDF_CACHE_DIR", "data/cache/pdf")
MAX_BYTES = 40_000_000  # the crawler's cap per PDF, so every corpus PDF fits
TIMEOUT_S = 60
_DOC_ID = re.compile(r"pdf:(\d{4}):(\w+)")

log = logging.getLogger(__name__)
_client: httpx.Client | None = None
_locks: dict[Path, threading.Lock] = {}
_locks_guard = threading.Lock()
# doc_id -> corpus.ocr's JSON output (bytes), None when the PDF has none: set by a store that holds them
remote_ocr: Callable[[str], bytes | None] | None = None
_no_ocr: set[str] = set()  # doc_ids remote_ocr has no output for (most PDFs have a text layer)


def split_doc_id(doc_id: str | None) -> tuple[str, str] | None:
    """(kommun code, pdf id) of a crawled PDF's doc_id 'pdf:<code>:<id>', else None."""
    match = _DOC_ID.fullmatch(doc_id or "")
    return (match.group(1), match.group(2)) if match else None


def ocr_path(doc_id: str | None) -> Path | None:
    """corpus.ocr's output for a scanned PDF (page texts and word boxes), None when it has none."""
    parts = split_doc_id(doc_id)
    if parts is None:
        return None
    path = WEB_DIR / parts[0] / "ocr" / f"{parts[1]}.json"
    if path.exists():
        return path
    cached = CACHE_DIR / parts[0] / f"{parts[1]}.ocr.json"
    if cached.exists():
        return cached
    if remote_ocr is None or doc_id in _no_ocr:
        return None
    data = remote_ocr(doc_id)
    if not data:
        _no_ocr.add(doc_id)
        return None
    cached.parent.mkdir(parents=True, exist_ok=True)
    part = cached.with_suffix(".part")
    part.write_bytes(data)
    part.replace(cached)
    return cached


def pdf_path(doc_id: str | None, url: str | None) -> Path | None:
    """Local file of a crawled PDF: the crawl folder's copy, else the cached download of `url` (fetched now when
    missing). None when the doc_id is not a crawled PDF's or the download fails (site down, link moved)."""
    parts = split_doc_id(doc_id)
    if parts is None:
        return None
    code, pdf_id = parts
    crawled = WEB_DIR / code / "pdf" / f"{pdf_id}.pdf"
    if crawled.exists():
        return crawled
    cached = CACHE_DIR / code / f"{pdf_id}.pdf"
    if not cached.exists() and url:
        with _lock(cached):  # parallel tool calls on the same PDF download it once
            if not cached.exists():
                _download(url, cached)
    return cached if cached.exists() else None


def _lock(path: Path) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(path, threading.Lock())


def _http() -> httpx.Client:
    global _client
    if _client is None:
        # Same client settings as the crawler: Windows certificate store (Högsby), HTTP/2 (Malmö)
        _client = httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=TIMEOUT_S,
                               verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT), http2=True)
    return _client


def _download(url: str, target: Path) -> None:
    part = target.with_suffix(".part")
    try:
        with _http().stream("GET", url) as response:
            if response.status_code != 200:
                log.warning("PDF %s: HTTP %s", url, response.status_code)
                return
            body = bytearray()
            for block in response.iter_bytes():
                body += block
                if len(body) > MAX_BYTES:
                    log.warning("PDF %s: over %d bytes", url, MAX_BYTES)
                    return
        if not body.startswith(b"%PDF-"):  # an HTML error or login page answered 200
            log.warning("PDF %s: not a PDF (%s)", url, response.headers.get("content-type"))
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        part.write_bytes(body)
        part.replace(target)
    except (httpx.HTTPError, OSError) as error:
        log.warning("PDF %s: %s", url, error)

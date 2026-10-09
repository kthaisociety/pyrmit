"""
Open a cited chunk in its original document, for the clickable citations of the chat:

- GET /api/docs/locate?chunk_id=...  -> where to open it: a crawled PDF at the page holding the chunk, or the
  original web page / statute with a text fragment (#:~:text=...) that Chrome scrolls to and highlights
- GET /api/docs/pdf/{chunk_id}       -> that PDF with the chunk's text highlighted (PyMuPDF annotations)

The page is found by searching the chunk's wording in the PDF (chunks don't store page numbers); for scanned PDFs,
in the OCR text of each page (page only, no highlight).
"""

import json
import re
from functools import lru_cache
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from dependencies import get_current_user
import models

router = APIRouter()

WINDOW = 6          # words per searched phrase
MAX_SEARCHES = 80   # phrases searched per chunk


def _chunk(chunk_id: str) -> dict:
    from agentic.service import get_tools

    chunk = get_tools().get_chunk(chunk_id)
    if chunk is None:
        raise HTTPException(status_code=404, detail=f"Unknown chunk {chunk_id}")
    return chunk


def _pdf_path(chunk: dict):
    from corpus.common import WEB_DIR

    match = re.fullmatch(r"pdf:(\d{4}):(\w+)", chunk.get("doc_id") or "")
    if not match:
        return None, None
    path = WEB_DIR / match.group(1) / "pdf" / f"{match.group(2)}.pdf"
    ocr = WEB_DIR / match.group(1) / "ocr" / f"{match.group(2)}.json"
    return (path if path.exists() else None), (ocr if ocr.exists() else None)


def _phrases(text: str) -> list[str]:
    """Consecutive WINDOW-word phrases of each paragraph (search units robust to line wraps and hyphenation)."""
    phrases = []
    for paragraph in re.split(r"\n\s*\n|\n", text):
        words = [w for w in paragraph.split() if w.strip("•–-")]
        for start in range(0, max(len(words) - WINDOW + 1, 1), WINDOW):
            phrase = " ".join(words[start:start + WINDOW])
            if len(phrase) >= 12:
                phrases.append(phrase)
    return phrases[:MAX_SEARCHES]


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


@lru_cache(maxsize=256)
def _pdf_page(chunk_id: str) -> int | None:
    """0-based page whose text holds most of the chunk's phrases (OCR text for scanned PDFs)."""
    import pymupdf

    chunk = _chunk(chunk_id)
    path, ocr = _pdf_path(chunk)
    if path is None:
        return None
    phrases = [_norm(p) for p in _phrases(chunk["text"])]
    if ocr is not None and len(chunk["text"]) > 0:
        pages = [_norm(p) for p in json.loads(ocr.read_text(encoding="utf-8"))["pages"]]
    else:
        with pymupdf.open(path) as pdf:
            pages = [_norm(page.get_text()) for page in pdf]
    scores = [sum(phrase in page for phrase in phrases) for page in pages]
    if not scores or max(scores) == 0:
        # Phrase hits fail on rejoined hyphenation: fall back to shared rare words
        words = {w for w in _norm(chunk["text"]).split() if len(w) > 6}
        scores = [len(words & set(page.split())) for page in pages]
    best = max(range(len(scores)), key=scores.__getitem__) if scores else None
    return best if best is not None and scores[best] > 0 else None


def _highlight(pdf, page_index: int, text: str) -> list:
    """Highlight the chunk's phrases on its page (and the next one, where it may continue); the found rects."""
    rects = []
    for index in (page_index, page_index + 1):
        if index >= len(pdf):
            break
        page = pdf[index]
        for phrase in _phrases(text):
            quads = page.search_for(phrase, quads=True)
            if quads:
                page.add_highlight_annot(quads)
                if index == page_index:
                    rects += [quad.rect for quad in quads]
    return rects


@lru_cache(maxsize=256)
def _view(chunk_id: str) -> dict | None:
    """Zoom on the highlighted passage: Adobe/Chrome open parameters #zoom=scale,left,top (PDF points, origin
    bottom-left). Large plankartor open at ~13 % otherwise, with the highlight invisible."""
    import pymupdf

    chunk = _chunk(chunk_id)
    path, ocr = _pdf_path(chunk)
    page_index = _pdf_page(chunk_id)
    if path is None or ocr is not None or page_index is None:
        return None
    with pymupdf.open(path) as pdf:
        rects = _highlight(pdf, page_index, chunk["text"])
        page = pdf[page_index].rect
    if not rects:
        return None
    box = rects[0]
    for rect in rects[1:]:
        box |= rect
    margin = 40
    width = max(box.width + 2 * margin, 300)
    # Viewer ~780 px wide, 1 pt = 1.333 px at 100 %: fit the passage's width, never below the page fit nor above 400 %
    fit = 780 / 1.333 * 100
    scale = round(min(max(fit / width, fit / page.width), 400))
    return {"zoom": scale, "left": round(max(box.x0 - margin, 0)), "top": round(page.height - max(box.y0 - margin, 0))}


def _text_fragment(url: str, text: str) -> str:
    """URL with a #:~:text= fragment on the chunk's first sentence-like run of words."""
    for line in text.splitlines():
        words = line.split()
        if len(words) >= 5:
            # Exact consecutive text; "-", "," and "&" are syntax in text directives, so percent-encoded
            phrase = " ".join(words[:8]).rstrip(".,;:")
            return f"{url}#:~:text={quote(phrase, safe='').replace('-', '%2D')}"
    return url


@router.get("/docs/locate")
def locate(chunk_id: str = Query(...), _user: models.User = Depends(get_current_user)):
    chunk = _chunk(chunk_id)
    base = {"chunk_id": chunk_id, "title": chunk.get("title"), "kommun": chunk.get("kommun"),
            "section": chunk.get("section"), "source_url": chunk.get("url")}
    path, ocr = _pdf_path(chunk)
    if path is not None:
        page = _pdf_page(chunk_id)
        view = _view(chunk_id)
        return {**base, "type": "pdf", "page": (page or 0) + 1, "found": page is not None,
                "highlighted": view is not None, "view": view, "pdf_url": f"/api/docs/pdf/{chunk_id}"}
    if chunk.get("url"):
        text = chunk["text"]
        if chunk.get("kind") == "law":  # the statute page: aim at the section's own wording
            text = re.sub(r"^\s*\d+\s*[a-z]?\s*§\s*", "", text)
        return {**base, "type": "url", "url": _text_fragment(chunk["url"], text)}
    return {**base, "type": "none"}


@router.get("/docs/pdf/{chunk_id}")
def pdf_with_highlight(chunk_id: str, _user: models.User = Depends(get_current_user)):
    import pymupdf

    chunk = _chunk(chunk_id)
    path, ocr = _pdf_path(chunk)
    if path is None:
        raise HTTPException(status_code=404, detail="No PDF for this chunk")
    page_index = _pdf_page(chunk_id)
    with pymupdf.open(path) as pdf:
        if page_index is not None and ocr is None:
            _highlight(pdf, page_index, chunk["text"])
        data = pdf.tobytes()
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{chunk_id}.pdf"'})

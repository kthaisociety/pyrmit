"""Acceptance tests of issue #83: a citation into a scanned PDF opens at the page that holds the passage, zoomed on
it and highlighted, located through the word positions corpus.ocr stored (no real corpus, PDF download or OCR run,
PCR-0011)."""

import json
import sys
from itertools import count
from types import SimpleNamespace

import pymupdf
import pytest

import corpus.pdf_files
from routers import docs

PASSAGE = "Byggnader får uppföras till en högsta nockhöjd av åtta meter över mark"
# Where the OCR read the passage on the scan's second page (PDF points, unrotated page, origin top-left)
LINE = (100.0, 500.0, 480.0, 514.0)
PAGE_SIZE = (595, 842)
_ids = count()


def _scan(path) -> None:
    """A three-page PDF with no text layer, as a scanned plan has: only a drawn shape on each page."""
    pdf = pymupdf.open()
    for _ in range(3):
        page = pdf.new_page(width=PAGE_SIZE[0], height=PAGE_SIZE[1])
        page.draw_rect(pymupdf.Rect(50, 50, 545, 792))
    pdf.save(path)


def _ocr_words(page: int, text: str, line: tuple) -> list[list]:
    """corpus.ocr's word list for one printed line: [page, x0, y0, x1, y1, text, score] per word."""
    x0, y0, x1, y1 = line
    words = text.split()
    step = (x1 - x0) / len(words)
    return [[page, round(x0 + i * step, 1), y0, round(x0 + (i + 1) * step - 4, 1), y1, word, 0.98]
            for i, word in enumerate(words)]


@pytest.fixture
def scanned(tmp_path, monkeypatch):
    """A cited chunk of a scanned PDF whose OCR output holds `PASSAGE` on page 2; returns the chunk id."""
    pdf_file = tmp_path / "scan.pdf"
    _scan(pdf_file)
    ocr = {"engine": "rapid-v6-medium", "text_from": "words", "word_coordinates": "pdf points, unrotated page",
           "pages": ["PLANBESTÄMMELSER", f"Utformning\n{PASSAGE}", "Genomförandetid"],
           "words": _ocr_words(0, "PLANBESTÄMMELSER", (200, 80, 400, 96)) + _ocr_words(1, PASSAGE, LINE)}
    ocr_file = tmp_path / "scan.json"
    ocr_file.write_text(json.dumps(ocr, ensure_ascii=False), encoding="utf-8")

    chunk_id = f"scan-{next(_ids)}"  # locate caches per chunk id: a fresh one per test
    chunk = {"chunk_id": chunk_id, "doc_id": "pdf:0115:aa", "url": "https://www.vallentuna.se/plan.pdf",
             "kind": "plan", "title": "Detaljplan Kårsta", "text": PASSAGE}
    tools = SimpleNamespace(get_chunk=lambda cid: chunk if cid == chunk_id else None)
    monkeypatch.setitem(sys.modules, "agentic.service", SimpleNamespace(get_tools=lambda: tools))
    monkeypatch.setattr(corpus.pdf_files, "pdf_path", lambda doc_id, url: pdf_file)
    monkeypatch.setattr(corpus.pdf_files, "ocr_path", lambda doc_id: ocr_file)
    return chunk_id


def test_scanned_pdf_opens_with_the_passage_highlighted(scanned):
    """locate says a scanned PDF's cited passage is highlighted, as it does for a text PDF."""
    location = docs.locate(chunk_id=scanned, download=True, _user=None)
    assert location["page"] == 2
    assert location["highlighted"] is True


def test_scanned_pdf_opens_zoomed_on_the_passage(scanned):
    """locate gives a scanned PDF a zoom whose top-left corner sits just above and left of the passage's OCR words."""
    view = docs.locate(chunk_id=scanned, download=True, _user=None)["view"]
    assert view is not None
    x0, y0 = LINE[0], LINE[1]
    assert view["left"] <= x0
    # #zoom's top is measured from the page bottom: the passage's top edge is below it, within one line or so
    top_from_page_top = PAGE_SIZE[1] - view["top"]
    assert top_from_page_top <= y0
    assert y0 - top_from_page_top <= 100


def test_scanned_pdf_is_served_with_a_highlight_over_the_passage(scanned):
    """The served scanned PDF carries a highlight on the cited page that covers the passage's OCR word boxes."""
    response = docs.pdf_with_highlight(chunk_id=scanned, _user=None)
    with pymupdf.open(stream=response.body, filetype="pdf") as pdf:
        highlights = [annot.rect for annot in pdf[1].annots() if annot.type[1] == "Highlight"]
    assert highlights
    covered = highlights[0]
    for rect in highlights[1:]:
        covered |= rect
    assert covered.intersects(pymupdf.Rect(*LINE))
    assert covered.x0 <= LINE[0] + 5 and covered.x1 >= LINE[2] - 5


def test_scanned_pdf_highlight_stays_off_the_other_pages(scanned):
    """The served scanned PDF has no highlight on a page that does not hold the passage."""
    response = docs.pdf_with_highlight(chunk_id=scanned, _user=None)
    with pymupdf.open(stream=response.body, filetype="pdf") as pdf:
        assert list(pdf[1].annots())  # the cited page is highlighted ...
        assert not list(pdf[0].annots())  # ... and the page before it is not

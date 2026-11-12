"""Opening a cited chunk of a scanned PDF: the page that holds it, zoomed on it and highlighted on the word boxes
corpus.ocr stored. A three-page PDF with no text layer and a fake OCR output stand in for the corpus (PCR-0011)."""

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
LINE = pymupdf.Rect(100.0, 500.0, 480.0, 514.0)
PAGE_SIZE = (595, 842)
PAGE_TEXTS = ["PLANBESTÄMMELSER", f"Utformning\n{PASSAGE}", "Genomförandetid"]
_ids = count()


def _ocr_line(page: int, text: str, line: pymupdf.Rect) -> list[list]:
    """corpus.ocr's words of one printed line: [page, x0, y0, x1, y1, text, score] per word."""
    words = text.split()
    step = line.width / len(words)
    return [[page, round(line.x0 + i * step, 1), line.y0, round(line.x0 + (i + 1) * step - 4, 1), line.y1, word, 0.98]
            for i, word in enumerate(words)]


def _serve(tmp_path, monkeypatch, ocr: dict) -> str:
    """Serve a scanned three-page PDF and `ocr` as the original of a fresh cited chunk holding PASSAGE; its id."""
    pdf = pymupdf.open()
    for _ in PAGE_TEXTS:
        pdf.new_page(width=PAGE_SIZE[0], height=PAGE_SIZE[1]).draw_rect(pymupdf.Rect(50, 50, 545, 792))
    pdf_file = tmp_path / "scan.pdf"
    pdf.save(pdf_file)
    ocr_file = tmp_path / "scan.json"
    ocr_file.write_text(json.dumps(ocr, ensure_ascii=False), encoding="utf-8")

    chunk_id = f"scan-{next(_ids)}"  # locate caches per chunk id
    chunk = {"chunk_id": chunk_id, "doc_id": "pdf:0115:aa", "url": "https://www.vallentuna.se/plan.pdf",
             "kind": "plan", "title": "Detaljplan Kårsta", "text": PASSAGE}
    tools = SimpleNamespace(get_chunk=lambda wanted: chunk if wanted == chunk_id else None)
    monkeypatch.setitem(sys.modules, "agentic.service", SimpleNamespace(get_tools=lambda: tools))
    monkeypatch.setattr(corpus.pdf_files, "pdf_path", lambda doc_id, url: pdf_file)
    monkeypatch.setattr(corpus.pdf_files, "ocr_path", lambda doc_id: ocr_file)
    return chunk_id


@pytest.fixture
def scanned(tmp_path, monkeypatch):
    """A cited chunk of a scanned PDF whose PP-OCRv6 output holds PASSAGE, with word boxes, on page 2."""
    words = _ocr_line(0, "PLANBESTÄMMELSER", pymupdf.Rect(200, 80, 400, 96)) + _ocr_line(1, PASSAGE, LINE)
    return _serve(tmp_path, monkeypatch, {"engine": "rapid-v6-medium", "text_from": "words",
                                          "pages": PAGE_TEXTS, "words": words})


@pytest.fixture
def scanned_without_positions(tmp_path, monkeypatch):
    """The same chunk, but its OCR output (EasyOCR, before 2026-10-23) has page texts and no word boxes."""
    return _serve(tmp_path, monkeypatch, {"engine": "easyocr sv+en", "dpi": 200, "pages": PAGE_TEXTS})


def _locate(chunk_id: str) -> dict:
    return docs.locate(chunk_id=chunk_id, download=True, _user=None)


def _highlighted_area(chunk_id: str, page_index: int) -> pymupdf.Rect | None:
    """The union of the highlights on one page of the PDF served for `chunk_id`, None when it has none."""
    with pymupdf.open(stream=docs.pdf_with_highlight(chunk_id=chunk_id, _user=None).body, filetype="pdf") as pdf:
        area = None
        for annot in pdf[page_index].annots():
            if annot.type[1] == "Highlight":
                area = annot.rect if area is None else area | annot.rect
        return area


def test_scanned_pdf_opens_at_the_page_holding_the_passage(scanned):
    assert _locate(scanned)["page"] == 2


def test_scanned_pdf_opens_with_the_passage_highlighted(scanned):
    """A scanned PDF's passage is highlighted, as a text PDF's is."""
    assert _locate(scanned)["highlighted"] is True


def test_scanned_pdf_zoom_starts_left_of_the_passage(scanned):
    assert _locate(scanned)["view"]["left"] <= LINE.x0


def test_scanned_pdf_zoom_starts_just_above_the_passage(scanned):
    """#zoom's top is measured from the page bottom: the passage starts within about a line below it."""
    top_from_page_top = PAGE_SIZE[1] - _locate(scanned)["view"]["top"]
    assert 0 <= LINE.y0 - top_from_page_top <= 100


def test_served_scanned_pdf_highlights_the_passage_line(scanned):
    assert _highlighted_area(scanned, 1).intersects(LINE)


def test_served_scanned_pdf_highlight_spans_the_passage(scanned):
    area = _highlighted_area(scanned, 1)
    assert area.x0 <= LINE.x0 + 5 and area.x1 >= LINE.x1 - 5


def test_served_scanned_pdf_leaves_the_other_pages_unmarked(scanned):
    assert _highlighted_area(scanned, 0) is None


def test_scanned_pdf_without_word_positions_opens_at_the_cited_page(scanned_without_positions):
    assert _locate(scanned_without_positions)["page"] == 2


def test_scanned_pdf_without_word_positions_opens_without_highlight(scanned_without_positions):
    assert _locate(scanned_without_positions)["highlighted"] is False

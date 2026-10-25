"""OCR benchmark scoring: bag-of-words recall with near misses, property labels, words at the right place, tiles."""

from corpus.ocr_bench import located, norm, word_scores
import numpy as np

from corpus.ocr_engines import ocr_image, reading_order, split_line, tiles


def test_word_scores():
    reference = "Högsta byggnadshöjd 7,5 meter på fastigheten 3:226 (BÖ II)".split()
    predicted = "Hogsta byggnadshöjd 7,5 meter pa fastigheten 3:226 BÖ II extra".split()
    scores = word_scores(reference, predicted)
    assert scores["ref_words"] == 9 and scores["pred_words"] == 10
    assert scores["exact"] == 7  # "Hogsta" and "pa" are misread
    assert scores["near"] == 8  # "hogsta" is one edit from "högsta"; "pa" is too short for a near miss
    assert scores["labels"] == scores["labels_found"] == 1
    assert norm("(BÖ") == "bö" and norm("3:226,") == "3:226"


def test_located():
    reference = [[0, 0, 40, 10, "5:125"], [100, 0, 140, 10, "e1"]]
    predicted = [[2, 1, 41, 11, "5:125"], [300, 0, 340, 10, "e1"]]  # e1 read, but elsewhere
    assert located(reference, predicted) == (1, 1)


def test_tiles_cover_without_duplicates():
    cores = [core for _, _, core in tiles(5000, 3000, 2000, 200)]
    # Every pixel centre belongs to exactly one core
    for x, y in [(0, 0), (1899, 10), (1900, 10), (2999, 4999), (1000, 1850)]:
        assert sum(c[0] <= x < c[2] and c[1] <= y < c[3] for c in cores) == 1


def test_reading_order():
    lines = [[300, 52, 400, 70, "höger"], [0, 50, 100, 68, "vänster"], [0, 100, 200, 118, "nästa rad"]]
    assert reading_order(lines) == "vänster höger\nnästa rad"


def test_split_line():
    words = split_line([[0, 0], [100, 0], [100, 10], [0, 10]], "ab cd", 0.9)
    assert [w[4] for w in words] == ["ab", "cd"] and words[0][2] == 40 and words[1][0] == 60


def test_line_cut_by_a_tile_edge():
    """One printed line from x=1500 to 2700 crosses the edge of the first tile (0-2000; the second starts at 1800,
    cores split at 1900): each tile reads it cut, "bestämmelsen" read "bestämm" in the first (centre 1890) and
    "stämmelsen" in the second (centre 1930). Before, both lines were kept whole; now each word once, the cut word
    glued."""
    page = [(1500, 1600, "Där"), (1620, 1760, "gäller"), (1780, 2060, "bestämmelsen"), (2080, 2200, "inom"),
            (2220, 2700, "planområdet")]

    def run(image):  # the words of the line visible in the tile (one line, number 0), cut at its edges
        left, width = (0, 2000) if image.shape[1] == 2000 else (1800, image.shape[1])
        words = []
        for x0, x1, text in page:
            if x1 > left and x0 < left + width:
                text = text[:7] if x1 > left + width else text[2:] if x0 < left else text
                words.append([max(x0, left) - left, 100, min(x1, left + width) - left, 130, text, 1.0, 0])
        return words, [], "native"

    words, lines, _ = ocr_image(run, np.zeros((1000, 3000, 3), np.uint8), 2000, 200)
    assert reading_order(lines) == "Där gäller bestämmelsen inom planområdet"
    assert sum(w[4] == "inom" for w in words) == 1


def test_new_process_when_gpu_memory_is_high(tmp_path, monkeypatch):
    """The worker exits with RECYCLE_EXIT after a document once the card's memory passes --recycle-gpu-mb (not before
    RECYCLE_MIN_PAGES pages); corpus.ocr then starts a fresh process, which skips the outputs already written."""
    import json
    from types import SimpleNamespace

    import pytest

    from corpus import ocr_engines

    jobs = tmp_path / "jobs.jsonl"
    jobs.write_text("".join(json.dumps({"pdf": f"{i}.pdf", "out": str(tmp_path / f"{i}.json")}) + "\n" for i in range(3)))
    monkeypatch.setattr(ocr_engines, "ocr_pdf", lambda *a: {"pages": ["text"] * 15, "words": []})
    monkeypatch.setattr(ocr_engines, "gpu_memory_used_mb", lambda: 7000)
    args = SimpleNamespace(jobs=str(jobs), shard="0/1", dpi=300, map_dpi=200, tile=2000, overlap=200, recycle_pages=250,
                           recycle_gpu_mb=6500)
    with pytest.raises(SystemExit) as stop:
        ocr_engines.run_jobs(None, "rapid-v6-medium", args)
    assert stop.value.code == ocr_engines.RECYCLE_EXIT
    assert [(tmp_path / f"{i}.json").exists() for i in range(3)] == [True, True, False]  # 15 pages, then 30 > 20

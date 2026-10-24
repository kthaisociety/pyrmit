"""OCR benchmark scoring: bag-of-words recall with near misses, property labels, words at the right place, tiles."""

from corpus.ocr_bench import located, norm, word_scores
from corpus.ocr_engines import reading_order, split_line, tiles


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

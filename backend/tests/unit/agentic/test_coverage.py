"""Coverage benchmark: why a plan PDF listed by the kommun is missing from the corpus, from its crawl manifest; a
copy of a corpus PDF under another URL counts as found."""

from pathlib import Path

from agentic.coverage import CAUSES, kept_copy, missing_cause
from corpus.crawl import url_key

LIST = "https://k.se/detaljplaner/gallande-detaljplaner"
CRAWL = {"pages": {url_key(LIST), url_key(LIST + "/torget")},
         "pdfs": {url_key("https://k.se/download/1/Plankarta.pdf"): Path("a1.pdf"),
                  url_key("https://k.se/download/2/PB.pdf"): Path("b2.pdf")},
         "skipped": {url_key("https://k.se/download/3/Arsredovisning.pdf")}}


def cause(url, plan_url):
    return missing_cause([url_key(url)], plan_url, "0999", CRAWL, dropped={"pdf:0999:b2"})


def test_missing_causes():
    assert cause("https://k.se/download/1/Plankarta.pdf", LIST + "/torget") == "not_extracted"
    assert cause("https://k.se/download/2/PB.pdf", LIST + "/torget") == "filtered"
    assert cause("https://k.se/download/3/Arsredovisning.pdf", LIST + "/torget") == "skipped"
    assert cause("https://k.se/download/4/Lagakraftbevis.pdf", LIST + "/torget") == "link_not_taken"
    assert cause("https://k.se/media/x/1507-280-torsberg.pdf", None) == "link_not_taken"  # linked from the list page
    assert cause("https://k.se/download/5/Beskrivning.pdf", LIST + "/hamnen") == "page_not_crawled"
    assert set(CAUSES) == {"page_not_crawled", "link_not_taken", "skipped", "filtered", "not_extracted"}


def test_a_copy_under_another_url_is_found(tmp_path):
    kept, copy, other = tmp_path / "kept.pdf", tmp_path / "copy.pdf", tmp_path / "other.pdf"
    kept.write_bytes(b"%PDF plankarta")
    copy.write_bytes(b"%PDF plankarta")
    other.write_bytes(b"%PDF plankartb")  # same size, other content
    crawl = {"pdfs": {"k.se/a": copy, "k.se/b": other}, "kept": {len(b"%PDF plankarta"): [kept]}}
    assert kept_copy(["k.se/a"], crawl) and not kept_copy(["k.se/b"], crawl) and not kept_copy(["k.se/c"], crawl)

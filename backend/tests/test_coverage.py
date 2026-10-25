"""Coverage benchmark: why a plan PDF listed by the kommun is missing from the corpus, from its crawl manifest."""

from agentic.coverage import CAUSES, missing_cause
from corpus.crawl import url_key

LIST = "https://k.se/detaljplaner/gallande-detaljplaner"
CRAWL = {"pages": {url_key(LIST), url_key(LIST + "/torget")},
         "pdfs": {url_key("https://k.se/download/1/Plankarta.pdf"): "a1", url_key("https://k.se/download/2/PB.pdf"): "b2"},
         "skipped": {url_key("https://k.se/download/3/Arsredovisning.pdf")}}


def cause(url, plan_url):
    return missing_cause([url_key(url)], plan_url, "0999", CRAWL, dropped={"pdf:0999:b2"})


def test_missing_causes():
    assert cause("https://k.se/download/1/Plankarta.pdf", LIST + "/torget") == "copy"  # downloaded, not a document
    assert cause("https://k.se/download/2/PB.pdf", LIST + "/torget") == "filtered"
    assert cause("https://k.se/download/3/Arsredovisning.pdf", LIST + "/torget") == "skipped"
    assert cause("https://k.se/download/4/Lagakraftbevis.pdf", LIST + "/torget") == "link_not_taken"
    assert cause("https://k.se/media/x/1507-280-torsberg.pdf", None) == "link_not_taken"  # linked from the list page
    assert cause("https://k.se/download/5/Beskrivning.pdf", LIST + "/hamnen") == "page_not_crawled"
    assert set(CAUSES) == {"page_not_crawled", "link_not_taken", "skipped", "copy", "filtered"}

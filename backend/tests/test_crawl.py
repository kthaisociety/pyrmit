"""Crawler helpers: robots.txt wildcards, URL keys, off-topic PDFs, tolerant sitemaps."""

import gzip

from corpus.crawl import _SITE_INDEX, fold, link_relevance, off_topic_pdf, parse_sitemap, robots_parser, url_key

AGENT = "PyrmitCorpusBuilder/0.1"


def test_robots_wildcards():
    parser = robots_parser("User-agent: *\nDisallow: /*.html.printable\nDisallow: /*?sv.state=*\nDisallow: /bd$\n"
                           "Allow: /x/y\nDisallow: /x\n")
    assert parser.can_fetch(AGENT, "https://a.se/bygga/bygglov.html")
    assert not parser.can_fetch(AGENT, "https://a.se/bygga/bygglov.html.printable")
    assert not parser.can_fetch(AGENT, "https://a.se/sida?sv.state=1")
    assert not parser.can_fetch(AGENT, "https://a.se/bd") and parser.can_fetch(AGENT, "https://a.se/bdx")
    assert parser.can_fetch(AGENT, "https://a.se/x/y") and not parser.can_fetch(AGENT, "https://a.se/x/z")


def test_url_key_merges_scheme_and_www():
    assert url_key("http://www.essunga.se/download/a.pdf") == url_key("https://essunga.se/download/a.pdf#page=2")
    assert url_key("https://a.se/p?id=1") != url_key("https://a.se/p?id=2")
    page = "https://heby.se/detaljplaner/dp-405"
    assert url_key(page + "?open.12_4c7cc5c917a1d92c1eafbc=true") == url_key(page) == url_key(page + ".printable")
    assert url_key(page + "?sv.url=12.4a4c43&state=showSendMessage") == url_key(page)


def test_off_topic_pdf():
    assert off_topic_pdf("Årsredovisning 2024")
    assert off_topic_pdf("https://x.se/Anm%C3%A4lan%20om%20hygienisk%20verksamhet.pdf")
    assert not off_topic_pdf("Detaljplan för vårdboende (hemtjanst)")
    # Only the obvious: meeting packs, waste and budgets may hold planning facts (left to corpus.pdf_filter)
    assert not off_topic_pdf("Kallelse MSN 2024-12-11", "Beslut om planuppdrag")
    assert not off_topic_pdf("Riktlinjer för avfallsutrymmen")
    assert not off_topic_pdf("Taxa för bygglov 2026")
    assert not off_topic_pdf("Plankarta Kumla 1:2")
    # The section of the URL does not count, only its file name
    assert not off_topic_pdf("https://www.nacka.se/globalassets/nackavattenavfall/dokument/va/ansokan-anslutning.pdf",
                             "Ansökan om anslutning till kommunalt vatten")
    assert off_topic_pdf("https://x.se/dokument/arsredovisning-2026.pdf")


def test_sitemap_with_bad_byte_and_gzip():
    xml = (b'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
           b"<url><loc>https://a.se/\xb4n.html</loc></url><url><loc>https://a.se/bygglov.html</loc></url></urlset>")
    for content in (xml, gzip.compress(xml)):
        assert [loc.text for loc in parse_sitemap(content).iter("{*}loc")][-1] == "https://a.se/bygglov.html"


def test_link_text_with_a_negative_word():
    # Surahammar's home card: the section is on topic although its description lists "livsmedel"
    card = ("Bygg, miljö och boende Bygglov, vägar, boende, stadsutveckling, detaljplaner, vatten, avlopp, felanmälan, "
            "tomter, livsmedel, hälsoskydd, miljöskydd, strandskydd, naturvård")
    assert link_relevance("/bygg-miljo-och-boende.html", card) > 0
    assert link_relevance("/nyheter/ny-detaljplan.html", "Ny detaljplan") < 0  # a negative path still excludes
    assert link_relevance("/tillstand.html", "Alkohol och tobak") < 0


def test_site_index_links():
    assert all(_SITE_INDEX.match(fold(text)) for text in ("Webbkarta", "A-Ö", "Sitemap", "Innehåll A-Ö"))
    assert not _SITE_INDEX.match(fold("Bygga, bo och miljö"))

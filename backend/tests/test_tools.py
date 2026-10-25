"""Agent tools on a fake corpus: ids as the model writes them, section formats, grep filters; law chapter chunking."""

from types import SimpleNamespace

import pytest

from agentic import tools as T
from corpus.chunk import law_chunks

CHUNKS = {
    "a1cbd51fb395f18a": {"chunk_id": "a1cbd51fb395f18a", "doc_id": "pdf:0115:9f7dbdbeeb1b2010", "header": "", "text": "first", "kind": "pdf"},
    "b2cbd51fb395f18a": {"chunk_id": "b2cbd51fb395f18a", "doc_id": "pdf:0115:9f7dbdbeeb1b2010", "header": "", "text": "second", "kind": "pdf"},
}


class FakeCorpus:
    def chunk(self, chunk_id):
        return CHUNKS.get(chunk_id)

    def ids_with_prefix(self, prefix, limit=2):
        return [c for c in CHUNKS if c.startswith(prefix)][:limit]

    def doc(self, doc_id):
        return {"doc_id": doc_id, "title": "Planbeskrivning", "kommun": "Vallentuna", "doc_type": "detaljplan",
                "url": None} if doc_id == "pdf:0115:9f7dbdbeeb1b2010" else None

    def doc_ids_ending(self, suffix, limit=2):
        return ["pdf:0115:9f7dbdbeeb1b2010"] if "pdf:0115:9f7dbdbeeb1b2010".endswith(":" + suffix) else []

    def doc_chunk_ids(self, doc_id):
        return list(CHUNKS) if doc_id == "pdf:0115:9f7dbdbeeb1b2010" else []

    def grep(self, regex, scope, codes, limit):
        raise AssertionError("grep must not reach the corpus without a filter")


@pytest.fixture
def tools():
    instance = T.CorpusTools.__new__(T.CorpusTools)
    instance.corpus = FakeCorpus()
    instance.retriever = SimpleNamespace(places=SimpleNamespace(detect=lambda place: []))
    return instance


@pytest.mark.parametrize("chunk_id", ["a1cbd51fb395f18a", "c:a1cbd51fb395f18a", "[c:a1cbd51fb395f18a]", "a1cbd51f",
                                      "pdf:0115:9f7dbdbeeb1b2010", "0115:9f7dbdbeeb1b2010",
                                      "c:9f7dbdbeeb1b2010", "doc pdf:0115:9f7dbdbeeb1b2010",
                                      "doc:pdf:0115:9f7dbdbeeb1b2010",  # agentic.replay 2026-10-25
                                      "page:0115:a1cbd51fb395f18a"])  # a chunk id glued to a doc prefix
def test_read_accepts_ids_as_written(tools, chunk_id):
    assert tools.read(chunk_id=chunk_id).chunk_ids == list(CHUNKS)


def test_read_doc_id_as_written(tools):
    for doc_id in ("doc pdf:0115:9f7dbdbeeb1b2010", "(doc pdf:0115:9f7dbdbeeb1b2010)", "c:a1cbd51fb395f18a"):
        assert tools.read(doc_id=doc_id).chunk_ids == list(CHUNKS), doc_id


@pytest.mark.parametrize("chunk_id", ["c:page0115:9f7dbdbeeb1b2010", "c6c0157249a0f646", "a4"])
def test_read_falls_back_on_the_doc_id(tools, chunk_id):
    # a stale or invented chunk id next to a valid doc_id (forms found by agentic.replay in stored runs)
    result = tools.read(chunk_id=chunk_id, doc_id="pdf:0115:9f7dbdbeeb1b2010")
    assert result.chunk_ids == list(CHUNKS) and not result.error


def test_read_doc_id_without_prefix_and_past_the_end(tools):
    assert tools.read(doc_id="0115:9f7dbdbeeb1b2010").chunk_ids == list(CHUNKS)
    out = tools.read(doc_id="pdf:0115:9f7dbdbeeb1b2010", start=99)
    assert out.chunk_ids == [] and "past the end" in out.text
    assert tools.read(chunk_id="nope").text.startswith("Unknown chunk_id")


@pytest.mark.parametrize("raw, normalized", [
    ("9 kap. 4 §", "9 kap. 4 §"), ("9 kap 4§", "9 kap. 4 §"), ("9:4", "9 kap. 4 §"), ("9 kap. 4a §", "9 kap. 4 a §"),
    ("7 kap. 18 c § punkt 1", "7 kap. 18 c §"), ("13 §", "13 §"), ("6a kap. 2 §", "6 a kap. 2 §"),
    ("2 kap. 3 § första stycket", "2 kap. 3 §"), ("9 kap. 4 a", "9 kap. 4 a §"),
])
def test_normalize_section(raw, normalized):
    assert T.normalize_section(raw) == normalized


def test_grep_needs_a_filter(tools):
    assert "needs a kommun" in tools.grep("nockhöjd").text
    assert "Unknown kommun" in tools.grep("nockhöjd", kommun="Atlantis").text


def _doc_chunks(doc, doc_type, title, texts, kommun_code="0115"):
    return [{"chunk_id": f"{doc}{i:02d}".ljust(16, "0"), "doc_id": f"pdf:{kommun_code}:{doc}", "kind": "pdf",
             "doc_type": doc_type, "title": title, "kommun": "Vallentuna", "kommun_code": kommun_code, "url": None,
             "header": "", "text": text, "chunk_index": i} for i, text in enumerate(texts)]


@pytest.fixture
def memory_tools():
    chunks = (_doc_chunks("aa", "detaljplan", "Planbeskrivning Kårsta", ["Högsta nockhöjd 7 meter", "nockhöjd 5 meter", "x"])
              + _doc_chunks("bb", "oversiktsplan", "Översiktsplan 2040", ["Ny bebyggelse, nockhöjd anpassas"])
              + _doc_chunks("cc", "taxa", "Taxa bygglov", ["avgift 5000 kronor"])
              + [{"chunk_id": "ffff000000000001", "doc_id": "law:pbl", "kind": "law", "title": "Plan- och bygglag",
                  "header": "", "text": "nockhöjd i lagen", "section": "1 kap. 4 §", "chunk_index": 0}])
    instance = T.CorpusTools.__new__(T.CorpusTools)
    instance.corpus = T._MemoryCorpus(chunks)
    instance._plan_registry = {}
    return instance


@pytest.mark.parametrize("value, expected", [
    (None, None), ("detaljplan", ["detaljplan"]), (["Översiktsplan", "taxa"], ["oversiktsplan", "taxa"]),
    ("detaljplan, avlopp", ["detaljplan", "avlopp"]),
])
def test_parse_doc_types(value, expected):
    assert T.parse_doc_types(value) == expected


def test_doc_type_filters(memory_tools):
    assert memory_tools.grep("nockhöjd", kommun="0115").text.startswith("4 matching chunks")  # 3 documents + the law
    only_plans = memory_tools.grep("nockhöjd", kommun="0115", doc_types=["detaljplan"])
    assert only_plans.text.startswith("2 matching chunks") and "law" not in only_plans.text
    assert memory_tools.grep("nockhöjd", kommun="0115", title_contains="översikt").text.startswith("1 matching")
    assert memory_tools.grep("x", kommun="0115", doc_types="plankarta").error == "bad_args"
    listed = memory_tools.list_documents("0115", doc_types=["oversiktsplan", "taxa"])
    assert "pdf:0115:bb" in listed.text and "pdf:0115:cc" in listed.text and "pdf:0115:aa" not in listed.text
    assert "pdf:0115:aa" in memory_tools.list_documents("0115", doc_type="detaljplan").text  # the old parameter


def test_grep_documents_output(memory_tools):
    result = memory_tools.grep("nockhöjd", kommun="0115", output="documents")
    lines = result.text.splitlines()
    assert lines[0].startswith("4 matching chunks in 3 documents")
    assert lines[1].startswith("pdf:0115:aa") and "2 matching chunk(s)" in lines[1]  # most matches first
    assert len(result.chunk_ids) == 3


def test_list_documents_pages(memory_tools):
    first = memory_tools.list_documents("0115", limit=2)
    assert "showing 1-2; next page: offset=2" in first.text
    assert "showing 3-3)" in memory_tools.list_documents("0115", limit=2, offset=2).text


def test_view_map_area_on_a_scan(memory_tools, tmp_path, monkeypatch):
    """A plankarta without a text layer: the property number is found among the OCR words, read with a point."""
    import json

    import pymupdf

    monkeypatch.setattr(T, "WEB_DIR", tmp_path)
    (tmp_path / "0115" / "pdf").mkdir(parents=True)
    (tmp_path / "0115" / "ocr").mkdir()
    pdf = pymupdf.open()
    page = pdf.new_page(width=600, height=400)
    page.draw_rect(pymupdf.Rect(50, 50, 550, 350), color=(0, 0, 0))  # drawn, no text: a scan for the tool
    pdf.save(tmp_path / "0115" / "pdf" / "dd.pdf")
    (tmp_path / "0115" / "ocr" / "dd.json").write_text(json.dumps({"engine": "rapid-v6-medium", "words": [
        [0, 100, 100, 130, 110, "5.125", 0.9], [0, 140, 100, 150, 110, "e1", 0.9], [0, 500, 300, 520, 310, "e2", 0.8]]}))
    result = memory_tools.view_map_area("pdf:0115:dd", "5:125", size="near")
    assert result.image_png and "read by OCR" in result.text
    assert "e1:" in result.text and "e2:" not in result.text  # only the codes near the property
    assert memory_tools.view_map_area("pdf:0115:dd", "7:1").error == "not_found"
    (tmp_path / "0115" / "ocr" / "dd.json").unlink()
    assert memory_tools.view_map_area("pdf:0115:dd", "5:125").error == "no_data"  # not OCRed yet


def test_law_chapters():
    text = ("Källa: test\n\n"
            "1 kap.\n\n1 § Första kapitlet utan rubrik.\n\n"
            "3 kap. Grundläggande bestämmelser\n\n1 § Tredje kapitlet. Se 18 kap.\n\n"
            "4 kap. Särskilda bestämmelser för hushållning med mark och\n\nvatten för vissa områden\n\n"
            "Områden som i sin helhet är av riksintresse\n\n1 § Fjärde kapitlet.\n\n"
            "10 Kap. Bostadsarrende\n\n1 § Tionde kapitlet.\n\n"
            "14 kap.\n\nFastighetsbestämning\n\n1 § Fjortonde kapitlet.\n")
    chunks = law_chunks({"title": "Testlag", "text": text}, 1500)
    assert [c["section"] for c in chunks] == ["1 kap. 1 §", "3 kap. 1 §", "4 kap. 1 §", "10 kap. 1 §", "14 kap. 1 §"]
    assert chunks[2]["header"].startswith("Testlag, 4 kap. 1 § (4 kap. Särskilda bestämmelser för hushållning med mark "
                                          "och vatten för vissa områden")
    assert "Fastighetsbestämning" in chunks[4]["header"]


def test_law_reference_wrapped_after_kap():
    # "enligt 6 kap." ends a wrapped line: "35 § 4 miljöbalken" / "1 § 2 b." are not new sections (MBF 18 §, PBL 5:11 a)
    text = ("Källa: test\n\n5 kap. Detaljplan\n\n10 § Programmet.\n\n"
            "11 a § Kommunen ska undersöka enligt 6 kap.\n\n1 § 2 b. Kommunen ska avgöra frågan.\n\n"
            "11 b § Om genomförandet. Bestämmelser finns i 9 kap.\n\n12 § Kommunen ska samråda.\n\n"
            "13 § Andra stycket.\n\n1 § 1 och 3 gäller också.\n")
    chunks = law_chunks({"title": "Testlag", "text": text}, 1500)
    assert [c["section"] for c in chunks] == ["5 kap. 10 §", "5 kap. 11 a §", "5 kap. 11 b §", "5 kap. 12 §", "5 kap. 13 §"]
    assert chunks[1]["text"].endswith("enligt 6 kap. 1 § 2 b. Kommunen ska avgöra frågan.")
    assert chunks[4]["text"].endswith("1 § 1 och 3 gäller också.")


def test_resolve_cited_miscopied_ids():
    known = {"4463112e3a73206d": {"chunk_id": "4463112e3a73206d"}, "4463112e3a99aaaa": {"chunk_id": "4463112e3a99aaaa"}}
    # the model kept the first characters of an id it was shown and invented the rest
    assert T.resolve_cited(known.get, "4463112e2b2b1435", ["4463112e3a73206d"])["chunk_id"] == "4463112e3a73206d"
    assert T.resolve_cited(known.get, "4463112e2b2b1435", []) is None  # nothing shown: not resolved
    assert T.resolve_cited(known.get, "4463112e3a2b1435", list(known)) is None  # two equally close: ambiguous
    assert T.resolve_cited(known.get, "44631100ffffffff", ["4463112e3a73206d"]) is None  # under 8 characters


@pytest.mark.parametrize("garbled, fixed", [
    ("OmvandlingsomrÃ¥den - Haninge kommun", "Omvandlingsområden - Haninge kommun"),
    ("VÃ¤lj kranvatten â\x80\x93 bra", "Välj kranvatten – bra"),  # read as latin-1
    ("VÃ¤lj kranvatten â€“ bra", "Välj kranvatten – bra"),  # read as cp1252
    ("Planprogram för Ã rsta Slott", "Planprogram för Årsta Slott"),  # the 0x85 of "Å" became a space
    ("Café Ångström – 50 m² “citat”", "Café Ångström – 50 m² “citat”"),  # correct text is left alone
    ("", ""),
])
def test_repair_mojibake(garbled, fixed):
    from corpus.common import repair_mojibake

    assert repair_mojibake(garbled) == fixed


@pytest.mark.parametrize("texts, expected", [
    (("https://www.kalix.se/plan/25_P92_2_PB.pdf",), "detaljplan"),  # planbeskrivning in a plan archive's code
    (("1468 - Byggnadsplan för Stora Skedvi Kyrkby",), "detaljplan"),  # pre-1987 plan, a detaljplan today
    (("Stadsplanering och trafik",), "other"),
])
def test_doc_type(texts, expected):
    from corpus.extract import doc_type

    assert doc_type(*texts) == expected

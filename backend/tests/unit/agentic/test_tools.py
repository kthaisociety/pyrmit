"""agentic.tools on fake corpora: ids as the model writes them, section formats, grep and document filters, pages of
documents, map labels on a scan, miscopied citations, and reading a pinned plan's documents in memory and through the
hosted corpus's SQL. No real services (PCR-0011)."""

import sqlite3
from types import SimpleNamespace

import pytest

from agentic import tools as tools_module
from agentic.tools import CorpusTools, _DiskCorpus, _MemoryCorpus
from localrag.store import DiskStore

MAP, DESCRIPTION = "pdf:0380:map", "pdf:0380:description"


def chunk(doc_id, index, section, text):
    return {"chunk_id": f"{doc_id[-4:]}{index:012d}", "doc_id": doc_id, "chunk_index": index, "section": section,
            "text": text, "header": "", "title": doc_id, "kind": "pdf", "doc_type": "detaljplan", "kommun": "Uppsala",
            "kommun_code": "0380", "url": f"https://www.uppsala.se/{doc_id[9:]}.pdf"}


CHUNKS = [chunk(DESCRIPTION, 1, "Planens syfte", "Andra stycket"), chunk(DESCRIPTION, 0, "Bakgrund", "Första stycket"),
          chunk(DESCRIPTION, 2, "Planens syfte", "Tredje stycket"), chunk(MAP, 0, None, "Bestämmelser: e1 300 m²")]
COLUMNS = tuple(CHUNKS[0])


@pytest.fixture
def tools():
    instance = CorpusTools.__new__(CorpusTools)
    instance.corpus = _MemoryCorpus(CHUNKS)
    return instance


@pytest.fixture
def hosted_tools():
    """The tools over the store the hosted corpus reads through: SQL on a chunks table, nothing else."""
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute(f"CREATE TABLE chunks ({', '.join(COLUMNS)})")
    connection.executemany(f"INSERT INTO chunks VALUES ({','.join('?' * len(COLUMNS))})",
                           [tuple(row[column] for column in COLUMNS) for row in CHUNKS])
    store = SimpleNamespace(query=lambda sql, params=(): connection.execute(sql, tuple(params)).fetchall(),
                            _chunk=DiskStore._chunk)
    instance = CorpusTools.__new__(CorpusTools)
    instance.corpus = _DiskCorpus(store)
    return instance


READING_ORDER = ("e1 300 m²", "Första stycket", "Andra stycket", "Tredje stycket")


def test_read_plan_gives_the_documents_in_reading_order(tools):
    """The documents come in the order asked for, each one's chunks in chunk order, however they are stored."""
    text = tools.read_plan([MAP, DESCRIPTION]).text
    order = [text.index(words) for words in READING_ORDER]
    assert order == sorted(order)


def test_read_plan_keeps_the_reading_order_through_the_hosted_corpus(hosted_tools):
    """The hosted corpus's SQL gives the same order, with chunk_index compared as a number."""
    text = hosted_tools.read_plan([MAP, DESCRIPTION]).text
    order = [text.index(words) for words in READING_ORDER]
    assert order == sorted(order)


def test_read_plan_shows_the_chunks_it_returns_with_their_citations(tools):
    """Every chunk id returned is in the text as [c:<id>]."""
    result = tools.read_plan([DESCRIPTION])
    assert [f"[c:{chunk_id}]" in result.text for chunk_id in result.chunk_ids] == [True, True, True]


def test_read_plan_lists_the_headings_before_the_text(tools):
    """Read whole, a document's headings come first, so a later call can ask for one section."""
    text = tools.read_plan([DESCRIPTION]).text
    assert text.index("Planens syfte") < text.index("Första stycket")


def test_read_plan_reads_one_section_ignoring_case(tools):
    """With a section only the chunks under matching headings come."""
    result = tools.read_plan([DESCRIPTION], section="planens SYFTE")
    assert result.chunk_ids == ["tion000000000001", "tion000000000002"]


def test_read_plan_says_which_headings_there_are_when_a_section_is_not_found(tools):
    """The text of a section no heading contains lists the headings."""
    assert "Planens syfte" in tools.read_plan([DESCRIPTION], section="Parkering").text


def test_a_section_no_heading_contains_is_not_found(tools):
    assert tools.read_plan([DESCRIPTION], section="Parkering").error == "not_found"


def test_read_plan_reads_a_long_document_in_pieces_every_chunk_once(tools, monkeypatch):
    """Past the limit the text ends with the call that continues; following it reads every chunk exactly once."""
    monkeypatch.setattr(tools_module, "PLAN_READ_LIMIT", 40)
    seen, start = [], 0
    for _ in range(len(CHUNKS) + 1):
        result = tools.read_plan([MAP, DESCRIPTION], start=start)
        seen += result.chunk_ids
        if "start=" not in result.text:
            break
        start = int(result.text.rsplit("start=", 1)[1].split(")")[0])
    assert sorted(seen) == sorted(row["chunk_id"] for row in CHUNKS)


def test_the_call_that_continues_keeps_to_the_section(tools, monkeypatch):
    """Reading a section on stays within the section."""
    monkeypatch.setattr(tools_module, "PLAN_READ_LIMIT", 5)
    text = tools.read_plan([DESCRIPTION], section="Planens syfte").text
    assert f"read_plan(doc_ids=['{DESCRIPTION}'], section='Planens syfte', start=1)" in text


def test_read_plan_shows_a_chunk_longer_than_the_limit(tools, monkeypatch):
    """A chunk over the limit is still shown: a call always moves on."""
    monkeypatch.setattr(tools_module, "PLAN_READ_LIMIT", 5)
    assert len(tools.read_plan([DESCRIPTION]).chunk_ids) == 1


@pytest.mark.parametrize(("doc_ids", "chunks"), [(DESCRIPTION, 3), (f"{MAP}, {DESCRIPTION}", 4), ([f"doc {MAP}"], 1)])
def test_read_plan_takes_ids_as_the_model_writes_them(tools, doc_ids, chunks):
    """One id, a comma-separated string and ids copied with their "doc " all work."""
    assert len(tools.read_plan(doc_ids).chunk_ids) == chunks


def test_read_plan_names_an_id_it_does_not_hold(tools):
    assert "pdf:0380:gone" in tools.read_plan(["pdf:0380:gone", MAP]).text


def test_read_plan_reads_the_rest_past_an_id_it_does_not_hold(tools):
    assert len(tools.read_plan(["pdf:0380:gone", MAP]).chunk_ids) == 1


@pytest.mark.parametrize(("arguments", "error"), [({"doc_ids": []}, "bad_args"), ({"doc_ids": None}, "bad_args"),
                                                  ({"doc_ids": ["pdf:0380:gone"]}, "unknown_id"),
                                                  ({"doc_ids": [MAP], "start": 9}, "bad_args")])
def test_read_plan_fails_in_words(tools, arguments, error):
    """No ids, only unknown ids and a start past the end come back as errors the agent can read."""
    assert tools.read_plan(**arguments).error == error


def test_read_plan_needs_nothing_but_the_corpus(hosted_tools, monkeypatch, tmp_path):
    """No registry, snapshot or crawled file is touched: the hosted corpus is enough (ADR-0010)."""
    def on_disk(*args, **kwargs):
        raise AssertionError("read_plan went to a local file")
    monkeypatch.setattr(tools_module, "PLANS_PATH", tmp_path / "missing.jsonl")
    monkeypatch.setattr(tools_module, "pdf_path", on_disk)
    monkeypatch.setattr(tools_module, "ocr_path", on_disk)
    assert len(hosted_tools.read_plan([MAP, DESCRIPTION]).chunk_ids) == 4


# --- Ids as the model writes them, filters, documents, map labels (v2's tests/test_tools.py) ---

ID_CHUNKS = {
    "a1cbd51fb395f18a": {"chunk_id": "a1cbd51fb395f18a", "doc_id": "pdf:0115:9f7dbdbeeb1b2010", "header": "", "text": "first", "kind": "pdf"},
    "b2cbd51fb395f18a": {"chunk_id": "b2cbd51fb395f18a", "doc_id": "pdf:0115:9f7dbdbeeb1b2010", "header": "", "text": "second", "kind": "pdf"},
}


class FakeCorpus:
    def chunk(self, chunk_id):
        return ID_CHUNKS.get(chunk_id)

    def ids_with_prefix(self, prefix, limit=2):
        return [c for c in ID_CHUNKS if c.startswith(prefix)][:limit]

    def doc(self, doc_id):
        return {"doc_id": doc_id, "title": "Planbeskrivning", "kommun": "Vallentuna", "doc_type": "detaljplan",
                "url": None} if doc_id == "pdf:0115:9f7dbdbeeb1b2010" else None

    def doc_ids_ending(self, suffix, limit=2):
        return ["pdf:0115:9f7dbdbeeb1b2010"] if "pdf:0115:9f7dbdbeeb1b2010".endswith(":" + suffix) else []

    def doc_chunk_ids(self, doc_id):
        return list(ID_CHUNKS) if doc_id == "pdf:0115:9f7dbdbeeb1b2010" else []

    def grep(self, regex, scope, codes, limit):
        raise AssertionError("grep must not reach the corpus without a filter")


@pytest.fixture
def id_tools():
    instance = tools_module.CorpusTools.__new__(tools_module.CorpusTools)
    instance.corpus = FakeCorpus()
    instance.retriever = SimpleNamespace(places=SimpleNamespace(detect=lambda place: []))
    return instance


@pytest.mark.parametrize("chunk_id", ["a1cbd51fb395f18a", "c:a1cbd51fb395f18a", "[c:a1cbd51fb395f18a]", "a1cbd51f",
                                      "pdf:0115:9f7dbdbeeb1b2010", "0115:9f7dbdbeeb1b2010",
                                      "c:9f7dbdbeeb1b2010", "doc pdf:0115:9f7dbdbeeb1b2010",
                                      "doc:pdf:0115:9f7dbdbeeb1b2010",  # agentic.replay 2026-10-25
                                      "page:0115:a1cbd51fb395f18a"])  # a chunk id glued to a doc prefix
def test_read_accepts_ids_as_written(id_tools, chunk_id):
    assert id_tools.read(chunk_id=chunk_id).chunk_ids == list(ID_CHUNKS)


def test_read_doc_id_as_written(id_tools):
    for doc_id in ("doc pdf:0115:9f7dbdbeeb1b2010", "(doc pdf:0115:9f7dbdbeeb1b2010)", "c:a1cbd51fb395f18a"):
        assert id_tools.read(doc_id=doc_id).chunk_ids == list(ID_CHUNKS), doc_id


@pytest.mark.parametrize("chunk_id", ["c:page0115:9f7dbdbeeb1b2010", "c6c0157249a0f646", "a4"])
def test_read_falls_back_on_the_doc_id(id_tools, chunk_id):
    # a stale or invented chunk id next to a valid doc_id (forms found by agentic.replay in stored runs)
    result = id_tools.read(chunk_id=chunk_id, doc_id="pdf:0115:9f7dbdbeeb1b2010")
    assert result.chunk_ids == list(ID_CHUNKS) and not result.error


def test_read_doc_id_without_prefix_and_past_the_end(id_tools):
    assert id_tools.read(doc_id="0115:9f7dbdbeeb1b2010").chunk_ids == list(ID_CHUNKS)
    out = id_tools.read(doc_id="pdf:0115:9f7dbdbeeb1b2010", start=99)
    assert out.chunk_ids == [] and "past the end" in out.text
    assert id_tools.read(chunk_id="nope").text.startswith("Unknown chunk_id")


@pytest.mark.parametrize("raw, normalized", [
    ("9 kap. 4 §", "9 kap. 4 §"), ("9 kap 4§", "9 kap. 4 §"), ("9:4", "9 kap. 4 §"), ("9 kap. 4a §", "9 kap. 4 a §"),
    ("7 kap. 18 c § punkt 1", "7 kap. 18 c §"), ("13 §", "13 §"), ("6a kap. 2 §", "6 a kap. 2 §"),
    ("2 kap. 3 § första stycket", "2 kap. 3 §"), ("9 kap. 4 a", "9 kap. 4 a §"),
])
def test_normalize_section(raw, normalized):
    assert tools_module.normalize_section(raw) == normalized


def test_grep_needs_a_filter(id_tools):
    assert "needs a kommun" in id_tools.grep("nockhöjd").text
    assert "Unknown kommun" in id_tools.grep("nockhöjd", kommun="Atlantis").text


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
    instance = tools_module.CorpusTools.__new__(tools_module.CorpusTools)
    instance.corpus = tools_module._MemoryCorpus(chunks)
    instance._plan_registry = {}
    return instance


@pytest.mark.parametrize("value, expected", [
    (None, None), ("detaljplan", ["detaljplan"]), (["Översiktsplan", "taxa"], ["oversiktsplan", "taxa"]),
    ("detaljplan, avlopp", ["detaljplan", "avlopp"]),
])
def test_parse_doc_types(value, expected):
    assert tools_module.parse_doc_types(value) == expected


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


def test_agent_told_which_kommuner_the_corpus_holds(memory_tools, monkeypatch):
    """On a snapshot (the Neon demo) the agent must not claim all 290 kommuner, which the gazetteer still knows."""
    from agentic import agent

    monkeypatch.setattr(agent, "kommun_label", lambda code: {"0115": "Vallentuna (0115)"}.get(code, code))
    assert memory_tools.corpus_kommuner() == ["0115"]
    scope = agent.kommun_scope(memory_tools)
    assert scope.startswith("- The websites of 1 kommuner only: Vallentuna (0115)") and "no document" in scope
    national = type("Tools", (), {"corpus_kommuner": lambda self: [f"{n:04d}" for n in range(289)]})()
    assert agent.kommun_scope(national) == agent.NATIONAL_SCOPE  # the national corpus keeps the prompt as it was
    assert agent.kommun_scope(None) == agent.NATIONAL_SCOPE


def test_list_documents_pages(memory_tools):
    first = memory_tools.list_documents("0115", limit=2)
    assert "showing 1-2; next page: offset=2" in first.text
    assert "showing 3-3)" in memory_tools.list_documents("0115", limit=2, offset=2).text


def test_view_map_area_on_a_scan(memory_tools, tmp_path, monkeypatch):
    """A plankarta without a text layer: the property number is found among the OCR words, read with a point."""
    import json

    import pymupdf

    from corpus import pdf_files

    monkeypatch.setattr(pdf_files, "WEB_DIR", tmp_path)
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


def test_resolve_cited_miscopied_ids():
    known = {"4463112e3a73206d": {"chunk_id": "4463112e3a73206d"}, "4463112e3a99aaaa": {"chunk_id": "4463112e3a99aaaa"}}
    # the model kept the first characters of an id it was shown and invented the rest
    assert tools_module.resolve_cited(known.get, "4463112e2b2b1435", ["4463112e3a73206d"])["chunk_id"] == "4463112e3a73206d"
    assert tools_module.resolve_cited(known.get, "4463112e2b2b1435", []) is None  # nothing shown: not resolved
    assert tools_module.resolve_cited(known.get, "4463112e3a2b1435", list(known)) is None  # two equally close: ambiguous
    assert tools_module.resolve_cited(known.get, "44631100ffffffff", ["4463112e3a73206d"]) is None  # under 8 characters


@pytest.mark.parametrize("texts, expected", [
    (("https://www.kalix.se/plan/25_P92_2_PB.pdf",), "detaljplan"),  # planbeskrivning in a plan archive's code
    (("1468 - Byggnadsplan för Stora Skedvi Kyrkby",), "detaljplan"),  # pre-1987 plan, a detaljplan today
    (("Stadsplanering och trafik",), "other"),
])
def test_doc_type(texts, expected):
    from corpus.extract import doc_type

    assert doc_type(*texts) == expected

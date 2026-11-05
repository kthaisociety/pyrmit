"""agentic.tools: reading a pinned plan's documents, on chunks in memory and through the hosted corpus's SQL. No real
services (PCR-0011)."""

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

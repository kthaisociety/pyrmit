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
                                      "c:9f7dbdbeeb1b2010"])
def test_read_accepts_ids_as_written(tools, chunk_id):
    assert tools.read(chunk_id=chunk_id).chunk_ids == list(CHUNKS)


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

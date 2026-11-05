"""The streamed agent answer gets its [c:<chunk_id>] citations numbered whatever the delta boundaries."""

import pytest

from agentic.service import CitationNumberer

A, B, C, D = "a" * 16, "b" * 16, "c" * 16, "d" * 16
CHUNKS = {
    A: {"chunk_id": A, "kind": "law", "title": "PBL", "section": "9 kap. 4 §", "header": "PBL", "text": "a"},
    B: {"chunk_id": B, "kind": "local", "kommun": "Ydre", "title": "Avlopp", "header": "Ydre", "text": "b"},
    # same source label as A
    C: {"chunk_id": C, "kind": "law", "title": "PBL", "section": "9 kap. 4 §", "header": "PBL", "text": "c"},
}


def get_chunk(chunk_id: str) -> dict | None:
    """Like CorpusTools.get_chunk: exact id, or a truncated id that is the prefix of exactly one chunk."""
    if chunk_id in CHUNKS:
        return CHUNKS[chunk_id]
    matches = [key for key in CHUNKS if len(chunk_id) >= 8 and key.startswith(chunk_id)]
    return CHUNKS[matches[0]] if len(matches) == 1 else None


ANSWER = (f"Rule [c:{A}] [c:{C}] and [c:{B}; c:{C}] bad [c:{D}] see [PBL 9 kap. 4 §; c:{A}]. "
          f"A [link](x) and cc: [c:{A}]\n- next [c:{B}] [c:{A}] [c:{A}, c:{D}; PBL 9 kap. 3 §, 4 §] "
          f"short [c:{B[:12]}] end c")
# Unknown ids (D) are dropped; commas inside a law reference are kept; a truncated id resolves by prefix
EXPECTED = ("Rule [1] and [2; 1] bad see [PBL 9 kap. 4 §; 1]. A [link](x) and cc: [1]\n"
            "- next [2] [1] [1; PBL 9 kap. 3 §, 4 §] short [2] end c")


@pytest.mark.parametrize("size", range(1, 60))
def test_numbering_is_independent_of_delta_size(size):
    numberer = CitationNumberer(get_chunk)
    out = "".join(numberer.feed(ANSWER[i:i + size]) for i in range(0, len(ANSWER), size)) + numberer.close()
    assert out == EXPECTED
    assert numberer.labels == ["PBL, 9 kap. 4 §", "Ydre – Avlopp"]
    assert [len(c["chunks"]) for c in numberer.citations()] == [2, 1]

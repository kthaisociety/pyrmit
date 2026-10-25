"""Replay a sample of the tool calls the agent really made (stored benchmark runs) on the current corpus.

Needs the disk store (backend/data/, not versioned): skipped without it. ~1-2 min. See agentic/replay.py.
"""

import random

import pytest

from agentic import replay
from corpus.common import INDEX_DIR

STORE = INDEX_DIR / "store" / "st-arctic-l-v2" / "corpus.sqlite"


@pytest.mark.skipif(not STORE.exists(), reason="needs the disk store (backend/data/index/store)")
def test_stored_tool_calls_still_work():
    calls = replay.load_calls([str(replay.RESULTS / "bench-*.json")])
    assert calls, "no stored benchmark runs"
    sample = random.Random(1).sample(calls, min(1500, len(calls)))
    result = replay.replay(replay.build_tools(), sample)
    failures = {tool: examples[:5] for tool, examples in result["violations"].items() if examples}
    assert not failures, failures

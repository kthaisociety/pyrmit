"""agentic/service.py: what the chat router gets back from an agent run (fake agent, no corpus)."""

import json
from types import SimpleNamespace

import agentic.agent
import agentic.service
from agentic.agent import AgentRun, AskedQuestion


def test_the_agent_service_returns_the_card_of_the_run(monkeypatch):
    """stream_agent hands the router the run's questions as plain data."""
    run = AgentRun(answer="What will the building be used for?",
                   questions=[AskedQuestion("What will the building be used for?", ["A permanent home"])])
    monkeypatch.setattr(agentic.agent, "run_agent", lambda *args, **kwargs: run)
    monkeypatch.setattr(agentic.service, "get_tools", lambda: SimpleNamespace(get_chunk=lambda chunk_id: None))
    stream = agentic.service.stream_agent("q", [], lambda **call: None, json.dumps)
    try:
        while True:
            next(stream)
    except StopIteration as done:
        outcome = done.value
    assert outcome["questions"] == [{"question": "What will the building be used for?",
                                     "options": ["A permanent home"]}]


def test_an_off_topic_reply_shows_no_sources(monkeypatch):
    """A reply in the off_topic mode lists no retrieval rows, also when the agent searched before declining."""
    chunk = {"chunk_id": "a" * 16, "kind": "law", "text": "Text", "header": "PBL", "title": "PBL"}
    run = AgentRun(answer="Det ligger utanför vad jag hjälper till med.", mode="off_topic", seen_chunks=["a" * 16])
    monkeypatch.setattr(agentic.agent, "run_agent", lambda *args, **kwargs: run)
    monkeypatch.setattr(agentic.service, "get_tools", lambda: SimpleNamespace(get_chunk=lambda chunk_id: chunk))
    stream = agentic.service.stream_agent("Får jag ROT-avdrag?", [], lambda **call: None, json.dumps)
    try:
        while True:
            next(stream)
    except StopIteration as done:
        outcome = done.value
    assert (outcome["law_rows"], outcome["local_rows"]) == ([], [])

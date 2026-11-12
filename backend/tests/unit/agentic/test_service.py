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

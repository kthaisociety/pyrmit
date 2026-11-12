"""Unit tests for agents.law_agent: the reading asked in Swedish. The database and the model are faked."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from agents.law_agent import LawAgent


class CapturingClient:
    """A fake model client: keeps every request, answers with a fixed JSON reading."""

    def __init__(self):
        self.calls = []
        self.responses = SimpleNamespace(create=self.create)
        self.embeddings = SimpleNamespace(create=lambda **kw: SimpleNamespace(data=[SimpleNamespace(embedding=[0.0])]))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text='{"max_units_allowed": 10, "conditions": []}', usage=None)


def test_a_swedish_law_reading_is_not_asked_in_english():
    client = CapturingClient()
    LawAgent(MagicMock(), client).query("Uppsala", "residential", 10, language="sv")
    sent = client.calls[-1]
    assert "in English" not in f"{sent.get('instructions', '')}\n{sent.get('input', '')}"

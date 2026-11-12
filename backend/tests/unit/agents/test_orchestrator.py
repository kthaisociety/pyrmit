"""Unit tests for agents.orchestrator: the analysis in Swedish. The two agents are faked."""

from agents.orchestrator import Orchestrator


class FakeAgent:
    def __init__(self, result):
        self.result = result

    def query(self, location, project_type, units, language="en"):
        return dict(self.result)


def test_a_swedish_analysis_has_swedish_next_steps():
    """An analysis in Swedish gives its next steps in Swedish, not the English defaults."""
    law = {"max_units_allowed": 50, "conditions": [], "sources": []}
    document = {"approval_rate": 0.9, "common_requirements": [], "sources": []}
    english = Orchestrator(FakeAgent(law), FakeAgent(document)).analyze("Uppsala", "residential", 10)["next_steps"]
    swedish = Orchestrator(FakeAgent(law), FakeAgent(document)).analyze("Uppsala", "residential", 10,
                                                                         language="sv")["next_steps"]
    assert swedish and not set(swedish) & set(english)

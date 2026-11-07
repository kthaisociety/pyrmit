"""
Unit tests for backend agents.
Run from backend/: python -m pytest tests/ -v
"""

import json
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

# Stub packages that are only available inside Docker / the full backend environment.
# This lets the agent logic be tested without sqlalchemy/openai/pgvector installed.
_STUBS = [
    "sqlalchemy", "sqlalchemy.orm", "sqlalchemy.sql", "sqlalchemy.sql.expression",
    "openai",
    "pgvector", "pgvector.sqlalchemy",
]
for _mod in _STUBS:
    sys.modules.setdefault(_mod, MagicMock())

# models must be stubbed before it's imported by the agent modules
sys.modules.setdefault("models", MagicMock())

from agents.law_agent import LawAgent
from agents.document_agent import DocumentAgent
from agents.orchestrator import Orchestrator
from agents.parsers import parse_query, format_response


# ---------------------------------------------------------------------------
# parse_query
# ---------------------------------------------------------------------------

class TestParseQuery(unittest.TestCase):
    def test_extracts_units(self):
        self.assertEqual(parse_query("Can I build 20 units in Stockholm?")["units"], 20)

    def test_extracts_location(self):
        self.assertEqual(parse_query("Can I build 20 units in Stockholm?")["location"], "Stockholm")

    def test_detects_multi_family(self):
        self.assertEqual(parse_query("Build apartment complex with 30 units")["project_type"], "multi-family residential")

    def test_detects_single_family(self):
        self.assertEqual(parse_query("Build a single-family house")["project_type"], "single-family residential")

    def test_default_project_type(self):
        self.assertEqual(parse_query("Build something in Goteborg")["project_type"], "residential")

    def test_missing_units_returns_none(self):
        self.assertIsNone(parse_query("What can I build in Malmo?")["units"])

    def test_original_query_preserved(self):
        q = "Can I build 10 units in Uppsala?"
        self.assertEqual(parse_query(q)["original_query"], q)


# ---------------------------------------------------------------------------
# format_response
# ---------------------------------------------------------------------------

class TestFormatResponse(unittest.TestCase):
    def _sample(self):
        return {
            "feasibility": "HIGHLY FEASIBLE",
            "confidence": 85,
            "summary": "Project is viable.",
            "law_findings": "Max 20 units allowed.",
            "case_findings": "3 similar cases found.",
            "requirements": ["Environmental review", "Community meeting"],
            "timeline": 18,
            "next_steps": ["Schedule meeting", "Prepare application"],
        }

    def test_contains_feasibility(self):
        self.assertIn("HIGHLY FEASIBLE", format_response(self._sample()))

    def test_contains_confidence(self):
        self.assertIn("85%", format_response(self._sample()))

    def test_contains_first_requirement(self):
        self.assertIn("Environmental review", format_response(self._sample()))

    def test_contains_second_requirement(self):
        self.assertIn("Community meeting", format_response(self._sample()))

    def test_contains_next_steps(self):
        self.assertIn("Schedule meeting", format_response(self._sample()))


# ---------------------------------------------------------------------------
# Orchestrator.analyze (agents faked: they return their structured readings)
# ---------------------------------------------------------------------------

class _FakeAgent:
    def __init__(self, result):
        self.result = result

    def query(self, location, project_type, units, language="en"):
        return dict(self.result)


def _analyze(units, law, doc):
    return Orchestrator(_FakeAgent(law), _FakeAgent(doc)).analyze("Uppsala", "residential", units)


class TestFeasibility(unittest.TestCase):
    def _law(self, max_units, confidence=0.9):
        return {"max_units_allowed": max_units, "confidence": confidence}

    def _doc(self, approval_rate, confidence=0.8):
        return {"approval_rate": approval_rate, "confidence": confidence}

    def test_highly_feasible(self):
        self.assertEqual(_analyze(10, self._law(20), self._doc("80%"))["feasibility"], "HIGHLY FEASIBLE")

    def test_feasible_with_challenges(self):
        self.assertEqual(_analyze(10, self._law(20), self._doc("50%"))["feasibility"], "FEASIBLE WITH CHALLENGES")

    def test_not_feasible(self):
        self.assertEqual(_analyze(30, self._law(20), self._doc("80%"))["feasibility"], "NOT FEASIBLE")

    def test_uncertain_when_max_unknown(self):
        self.assertEqual(_analyze(10, self._law("unknown"), self._doc("80%"))["feasibility"], "UNCERTAIN")

    def test_uncertain_when_max_varies(self):
        self.assertEqual(_analyze(10, self._law("varies"), self._doc("80%"))["feasibility"], "UNCERTAIN")

    def test_confidence_is_int(self):
        self.assertIsInstance(_analyze(10, self._law(20), self._doc("80%"))["confidence"], int)

    def test_boundary_exactly_at_max(self):
        # units == max_allowed should be allowed (<=)
        self.assertEqual(_analyze(20, self._law(20), self._doc("80%"))["feasibility"], "HIGHLY FEASIBLE")


class TestRequirements(unittest.TestCase):
    def test_combines_without_duplicates(self):
        reqs = _analyze(10, {"conditions": ["Parking plan"]},
                        {"common_requirements": ["Noise study", "Parking plan"]})["requirements"]
        self.assertEqual(reqs, ["Parking plan", "Noise study"])

    def test_default_when_empty(self):
        self.assertEqual(_analyze(10, {}, {})["requirements"], ["Consult with local planning department"])

    def test_law_conditions_come_first(self):
        self.assertEqual(_analyze(10, {"conditions": ["A"]}, {"common_requirements": ["B"]})["requirements"][0], "A")


class TestNextSteps(unittest.TestCase):
    def test_highly_feasible_mentions_preapplication(self):
        steps = _analyze(10, {"max_units_allowed": 20}, {"approval_rate": "80%"})["next_steps"]
        self.assertTrue(any("pre-application" in s.lower() for s in steps))

    def test_not_feasible_mentions_variance(self):
        steps = _analyze(30, {"max_units_allowed": 20}, {"approval_rate": "80%"})["next_steps"]
        self.assertTrue(any("variance" in s.lower() for s in steps))

    def test_uncertain_returns_steps(self):
        self.assertTrue(_analyze(10, {}, {})["next_steps"])


# ---------------------------------------------------------------------------
# LawAgent.query / DocumentAgent.query (the database and the model client faked)
# ---------------------------------------------------------------------------

def _answering_client(output_text):
    """A fake model client whose every answer is `output_text`."""
    client = MagicMock()
    client.responses.create.return_value = SimpleNamespace(output_text=output_text, usage=None)
    return client


def _law_reading(output_text):
    return LawAgent(db=MagicMock(), openai_client=_answering_client(output_text)).query("Stockholm", "residential", 15)


def _document_reading(output_text):
    return DocumentAgent(db=MagicMock(), openai_client=_answering_client(output_text)).query("Stockholm", "residential", 12)


LAW_JSON = json.dumps({"max_units_allowed": 20, "base_zoning": "R-3", "applicable_laws": ["PBL 4:1"], "conditions": [],
                       "special_provisions": "", "confidence": 0.85})
DOCUMENT_JSON = json.dumps({
    "similar_cases": [{"address": "Storgatan 1", "units": 12, "outcome": "APPROVED", "year": 2022, "conditions": []}],
    "approval_rate": "75%", "common_requirements": ["Noise study"], "typical_timeline_months": 18,
    "political_climate": "supportive", "confidence": 0.7,
})


class TestLawAgentQuery(unittest.TestCase):
    def test_returns_the_parsed_units(self):
        self.assertEqual(_law_reading(LAW_JSON)["max_units_allowed"], 20)

    def test_returns_the_parsed_confidence(self):
        self.assertAlmostEqual(_law_reading(LAW_JSON)["confidence"], 0.85)

    def test_bad_json_gives_unknown_units(self):
        self.assertEqual(_law_reading("not json")["max_units_allowed"], "unknown")

    def test_bad_json_gives_low_confidence(self):
        self.assertEqual(_law_reading("not json")["confidence"], 0.3)

    def test_bad_json_gives_no_laws(self):
        self.assertEqual(_law_reading("not json")["applicable_laws"], [])

    def test_handles_fenced_json(self):
        fenced = '```json\n{"max_units_allowed": 10, "applicable_laws": [], "conditions": [], "confidence": 0.6}\n```'
        self.assertEqual(_law_reading(fenced)["max_units_allowed"], 10)

    def test_handles_fenced_json_without_language(self):
        fenced = '```\n{"max_units_allowed": 12, "applicable_laws": [], "conditions": [], "confidence": 0.6}\n```'
        self.assertEqual(_law_reading(fenced)["max_units_allowed"], 12)


class TestDocumentAgentQuery(unittest.TestCase):
    def test_returns_the_parsed_approval_rate(self):
        self.assertEqual(_document_reading(DOCUMENT_JSON)["approval_rate"], "75%")

    def test_returns_the_parsed_cases(self):
        self.assertEqual(len(_document_reading(DOCUMENT_JSON)["similar_cases"]), 1)

    def test_bad_json_gives_no_cases(self):
        self.assertEqual(_document_reading("bad response")["similar_cases"], [])

    def test_bad_json_gives_low_confidence(self):
        self.assertEqual(_document_reading("bad response")["confidence"], 0.3)


if __name__ == "__main__":
    unittest.main()

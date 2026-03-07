"""
Unit tests for backend agents.
Run from backend/: python -m pytest tests/ -v
"""

import json
import sys
import os
import unittest
from unittest.mock import MagicMock, patch

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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.base import BaseRAGAgent
from agents.law_agent import LawAgent
from agents.document_agent import DocumentAgent
from agents.orchestrator import Orchestrator
from agents.parsers import parse_query, format_response


# ---------------------------------------------------------------------------
# BaseRAGAgent._extract_json
# ---------------------------------------------------------------------------

class TestExtractJson(unittest.TestCase):
    def test_plain_json(self):
        text = '{"key": "value", "num": 42}'
        result = BaseRAGAgent._extract_json(text)
        self.assertEqual(result["key"], "value")
        self.assertEqual(result["num"], 42)

    def test_json_fenced_with_language(self):
        text = '```json\n{"status": "ok"}\n```'
        result = BaseRAGAgent._extract_json(text)
        self.assertEqual(result["status"], "ok")

    def test_json_fenced_without_language(self):
        text = '```\n{"status": "ok"}\n```'
        result = BaseRAGAgent._extract_json(text)
        self.assertEqual(result["status"], "ok")

    def test_invalid_json_raises(self):
        with self.assertRaises(json.JSONDecodeError):
            BaseRAGAgent._extract_json("not json at all")


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

    def test_contains_requirements(self):
        output = format_response(self._sample())
        self.assertIn("Environmental review", output)
        self.assertIn("Community meeting", output)

    def test_contains_next_steps(self):
        self.assertIn("Schedule meeting", format_response(self._sample()))


# ---------------------------------------------------------------------------
# Orchestrator._determine_feasibility
# ---------------------------------------------------------------------------

class TestDetermineFeasibility(unittest.TestCase):
    def setUp(self):
        self.orch = Orchestrator(MagicMock(), MagicMock())

    def _law(self, max_units, confidence=0.9):
        return {"max_units_allowed": max_units, "confidence": confidence}

    def _doc(self, approval_rate, confidence=0.8):
        return {"approval_rate": approval_rate, "confidence": confidence}

    def test_highly_feasible(self):
        self.assertEqual(
            self.orch._determine_feasibility(10, self._law(20), self._doc("80%"))["status"],
            "HIGHLY FEASIBLE"
        )

    def test_feasible_with_challenges(self):
        self.assertEqual(
            self.orch._determine_feasibility(10, self._law(20), self._doc("50%"))["status"],
            "FEASIBLE WITH CHALLENGES"
        )

    def test_not_feasible(self):
        self.assertEqual(
            self.orch._determine_feasibility(30, self._law(20), self._doc("80%"))["status"],
            "NOT FEASIBLE"
        )

    def test_uncertain_when_max_unknown(self):
        self.assertEqual(
            self.orch._determine_feasibility(10, self._law("unknown"), self._doc("80%"))["status"],
            "UNCERTAIN"
        )

    def test_uncertain_when_max_varies(self):
        self.assertEqual(
            self.orch._determine_feasibility(10, self._law("varies"), self._doc("80%"))["status"],
            "UNCERTAIN"
        )

    def test_confidence_is_int(self):
        result = self.orch._determine_feasibility(10, self._law(20), self._doc("80%"))
        self.assertIsInstance(result["confidence"], int)

    def test_boundary_exactly_at_max(self):
        # units == max_allowed should be allowed (<=)
        self.assertIn(
            self.orch._determine_feasibility(20, self._law(20), self._doc("80%"))["status"],
            ["HIGHLY FEASIBLE", "FEASIBLE WITH CHALLENGES"]
        )


# ---------------------------------------------------------------------------
# Orchestrator._extract_requirements
# ---------------------------------------------------------------------------

class TestExtractRequirements(unittest.TestCase):
    def setUp(self):
        self.orch = Orchestrator(MagicMock(), MagicMock())

    def test_combines_without_duplicates(self):
        law = {"conditions": ["Parking plan"]}
        doc = {"common_requirements": ["Noise study", "Parking plan"]}
        reqs = self.orch._extract_requirements(law, doc)
        self.assertEqual(reqs.count("Parking plan"), 1)
        self.assertIn("Noise study", reqs)

    def test_default_when_empty(self):
        self.assertEqual(
            self.orch._extract_requirements({}, {}),
            ["Consult with local planning department"]
        )

    def test_law_conditions_come_first(self):
        law = {"conditions": ["A"]}
        doc = {"common_requirements": ["B"]}
        reqs = self.orch._extract_requirements(law, doc)
        self.assertEqual(reqs[0], "A")


# ---------------------------------------------------------------------------
# Orchestrator._generate_next_steps
# ---------------------------------------------------------------------------

class TestGenerateNextSteps(unittest.TestCase):
    def setUp(self):
        self.orch = Orchestrator(MagicMock(), MagicMock())

    def test_highly_feasible_mentions_preapplication(self):
        steps = self.orch._generate_next_steps({"status": "HIGHLY FEASIBLE"})
        self.assertTrue(any("pre-application" in s.lower() for s in steps))

    def test_not_feasible_mentions_variance(self):
        steps = self.orch._generate_next_steps({"status": "NOT FEASIBLE"})
        self.assertTrue(any("variance" in s.lower() for s in steps))

    def test_all_statuses_return_nonempty(self):
        for status in ("HIGHLY FEASIBLE", "FEASIBLE WITH CHALLENGES", "NOT FEASIBLE", "UNCERTAIN"):
            self.assertTrue(len(self.orch._generate_next_steps({"status": status})) > 0)


# ---------------------------------------------------------------------------
# LawAgent.query (mocked _retrieve and _call_llm)
# ---------------------------------------------------------------------------

class TestLawAgentQuery(unittest.TestCase):
    def _make_agent(self):
        return LawAgent(db=MagicMock(), openai_client=MagicMock())

    def test_returns_parsed_json(self):
        agent = self._make_agent()
        llm_response = json.dumps({
            "max_units_allowed": 20,
            "base_zoning": "R-3",
            "applicable_laws": ["PBL 4:1"],
            "conditions": [],
            "special_provisions": "",
            "confidence": 0.85,
        })
        with patch.object(agent, "_retrieve", return_value=["law text"]):
            with patch.object(agent, "_call_llm", return_value=llm_response):
                result = agent.query("Stockholm", "multi-family residential", 15)
        self.assertEqual(result["max_units_allowed"], 20)
        self.assertAlmostEqual(result["confidence"], 0.85)

    def test_fallback_on_bad_json(self):
        agent = self._make_agent()
        with patch.object(agent, "_retrieve", return_value=[]):
            with patch.object(agent, "_call_llm", return_value="not json"):
                result = agent.query("Stockholm", "residential", 10)
        self.assertEqual(result["max_units_allowed"], "unknown")
        self.assertEqual(result["confidence"], 0.3)
        self.assertEqual(result["applicable_laws"], [])

    def test_handles_fenced_json(self):
        agent = self._make_agent()
        llm_response = '```json\n{"max_units_allowed": 10, "base_zoning": "R-2", "applicable_laws": [], "conditions": [], "special_provisions": "", "confidence": 0.6}\n```'
        with patch.object(agent, "_retrieve", return_value=[]):
            with patch.object(agent, "_call_llm", return_value=llm_response):
                result = agent.query("Malmo", "residential", 8)
        self.assertEqual(result["max_units_allowed"], 10)


# ---------------------------------------------------------------------------
# DocumentAgent.query (mocked _retrieve and _call_llm)
# ---------------------------------------------------------------------------

class TestDocumentAgentQuery(unittest.TestCase):
    def _make_agent(self):
        return DocumentAgent(db=MagicMock(), openai_client=MagicMock())

    def test_returns_parsed_json(self):
        agent = self._make_agent()
        llm_response = json.dumps({
            "similar_cases": [{"address": "Storgatan 1", "units": 12, "outcome": "APPROVED", "year": 2022, "conditions": []}],
            "approval_rate": "75%",
            "common_requirements": ["Noise study"],
            "typical_timeline_months": 18,
            "political_climate": "supportive",
            "confidence": 0.7,
        })
        with patch.object(agent, "_retrieve", return_value=["doc text"]):
            with patch.object(agent, "_call_llm", return_value=llm_response):
                result = agent.query("Stockholm", "residential", 12)
        self.assertEqual(result["approval_rate"], "75%")
        self.assertEqual(len(result["similar_cases"]), 1)

    def test_fallback_on_bad_json(self):
        agent = self._make_agent()
        with patch.object(agent, "_retrieve", return_value=[]):
            with patch.object(agent, "_call_llm", return_value="bad response"):
                result = agent.query("Goteborg", "residential", 5)
        self.assertEqual(result["similar_cases"], [])
        self.assertEqual(result["confidence"], 0.3)


if __name__ == "__main__":
    unittest.main()

"""
Orchestrator agent that coordinates law and document agents.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict

logger = logging.getLogger(__name__)


class Orchestrator:
    """Coordinates multiple specialist agents and synthesizes results."""

    def __init__(self, law_agent, document_agent):
        self.law_agent = law_agent
        self.document_agent = document_agent

    def analyze(self, location: str, project_type: str, units: int) -> Dict[str, Any]:
        logger.info("Starting analysis: %d %s units in %s", units, project_type, location)
        with ThreadPoolExecutor(max_workers=2) as executor:
            law_future = executor.submit(self.law_agent.query, location, project_type, units)
            doc_future = executor.submit(self.document_agent.query, location, project_type, units)
            law_result = law_future.result()
            document_result = doc_future.result()
        feasibility = self._determine_feasibility(units, law_result, document_result)
        logger.info("Feasibility verdict: %s (confidence: %s%%)", feasibility["status"], feasibility["confidence"])
        sources = list(dict.fromkeys(
            law_result.get("sources", []) + document_result.get("sources", [])
        ))
        return {
            "feasibility": feasibility["status"],
            "confidence": feasibility["confidence"],
            "summary": feasibility["summary"],
            "law_findings": self._summarize_law_findings(law_result),
            "case_findings": self._summarize_case_findings(document_result),
            "requirements": self._extract_requirements(law_result, document_result),
            "timeline": document_result.get("typical_timeline_months", "Unknown"),
            "next_steps": self._generate_next_steps(feasibility),
            "sources": sources,
        }

    def _determine_feasibility(
        self, units: int, law_result: dict, document_result: dict
    ) -> dict:
        max_allowed = law_result.get("max_units_allowed")
        approval_rate_str = document_result.get("approval_rate", "0%")

        try:
            approval_rate = float(str(approval_rate_str).replace("%", "")) / 100
        except (ValueError, AttributeError):
            approval_rate = 0.5

        law_confidence = law_result.get("confidence", 0.5)
        doc_confidence = document_result.get("confidence", 0.5)

        if isinstance(max_allowed, (int, float)):
            legally_allowed = units <= max_allowed
        else:
            legally_allowed = None  # "varies", "unknown", or missing

        if legally_allowed is True and approval_rate >= 0.7:
            return {
                "status": "HIGHLY FEASIBLE",
                "summary": f"Project appears viable. Law allows up to {max_allowed} units, and similar projects have {approval_rate_str} approval rate.",
                "confidence": int(min(law_confidence, doc_confidence) * 100),
            }
        if legally_allowed is True and approval_rate >= 0.4:
            return {
                "status": "FEASIBLE WITH CHALLENGES",
                "summary": f"Project is legally allowed but may face approval challenges. Approval rate for similar projects: {approval_rate_str}.",
                "confidence": int(min(law_confidence, doc_confidence) * 100),
            }
        if legally_allowed is False:
            return {
                "status": "NOT FEASIBLE",
                "summary": f"Project exceeds maximum allowed density. Law allows {max_allowed} units, but you proposed {units} units.",
                "confidence": int(law_confidence * 100),
            }
        return {
            "status": "UNCERTAIN",
            "summary": "Unable to determine feasibility with available information. Legal requirements unclear.",
            "confidence": int((law_confidence + doc_confidence) / 2 * 60),
        }

    def _extract_requirements(self, law_result: dict, document_result: dict) -> list:
        requirements = list(law_result.get("conditions", []))
        for req in document_result.get("common_requirements", []):
            if req not in requirements:
                requirements.append(req)
        return requirements or ["Consult with local planning department"]

    def _generate_next_steps(self, feasibility: dict) -> list:
        status = feasibility["status"]
        if status == "HIGHLY FEASIBLE":
            return [
                "Schedule pre-application meeting with planning department",
                "Prepare formal application with required documents",
                "Engage community early to build support",
            ]
        if status == "FEASIBLE WITH CHALLENGES":
            return [
                "Consult with land use attorney",
                "Review similar approved projects for strategy",
                "Consider design modifications to increase approval likelihood",
            ]
        if status == "NOT FEASIBLE":
            return [
                "Explore variance or conditional use permit options",
                "Consider reducing project size to meet requirements",
                "Consult legal counsel about potential challenges to regulations",
            ]
        return [
            "Request official zoning interpretation from city",
            "Hire local land use consultant familiar with jurisdiction",
            "Research recent regulatory changes",
        ]

    def _summarize_law_findings(self, law_result: dict) -> str:
        max_units = law_result.get("max_units_allowed", "unknown")
        laws = law_result.get("applicable_laws", [])
        special = law_result.get("special_provisions", "")
        parts = [f"Maximum allowed: {max_units} units"]
        if laws:
            parts.append(f"Applicable laws: {', '.join(laws[:3])}")
        if special:
            parts.append(f"Special provisions: {special}")
        return "\n".join(parts)

    def _summarize_case_findings(self, document_result: dict) -> str:
        cases = document_result.get("similar_cases", [])
        approval_rate = document_result.get("approval_rate", "unknown")
        timeline = document_result.get("typical_timeline_months", "unknown")
        return f"Similar cases found: {len(cases)}\nApproval rate: {approval_rate}\nTypical timeline: {timeline} months"

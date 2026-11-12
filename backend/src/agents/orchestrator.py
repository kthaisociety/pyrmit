"""
Orchestrator agent that coordinates law and document agents.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict

from answer_language import Language

logger = logging.getLogger(__name__)

# The analysis' fixed texts per answer language (PCR-0006): format strings filled in by the methods below
_TEXTS: dict[str, dict[str, str]] = {
    "en": {
        "HIGHLY FEASIBLE": "Project appears viable. Law allows up to {max_allowed} units, and similar projects have "
                           "{approval_rate} approval rate.",
        "FEASIBLE WITH CHALLENGES": "Project is legally allowed but may face approval challenges. Approval rate for "
                                    "similar projects: {approval_rate}.",
        "NOT FEASIBLE": "Project exceeds maximum allowed density. Law allows {max_allowed} units, but you proposed "
                        "{units} units.",
        "UNCERTAIN": "Unable to determine feasibility with available information. Legal requirements unclear.",
        "fallback_requirement": "Consult with local planning department",
        "unknown": "unknown",
        "unknown_timeline": "Unknown",
        "max_units": "Maximum allowed: {max_units} units",
        "laws": "Applicable laws: {laws}",
        "special": "Special provisions: {special}",
        "cases": "Similar cases found: {count}\nApproval rate: {approval_rate}\nTypical timeline: {timeline} months",
    },
    "sv": {
        "HIGHLY FEASIBLE": "Projektet ser genomförbart ut. Lagen tillåter upp till {max_allowed} bostäder, och liknande "
                           "projekt har godkänts i {approval_rate} av fallen.",
        "FEASIBLE WITH CHALLENGES": "Projektet är tillåtet enligt lagen men kan möta svårigheter vid prövningen. Andel "
                                    "godkända liknande projekt: {approval_rate}.",
        "NOT FEASIBLE": "Projektet överskrider den högsta tillåtna tätheten. Lagen tillåter {max_allowed} bostäder, men "
                        "du föreslår {units}.",
        "UNCERTAIN": "Det går inte att bedöma genomförbarheten med den information som finns. Lagkraven är oklara.",
        "fallback_requirement": "Rådgör med kommunens plan- och byggavdelning",
        "unknown": "okänt",
        "unknown_timeline": "Okänd",
        "max_units": "Högsta tillåtna antal: {max_units} bostäder",
        "laws": "Tillämpliga lagar: {laws}",
        "special": "Särskilda bestämmelser: {special}",
        "cases": "Liknande ärenden: {count}\nAndel godkända: {approval_rate}\nTypisk handläggningstid: {timeline} "
                 "månader",
    },
}

_NEXT_STEPS: dict[str, dict[str, list[str]]] = {
    "en": {
        "HIGHLY FEASIBLE": [
            "Schedule pre-application meeting with planning department",
            "Prepare formal application with required documents",
            "Engage community early to build support",
        ],
        "FEASIBLE WITH CHALLENGES": [
            "Consult with land use attorney",
            "Review similar approved projects for strategy",
            "Consider design modifications to increase approval likelihood",
        ],
        "NOT FEASIBLE": [
            "Explore variance or conditional use permit options",
            "Consider reducing project size to meet requirements",
            "Consult legal counsel about potential challenges to regulations",
        ],
        "UNCERTAIN": [
            "Request official zoning interpretation from city",
            "Hire local land use consultant familiar with jurisdiction",
            "Research recent regulatory changes",
        ],
    },
    "sv": {
        "HIGHLY FEASIBLE": [
            "Boka ett förmöte med kommunens plan- och byggavdelning",
            "Förbered ansökan med de handlingar som krävs",
            "Involvera grannar och närboende tidigt",
        ],
        "FEASIBLE WITH CHALLENGES": [
            "Rådgör med en jurist inom plan- och byggrätt",
            "Gå igenom liknande projekt som har godkänts",
            "Överväg ändringar av utformningen som ökar chansen till godkännande",
        ],
        "NOT FEASIBLE": [
            "Undersök möjligheten till planbesked eller avvikelse från detaljplanen",
            "Överväg att minska projektet så att det uppfyller kraven",
            "Rådgör med en jurist om möjligheterna att överklaga",
        ],
        "UNCERTAIN": [
            "Be kommunen om en tolkning av detaljplanen som gäller",
            "Anlita en lokal konsult inom plan- och bygg",
            "Undersök om reglerna har ändrats nyligen",
        ],
    },
}


class Orchestrator:
    """Coordinates multiple specialist agents and synthesizes results."""

    def __init__(self, law_agent, document_agent):
        self.law_agent = law_agent
        self.document_agent = document_agent

    def analyze(self, location: str, project_type: str, units: int, language: Language = "en") -> Dict[str, Any]:
        """The feasibility analysis, with every text field (summary, findings, requirements, next steps) in
        `language`; the agents are asked in it too. The feasibility status stays the English code either way."""
        logger.info("Starting analysis: %d %s units in %s", units, project_type, location)
        with ThreadPoolExecutor(max_workers=2) as executor:
            law_future = executor.submit(self.law_agent.query, location, project_type, units, language)
            doc_future = executor.submit(self.document_agent.query, location, project_type, units, language)
            law_result = law_future.result()
            document_result = doc_future.result()
        feasibility = self._determine_feasibility(units, law_result, document_result, language)
        logger.info("Feasibility verdict: %s (confidence: %s%%)", feasibility["status"], feasibility["confidence"])
        sources = list(dict.fromkeys(
            law_result.get("sources", []) + document_result.get("sources", [])
        ))
        return {
            "feasibility": feasibility["status"],
            "confidence": feasibility["confidence"],
            "summary": feasibility["summary"],
            "law_findings": self._summarize_law_findings(law_result, language),
            "case_findings": self._summarize_case_findings(document_result, language),
            "requirements": self._extract_requirements(law_result, document_result, language),
            "timeline": document_result.get("typical_timeline_months", _TEXTS[language]["unknown_timeline"]),
            "next_steps": self._generate_next_steps(feasibility, language),
            "sources": sources,
            # Raw agent outputs (incl. retrieval traces) for the pipeline inspector
            "agent_outputs": {"law": law_result, "document": document_result},
        }

    def _determine_feasibility(
        self, units: int, law_result: dict, document_result: dict, language: Language = "en"
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
            status, confidence = "HIGHLY FEASIBLE", int(min(law_confidence, doc_confidence) * 100)
        elif legally_allowed is True and approval_rate >= 0.4:
            status, confidence = "FEASIBLE WITH CHALLENGES", int(min(law_confidence, doc_confidence) * 100)
        elif legally_allowed is False:
            status, confidence = "NOT FEASIBLE", int(law_confidence * 100)
        else:
            status, confidence = "UNCERTAIN", int((law_confidence + doc_confidence) / 2 * 60)
        summary = _TEXTS[language][status].format(max_allowed=max_allowed, approval_rate=approval_rate_str, units=units)
        return {"status": status, "summary": summary, "confidence": confidence}

    def _extract_requirements(self, law_result: dict, document_result: dict, language: Language = "en") -> list:
        requirements = list(law_result.get("conditions", []))
        for req in document_result.get("common_requirements", []):
            if req not in requirements:
                requirements.append(req)
        return requirements or [_TEXTS[language]["fallback_requirement"]]

    def _generate_next_steps(self, feasibility: dict, language: Language = "en") -> list:
        steps = _NEXT_STEPS[language]
        return steps.get(feasibility["status"], steps["UNCERTAIN"])

    def _summarize_law_findings(self, law_result: dict, language: Language = "en") -> str:
        texts = _TEXTS[language]
        laws = law_result.get("applicable_laws", [])
        special = law_result.get("special_provisions", "")
        parts = [texts["max_units"].format(max_units=law_result.get("max_units_allowed", texts["unknown"]))]
        if laws:
            parts.append(texts["laws"].format(laws=", ".join(laws[:3])))
        if special:
            parts.append(texts["special"].format(special=special))
        return "\n".join(parts)

    def _summarize_case_findings(self, document_result: dict, language: Language = "en") -> str:
        texts = _TEXTS[language]
        return texts["cases"].format(count=len(document_result.get("similar_cases", [])),
                                     approval_rate=document_result.get("approval_rate", texts["unknown"]),
                                     timeline=document_result.get("typical_timeline_months", texts["unknown"]))

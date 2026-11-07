"""
Utilities for parsing user queries and formatting agent responses.
"""

import re

from answer_language import Language


def parse_query(query: str) -> dict:
    """
    Extract key information from user query.

    Args:
        query: Natural language query from user

    Returns:
        Dictionary with parsed information
    """
    parsed = {
        "original_query": query,
        "location": None,
        "units": None,
        "project_type": None,
    }

    # Extract number of units (English + Swedish)
    units_match = re.search(
        r"(\d+)\s*[-\s]?(?:unit|lägenheter|bostäder|enheter|hus)",
        query, re.IGNORECASE,
    )
    if units_match:
        parsed["units"] = int(units_match.group(1))

    # Extract location (English "in/at" + Swedish "i/på/vid")
    # Use a word-boundary anchor on the preposition so it doesn't match mid-word
    location_match = re.search(
        r"(?:^|(?<=\s))(?:in|at|i|på|vid)\s+([\w\-åäöÅÄÖ]+(?:\s+[\w\-åäöÅÄÖ]+)?)(?=[,\.\?\!]|\s+CA|\s*$)",
        query, re.IGNORECASE,
    )
    if location_match:
        parsed["location"] = location_match.group(1).strip().title()

    # Detect project type (English + Swedish)
    lower = query.lower()
    if any(w in lower for w in ["apartment", "multi-family", "units", "flerbostadshus", "lägenheter"]):
        parsed["project_type"] = "multi-family residential"
    elif any(w in lower for w in ["house", "single-family", "home", "villa", "enfamiljshus", "radhus"]):
        parsed["project_type"] = "single-family residential"
    else:
        parsed["project_type"] = "residential"

    return parsed


_LABELS: dict[str, dict[str, str]] = {
    "en": {"title": "Feasibility Analysis", "feasibility": "Feasibility", "confidence": "Confidence",
           "summary": "Summary", "law": "Law Findings", "cases": "Historical Precedent", "requirements": "Requirements",
           "timeline": "Estimated Timeline", "months": "months", "next_steps": "Recommended Next Steps"},
    "sv": {"title": "Bedömning av genomförbarhet", "feasibility": "Genomförbarhet", "confidence": "Säkerhet",
           "summary": "Sammanfattning", "law": "Lagstiftning", "cases": "Tidigare ärenden", "requirements": "Krav",
           "timeline": "Beräknad tid", "months": "månader", "next_steps": "Rekommenderade nästa steg"},
}
_STATUS_LABELS: dict[str, dict[str, str]] = {
    "en": {},
    "sv": {"HIGHLY FEASIBLE": "MYCKET GENOMFÖRBART", "FEASIBLE WITH CHALLENGES": "GENOMFÖRBART MED UTMANINGAR",
           "NOT FEASIBLE": "INTE GENOMFÖRBART", "UNCERTAIN": "OSÄKERT"},
}


def format_response(response: dict, language: Language = "en") -> str:
    """
    Format the orchestrator response for human readability (Markdown).

    Args:
        response: Response dictionary from orchestrator
        language: the answer's language (answer_language). "sv" writes every heading and label in Swedish
            ("## Bedömning av genomförbarhet", "**Genomförbarhet:**", "**Säkerhet:**", "### Sammanfattning",
            "### Lagstiftning", "### Tidigare ärenden", "### Krav", "**Beräknad tid:** <n> månader",
            "### Rekommenderade nästa steg") and the feasibility status as a Swedish label; "en" is unchanged.

    Returns:
        Markdown-formatted string
    """
    labels = _LABELS[language]
    output = []
    output.append(f"## {labels['title']}")
    status = response["feasibility"]
    output.append(f"\n**{labels['feasibility']}:** {_STATUS_LABELS[language].get(status, status)}")
    output.append(f"**{labels['confidence']}:** {response['confidence']}%")
    output.append(f"\n### {labels['summary']}\n{response['summary']}")

    if response.get("law_findings"):
        output.append(f"\n### {labels['law']}\n{response['law_findings']}")

    if response.get("case_findings"):
        output.append(f"\n### {labels['cases']}\n{response['case_findings']}")

    if response.get("requirements"):
        output.append(f"\n### {labels['requirements']}")
        for req in response["requirements"]:
            output.append(f"- {req}")

    if response.get("timeline"):
        output.append(f"\n**{labels['timeline']}:** {response['timeline']} {labels['months']}")

    if response.get("next_steps"):
        output.append(f"\n### {labels['next_steps']}")
        for i, step in enumerate(response["next_steps"], 1):
            output.append(f"{i}. {step}")

    return "\n".join(output)

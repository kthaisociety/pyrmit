"""
Utilities for parsing user queries and formatting agent responses.
"""

import re


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


def format_response(response: dict) -> str:
    """
    Format the orchestrator response for human readability.

    Args:
        response: Response dictionary from orchestrator

    Returns:
        Formatted string
    """
    output = []
    output.append("=" * 60)
    output.append("FEASIBILITY ANALYSIS")
    output.append("=" * 60)
    output.append(f"\nFEASIBILITY: {response['feasibility']}")
    output.append(f"CONFIDENCE: {response['confidence']}%")
    output.append(f"\nSUMMARY:\n{response['summary']}")

    if response.get("law_findings"):
        output.append(f"\n{'─' * 60}")
        output.append("LAW FINDINGS:")
        output.append(f"{response['law_findings']}")

    if response.get("case_findings"):
        output.append(f"\n{'─' * 60}")
        output.append("HISTORICAL PRECEDENT:")
        output.append(f"{response['case_findings']}")

    if response.get("requirements"):
        output.append(f"\n{'─' * 60}")
        output.append("REQUIREMENTS:")
        for req in response["requirements"]:
            output.append(f"  • {req}")

    if response.get("timeline"):
        output.append(f"\nESTIMATED TIMELINE: {response['timeline']}")

    if response.get("next_steps"):
        output.append(f"\n{'─' * 60}")
        output.append("RECOMMENDED NEXT STEPS:")
        for i, step in enumerate(response["next_steps"], 1):
            output.append(f"  {i}. {step}")

    output.append("=" * 60)

    return "\n".join(output)

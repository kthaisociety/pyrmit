"""
Utilities for parsing user queries.
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
        "project_type": None
    }
    
    # Extract number of units
    units_match = re.search(r'(\d+)\s*[-\s]?unit', query, re.IGNORECASE)
    if units_match:
        parsed["units"] = int(units_match.group(1))
    
    # Extract location (simple pattern matching)
    # Look for "in [Location]" or "at [Location]"
    location_match = re.search(r'(?:in|at)\s+([a-zA-Z\s]+?)(?:[,\.]|\s+CA|\?|$)', query, re.IGNORECASE)
    if location_match:
        parsed["location"] = location_match.group(1).strip().title()
    
    # Detect project type
    if any(word in query.lower() for word in ['apartment', 'multi-family', 'units']):
        parsed["project_type"] = "multi-family residential"
    elif any(word in query.lower() for word in ['house', 'single-family', 'home']):
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
    
    if response.get('law_findings'):
        output.append(f"\n{'─' * 60}")
        output.append("LAW FINDINGS:")
        output.append(f"{response['law_findings']}")
    
    if response.get('case_findings'):
        output.append(f"\n{'─' * 60}")
        output.append("HISTORICAL PRECEDENT:")
        output.append(f"{response['case_findings']}")
    
    if response.get('requirements'):
        output.append(f"\n{'─' * 60}")
        output.append("REQUIREMENTS:")
        for req in response['requirements']:
            output.append(f"  • {req}")
    
    if response.get('timeline'):
        output.append(f"\nESTIMATED TIMELINE: {response['timeline']}")
    
    if response.get('next_steps'):
        output.append(f"\n{'─' * 60}")
        output.append("RECOMMENDED NEXT STEPS:")
        for i, step in enumerate(response['next_steps'], 1):
            output.append(f"  {i}. {step}")
    
    output.append("=" * 60)
    
    return "\n".join(output)

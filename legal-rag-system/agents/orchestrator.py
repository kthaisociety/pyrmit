"""
Orchestrator agent that coordinates law and case agents.
"""

from typing import Dict, Any


class Orchestrator:
    """Coordinates multiple specialist agents and synthesizes results."""

    def __init__(self, law_agent, case_agent):
        self.law_agent = law_agent
        self.case_agent = case_agent

    def analyze(self, location: str, project_type: str, units: int) -> Dict[str, Any]:
        """
        Perform complete feasibility analysis.

        Args:
            location: City/jurisdiction
            project_type: Type of development
            units: Number of units

        Returns:
            Comprehensive analysis dictionary
        """
        print(f"\n{'=' * 60}")
        print(f"ORCHESTRATOR: Analyzing {units}-unit {project_type} in {location}")
        print(f"{'=' * 60}\n")

        # Step 1: Query law agent
        law_result = self.law_agent.query(location, project_type, units)

        # Step 2: Query case agent
        case_result = self.case_agent.query(location, project_type, units)

        # Step 3: Synthesize results with simple decision logic
        feasibility = self._determine_feasibility(units, law_result, case_result)

        # Step 4: Generate recommendations
        requirements = self._extract_requirements(law_result, case_result)
        next_steps = self._generate_next_steps(feasibility, law_result, case_result)

        # Step 5: Build final response
        response = {
            "feasibility": feasibility["status"],
            "confidence": feasibility["confidence"],
            "summary": feasibility["summary"],
            "law_findings": self._summarize_law_findings(law_result),
            "case_findings": self._summarize_case_findings(case_result),
            "requirements": requirements,
            "timeline": case_result.get("typical_timeline_months", "Unknown"),
            "next_steps": next_steps,
            "raw_data": {"law": law_result, "cases": case_result},
        }

        print(f"\n[Orchestrator] Analysis complete: {feasibility['status']}")
        return response

    def _determine_feasibility(
        self, units: int, law_result: dict, case_result: dict
    ) -> dict:
        """Determine overall feasibility using decision logic."""

        # Extract key info
        max_allowed = law_result.get("max_units_allowed")
        approval_rate_str = case_result.get("approval_rate", "0%")

        # Parse approval rate
        try:
            approval_rate = float(approval_rate_str.replace("%", "")) / 100
        except (ValueError, AttributeError):
            approval_rate = 0.5  # Default to 50% if unknown

        law_confidence = law_result.get("confidence", 0.5)
        case_confidence = case_result.get("confidence", 0.5)

        # Decision logic - determine if legally allowed
        legally_allowed = None  # Default to uncertain
        if isinstance(max_allowed, (int, float)):
            legally_allowed = units <= max_allowed
        elif max_allowed == "varies":
            legally_allowed = None  # Keep as uncertain for "varies"
        elif max_allowed == "unknown":
            legally_allowed = None

        # Determine status
        if legally_allowed is True and approval_rate >= 0.7:
            status = "HIGHLY FEASIBLE"
            summary = f"Project appears viable. Law allows up to {max_allowed} units, and similar projects have {approval_rate_str} approval rate."
            confidence = int(min(law_confidence, case_confidence) * 100)

        elif legally_allowed is True and approval_rate >= 0.4:
            status = "FEASIBLE WITH CHALLENGES"
            summary = f"Project is legally allowed but may face approval challenges. Approval rate for similar projects: {approval_rate_str}."
            confidence = int(min(law_confidence, case_confidence) * 80)

        elif legally_allowed is False:
            status = "NOT FEASIBLE"
            summary = f"Project exceeds maximum allowed density. Law allows {max_allowed} units, but you proposed {units} units."
            confidence = int(law_confidence * 100)

        else:  # Uncertain (legally_allowed is None)
            status = "UNCERTAIN"
            summary = "Unable to determine feasibility with available information. Legal requirements unclear."
            confidence = int((law_confidence + case_confidence) / 2 * 60)

        return {"status": status, "summary": summary, "confidence": confidence}

    def _extract_requirements(self, law_result: dict, case_result: dict) -> list:
        """Extract list of requirements from both agents."""
        requirements = []

        # From law
        conditions = law_result.get("conditions", [])
        requirements.extend(conditions)

        # From cases
        common_reqs = case_result.get("common_requirements", [])
        for req in common_reqs:
            if req not in requirements:
                requirements.append(req)

        return (
            requirements if requirements else ["Consult with local planning department"]
        )

    def _generate_next_steps(
        self, feasibility: dict, law_result: dict, case_result: dict
    ) -> list:
        """Generate recommended next steps."""
        steps = []

        if feasibility["status"] == "HIGHLY FEASIBLE":
            steps.append("Schedule pre-application meeting with planning department")
            steps.append("Prepare formal application with required documents")
            steps.append("Engage community early to build support")

        elif feasibility["status"] == "FEASIBLE WITH CHALLENGES":
            steps.append("Consult with land use attorney")
            steps.append("Review similar approved projects for strategy")
            steps.append(
                "Consider design modifications to increase approval likelihood"
            )

        elif feasibility["status"] == "NOT FEASIBLE":
            steps.append("Explore variance or conditional use permit options")
            steps.append("Consider reducing project size to meet requirements")
            steps.append(
                "Consult legal counsel about potential challenges to regulations"
            )

        else:  # UNCERTAIN
            steps.append("Request official zoning interpretation from city")
            steps.append("Hire local land use consultant familiar with jurisdiction")
            steps.append("Research recent regulatory changes")

        return steps

    def _summarize_law_findings(self, law_result: dict) -> str:
        """Create readable summary of law findings."""
        laws = law_result.get("applicable_laws", [])
        max_units = law_result.get("max_units_allowed", "unknown")
        special = law_result.get("special_provisions", "")

        summary = f"Maximum allowed: {max_units} units\n"
        if laws:
            summary += f"Applicable laws: {', '.join(laws[:3])}\n"
        if special:
            summary += f"Special provisions: {special}"

        return summary.strip()

    def _summarize_case_findings(self, case_result: dict) -> str:
        """Create readable summary of case findings."""
        cases = case_result.get("similar_cases", [])
        approval_rate = case_result.get("approval_rate", "unknown")
        timeline = case_result.get("typical_timeline_months", "unknown")

        summary = f"Similar cases found: {len(cases)}\n"
        summary += f"Approval rate: {approval_rate}\n"
        summary += f"Typical timeline: {timeline} months"

        return summary.strip()

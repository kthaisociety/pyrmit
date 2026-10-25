"""
Tool health of agent runs: how many tool calls returned nothing usable, per tool and per reason.

The answer scores do not show failed tool calls (the agent works around them with more searches): before
2026-10-22, 57 % of the answers lost a `read` without any score moving. The benchmark prints this table after
every run and the report shows it, so a broken tool shows up as a number.

    cd backend && python -m agentic.health data/agentic/bench-*.json
"""

import argparse
import glob
import json
from collections import Counter, defaultdict

# Failure rate above which a tool is flagged (searches and listings that find nothing are normal answers)
THRESHOLDS = {"read": 0.05, "law_section": 0.15, "plan_rules": 0.10, "view_map_area": 0.40, "view_pdf_page": 0.10}
DEFAULT_THRESHOLD = 0.25
# Steps recorded before the `error` field (2026-10-22): a read / law_section / plan_rules without chunks failed
_NEEDS_CHUNKS = {"read", "law_section", "plan_rules"}


def step_error(step: dict) -> str:
    if "error" in step:
        return step["error"] or ""
    if step["tool"] in _NEEDS_CHUNKS and not step.get("chunks"):
        return "empty"
    return ""


def tool_health(rows: list[dict]) -> dict[str, dict]:
    """Per tool: calls, failed, failure rate, failures by reason, failures per answer."""
    calls, failed, reasons = Counter(), Counter(), defaultdict(Counter)
    answers = [row for row in rows if row.get("system", "agent") == "agent" and not row.get("error")]
    for row in answers:
        for step in row.get("steps") or []:
            calls[step["tool"]] += 1
            reason = step_error(step)
            if reason:
                failed[step["tool"]] += 1
                reasons[step["tool"]][reason] += 1
    return {tool: {"calls": calls[tool], "failed": failed[tool], "rate": failed[tool] / calls[tool],
                   "per_answer": failed[tool] / max(len(answers), 1), "reasons": dict(reasons[tool]),
                   "flag": failed[tool] / calls[tool] > THRESHOLDS.get(tool, DEFAULT_THRESHOLD)}
            for tool in sorted(calls, key=lambda t: -calls[t])}


def health_lines(rows: list[dict]) -> list[str]:
    health = tool_health(rows)
    lines = [f"{'tool':<15} {'calls':>6} {'failed':>7} {'rate':>6}  reasons"]
    for tool, h in health.items():
        reasons = ", ".join(f"{k} {v}" for k, v in sorted(h["reasons"].items(), key=lambda kv: -kv[1]))
        lines.append(f"{tool:<15} {h['calls']:>6} {h['failed']:>7} {h['rate']:>6.0%}  {reasons}"
                     + ("   <-- above the threshold" if h["flag"] else ""))
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="Tool health of stored benchmark runs")
    parser.add_argument("files", nargs="+")
    args = parser.parse_args()
    rows = [row for pattern in args.files for path in glob.glob(pattern)
            for row in json.load(open(path, encoding="utf-8"))]
    print("\n".join(health_lines(rows)))


if __name__ == "__main__":
    main()

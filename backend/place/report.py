"""
The place evaluation report (Markdown) from the result files of the place checks and benchmarks: the snapshots
against their sources (place.check_sources), the address search against the kommun's register (place.check_search,
before and after a change) and the answers with and without a pin (place.bench_answers, two judges). Tables and
figures are read from the files; the findings that interpret them are written by hand in place/report_findings.md
from those figures, so update that file after new runs.

    cd backend && python -m place.report --sources data/agentic/place-sources-<time>.json \\
        --search nominatim=data/agentic/place-search-<a>.json register=data/agentic/place-search-<b>.json \\
        --answers data/agentic/place-answers-<time>.json [--findings place/report_findings.md]
"""

import argparse
import json
from collections import Counter
from pathlib import Path

from place.bench_answers import CONDITIONS, load_cases

REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"
FINDINGS_PATH = Path(__file__).resolve().parent / "report_findings.md"
CONDITION_TEXT = {"pin": "Pin (place profile before the question)", "address": "Address in the question, no pin",
                  "vague": "No place at all", "conflict": "Pinned at one place, asks about another"}


def _pct(value) -> str:
    return "–" if value is None else f"{value * 100:.0f} %"


def _num(value, digits: int = 2) -> str:
    return "–" if value is None else f"{value:.{digits}f}"


def _table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    return "\n".join(lines + ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows])


def sources_section(result: dict) -> str:
    summary = result["summary"]
    layers = [[layer, stats["present"], f"{stats['agree']}/{stats['points']}", _pct(stats["precision"]),
               _pct(stats["recall"]), stats["missing"], stats["extra"]]
              for layer, stats in summary["layers"].items() if stats["present"]]
    profile = summary["profile"]
    disagreements = [f"- `{point['origin']}` ({point['lat']}, {point['lon']}), {layer}: missing {row['missing'] or '–'},"
                     f" extra {row['extra'] or '–'}"
                     for point in result["points"] for layer, row in point["sources"]["layers"].items() if not row["agree"]]
    return "\n\n".join([
        f"{summary['points']} points of kommun {result['kommun']} (seed {result['seed']}: half inside plans, half "
        f"anywhere in the kommun, plus the proposed facit places), checked on {result['date'][:10]} against snapshots "
        f"fetched {sorted(set(result['snapshot'].values()))[-1]}. Every layer agrees with its source at "
        f"**{summary['all_agree']} of {summary['checked']} points** ({summary['source_errors']} source errors).",
        _table(["Layer", "Points with a feature", "Agree", "Precision", "Recall", "Missing", "Extra"], layers),
        "Disagreements:\n" + ("\n".join(disagreements) or "- none"),
        f"A whole place profile (snapshot layers + the live property and ancient-remains lookups) took "
        f"**{_num(profile['p50_s'])} s** at the median, {_num(profile['p90_s'])} s at p90 and {_num(profile['max_s'])} s"
        f" at most, over {profile['timed']} points; {profile['errors']} failed, the property service was unavailable "
        f"{profile['property_unavailable']} times and the ancient-remains register {profile['remains_unavailable']} "
        f"times. Detaljplan: inside {profile['detaljplan']['inside']}, outside {profile['detaljplan']['outside']}, "
        f"unknown {profile['detaljplan']['unknown']}."])


def search_section(runs: dict[str, dict]) -> str:
    keys = ["found", "within_30m", "within_100m", "within_500m", "same_property", "label_ok"]
    rows = [[name, run["summary"]["addresses"], *(_pct(run["summary"][key]) for key in keys),
             f"{_num(run['summary']['median_top_m'], 0)} m"] for name, run in runs.items()]
    kinds = []
    for name, run in runs.items():
        counted = Counter(row.get("kind") or "not found" for row in run["rows"])
        kinds.append(f"- {name}: " + ", ".join(f"{kind} {count}" for kind, count in counted.most_common(6)))
    return "\n\n".join([
        _table(["Search", "Addresses", "Found", "≤ 30 m", "≤ 100 m", "≤ 500 m", "Same property", "Label right",
                "Median distance"], rows),
        "Kind of first match:\n" + "\n".join(kinds)])


def _judges(result: dict) -> list[str]:
    return list(dict.fromkeys([result["judge"], *(result.get("summaries") or {})]))


def answers_section(result: dict, cases: dict[str, dict]) -> str:
    from place.bench_answers import summarise

    judges = _judges(result)
    blocks = [f"Agent: `{result['agent']['model']}`, answer effort {result['agent']['effort']}, exploration effort "
              f"{result['agent']['explore_effort']}, at most {result['agent']['max_steps']} steps (the chat's settings). "
              f"{len(result['rows'])} answers over {len(result['cases'])} cases, spent ${result.get('spent', 0):.2f} "
              f"including the first judge."]
    for judge in judges:
        summary = summarise(result["rows"], judge)
        rows = [[CONDITION_TEXT[condition], stats["answers"], stats["errors"], _num(stats["points"]),
                 _pct(stats["facts"]), _num(stats["wrong_place"]), _num(stats["unsupported"]), _pct(stats["asks"]),
                 _pct(stats["asks_ok"])]
                for condition, stats in summary.items() if condition in CONDITIONS]
        blocks.append(f"**Judge `{judge}`**\n\n" + _table(
            ["Condition", "Answers", "Errors", "Key points (0-1)", "Place facts named", "Wrong place claims",
             "Unsupported claims", "Asks for the place", "Right about asking"], rows))
    first = summarise(result["rows"], judges[0])
    timing = [[CONDITION_TEXT[condition], _num(stats["seconds"], 1), _num(stats["first_token_s"], 1),
               _num(stats["tool_calls"], 1), f"${_num(stats['cost'], 4)}"]
              for condition, stats in first.items() if condition in CONDITIONS]
    blocks.append(_table(["Condition", "Seconds", "First token (s)", "Tool calls", "Cost per answer"], timing))
    per_case = []
    for case_id, conditions in first["by_case"].items():
        pin, address = conditions.get("pin", {}), conditions.get("address", {})
        per_case.append([f"`{case_id}`", cases[case_id]["pin"]["label"], _num(pin.get("points")),
                         _num(address.get("points")), _pct(pin.get("facts")), _pct(address.get("facts"))])
    blocks.append(f"Per case (judge `{judges[0]}`, mean of the repeats):\n\n" + _table(
        ["Case", "Place", "Points, pin", "Points, address", "Facts, pin", "Facts, address"], per_case))
    if len(judges) > 1:
        blocks.append(agreement(result, judges[0], judges[1]))
    return "\n\n".join(blocks)


def agreement(result: dict, first: str, second: str) -> str:
    """How far two judges agree on the same answers: mean absolute difference of the key point scores and the share
    of answers where they agree on asking for the place."""
    pairs = [(row["grades"][first], row["grades"][second]) for row in result["rows"]
             if first in (row.get("grades") or {}) and second in row["grades"]]
    points = [abs(a["points"] - b["points"]) for a, b in pairs if a["points"] is not None and b["points"] is not None]
    asks = [a["asks"] == b["asks"] for a, b in pairs if a["asks"] is not None and b["asks"] is not None]
    return (f"Judge agreement on {len(pairs)} answers: key point scores differ by {_num(sum(points) / len(points))} on "
            f"average (0-1 scale), asking for the place agrees on {_pct(sum(asks) / len(asks) if asks else None)}."
            if pairs and points else "")


def build(sources: dict, search: dict[str, dict], answers: dict, findings: str = "_No findings written yet._") -> str:
    cases = {case["id"]: case for case in load_cases()}
    return "\n\n".join([
        "# Place lookup and pinned answers: evaluation report",
        f"_Tables generated by `python -m place.report` from the result files of {answers['date'][:10]}; the findings "
        "are written by hand in `backend/place/report_findings.md`._",
        findings,
        "## 1. The snapshots against their sources", sources_section(sources),
        "## 2. The address search against Uppsala's address register", search_section(search),
        "## 3. Answers with and without the pin", answers_section(answers, cases),
    ]) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the place evaluation report")
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--search", nargs="+", required=True, help="name=path of each search run, in order")
    parser.add_argument("--answers", type=Path, required=True)
    parser.add_argument("--findings", type=Path, default=FINDINGS_PATH)
    parser.add_argument("--out", type=Path, default=REPORTS_DIR / "place_eval_report.md")
    args = parser.parse_args()
    read = lambda path: json.loads(Path(path).read_text(encoding="utf-8"))
    search = {name: read(path) for name, path in (item.split("=", 1) for item in args.search)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    findings = args.findings.read_text(encoding="utf-8") if args.findings.exists() else "_No findings written yet._"
    args.out.write_text(build(read(args.sources), search, read(args.answers), findings), encoding="utf-8")
    print(args.out)


if __name__ == "__main__":
    main()

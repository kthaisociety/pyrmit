"""place.report: the evaluation report's tables from small fake result files."""

from place.check_sources import compare
from place.report import (
    agreement,
    answers_section,
    comparison_section,
    search_section,
    sources_section,
)

SOURCES = {"kommun": "0380", "seed": 25, "date": "2026-10-25T11:40:53+01:00", "snapshot": {"plans": "2026-10-25"},
           "points": [{"origin": "sample", "lat": 59.85, "lon": 17.64,
                       "sources": {"error": None, "layers": {"plans": compare(["1"], ["1", "2"])}}}],
           "summary": {"points": 1, "checked": 1, "source_errors": 0, "all_agree": 0,
                       "layers": {"plans": {"points": 1, "present": 1, "agree": 0, "precision": 1.0, "recall": 0.5,
                                            "missing": 1, "extra": 0}},
                       "profile": {"timed": 1, "p50_s": 0.3, "p90_s": 0.7, "max_s": 1.8, "errors": 0,
                                   "property_unavailable": 0, "remains_unavailable": 0,
                                   "detaljplan": {"inside": 1, "outside": 0, "unknown": 0}}}}


def test_the_sources_section_lists_layers_and_disagreements():
    text = sources_section(SOURCES)
    assert "| plans | 1 | 0/1 | 100 % | 50 % | 1 | 0 |" in text
    assert "missing ['2']" in text and "0.30 s" in text


def test_the_search_section_compares_runs():
    run = {"summary": {"addresses": 2, "found": 1.0, "within_30m": 0.5, "within_100m": 0.5, "within_500m": 1.0,
                       "same_property": 0.5, "label_ok": 0.5, "median_top_m": 48.1},
           "rows": [{"kind": "house"}, {"kind": "road"}]}
    text = search_section({"nominatim": run, "register": run})
    assert text.count("| 2 | 100 % | 50 % |") == 2 and "nominatim: house 1, road 1" in text


ROWS = [{"case": "norby", "condition": "pin", "repeat": 0, "answer": "a", "facts_share": 1.0, "seconds": 50,
         "first_token_s": 40, "cost": 0.008, "tool_calls": 20,
         "grades": {"j1": {"points": 0.5, "asks": False, "asks_ok": True, "unsupported": 1, "wrong_place": 0},
                    "j2": {"points": 1.0, "asks": False, "asks_ok": True, "unsupported": 0, "wrong_place": 0}}}]


def test_the_answers_section_has_a_table_per_judge_and_their_agreement():
    result = {"agent": {"model": "openai/gpt-6-luna", "effort": "medium", "explore_effort": "medium", "max_steps": 10},
              "judge": "j1", "summaries": {"j2": {}}, "cases": ["norby"], "rows": ROWS, "spent": 0.01}
    text = answers_section(result, {"norby": {"pin": {"label": "Eksoppsvägen 37, Uppsala"}}})
    assert "**Judge `j1`**" in text and "**Judge `j2`**" in text
    assert "| `norby` | Eksoppsvägen 37, Uppsala | 0.50 |" in text
    assert "differ by 0.50" in agreement(result, "j1", "j2")


def test_the_comparison_sets_runs_side_by_side():
    before = {"judge": "j1", "rows": ROWS}
    after = {"judge": "j1", "rows": [{**ROWS[0], "grades": {"j1": {**ROWS[0]["grades"]["j1"], "points": 1.0}}}]}
    text = comparison_section({"before": before, "after": after})
    assert "| Pin (place profile before the question) | before | 1 | 0.50 |" in text
    assert "| Pin (place profile before the question) | after | 1 | 1.00 |" in text

"""Tool health counts failed calls per tool, from the `error` field or, for older rows, empty reads."""

from agentic.health import tool_health


def test_tool_health_counts_failures_and_flags():
    rows = [{"system": "agent", "steps": [
        {"tool": "read", "chunks": ["a"], "error": ""},
        {"tool": "read", "chunks": [], "error": "unknown_id"},
        {"tool": "search", "chunks": []},  # a search that finds nothing is an answer, not a failure
        {"tool": "law_section", "chunks": []},  # row from before the error field: empty = failed
    ]}, {"system": "rag", "steps": [{"tool": "read", "chunks": [], "error": "unknown_id"}]}]  # RAG rows ignored
    health = tool_health(rows)
    assert health["read"]["calls"] == 2 and health["read"]["failed"] == 1 and health["read"]["flag"]
    assert health["read"]["reasons"] == {"unknown_id": 1}
    assert health["search"]["failed"] == 0 and not health["search"]["flag"]
    assert health["law_section"]["reasons"] == {"empty": 1}

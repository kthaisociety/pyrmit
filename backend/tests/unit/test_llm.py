"""Unit tests for llm."""

import pytest

# --- the decision model (Jev) ------------------------------------------------------------------------------------------

def test_the_decision_model_is_asked_through_openrouters_system_one(monkeypatch):
    """A question goes to OpenRouter's System One endpoint with the OpenRouter key, and its answers come back."""
    import llm

    sent = {}

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"answers": {"supported": {"type": "noul", "noul": 0.9}}}

    def post(url, json, headers, timeout):
        sent.update(url=url, body=json, auth=headers["Authorization"])
        return Response()

    monkeypatch.setenv("OPENROUTER_KEY", "sk-or-test")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("DECISION_MODEL", raising=False)
    monkeypatch.setattr(llm.httpx, "post", post)
    answers = llm.ask_decision_model({"claim": "x"}, {"supported": {"type": "noul", "instructions": "?"}})
    assert answers == {"supported": {"type": "noul", "noul": 0.9}}
    assert (sent["url"], sent["body"]["model"], sent["auth"]) == (
        "https://openrouter.ai/api/v1/systemone", "typesafe/jev-1.14", "Bearer sk-or-test")


def test_the_decision_model_needs_an_openrouter_key(monkeypatch):
    import llm

    monkeypatch.delenv("OPENROUTER_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        llm.ask_decision_model({}, {})


def test_the_decision_model_is_asked_once_more_after_a_rate_limit(monkeypatch):
    """A 429 (or 5xx) from OpenRouter is answered by one more call, whose answers are returned."""
    import llm

    replies = iter([429, 200])

    class Response:
        def __init__(self):
            self.status_code = next(replies)

        def raise_for_status(self):
            return None

        def json(self):
            return {"answers": {"q": {"type": "noul", "noul": 0.7}}}

    monkeypatch.setenv("OPENROUTER_KEY", "sk-or-test")
    monkeypatch.setattr(llm.httpx, "post", lambda *args, **kwargs: Response())
    assert llm.ask_decision_model({}, {"q": {}}) == {"q": {"type": "noul", "noul": 0.7}}

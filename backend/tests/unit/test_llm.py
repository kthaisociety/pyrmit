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


# --- the user's own OpenRouter key (issue #108) ------------------------------------------------------------------------

SHARED_KEY, USER_KEY = "sk-or-shared-0000", "sk-or-user-abcd"


@pytest.fixture
def openrouter(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", SHARED_KEY)
    monkeypatch.delenv("OPENROUTER_KEY", raising=False)


def test_the_chat_model_uses_the_shared_key_when_the_user_has_none(openrouter):
    import llm

    with llm.openrouter_key(None):
        assert llm.chat_client_settings() == (SHARED_KEY, llm.OPENROUTER_BASE_URL)
    assert llm.chat_client_settings()[0] == SHARED_KEY


def test_the_chat_model_uses_the_users_own_key(openrouter):
    import llm

    with llm.openrouter_key(USER_KEY):
        assert llm.chat_client_settings() == (USER_KEY, llm.OPENROUTER_BASE_URL)
        assert llm.get_openai_client().api_key == USER_KEY
    assert llm.chat_client_settings()[0] == SHARED_KEY  # back to the shared key after the request


def test_the_traced_client_uses_the_users_own_key_without_sharing_it(openrouter):
    import llm
    import observability

    with llm.openrouter_key(USER_KEY):
        users_client = observability.get_openai_client()
    shared_client = observability.get_openai_client()
    assert users_client.api_key == USER_KEY
    assert shared_client.api_key == SHARED_KEY
    assert str(users_client.base_url).rstrip("/") == llm.OPENROUTER_BASE_URL


def test_a_user_key_works_without_a_shared_key(monkeypatch):
    import llm

    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_KEY", raising=False)
    with llm.openrouter_key(USER_KEY):
        assert llm.chat_client_settings()[0] == USER_KEY
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        llm.chat_client_settings()


def test_the_users_key_is_not_used_for_another_chat_provider(monkeypatch):
    """An OpenRouter key means nothing to OpenAI or the AI Gateway: those providers keep their own key."""
    import llm

    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    with llm.openrouter_key(USER_KEY):
        assert llm.chat_client_settings()[0] == "sk-openai"


def test_the_decision_model_runs_on_the_users_own_key(openrouter, monkeypatch):
    import llm

    sent = []

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"answers": {}}

    def post(url, json, headers, timeout):
        sent.append(headers["Authorization"])
        return Response()

    monkeypatch.setattr(llm.httpx, "post", post)
    with llm.openrouter_key(USER_KEY):
        llm.ask_decision_model({}, {})
    llm.ask_decision_model({}, {})
    assert sent == [f"Bearer {USER_KEY}", f"Bearer {SHARED_KEY}"]


def test_another_thread_never_sees_the_users_key(openrouter):
    """Concurrent requests: a thread started outside the request's context gets the shared key."""
    import threading

    import llm

    seen = []
    with llm.openrouter_key(USER_KEY):
        thread = threading.Thread(target=lambda: seen.append(llm.openrouter_api_key()))
        thread.start()
        thread.join()
    assert seen == [SHARED_KEY]


def test_embeddings_stay_on_the_shared_key(openrouter):
    """Question embeddings (or-bge-m3 through OpenRouter) are paid by the shared key, also inside a user's request."""
    import llm
    from embeddings import Embedder, EmbeddingConfig

    with llm.openrouter_key(USER_KEY):
        client = Embedder(EmbeddingConfig(provider="openrouter", model="baai/bge-m3", dim=1024))._get_client()
    assert client.api_key == SHARED_KEY


def test_an_error_never_shows_a_key(openrouter):
    import llm

    with llm.openrouter_key(USER_KEY):
        text = llm.public_error(RuntimeError(f"failed with {USER_KEY} and {SHARED_KEY}"))
    assert USER_KEY not in text and SHARED_KEY not in text
    assert "…abcd" in text


@pytest.mark.parametrize("status, words", [(401, "was refused"), (402, "has no credits left")])
def test_a_refused_user_key_says_what_to_do(openrouter, status, words):
    import llm

    class Refused(Exception):
        status_code = status

    with llm.openrouter_key(USER_KEY):
        text = llm.public_error(Refused("Error code: 401"))
    assert words in text and "Settings" in text


def test_a_refused_shared_key_is_not_blamed_on_the_user(openrouter):
    import llm

    class Refused(Exception):
        status_code = 401

    assert "Settings" not in llm.public_error(Refused("Error code: 401"))

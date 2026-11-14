from contextlib import contextmanager
import logging
import os
from typing import Any

from llm import chat_client_settings

logger = logging.getLogger(__name__)

_LANGFUSE_EXTRA_KEYS = {
    "name",
    "metadata",
    "session_id",
    "user_id",
    "tags",
    "trace_id",
    "parent_observation_id",
}

try:
    from langfuse.openai import openai as _openai_client
    from langfuse import get_client as _get_langfuse_client, propagate_attributes as _propagate_attributes

    _LANGFUSE_IMPORT_OK = True
except ImportError:
    import openai as _openai_client

    _get_langfuse_client = None
    _propagate_attributes = None
    _LANGFUSE_IMPORT_OK = False


def _langfuse_configured() -> bool:
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))


def _strip_langfuse_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in kwargs.items() if key not in _LANGFUSE_EXTRA_KEYS}


def get_openai_client():
    """A new client (traced by Langfuse when configured) for the chat provider. Never the module-level client with
    its key set: the key can be the signed-in user's own (llm.openrouter_key, #108), and a shared client would hand
    it to every other request."""
    api_key, base_url = chat_client_settings()
    return _openai_client.OpenAI(api_key=api_key, base_url=base_url)


def langfuse_enabled() -> bool:
    return _LANGFUSE_IMPORT_OK and _langfuse_configured()


class _NoopObservation:
    def update(self, **kwargs):
        return None


@contextmanager
def start_observation(name: str, *, as_type: str = "span", **kwargs):
    if not langfuse_enabled() or _get_langfuse_client is None:
        yield _NoopObservation()
        return

    client = _get_langfuse_client()
    with client.start_as_current_observation(name=name, as_type=as_type, **kwargs) as observation:
        yield observation


@contextmanager
def propagate_trace_attributes(*, user_id: str | None = None, session_id: str | None = None, metadata: dict[str, Any] | None = None):
    if not langfuse_enabled() or _propagate_attributes is None:
        yield
        return

    safe_metadata = None
    if metadata:
        safe_metadata = {str(key): str(value)[:200] for key, value in metadata.items()}

    with _propagate_attributes(user_id=user_id, session_id=session_id, metadata=safe_metadata):
        yield


def reasoning_effort(name: str) -> str:
    """LLM_REASONING_EFFORT for answers/analyses; LLM_REWRITE_REASONING_EFFORT (default low) for query rewrites,
    which only need to be fast."""
    if any(word in name.lower() for word in ("rewrite", "translation")):
        return os.getenv("LLM_REWRITE_REASONING_EFFORT", "low").strip() if os.getenv("LLM_REASONING_EFFORT") else ""
    return os.getenv("LLM_REASONING_EFFORT", "").strip()


def create_chat_completion(client: Any, **kwargs):
    if hasattr(client, "responses"):
        effort = reasoning_effort(str(kwargs.get("name", "")))
        if effort and "reasoning" not in kwargs:
            kwargs["reasoning"] = {"effort": effort}
        return client.responses.create(**_strip_langfuse_kwargs(kwargs))
    return client.chat.completions.create(**_strip_langfuse_kwargs(kwargs))


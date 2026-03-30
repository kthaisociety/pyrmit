from contextlib import contextmanager
import logging
import os
from typing import Any

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
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        _openai_client.api_key = api_key

    base_url = os.getenv("OPENAI_BASE_URL")
    if base_url:
        _openai_client.base_url = base_url

    return _openai_client


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


def create_chat_completion(client: Any, **kwargs):
    return client.chat.completions.create(**_strip_langfuse_kwargs(kwargs))


def create_embedding(client: Any, **kwargs):
    return client.embeddings.create(**_strip_langfuse_kwargs(kwargs))

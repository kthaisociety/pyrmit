"""
Records LLM and embedding calls made while answering a chat message, so the
frontend pipeline inspector can show the exact prompts, outputs and timings.
"""

import threading
import time
from typing import Any

from llm import get_response_output_text
from observability import create_chat_completion, create_embedding


def response_usage(response: Any) -> dict[str, int] | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    fields = ("input_tokens", "output_tokens", "total_tokens", "prompt_tokens", "completion_tokens")
    values = {field: getattr(usage, field) for field in fields if isinstance(getattr(usage, field, None), int)}
    return values or None


class CallRecorder:
    """Thread-safe list of call records (agents run in a thread pool)."""

    def __init__(self):
        self._calls: list[dict[str, Any]] = []
        self._drained = 0
        self._lock = threading.Lock()

    def record(self, **call: Any) -> None:
        with self._lock:
            self._calls.append(call)

    def drain(self) -> list[dict[str, Any]]:
        """Return the calls recorded since the previous drain."""
        with self._lock:
            new_calls = self._calls[self._drained:]
            self._drained = len(self._calls)
            return new_calls


def recorded_chat_completion(recorder: CallRecorder | None, client: Any, *, name: str, **kwargs) -> Any:
    """Non-streaming create_chat_completion that also records the call."""
    if recorder is None:
        return create_chat_completion(client, name=name, **kwargs)

    started = time.perf_counter()
    call = {
        "kind": "llm",
        "name": name,
        "model": kwargs.get("model"),
        "temperature": kwargs.get("temperature"),
        "instructions": kwargs.get("instructions"),
        "input": kwargs.get("input"),
    }
    try:
        response = create_chat_completion(client, name=name, **kwargs)
    except Exception as exc:
        recorder.record(**call, error=str(exc), duration_ms=round((time.perf_counter() - started) * 1000))
        raise
    recorder.record(
        **call,
        output=get_response_output_text(response),
        usage=response_usage(response),
        duration_ms=round((time.perf_counter() - started) * 1000),
    )
    return response


def recorded_embedding(recorder: CallRecorder | None, client: Any, *, name: str, **kwargs) -> Any:
    if recorder is None:
        return create_embedding(client, **kwargs)

    started = time.perf_counter()
    call = {"kind": "embedding", "name": name, "model": kwargs.get("model"), "input": kwargs.get("input")}
    try:
        response = create_embedding(client, **kwargs)
    except Exception as exc:
        recorder.record(**call, error=str(exc), duration_ms=round((time.perf_counter() - started) * 1000))
        raise
    recorder.record(
        **call,
        dimensions=len(response.data[0].embedding) if response.data else None,
        usage=response_usage(response),
        duration_ms=round((time.perf_counter() - started) * 1000),
    )
    return response

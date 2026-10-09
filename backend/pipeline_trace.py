"""
Records LLM calls made while answering a chat message, so the
frontend pipeline inspector can show the exact prompts, outputs and timings.
"""

import threading
import time
from typing import Any

from llm import get_response_output_text
from observability import create_chat_completion, reasoning_effort


def response_usage(response: Any) -> dict[str, float] | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    fields = ("input_tokens", "output_tokens", "total_tokens", "prompt_tokens", "completion_tokens")
    values: dict[str, float] = {
        field: getattr(usage, field) for field in fields if isinstance(getattr(usage, field, None), int)
    }
    details = getattr(usage, "output_tokens_details", None)
    if isinstance(getattr(details, "reasoning_tokens", None), int):
        values["reasoning_tokens"] = details.reasoning_tokens
    # OpenRouter reports the billed price of each call (USD)
    cost = getattr(usage, "cost", None)
    if isinstance(cost, (int, float)):
        values["cost"] = float(cost)
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
        "reasoning_effort": reasoning_effort(name) or None,
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


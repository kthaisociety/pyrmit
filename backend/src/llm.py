import os
from typing import Any, Iterable

import httpx
from openai import OpenAI

VERCEL_AI_GATEWAY_BASE_URL = "https://ai-gateway.vercel.sh/v1"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_CHAT_PROVIDERS = {"openai", "gateway", "openrouter"}
# The decision model (TypeSafe Jev): answers fixed questions with probabilities instead of writing text, through
# OpenRouter's System One endpoint with the OpenRouter key. DECISION_MODEL overrides the model id.
SYSTEM_ONE_URL = f"{OPENROUTER_BASE_URL}/systemone"
DEFAULT_DECISION_MODEL = "typesafe/jev-1.14"
DECISION_TIMEOUT_S = 10.0  # one decision model call; Jev answers in about half a second
_DECISION_RETRY_STATUS = {429, 500, 502, 503, 504, 529}  # answered once more: rate limit or an overloaded server


def _get_ai_gateway_key() -> str:
    return os.getenv("AI_GATEWAY_API_KEY", "").strip()


def _get_openai_api_key() -> str:
    return os.getenv("OPENAI_API_KEY", "").strip()


def chat_provider() -> str:
    """LLM_PROVIDER (openai | gateway | openrouter); defaults to gateway when AI_GATEWAY_API_KEY is set."""
    provider = os.getenv("LLM_PROVIDER", "").strip().lower()
    if provider:
        if provider not in _CHAT_PROVIDERS:
            raise ValueError(f"Unknown LLM_PROVIDER {provider!r}, expected one of {sorted(_CHAT_PROVIDERS)}")
        return provider
    return "gateway" if _get_ai_gateway_key() else "openai"


def chat_client_settings() -> tuple[str, str | None]:
    """(api_key, base_url) for the chat model provider; base_url None means api.openai.com."""
    provider = chat_provider()
    if provider == "openrouter":
        api_key, base_url, key_name = (os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENROUTER_KEY") or "").strip(), OPENROUTER_BASE_URL, "OPENROUTER_API_KEY"
    elif provider == "gateway":
        api_key, base_url, key_name = _get_ai_gateway_key(), VERCEL_AI_GATEWAY_BASE_URL, "AI_GATEWAY_API_KEY"
    else:
        api_key, base_url, key_name = _get_openai_api_key(), os.getenv("OPENAI_BASE_URL") or None, "OPENAI_API_KEY"
    if not api_key:
        raise RuntimeError(f"{key_name} is required for LLM_PROVIDER={provider}")
    return api_key, base_url


def using_ai_gateway() -> bool:
    return chat_provider() == "gateway"


def resolve_model_name(model_name: str) -> str:
    normalized = model_name.strip()
    if not normalized:
        raise ValueError("Model name cannot be empty")

    if chat_provider() in {"gateway", "openrouter"}:
        # Both route on "vendor/model" ids
        return normalized if "/" in normalized else f"openai/{normalized}"

    if normalized.startswith("openai/"):
        return normalized.split("/", 1)[1]

    return normalized


def build_responses_input(messages: Iterable[Any]) -> list[dict[str, str]]:
    response_input: list[dict[str, str]] = []

    for message in messages:
        if isinstance(message, dict):
            role = message.get("role")
            content = message.get("content")
        else:
            role = getattr(message, "role", None)
            content = getattr(message, "content", None)

        if role not in {"user", "assistant", "system", "developer"}:
            continue
        if not isinstance(content, str) or not content.strip():
            continue

        response_input.append({"role": role, "content": content})

    return response_input


def get_response_output_text(response: Any) -> str:
    output_text = getattr(response, "output_text", "")
    return output_text if isinstance(output_text, str) else ""


def get_openai_client() -> OpenAI:
    api_key, base_url = chat_client_settings()
    # The SDK default (600 s per read, 2 retries) let a stalled OpenRouter stream block a benchmark worker for
    # 30 min; LLM_TIMEOUT_S bounds the wait for each response / stream chunk, not the whole answer
    return OpenAI(api_key=api_key, base_url=base_url, timeout=float(os.getenv("LLM_TIMEOUT_S", "180")), max_retries=1)


def decision_model() -> str:
    """The decision model's id: DECISION_MODEL, else DEFAULT_DECISION_MODEL."""
    return os.getenv("DECISION_MODEL", "").strip() or DEFAULT_DECISION_MODEL


def ask_decision_model(state: Any, questions: dict[str, dict],
                       timeout_s: float = DECISION_TIMEOUT_S) -> dict[str, dict]:
    """Ask the decision model `questions` about `state` (System One format: a question's `instructions` name state
    fields in backticks; types "noul" (yes/no), "choice" and "score") and return its answers by question name, e.g.
    {"supported": {"type": "noul", "noul": 0.87}}. A rate limit or server error (429, 5xx) is asked once more.
    Raises RuntimeError without an OpenRouter key and httpx.HTTPError when the call fails or takes longer than
    `timeout_s`."""
    key = (os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENROUTER_KEY") or "").strip()
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is required for the decision model")
    body = {"model": decision_model(), "state": state, "questions": questions}
    response = httpx.post(SYSTEM_ONE_URL, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=timeout_s)
    if response.status_code in _DECISION_RETRY_STATUS:
        response = httpx.post(SYSTEM_ONE_URL, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=timeout_s)
    response.raise_for_status()
    return response.json()["answers"]

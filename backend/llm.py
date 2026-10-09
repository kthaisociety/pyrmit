import os
from typing import Any, Iterable

from openai import OpenAI

VERCEL_AI_GATEWAY_BASE_URL = "https://ai-gateway.vercel.sh/v1"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_CHAT_PROVIDERS = {"openai", "gateway", "openrouter"}


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
    return OpenAI(api_key=api_key, base_url=base_url)

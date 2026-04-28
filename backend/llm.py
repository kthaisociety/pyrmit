import os
from typing import Any, Iterable

from openai import OpenAI

VERCEL_AI_GATEWAY_BASE_URL = "https://ai-gateway.vercel.sh/v1"


def _get_ai_gateway_key() -> str:
    return os.getenv("AI_GATEWAY_API_KEY", "").strip()


def _get_openai_api_key() -> str:
    return os.getenv("OPENAI_API_KEY", "").strip()


def using_ai_gateway() -> bool:
    return bool(_get_ai_gateway_key())


def resolve_model_name(model_name: str) -> str:
    normalized = model_name.strip()
    if not normalized:
        raise ValueError("Model name cannot be empty")

    if using_ai_gateway():
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
    ai_gateway_key = _get_ai_gateway_key() or None
    openai_api_key = _get_openai_api_key() or None

    if ai_gateway_key:
        return OpenAI(
            api_key=ai_gateway_key,
            base_url=VERCEL_AI_GATEWAY_BASE_URL,
        )

    if openai_api_key:
        return OpenAI(api_key=openai_api_key)

    raise RuntimeError(
        "LLM configuration missing. Set AI_GATEWAY_API_KEY for Vercel AI Gateway "
        "or OPENAI_API_KEY for direct OpenAI access."
    )

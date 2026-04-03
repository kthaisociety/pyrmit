import os

from openai import OpenAI

VERCEL_AI_GATEWAY_BASE_URL = "https://ai-gateway.vercel.sh/v1"


def get_openai_client() -> OpenAI:
    ai_gateway_key = os.getenv("AI_GATEWAY_API_KEY", "").strip() or None
    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip() or None

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

import os

from openai import OpenAI


class CloudflareGatewayOpenAI(OpenAI):
    def __init__(self, *, cf_aig_token: str, provider_api_key: str | None, base_url: str):
        self._provider_api_key = provider_api_key
        default_headers = {
            "cf-aig-authorization": f"Bearer {cf_aig_token}",
        }
        byok_alias = os.getenv("CF_AIG_BYOK_ALIAS")
        if byok_alias:
            default_headers["cf-aig-byok-alias"] = byok_alias
        super().__init__(
            api_key=provider_api_key or "cf-gateway-auth",
            base_url=base_url,
            default_headers=default_headers,
        )

    @property
    def auth_headers(self) -> dict[str, str]:
        if not self._provider_api_key:
            return {}
        return {"Authorization": f"Bearer {self._provider_api_key}"}


def using_cloudflare_ai_gateway() -> bool:
    return all(
        os.getenv(name)
        for name in ("CF_AIG_TOKEN", "CF_ACCOUNT_ID", "CF_GATEWAY_ID")
    )


def get_openai_client() -> OpenAI:
    provider_preference = os.getenv("LLM_PROVIDER", "").strip().lower()
    openai_api_key = os.getenv("OPENAI_API_KEY")
    cloudflare_available = using_cloudflare_ai_gateway()

    if provider_preference == "openai":
        if not openai_api_key:
            raise RuntimeError("LLM_PROVIDER=openai but OPENAI_API_KEY is not configured.")
        return OpenAI(api_key=openai_api_key)

    if provider_preference == "cloudflare":
        if not cloudflare_available:
            raise RuntimeError(
                "LLM_PROVIDER=cloudflare but CF_AIG_TOKEN, CF_ACCOUNT_ID, and CF_GATEWAY_ID are not fully configured."
            )
        account_id = os.environ["CF_ACCOUNT_ID"]
        gateway_id = os.environ["CF_GATEWAY_ID"]
        return CloudflareGatewayOpenAI(
            cf_aig_token=os.environ["CF_AIG_TOKEN"],
            provider_api_key=openai_api_key,
            base_url=f"https://gateway.ai.cloudflare.com/v1/{account_id}/{gateway_id}/openai",
        )

    if openai_api_key:
        return OpenAI(api_key=openai_api_key)

    if cloudflare_available:
        account_id = os.environ["CF_ACCOUNT_ID"]
        gateway_id = os.environ["CF_GATEWAY_ID"]
        return CloudflareGatewayOpenAI(
            cf_aig_token=os.environ["CF_AIG_TOKEN"],
            provider_api_key=None,
            base_url=f"https://gateway.ai.cloudflare.com/v1/{account_id}/{gateway_id}/openai",
        )

    raise RuntimeError(
        "LLM configuration missing. Set OPENAI_API_KEY for direct OpenAI access "
        "or set CF_AIG_TOKEN, CF_ACCOUNT_ID, and CF_GATEWAY_ID for Cloudflare AI Gateway."
    )

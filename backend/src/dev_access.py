import hashlib
import hmac
import os

from fastapi import Request

DEV_ACCESS_COOKIE_NAME = "dev_access_granted"
DEV_ACCESS_HEADER_NAMES = ("x-access-gate-password", "x-dev-access-password")
ACCESS_GATE_UNLOCK_PATH = "/api/access-gate/unlock"


def _access_gate_password() -> str:
    return (
        os.getenv("ACCESS_GATE_PASSWORD", "").strip()
        or os.getenv("DEV_ACCESS_PASSWORD", "").strip()
    )


def is_dev_access_enabled() -> bool:
    return bool(_access_gate_password())


def dev_access_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def access_gate_cookie_secure() -> bool:
    return str(
        os.getenv("ACCESS_GATE_COOKIE_SECURE", os.getenv("COOKIE_SECURE", "false"))
    ).lower() in {"1", "true", "yes", "on"}


def access_gate_cookie_samesite() -> str:
    value = str(
        os.getenv("ACCESS_GATE_COOKIE_SAMESITE", os.getenv("COOKIE_SAMESITE", "lax"))
    ).lower()
    if value not in {"lax", "strict", "none"}:
        return "lax"
    return value


def access_gate_cookie_domain() -> str | None:
    value = os.getenv("ACCESS_GATE_COOKIE_DOMAIN", "").strip()
    return value or None


def is_access_gate_exempt_path(path: str) -> bool:
    return path == ACCESS_GATE_UNLOCK_PATH


def request_has_dev_access(request: Request) -> bool:
    password = _access_gate_password()
    if not password:
        return True

    expected_hash = dev_access_hash(password)
    cookie_value = request.cookies.get(DEV_ACCESS_COOKIE_NAME, "")
    if cookie_value and hmac.compare_digest(cookie_value, expected_hash):
        return True

    header_value = ""
    for header_name in DEV_ACCESS_HEADER_NAMES:
        header_value = request.headers.get(header_name, "").strip()
        if header_value:
            break

    if not header_value:
        return False

    return hmac.compare_digest(header_value, password) or hmac.compare_digest(
        header_value, expected_hash
    )

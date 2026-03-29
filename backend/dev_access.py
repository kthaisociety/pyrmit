import hashlib
import os

from fastapi import Request

DEV_ACCESS_COOKIE_NAME = "dev_access_granted"
DEV_ACCESS_HEADER_NAME = "x-dev-access-password"


def _dev_access_password() -> str:
    return os.getenv("DEV_ACCESS_PASSWORD", "").strip()


def is_dev_access_enabled() -> bool:
    return bool(_dev_access_password())


def dev_access_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def request_has_dev_access(request: Request) -> bool:
    password = _dev_access_password()
    if not password:
        return True

    expected_hash = dev_access_hash(password)
    cookie_value = request.cookies.get(DEV_ACCESS_COOKIE_NAME, "")
    if cookie_value == expected_hash:
        return True

    header_value = request.headers.get(DEV_ACCESS_HEADER_NAME, "").strip()
    if not header_value:
        return False

    return header_value == password or header_value == expected_hash

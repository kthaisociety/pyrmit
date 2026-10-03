import hmac

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel

from dev_access import (
    DEV_ACCESS_COOKIE_NAME,
    _access_gate_password,
    access_gate_cookie_domain,
    access_gate_cookie_samesite,
    access_gate_cookie_secure,
    dev_access_hash,
)

router = APIRouter()


class AccessGateUnlockRequest(BaseModel):
    password: str


@router.post("/unlock")
def unlock_access_gate(request: AccessGateUnlockRequest, response: Response):
    configured_password = _access_gate_password()
    if not configured_password:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Access gate is not configured",
        )

    submitted_password = request.password.strip()
    if not submitted_password:
        raise HTTPException(status_code=400, detail="Password is required")

    if not hmac.compare_digest(submitted_password, configured_password):
        raise HTTPException(status_code=401, detail="Invalid access password")

    response.set_cookie(
        key=DEV_ACCESS_COOKIE_NAME,
        value=dev_access_hash(configured_password),
        httponly=True,
        secure=access_gate_cookie_secure(),
        samesite=access_gate_cookie_samesite(),
        domain=access_gate_cookie_domain(),
        path="/",
        max_age=60 * 60 * 12,
    )
    return {"ok": True}

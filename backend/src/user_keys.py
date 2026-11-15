"""Users' own OpenRouter keys (issue #108). A user can store their OpenRouter API key; their chat answers then run on
it (llm.openrouter_key), and the shared OPENROUTER_API_KEY pays when they have none.

The key is stored encrypted (Fernet) under API_KEY_ENCRYPTION_KEY, in user_api_keys with its last 4 characters, the
only part ever sent back to the browser. Without API_KEY_ENCRYPTION_KEY (or with an invalid one) the feature is off:
nothing can be saved and every call uses the shared key. API_KEY_ENCRYPTION_KEY may list several Fernet keys separated
by commas, to rotate: the first encrypts, all decrypt. A stored key that none of them decrypts counts as no key."""
import logging
import os
import re
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy.orm import Session

import models

logger = logging.getLogger(__name__)

ENCRYPTION_KEY_ENV = "API_KEY_ENCRYPTION_KEY"
OPENROUTER = "openrouter"
# OpenRouter keys look like "sk-or-v1-" + 64 hex characters; the check stays loose so a new key format still passes
_OPENROUTER_KEY = re.compile(r"sk-or-[A-Za-z0-9_-]{16,200}")


class InvalidApiKey(ValueError):
    """The text is not an OpenRouter key. The message never contains the text."""


def _cipher() -> MultiFernet | None:
    return _cipher_for(os.getenv(ENCRYPTION_KEY_ENV, ""))


@lru_cache(maxsize=4)  # per value: an invalid key is logged once, not on every request
def _cipher_for(raw: str) -> MultiFernet | None:
    keys = [part.strip() for part in raw.split(",") if part.strip()]
    if not keys:
        return None
    try:
        return MultiFernet([Fernet(key) for key in keys])
    except (ValueError, TypeError):
        # Never log the value itself
        logger.error("%s is not a valid Fernet key (32 url-safe base64-encoded bytes): users' own API keys are off",
                     ENCRYPTION_KEY_ENV)
        return None


def enabled() -> bool:
    """Whether users can store their own key: API_KEY_ENCRYPTION_KEY is set and valid."""
    return _cipher() is not None


def encrypt(api_key: str) -> str:
    cipher = _cipher()
    if cipher is None:
        raise RuntimeError(f"{ENCRYPTION_KEY_ENV} is not set")
    return cipher.encrypt(api_key.encode()).decode()


def decrypt(token: str) -> str | None:
    """The key, or None when the feature is off or the token does not decrypt (rotated or wrong encryption key)."""
    cipher = _cipher()
    if cipher is None:
        return None
    try:
        return cipher.decrypt(token.encode()).decode()
    except InvalidToken:
        logger.warning("A stored user API key does not decrypt with %s: using the shared key", ENCRYPTION_KEY_ENV)
        return None


def normalise(api_key: str) -> str:
    """The pasted key without surrounding whitespace; InvalidApiKey when it is not an OpenRouter key."""
    key = api_key.strip()
    if not _OPENROUTER_KEY.fullmatch(key):
        raise InvalidApiKey("That is not an OpenRouter API key: it starts with sk-or-")
    return key


def _row(db: Session, user_id: str) -> models.UserApiKey | None:
    return db.get(models.UserApiKey, (user_id, OPENROUTER))


def status(db: Session, user_id: str) -> dict:
    """{"enabled", "has_key", "last4"}: never the key. A key that no longer decrypts is reported as no key."""
    row = _row(db, user_id) if enabled() else None
    usable = row is not None and decrypt(row.encrypted_key) is not None
    return {"enabled": enabled(), "has_key": usable, "last4": row.last4 if usable else None}


def save(db: Session, user_id: str, api_key: str) -> None:
    """Store (or replace) the user's key, encrypted. InvalidApiKey for a text that is not a key."""
    key = normalise(api_key)
    row = _row(db, user_id)
    if row is None:
        row = models.UserApiKey(user_id=user_id, provider=OPENROUTER)
        db.add(row)
    row.encrypted_key = encrypt(key)
    row.last4 = key[-4:]
    db.commit()


def delete(db: Session, user_id: str) -> None:
    row = _row(db, user_id)
    if row is not None:
        db.delete(row)
        db.commit()


def key_for(db: Session, user_id: str) -> str | None:
    """The user's own OpenRouter key, or None: the feature is off, they have none, or it does not decrypt."""
    if not enabled():
        return None
    row = _row(db, user_id)
    return decrypt(row.encrypted_key) if row is not None else None

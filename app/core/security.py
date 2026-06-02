from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from app.core.config import settings


def create_access_token(subject: str, expires_in_seconds: int = 60 * 60 * 24) -> str:
    now = int(time.time())
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + expires_in_seconds,
    }
    signing_input = ".".join(
        [
            _base64url_json({"alg": "HS256", "typ": "JWT"}),
            _base64url_json(payload),
        ]
    )
    signature = hmac.new(_jwt_secret(), signing_input.encode("utf-8"), hashlib.sha256).digest()
    return f"{signing_input}.{_base64url_bytes(signature)}"


def decode_access_token(token: str) -> dict[str, Any] | None:
    parts = token.split(".")
    if len(parts) != 3:
        return None

    signing_input = ".".join(parts[:2])
    expected_signature = hmac.new(_jwt_secret(), signing_input.encode("utf-8"), hashlib.sha256).digest()
    actual_signature = _base64url_decode(parts[2])
    if not hmac.compare_digest(expected_signature, actual_signature):
        return None

    try:
        payload = json.loads(_base64url_decode(parts[1]).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None

    expires_at = payload.get("exp")
    if not isinstance(expires_at, int) or expires_at < int(time.time()):
        return None
    return payload


def _jwt_secret() -> bytes:
    secret = settings.jwt_secret_key or "tasteforge-local-dev-secret"
    return secret.encode("utf-8")


def _base64url_json(value: dict[str, Any]) -> str:
    return _base64url_bytes(json.dumps(value, separators=(",", ":")).encode("utf-8"))


def _base64url_bytes(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


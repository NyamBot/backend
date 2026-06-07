from __future__ import annotations

import secrets
import threading
import time


class AuthCodeStore:
    def __init__(self, ttl_seconds: int = 60) -> None:
        self.ttl_seconds = ttl_seconds
        self._tokens: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def issue(self, token: str) -> str:
        code = secrets.token_urlsafe(32)
        expires_at = time.time() + self.ttl_seconds
        with self._lock:
            self._cleanup_locked()
            self._tokens[code] = (token, expires_at)
        return code

    def consume(self, code: str) -> str | None:
        with self._lock:
            self._cleanup_locked()
            stored = self._tokens.pop(code, None)
        if not stored:
            return None

        token, expires_at = stored
        if expires_at < time.time():
            return None
        return token

    def _cleanup_locked(self) -> None:
        now = time.time()
        expired_codes = [code for code, (_, expires_at) in self._tokens.items() if expires_at < now]
        for code in expired_codes:
            self._tokens.pop(code, None)


auth_code_store = AuthCodeStore()

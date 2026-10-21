"""Admin login: password check, in-memory sessions and a lock after too many wrong passwords."""

from __future__ import annotations

import hashlib
import hmac
import math
import secrets
import threading
import time
from typing import Callable

from . import config

Clock = Callable[[], float]


def password_matches(supplied: str, password: str) -> bool:
    """Compare in constant time; an empty password never matches."""
    if not password:
        return False
    return hmac.compare_digest(hashlib.sha256(supplied.encode()).digest(), hashlib.sha256(password.encode()).digest())


class SessionStore:
    """Login sessions. They live in memory, so restarting the server logs the admin out."""

    def __init__(self, lifetime: float = config.SESSION_SECONDS, clock: Clock = time.time) -> None:
        """Create an empty store; `clock` can be replaced in tests."""
        self._expires: dict[str, float] = {}
        self._lifetime = lifetime
        self._clock = clock
        self._lock = threading.Lock()  # routes run in several worker threads

    def create(self) -> str:
        """Start a session and return its token."""
        token = secrets.token_hex(32)
        with self._lock:
            self._expires[token] = self._clock() + self._lifetime
        return token

    def is_valid(self, token: str | None) -> bool:
        """Whether the token belongs to a session that has not expired."""
        if not token:
            return False
        with self._lock:
            expires = self._expires.get(token)
            if expires is None:
                return False
            if expires < self._clock():
                del self._expires[token]
                return False
            return True

    def end(self, token: str | None) -> None:
        """End a session (logging out twice is fine)."""
        if token:
            with self._lock:
                self._expires.pop(token, None)


class LoginLimiter:
    """Locks a visitor out for a while after too many wrong passwords."""

    def __init__(
        self,
        max_attempts: int = config.MAX_LOGIN_ATTEMPTS,
        lock_seconds: float = config.LOGIN_LOCK_SECONDS,
        clock: Clock = time.time,
    ) -> None:
        """Create an empty limiter; `clock` can be replaced in tests."""
        self._failures: dict[str, tuple[int, float]] = {}  # ip -> (count, time of first failure)
        self._max_attempts = max_attempts
        self._lock_seconds = lock_seconds
        self._clock = clock
        self._lock = threading.Lock()  # routes run in several worker threads

    def minutes_locked(self, ip: str) -> int:
        """Minutes until this visitor may try again; 0 when not locked."""
        now = self._clock()
        with self._lock:
            count, since = self._failures.get(ip, (0, now))
            if now - since > self._lock_seconds:
                self._failures.pop(ip, None)
                return 0
        if count < self._max_attempts:
            return 0
        return math.ceil((since + self._lock_seconds - now) / 60)

    def failed(self, ip: str) -> None:
        """Count a wrong password."""
        with self._lock:
            count, since = self._failures.get(ip, (0, self._clock()))
            self._failures[ip] = (count + 1, since)

    def succeeded(self, ip: str) -> None:
        """Forget earlier wrong passwords after a successful login."""
        with self._lock:
            self._failures.pop(ip, None)

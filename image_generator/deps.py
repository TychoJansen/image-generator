"""FastAPI dependencies: settings, a database connection per request and the admin check."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request

from . import config
from .auth import LoginLimiter, SessionStore
from .config import Settings
from .db import Database
from .errors import ApiError


def get_settings(request: Request) -> Settings:
    """The app's settings (set in create_app)."""
    return request.app.state.settings


def get_sessions(request: Request) -> SessionStore:
    """The admin sessions."""
    return request.app.state.sessions


def get_limiter(request: Request) -> LoginLimiter:
    """The lock after too many wrong passwords."""
    return request.app.state.limiter


def get_db(settings: Annotated[Settings, Depends(get_settings)]) -> Iterator[Database]:
    """A database connection for one request, closed afterwards."""
    db = Database(settings.db_path)
    try:
        yield db
    finally:
        db.close()


def is_admin(request: Request) -> bool:
    """Whether this browser is logged in as admin."""
    return get_sessions(request).is_valid(request.cookies.get(config.SESSION_COOKIE))


def require_admin(request: Request) -> None:
    """Stop the request with 401 unless the admin is logged in."""
    if not is_admin(request):
        raise ApiError(401, "Log eerst in op het tabblad Genereren.")


def client_ip(request: Request) -> str:
    """The visitor's IP; behind cloudflared it is in the CF-Connecting-IP header."""
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "unknown")


SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[Database, Depends(get_db)]
AdminOnly = Depends(require_admin)

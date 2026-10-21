"""Logging in and out as admin."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .. import config
from ..auth import LoginLimiter, SessionStore, password_matches
from ..deps import SettingsDep, client_ip, get_limiter, get_sessions, is_admin
from ..errors import ApiError
from ..schemas import LoginIn

router = APIRouter(prefix="/api")

SessionsDep = Annotated[SessionStore, Depends(get_sessions)]
LimiterDep = Annotated[LoginLimiter, Depends(get_limiter)]


@router.get("/session")
def session(request: Request) -> dict[str, bool]:
    """Whether this browser is logged in as admin."""
    return {"admin": is_admin(request)}


@router.post("/login")
def login(
    body: LoginIn, request: Request, settings: SettingsDep, sessions: SessionsDep, limiter: LimiterDep
) -> JSONResponse:
    """Log in with the admin password (5 wrong tries lock the visitor out for 15 minutes)."""
    if not settings.admin_password:
        raise ApiError(503, "ADMIN_PASSWORD is niet ingesteld in .env. Vul het in en herstart de server.")
    ip = client_ip(request)
    minutes = limiter.minutes_locked(ip)
    if minutes:
        raise ApiError(429, f"Te vaak een verkeerd wachtwoord. Probeer het over {minutes} minuut/minuten opnieuw.")
    if not password_matches(body.password, settings.admin_password):
        limiter.failed(ip)
        raise ApiError(401, "Verkeerd wachtwoord.")
    limiter.succeeded(ip)
    response = JSONResponse({"admin": True})
    response.set_cookie(
        config.SESSION_COOKIE,
        sessions.create(),
        max_age=config.SESSION_SECONDS,
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https",
    )
    return response


@router.post("/logout")
def logout(request: Request, sessions: SessionsDep) -> JSONResponse:
    """End the admin session."""
    sessions.end(request.cookies.get(config.SESSION_COOKIE))
    response = JSONResponse({"admin": False})
    response.delete_cookie(config.SESSION_COOKIE)
    return response

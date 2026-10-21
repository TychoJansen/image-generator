"""The FastAPI app: wires the routers, error handlers and the static page together."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .auth import LoginLimiter, SessionStore
from .config import Settings
from .db import init_db
from .errors import ApiError, api_error_handler, validation_error_handler
from .routers import context, generate, images, photos, session, share, words


async def limit_body_size(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """Refuse bodies larger than one photo upload, before they are read."""
    length = request.headers.get("content-length", "")
    if length.isdigit() and int(length) > config.MAX_BODY_BYTES:
        return JSONResponse({"error": "Het verzoek is te groot."}, status_code=413)
    return await call_next(request)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app; the tests pass their own settings (a temporary data folder, fake keys)."""
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # Create the data folder, its subfolders and the database tables once at startup.
        settings.images_dir.mkdir(parents=True, exist_ok=True)
        settings.photos_dir.mkdir(parents=True, exist_ok=True)
        init_db(settings.db_path)
        yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.sessions = SessionStore()
    app.state.limiter = LoginLimiter()

    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.middleware("http")(limit_body_size)

    for module in (session, words, context, photos, images, share, generate):
        app.include_router(module.router)

    @app.get("/generate")
    def old_generate_page() -> RedirectResponse:
        """Old bookmarks of the separate generate page."""
        return RedirectResponse("/#generate", status_code=302)

    # Last, so the routes above win: index.html, app.js and style.css. All data lives outside public/.
    app.mount("/", StaticFiles(directory=settings.public_dir, html=True), name="public")
    return app

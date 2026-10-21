"""Errors are sent to the browser as {"error": "<Dutch message>"}, which the page shows as is."""

from __future__ import annotations

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

GENERIC_INVALID = "Ongeldige invoer."


class ApiError(Exception):
    """An error with an HTTP status and a message for the admin or visitor."""

    def __init__(self, status: int, message: str) -> None:
        """Remember the HTTP status and the message."""
        super().__init__(message)
        self.status = status
        self.message = message


async def api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
    """Send an ApiError as {"error": message}."""
    return JSONResponse({"error": exc.message}, status_code=exc.status)


async def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """Send a failed request model as 400 {"error": message}.

    The models raise ValueError with a Dutch message (e.g. "Het woord mag niet leeg zijn."); that message is used.
    Other problems (invalid JSON, a list instead of an object) get a generic message.
    """
    for error in exc.errors():
        if error.get("type") == "value_error":
            return JSONResponse({"error": str(error["ctx"]["error"])}, status_code=400)
    return JSONResponse({"error": GENERIC_INVALID}, status_code=400)

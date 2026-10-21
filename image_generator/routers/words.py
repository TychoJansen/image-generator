"""Words: anyone can add them, only the admin can list or delete them."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response

from ..deps import AdminOnly, DbDep
from ..errors import ApiError
from ..schemas import WordIn, to_id

router = APIRouter(prefix="/api/words")


@router.get("", dependencies=[AdminOnly])
def list_words(db: DbDep) -> list[dict[str, Any]]:
    """All words, newest first."""
    return db.list_words()


@router.post("", status_code=201)
def add_word(body: WordIn, db: DbDep) -> dict[str, str]:
    """Add a word or short phrase (public)."""
    db.insert_word(body.text)
    return {"text": body.text}


@router.delete("", dependencies=[AdminOnly])
def delete_all_words(db: DbDep) -> dict[str, int]:
    """Remove every word in one go, e.g. to start fresh."""
    return {"deleted": db.delete_all_words()}


@router.delete("/{word_id}", dependencies=[AdminOnly], status_code=204)
def delete_word(word_id: str, db: DbDep) -> Response:
    """Delete one word."""
    parsed = to_id(word_id)
    if parsed is None:
        raise ApiError(400, "Ongeldig woord-id.")
    if not db.delete_word(parsed):
        raise ApiError(404, "Woord niet gevonden.")
    return Response(status_code=204)

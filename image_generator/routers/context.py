"""Context ("Altijd meesturen" + glossary) and the word cloud variants (admin only)."""

from __future__ import annotations

from fastapi import APIRouter

from ..deps import AdminOnly, DbDep
from ..schemas import ContextIn, MergesIn

router = APIRouter(prefix="/api", dependencies=[AdminOnly])


@router.get("/context")
def get_context(db: DbDep) -> dict[str, str]:
    """The saved context and glossary."""
    return {"context": db.get_setting("context"), "glossary": db.get_setting("glossary")}


@router.put("/context")
def save_context(body: ContextIn, db: DbDep) -> dict[str, str]:
    """Save the context and glossary."""
    db.set_setting("context", body.context)
    db.set_setting("glossary", body.glossary)
    return {"context": body.context, "glossary": body.glossary}


@router.get("/merges")
def get_merges(db: DbDep) -> dict[str, str]:
    """The saved word cloud variants."""
    return {"merges": db.get_setting("merges")}


@router.put("/merges")
def save_merges(body: MergesIn, db: DbDep) -> dict[str, str]:
    """Save the word cloud variants."""
    db.set_setting("merges", body.merges)
    return {"merges": body.merges}

"""Choosing words and photos, the prompt preview and generating an image (admin only)."""

from __future__ import annotations

import base64
import binascii
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from ..config import Settings
from ..db import Database, Row
from ..deps import AdminOnly, DbDep, SettingsDep
from ..errors import ApiError
from ..prompt import build_prompt, match_glossary
from ..providers import GenerationError, ReferencePhoto, generate_with_cloudflare, generate_with_openai
from ..schemas import SelectionIn
from ..storage import large_name, save_image

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", dependencies=[AdminOnly])


@dataclass(frozen=True)
class Selection:
    """A checked selection: the photos to send and the prompt."""

    provider: str
    quality: str
    photos: list[Row]
    prompt: str


def read_selection(db: Database, body: SelectionIn) -> Selection:
    """Look up the chosen words and photos and build the prompt."""
    words = [db.get_word(word_id) for word_id in body.ids]
    if None in words:
        raise ApiError(400, "Een of meer geselecteerde woorden bestaan niet meer. Herlaad de pagina.")
    photos = [db.get_photo(photo_id) for photo_id in body.photo_ids]
    if None in photos:
        raise ApiError(400, "Een of meer geselecteerde foto's bestaan niet meer. Herlaad de pagina.")

    # Words are optional, but there must be something to make an image of.
    always = db.get_setting("context")
    if not words and not photos and not always:
        raise ApiError(
            400,
            "Er is niets om een afbeelding van te maken. "
            'Kies minstens één woord, een foto, of vul "Altijd meesturen" in bij Context.',
        )

    texts = [word["text"] for word in words]
    captions = [photo["caption"] for photo in photos]
    glossary = match_glossary(db.get_setting("glossary"), texts + captions)
    first_image_number = 1 if body.provider == "openai" else 0
    prompt = build_prompt(
        texts, captions, always, glossary, first_image_number, body.year, body.change_age, date.today().year
    )
    return Selection(body.provider, body.quality, photos, prompt)


def load_photos(settings: Settings, photos: list[Row], large: bool) -> list[ReferencePhoto]:
    """The photo files to send; OpenAI gets the large copy when there is one."""
    result = []
    for photo in photos:
        path = settings.photos_dir / photo["filename"]
        if large and (settings.photos_dir / large_name(photo["filename"])).exists():
            path = settings.photos_dir / large_name(photo["filename"])
        result.append(ReferencePhoto(photo["filename"], path.read_bytes()))
    return result


@router.get("/providers")
def providers(settings: SettingsDep) -> dict[str, Any]:
    """Which image services are set up in .env."""
    return {
        "cloudflare": not settings.missing_cloudflare(),
        "openai": bool(settings.openai_api_key),
        "openaiModel": settings.openai_model,
    }


@router.post("/prompt")
def preview_prompt(body: SelectionIn, db: DbDep) -> dict[str, str]:
    """The prompt that would be sent, without generating (and paying for) an image."""
    return {"prompt": read_selection(db, body).prompt}


@router.post("/generate")
async def generate(body: SelectionIn, db: DbDep, settings: SettingsDep) -> dict[str, str]:
    """Generate an image with Cloudflare or OpenAI and save it in the gallery.

    This route is async because the AI service can take a minute; database and file work runs in worker threads so
    other requests are not blocked meanwhile.
    """
    selection = await run_in_threadpool(read_selection, db, body)
    use_openai = selection.provider == "openai"
    photos = await run_in_threadpool(load_photos, settings, selection.photos, use_openai)
    try:
        if use_openai:
            result = await generate_with_openai(settings, selection.prompt, photos, selection.quality)
        else:
            result = await generate_with_cloudflare(settings, selection.prompt, photos)
        image = base64.b64decode(result.b64, validate=True)
    except GenerationError as err:
        logger.warning("Image generation failed: %s", err)
        raise ApiError(502, str(err)) from err
    except binascii.Error as err:
        raise ApiError(502, "Het antwoord van de AI-dienst bevatte geen geldige afbeelding.") from err

    filename = await run_in_threadpool(save_image, settings.images_dir, image)
    return {"prompt": selection.prompt, "model": result.model, "filename": filename, "url": f"/images/{filename}"}

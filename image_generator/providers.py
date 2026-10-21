"""Calling the image services: Cloudflare Workers AI (free) and OpenAI (paid)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import httpx

from . import config
from .config import Settings


class GenerationError(Exception):
    """An error with a message that can be shown to the admin as is."""


@dataclass(frozen=True)
class ReferencePhoto:
    """A reference photo to send along with the prompt."""

    filename: str
    data: bytes


@dataclass(frozen=True)
class GeneratedImage:
    """The model that was used and the image as base64."""

    model: str
    b64: str


def http_client() -> httpx.AsyncClient:
    """HTTP client for the image services (replaced by a fake in the tests)."""
    return httpx.AsyncClient(timeout=config.HTTP_TIMEOUT_SECONDS)


async def _post(service: str, url: str, **kwargs: Any) -> tuple[int, dict]:
    """POST and return (status code, JSON body); a body that is not a JSON object becomes {}."""
    try:
        async with http_client() as client:
            response = await client.post(url, **kwargs)
    except httpx.HTTPError as err:
        raise GenerationError(f"Kan de {service} API niet bereiken: {err}") from err
    try:
        body = response.json()
    except ValueError:
        body = None
    return response.status_code, body if isinstance(body, dict) else {}


def cloudflare_error_message(status: int, body: dict) -> str:
    """Turn a failed Cloudflare response into a readable message."""
    errors = [e for e in body.get("errors") or [] if isinstance(e, dict)]
    text = "; ".join(
        f"{e.get('message')} (code {e['code']})" if e.get("code") else str(e.get("message")) for e in errors
    )
    daily_limit = status == 429 or any(
        e.get("code") == 4006 or re.search(r"daily free allocation|neurons", str(e.get("message") or ""), re.I)
        for e in errors
    )
    if daily_limit:
        return (
            "Dagelijkse gratis limiet van Workers AI bereikt. Probeer het morgen opnieuw (de limiet wordt om "
            f"00:00 UTC gereset). Melding van Cloudflare: {text or f'HTTP {status}'}"
        )
    if status in (401, 403):
        return (
            f"Cloudflare heeft de inloggegevens geweigerd (HTTP {status}). Controleer CLOUDFLARE_ACCOUNT_ID en "
            f"CLOUDFLARE_API_TOKEN in .env. Melding van Cloudflare: {text or 'geen details'}"
        )
    return f"Fout van de Cloudflare API (HTTP {status}): {text or 'geen details'}"


def openai_error_message(status: int, body: dict, model: str) -> str:
    """Turn a failed OpenAI response into a readable message."""
    error = body.get("error") if isinstance(body.get("error"), dict) else {}
    text = error.get("message") or "geen details"
    if status == 401:
        return f"OpenAI heeft de API-sleutel geweigerd. Controleer OPENAI_API_KEY in .env. Melding van OpenAI: {text}"
    if error.get("code") in ("insufficient_quota", "billing_hard_limit_reached"):
        return (
            "Je OpenAI-tegoed of budgetlimiet is bereikt. Vul je tegoed aan of verhoog je limiet op "
            f"platform.openai.com. Melding van OpenAI: {text}"
        )
    if status == 429:
        return (
            "Te veel verzoeken naar OpenAI in korte tijd. Wacht even en probeer het opnieuw. "
            f"Melding van OpenAI: {text}"
        )
    if error.get("code") == "moderation_blocked" or re.search(r"safety|moderation", text, re.I):
        return (
            "OpenAI heeft dit verzoek geweigerd vanwege het veiligheidsbeleid. Pas de woorden, context of foto's aan. "
            f"Melding van OpenAI: {text}"
        )
    if status == 403 or re.search(r"verif", text, re.I):
        return (
            f"Je OpenAI-account heeft (nog) geen toegang tot {model}. Mogelijk moet je organisatie eerst geverifieerd "
            f"worden op platform.openai.com. Melding van OpenAI: {text}"
        )
    return f"Fout van de OpenAI API (HTTP {status}): {text}"


async def generate_with_cloudflare(settings: Settings, prompt: str, photos: list[ReferencePhoto]) -> GeneratedImage:
    """FLUX.1 schnell (JSON) for text only; FLUX.2 klein (multipart, small photos) with photos."""
    missing = settings.missing_cloudflare()
    if missing:
        raise GenerationError(
            f"Cloudflare-gegevens ontbreken: {', '.join(missing)}. Vul ze in het .env-bestand in en herstart de server."
        )
    model = config.CF_PHOTO_MODEL if photos else config.CF_MODEL
    url = f"https://api.cloudflare.com/client/v4/accounts/{settings.cloudflare_account_id}/ai/run/{model}"
    headers = {"Authorization": f"Bearer {settings.cloudflare_api_token}"}
    if photos:
        files = [(f"input_image_{i}", (p.filename, p.data, "image/jpeg")) for i, p in enumerate(photos)]
        data = {"prompt": prompt, "width": "1024", "height": "1024"}
        status, body = await _post("Cloudflare", url, headers=headers, data=data, files=files)
    else:
        status, body = await _post("Cloudflare", url, headers=headers, json={"prompt": prompt, "steps": 4})
    if not 200 <= status < 300 or body.get("success") is False:
        raise GenerationError(cloudflare_error_message(status, body))
    image = (body.get("result") or {}).get("image")
    if not image:
        raise GenerationError("Fout van de Cloudflare API: het antwoord bevatte geen afbeelding.")
    return GeneratedImage(model, image)


async def generate_with_openai(
    settings: Settings, prompt: str, photos: list[ReferencePhoto], quality: str
) -> GeneratedImage:
    """Use /images/generations for text only, /images/edits with the photos as reference images."""
    if not settings.openai_api_key:
        raise GenerationError("OPENAI_API_KEY ontbreekt. Vul hem in het .env-bestand in en herstart de server.")
    model = settings.openai_model
    headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
    params = {
        "model": model,
        "prompt": prompt,
        "size": "1024x1024",
        "quality": quality,
        "output_format": "jpeg",
        "n": 1,
    }
    if photos:
        if model in config.OPENAI_FIDELITY_MODELS:
            params["input_fidelity"] = "high"
        files = [("image[]", (p.filename, p.data, "image/jpeg")) for p in photos]
        data = {key: str(value) for key, value in params.items()}
        status, body = await _post(
            "OpenAI", "https://api.openai.com/v1/images/edits", headers=headers, data=data, files=files
        )
    else:
        status, body = await _post(
            "OpenAI", "https://api.openai.com/v1/images/generations", headers=headers, json=params
        )
    if not 200 <= status < 300:
        raise GenerationError(openai_error_message(status, body, model))
    items = body.get("data") or [{}]
    image = items[0].get("b64_json") if isinstance(items[0], dict) else None
    if not image:
        raise GenerationError("Fout van de OpenAI API: het antwoord bevatte geen afbeelding.")
    return GeneratedImage(model, image)

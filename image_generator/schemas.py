"""Pydantic models for the request bodies, with the Dutch messages the page shows.

Fields are lenient on purpose (like the page expects): a missing or non-text field counts as empty text, and ids
that are not whole numbers become None (and are then reported as "no longer exists").
"""

from __future__ import annotations

import base64
import binascii
import re
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

from . import config

JPEG_DATA_URL = re.compile(r"data:image/jpeg;base64,([A-Za-z0-9+/=]+)")


def as_text(value: Any) -> str:
    """Trimmed text; anything that is not a string becomes ""."""
    return value.strip() if isinstance(value, str) else ""


def as_raw_text(value: Any) -> str:
    """Text as given (not trimmed, e.g. a password); anything that is not a string becomes ""."""
    return value if isinstance(value, str) else ""


def to_id(value: Any) -> int | None:
    """An id from JSON or the URL; None when it is not a whole number."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def as_ids(value: Any) -> list[int | None]:
    """A list of ids; anything that is not a list becomes []."""
    return [to_id(item) for item in value] if isinstance(value, list) else []


def decode_jpeg(data_url: Any) -> bytes | None:
    """The bytes of a "data:image/jpeg;base64,..." string, or None when it is not one."""
    match = JPEG_DATA_URL.fullmatch(data_url) if isinstance(data_url, str) else None
    if not match:
        return None
    try:
        return base64.b64decode(match[1], validate=True)
    except binascii.Error:
        return None


def as_photo(value: Any) -> bytes:
    """The small photo (for Cloudflare, under 512x512) that the browser made."""
    data = decode_jpeg(value)
    if data is None:
        raise ValueError("Ongeldige foto. Kies een JPG- of PNG-bestand.")
    if len(data) > config.MAX_PHOTO_BYTES:
        raise ValueError("De foto is te groot.")
    return data


def as_large_photo(value: Any) -> bytes | None:
    """The optional larger copy (up to 1024px, for OpenAI)."""
    if not value:
        return None
    data = decode_jpeg(value)
    if data is None or len(data) > config.MAX_PHOTO_BYTES:
        raise ValueError("De grote versie van de foto is ongeldig of te groot.")
    return data


Text = Annotated[str, BeforeValidator(as_text)]
RawText = Annotated[str, BeforeValidator(as_raw_text)]
Ids = Annotated[list[int | None], BeforeValidator(as_ids)]


class WordIn(BaseModel):
    """A word or short phrase from a guest."""

    text: Text = Field(default="", validate_default=True)

    @field_validator("text")
    @classmethod
    def check_text(cls, text: str) -> str:
        """Not empty and not too long."""
        if not text:
            raise ValueError("Het woord mag niet leeg zijn.")
        if len(text) > config.MAX_WORD_LENGTH:
            raise ValueError(f"Een woord mag maximaal {config.MAX_WORD_LENGTH} tekens lang zijn.")
        return text


class LoginIn(BaseModel):
    """The admin password."""

    password: RawText = ""


class ContextIn(BaseModel):
    """The "Altijd meesturen" text and the glossary."""

    context: Text = ""
    glossary: Text = ""

    @field_validator("context")
    @classmethod
    def check_context(cls, context: str) -> str:
        """Not too long."""
        if len(context) > config.MAX_CONTEXT_LENGTH:
            raise ValueError(f'"Altijd meesturen" mag maximaal {config.MAX_CONTEXT_LENGTH} tekens lang zijn.')
        return context

    @field_validator("glossary")
    @classmethod
    def check_glossary(cls, glossary: str) -> str:
        """Not too long."""
        if len(glossary) > config.MAX_GLOSSARY_LENGTH:
            raise ValueError(f"De woordenlijst mag maximaal {config.MAX_GLOSSARY_LENGTH} tekens lang zijn.")
        return glossary


class MergesIn(BaseModel):
    """Word cloud variants, e.g. "paarden = paard, paardjes"."""

    merges: Text = ""

    @field_validator("merges")
    @classmethod
    def check_merges(cls, merges: str) -> str:
        """Not too long."""
        if len(merges) > config.MAX_MERGES_LENGTH:
            raise ValueError(f"De lijst mag maximaal {config.MAX_MERGES_LENGTH} tekens lang zijn.")
        return merges


class PhotoIn(BaseModel):
    """An uploaded reference photo; the browser already resized it to JPEG."""

    image: Annotated[bytes, BeforeValidator(as_photo)] = Field(default=b"", validate_default=True)
    caption: Text = ""
    large: Annotated[bytes | None, BeforeValidator(as_large_photo)] = None

    @field_validator("caption")
    @classmethod
    def check_caption(cls, caption: str) -> str:
        """Not too long."""
        if len(caption) > config.MAX_CAPTION_LENGTH:
            raise ValueError(f"De beschrijving mag maximaal {config.MAX_CAPTION_LENGTH} tekens lang zijn.")
        return caption


class SelectionIn(BaseModel):
    """What to generate: words, photos, the service and (for OpenAI) the quality."""

    model_config = ConfigDict(populate_by_name=True)

    ids: Ids = []
    photo_ids: Ids = Field(default=[], alias="photoIds")
    provider: Annotated[str, BeforeValidator(lambda v: "openai" if v == "openai" else "cloudflare")] = "cloudflare"
    quality: Annotated[str, BeforeValidator(lambda v: v if v in config.OPENAI_QUALITIES else "medium")] = "medium"
    # Time machine: show the scene in this year (negative = BC); empty = a normal image.
    year: Annotated[int | None, BeforeValidator(lambda v: None if v in (None, "") else v)] = None
    # Time machine: also make everyone older or younger by the number of years between now and `year`.
    change_age: Annotated[bool, BeforeValidator(lambda v: v is True)] = Field(default=False, alias="changeAge")

    @field_validator("ids")
    @classmethod
    def check_ids(cls, ids: list[int | None]) -> list[int | None]:
        """At most 20 words."""
        if len(ids) > config.MAX_WORDS_PER_PROMPT:
            raise ValueError(f"Selecteer maximaal {config.MAX_WORDS_PER_PROMPT} woorden.")
        return ids

    @field_validator("year")
    @classmethod
    def check_year(cls, year: int | None) -> int | None:
        """Within the time machine's range."""
        first, last = config.TIME_MACHINE_YEARS
        if year is not None and not first <= year <= last:
            raise ValueError(f"Vul een jaartal in tussen {first} en {last}.")
        return year

    @field_validator("photo_ids")
    @classmethod
    def check_photo_ids(cls, photo_ids: list[int | None]) -> list[int | None]:
        """At most 4 photos."""
        if len(photo_ids) > config.MAX_PHOTOS_PER_PROMPT:
            raise ValueError(f"Selecteer maximaal {config.MAX_PHOTOS_PER_PROMPT} foto's.")
        return photo_ids

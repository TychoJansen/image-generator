"""Files: generated images and reference photos in the data folder, and the text and photo files loaded at startup."""

from __future__ import annotations

import hashlib
import io
import re
import secrets
import time
from pathlib import Path

from PIL import Image, ImageOps

from . import config
from .config import Settings
from .db import Database, Row
from .errors import ApiError

# Only plain generated names, so nothing outside the data folders can be read or deleted.
IMAGE_NAME = re.compile(r"\d+\.(jpg|png)")
PHOTO_NAME = re.compile(r"\d+-[0-9a-f]{8}(-large)?\.jpg")
REFERENCE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def large_name(filename: str) -> str:
    """Name of the larger copy of a reference photo (used for OpenAI)."""
    return filename.removesuffix(".jpg") + "-large.jpg"


def new_photo_name() -> str:
    """A unique name for an uploaded photo."""
    return f"{int(time.time() * 1000)}-{secrets.token_hex(4)}.jpg"


def existing_file(folder: Path, filename: str, pattern: re.Pattern[str]) -> Path:
    """The path of a file in `folder` with an allowed name; 404 when it is not there."""
    path = folder / filename
    if not pattern.fullmatch(filename) or not path.is_file():
        raise ApiError(404, "Bestand niet gevonden.")
    return path


def list_images(folder: Path) -> list[str]:
    """Names of the generated images, newest first."""
    names = [path.name for path in folder.iterdir() if IMAGE_NAME.fullmatch(path.name)]
    return sorted(names, key=lambda name: int(name.split(".")[0]), reverse=True)


def save_image(folder: Path, image: bytes) -> str:
    """Save a generated image (PNG or JPEG) and return its name."""
    extension = "png" if image.startswith(b"\x89PNG") else "jpg"
    filename = f"{int(time.time() * 1000)}.{extension}"
    (folder / filename).write_bytes(image)
    return filename


def sync_text_file(path: Path | None, db: Database, setting: str, label: str, max_length: int) -> str | None:
    """Put a text file into a setting when the file is new or changed since it was last loaded.

    Edits made in the app are kept until the file itself changes again. Returns a message for the log, or None.
    """
    if path is None or not path.is_file():
        return None
    text = path.read_text(encoding="utf-8-sig").strip()  # utf-8-sig: also files saved with a BOM by Windows editors
    digest = hashlib.sha256(text.encode()).hexdigest()
    if db.get_setting(f"{setting}_file_hash") == digest:
        return None
    if len(text) > max_length:
        return (
            f"{path.name} is {len(text)} characters; {label} allows {max_length}. "
            "Not loaded: shorten the file and restart."
        )
    db.set_setting(setting, text)
    db.set_setting(f"{setting}_file_hash", digest)
    return f"Loaded {path.name} into {label}."


def sync_text_files(settings: Settings) -> list[str]:
    """Load context.txt into "Altijd meesturen" and woordenlijst.txt into "Woordenlijst" (when new or changed)."""
    db = Database(settings.db_path)
    try:
        messages = [
            sync_text_file(settings.context_file, db, "context", '"Altijd meesturen"', config.MAX_CONTEXT_LENGTH),
            sync_text_file(settings.glossary_file, db, "glossary", '"Woordenlijst"', config.MAX_GLOSSARY_LENGTH),
        ]
        return [message for message in messages if message]
    finally:
        db.close()


def resize_photo(data: bytes) -> tuple[bytes, bytes]:
    """A small JPEG (under 512x512, for Cloudflare) and a large one (up to 1024px, for OpenAI) of an image file.

    Raises OSError when Pillow cannot read the file.
    """
    with Image.open(io.BytesIO(data)) as original:
        image = ImageOps.exif_transpose(original).convert("RGB")  # phone photos: apply the rotation, drop alpha

    def jpeg(max_side: int) -> bytes:
        copy = image.copy()
        copy.thumbnail((max_side, max_side))
        out = io.BytesIO()
        copy.save(out, format="JPEG", quality=90)
        return out.getvalue()

    return jpeg(config.MAX_PHOTO_SIDE), jpeg(config.MAX_LARGE_PHOTO_SIDE)


def caption_from_filename(name: str) -> str:
    """'personx.jpg' -> 'personx'."""
    return re.sub(r"[_-]+", " ", Path(name).stem).strip()


def _remove_photo(settings: Settings, db: Database, photo: Row) -> None:
    db.delete_photo(photo["id"])
    (settings.photos_dir / photo["filename"]).unlink(missing_ok=True)
    (settings.photos_dir / large_name(photo["filename"])).unlink(missing_ok=True)


def sync_reference_photos(settings: Settings) -> list[str]:
    """Make "Foto's" match the reference-photos folder: add new files, replace changed ones, remove deleted ones.

    The description of a photo is its file name. Returns messages for the log.
    """
    folder = settings.reference_photos_dir
    if folder is None or not folder.is_dir():
        return []
    files = {p.name: p for p in sorted(folder.iterdir()) if p.is_file() and p.suffix.lower() in REFERENCE_SUFFIXES}
    hashes = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in files.items()}
    messages = []
    db = Database(settings.db_path)
    try:
        imported = set()
        for photo in db.photos_from_folder():
            if hashes.get(photo["source"]) == photo["source_hash"]:
                imported.add(photo["source"])
                continue
            _remove_photo(settings, db, photo)
            if photo["source"] not in files:
                messages.append(f"Removed reference photo {photo['source']} (no longer in {folder.name}/).")

        for name, path in files.items():
            if name in imported:
                continue
            if db.count_photos() >= config.MAX_PHOTOS_STORED:
                messages.append(f"Skipped {name}: the app already has {config.MAX_PHOTOS_STORED} photos.")
                continue
            try:
                small, large = resize_photo(path.read_bytes())
            except (OSError, Image.DecompressionBombError):
                messages.append(f"Skipped {name}: not an image that can be read (use JPG, PNG or WebP).")
                continue
            filename = new_photo_name()
            (settings.photos_dir / filename).write_bytes(small)
            (settings.photos_dir / large_name(filename)).write_bytes(large)
            db.insert_photo(filename, caption_from_filename(name), source=name, source_hash=hashes[name])
            messages.append(f"Added reference photo {name}.")
        return messages
    finally:
        db.close()

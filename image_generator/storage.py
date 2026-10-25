"""Files in the data folder: generated images and reference photos."""

from __future__ import annotations

import hashlib
import re
import secrets
import shutil
import sqlite3
import time
from pathlib import Path

from . import config
from .config import Settings
from .db import Database
from .errors import ApiError

# Only plain generated names, so nothing outside the data folders can be read or deleted.
IMAGE_NAME = re.compile(r"\d+\.(jpg|png)")
PHOTO_NAME = re.compile(r"\d+-[0-9a-f]{8}(-large)?\.jpg")


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


def sync_context_file(settings: Settings) -> str | None:
    """Put the context file's text into "Altijd meesturen" when the file is new or changed since the last load.

    Edits made in the app are kept until the file itself changes again. Returns a message for the log, or None.
    """
    path = settings.context_file
    if path is None or not path.is_file():
        return None
    text = path.read_text(encoding="utf-8-sig").strip()  # utf-8-sig: also files saved with a BOM by Windows editors
    digest = hashlib.sha256(text.encode()).hexdigest()
    db = Database(settings.db_path)
    try:
        if db.get_setting("context_file_hash") == digest:
            return None
        if len(text) > config.MAX_CONTEXT_LENGTH:
            return (
                f'{path.name} is {len(text)} characters; "Altijd meesturen" allows {config.MAX_CONTEXT_LENGTH}. '
                "Not loaded: shorten the file and restart."
            )
        db.set_setting("context", text)
        db.set_setting("context_file_hash", digest)
        return f'Loaded {path.name} into "Altijd meesturen".'
    finally:
        db.close()


def is_empty_db(path: Path) -> bool:
    """Whether the database has no words, photos or settings yet.

    The context loaded automatically from context.txt does not count: it is filled in again on the next start.
    """
    db = Database(path)
    try:
        counts = [db.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("words", "photos")]
        keys = {row[0] for row in db.conn.execute("SELECT key FROM settings")}
        context_from_file = keys <= {"context", "context_file_hash"} and "context_file_hash" in keys
        return counts == [0, 0] and (not keys or context_from_file)
    except sqlite3.DatabaseError:
        return False  # not a database we understand: leave it alone
    finally:
        db.close()


def copy_old_data(settings: Settings, old_root: Path) -> list[str]:
    """Copy data from the old layout (Node.js version) into the data folder; never overwrites anything.

    Old layout: words.db in the project folder, images in public/images/ and photos in uploads/.
    """
    copied = []
    old_db = old_root / "words.db"
    # An empty new database (the server was started before copying) may be replaced; one with data never.
    if old_db.is_file() and (not settings.db_path.exists() or is_empty_db(settings.db_path)):
        settings.db_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(old_db, settings.db_path)
        copied.append(f"Copied {old_db} -> {settings.db_path}")
    for old_folder, new_folder, pattern in [
        (old_root / "public" / "images", settings.images_dir, IMAGE_NAME),
        (old_root / "uploads", settings.photos_dir, PHOTO_NAME),
    ]:
        files = [p for p in old_folder.glob("*") if pattern.fullmatch(p.name)] if old_folder.is_dir() else []
        new_files = [p for p in files if not (new_folder / p.name).exists()]
        if new_files:
            new_folder.mkdir(parents=True, exist_ok=True)
            for path in new_files:
                shutil.copy2(path, new_folder / path.name)
            copied.append(f"Copied {len(new_files)} file(s) from {old_folder} -> {new_folder}")
    return copied or ["Nothing to copy: no old data found, or it was already copied."]

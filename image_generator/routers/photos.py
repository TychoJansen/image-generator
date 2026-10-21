"""Reference photos: upload, list, serve and delete (admin only)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response
from fastapi.responses import FileResponse

from .. import config
from ..db import Row
from ..deps import AdminOnly, DbDep, SettingsDep
from ..errors import ApiError
from ..schemas import PhotoIn, to_id
from ..storage import PHOTO_NAME, existing_file, large_name, new_photo_name

router = APIRouter(dependencies=[AdminOnly])


def photo_json(photo: Row) -> dict[str, Any]:
    """A photo as the page expects it."""
    return {"id": photo["id"], "caption": photo["caption"], "url": f"/photos/{photo['filename']}"}


@router.get("/api/photos")
def list_photos(db: DbDep) -> list[dict[str, Any]]:
    """All reference photos, newest first."""
    return [photo_json(photo) for photo in db.list_photos()]


@router.post("/api/photos", status_code=201)
def upload_photo(body: PhotoIn, db: DbDep, settings: SettingsDep) -> dict[str, Any]:
    """Store a reference photo (and its optional large copy) with an optional description."""
    if db.count_photos() >= config.MAX_PHOTOS_STORED:
        raise ApiError(400, f"Je kunt maximaal {config.MAX_PHOTOS_STORED} foto's bewaren. Verwijder er eerst een.")
    filename = new_photo_name()
    (settings.photos_dir / filename).write_bytes(body.image)
    if body.large:
        (settings.photos_dir / large_name(filename)).write_bytes(body.large)
    return photo_json(db.insert_photo(filename, body.caption))


@router.delete("/api/photos/{photo_id}", status_code=204)
def delete_photo(photo_id: str, db: DbDep, settings: SettingsDep) -> Response:
    """Delete a reference photo and its files."""
    photo = db.get_photo(to_id(photo_id))
    if not photo:
        raise ApiError(404, "Foto niet gevonden.")
    db.delete_photo(photo["id"])
    (settings.photos_dir / photo["filename"]).unlink(missing_ok=True)
    (settings.photos_dir / large_name(photo["filename"])).unlink(missing_ok=True)
    return Response(status_code=204)


@router.get("/photos/{filename}")
def photo_file(filename: str, settings: SettingsDep) -> FileResponse:
    """A reference photo file."""
    return FileResponse(existing_file(settings.photos_dir, filename, PHOTO_NAME))

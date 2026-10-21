"""Generated images: list, serve and delete (admin only)."""

from __future__ import annotations

from fastapi import APIRouter, Response
from fastapi.responses import FileResponse

from ..deps import AdminOnly, SettingsDep
from ..errors import ApiError
from ..storage import IMAGE_NAME, existing_file, list_images

router = APIRouter(dependencies=[AdminOnly])


@router.get("/api/images")
def images(settings: SettingsDep) -> list[dict[str, str]]:
    """All generated images, newest first."""
    return [{"filename": name, "url": f"/images/{name}"} for name in list_images(settings.images_dir)]


@router.delete("/api/images/{filename}", status_code=204)
def delete_image(filename: str, settings: SettingsDep) -> Response:
    """Delete a generated image."""
    if not IMAGE_NAME.fullmatch(filename):
        raise ApiError(400, "Ongeldige bestandsnaam.")
    path = settings.images_dir / filename
    if not path.exists():
        raise ApiError(404, "Afbeelding niet gevonden.")
    path.unlink()
    return Response(status_code=204)


@router.get("/images/{filename}")
def image_file(filename: str, settings: SettingsDep) -> FileResponse:
    """A generated image file."""
    return FileResponse(existing_file(settings.images_dir, filename, IMAGE_NAME))

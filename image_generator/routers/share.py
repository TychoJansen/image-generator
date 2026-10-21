"""The QR code for the share link (admin only).

The page passes its own address, so the code points to the public tunnel link when the admin opens the app via it.
"""

from __future__ import annotations

import re

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Response

from .. import config
from ..deps import AdminOnly
from ..errors import ApiError

HTTP_URL = re.compile(r"https?://\S+")

router = APIRouter(dependencies=[AdminOnly])


def qr_svg(url: str) -> str:
    """A QR code for the url as SVG, with a white background (also readable in dark mode)."""
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        border=2,
        image_factory=qrcode.image.svg.SvgPathFillImage,
    )
    qr.add_data(url)
    qr.make(fit=True)
    return qr.make_image().to_string(encoding="unicode")


@router.get("/api/qr.svg")
def qr_code(url: str = "") -> Response:
    """A QR code for the share link."""
    if not HTTP_URL.fullmatch(url) or len(url) > config.MAX_QR_URL_LENGTH:
        raise ApiError(400, "Ongeldige link voor de QR-code.")
    return Response(qr_svg(url), media_type="image/svg+xml")

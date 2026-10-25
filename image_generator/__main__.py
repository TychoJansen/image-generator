"""Start the image generator: ``image-generator`` (or ``python -m image_generator``)."""

from __future__ import annotations

import logging
import os

import uvicorn
from dotenv import load_dotenv

from .app import create_app
from .config import ROOT, Settings


def main() -> None:
    """Read .env, print warnings and run the web server (Ctrl+C stops it)."""
    load_dotenv(ROOT / ".env")
    settings = Settings.from_env()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(message)s")
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "3000"))
    for message in settings.startup_messages():
        print(message, flush=True)
    print(f"Open http://localhost:{port} once the server is running.", flush=True)
    uvicorn.run(create_app(settings), host=host, port=port, access_log=False)


if __name__ == "__main__":  # pragma: no cover
    main()

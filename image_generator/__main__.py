"""Command line: ``image-generator`` starts the server, ``image-generator copy-old-data`` copies old data.

Also works as ``python -m image_generator``.
"""

from __future__ import annotations

import argparse
import logging
import os

import uvicorn
from dotenv import load_dotenv

from .app import create_app
from .config import ROOT, Settings
from .storage import copy_old_data


def main(argv: list[str] | None = None) -> None:
    """Read .env, then start the web server (Ctrl+C stops it) or copy the old data."""
    parser = argparse.ArgumentParser(prog="image-generator", description="Guests add words; you make AI images.")
    parser.add_argument(
        "command",
        nargs="?",
        default="serve",
        choices=["serve", "copy-old-data"],
        help="serve (default): start the web server; copy-old-data: copy words.db, public/images/ and uploads/ "
        "from the old Node.js layout into the data folder (nothing is moved or overwritten)",
    )
    args = parser.parse_args(argv)

    load_dotenv(ROOT / ".env")
    settings = Settings.from_env()
    if args.command == "copy-old-data":
        for line in copy_old_data(settings, ROOT):
            print(line)
        return

    logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(message)s")
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "3000"))
    for message in settings.startup_messages():
        print(message, flush=True)
    print(f"Open http://localhost:{port} once the server is running.", flush=True)
    uvicorn.run(create_app(settings), host=host, port=port, access_log=False)


if __name__ == "__main__":  # pragma: no cover
    main()

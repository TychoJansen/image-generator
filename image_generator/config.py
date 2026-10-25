"""Settings, paths and limits for the image generator."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CF_MODEL = "@cf/black-forest-labs/flux-1-schnell"
# Used when reference photos are selected: accepts up to 4 input images, but costs more of the daily free limit.
CF_PHOTO_MODEL = "@cf/black-forest-labs/flux-2-klein-9b"

# OpenAI is optional; the model can be changed in .env (e.g. to a model your account can use).
DEFAULT_OPENAI_MODEL = "gpt-image-2.5-sunburst"
# Models that accept input_fidelity=high (keeps faces from reference photos closer); newer models must omit it.
OPENAI_FIDELITY_MODELS = ("gpt-image-1", "gpt-image-1.5")
OPENAI_QUALITIES = ("low", "medium", "high")

MAX_WORD_LENGTH = 50
MAX_WORDS_PER_PROMPT = 20
MAX_CONTEXT_LENGTH = 1000
MAX_GLOSSARY_LENGTH = 3000
MAX_MERGES_LENGTH = 3000
MAX_CAPTION_LENGTH = 100
MAX_PHOTOS_STORED = 20
MAX_PHOTOS_PER_PROMPT = 4
MAX_PHOTO_BYTES = 1024 * 1024
MAX_BODY_BYTES = 2 * 1024 * 1024  # room for one uploaded photo (small and large version)
MAX_QR_URL_LENGTH = 500

SESSION_COOKIE = "admin_session"
SESSION_SECONDS = 12 * 60 * 60
MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCK_SECONDS = 15 * 60

# OpenAI can take up to a minute or more per image.
HTTP_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class Settings:
    """Everything the app needs from the environment, plus where it keeps its files.

    All data (database, generated images, reference photos) lives in `data_dir`, separate from the code.
    """

    public_dir: Path = ROOT / "public"
    data_dir: Path = ROOT / "data"
    admin_password: str = ""
    cloudflare_account_id: str = ""
    cloudflare_api_token: str = field(default="", repr=False)
    openai_api_key: str = field(default="", repr=False)
    openai_model: str = DEFAULT_OPENAI_MODEL
    # Text file whose content is put into "Altijd meesturen" at startup (when it is new or changed); None = off.
    context_file: Path | None = None

    @property
    def db_path(self) -> Path:
        """The SQLite database with words, settings and the photo list."""
        return self.data_dir / "words.db"

    @property
    def images_dir(self) -> Path:
        """Generated images (admin only)."""
        return self.data_dir / "images"

    @property
    def photos_dir(self) -> Path:
        """Uploaded reference photos (admin only)."""
        return self.data_dir / "photos"

    @classmethod
    def from_env(cls) -> Settings:
        """Read the settings from environment variables (filled from .env at startup)."""
        return cls(
            data_dir=ROOT / os.getenv("DATA_DIR", "data"),  # a relative DATA_DIR is relative to the project
            admin_password=os.getenv("ADMIN_PASSWORD", ""),
            cloudflare_account_id=os.getenv("CLOUDFLARE_ACCOUNT_ID", ""),
            cloudflare_api_token=os.getenv("CLOUDFLARE_API_TOKEN", ""),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_model=os.getenv("OPENAI_IMAGE_MODEL") or DEFAULT_OPENAI_MODEL,
            context_file=ROOT / context_file if (context_file := os.getenv("CONTEXT_FILE", "context.txt")) else None,
        )

    def missing_cloudflare(self) -> list[str]:
        """Names of the Cloudflare settings that are not filled in."""
        values = {
            "CLOUDFLARE_ACCOUNT_ID": self.cloudflare_account_id,
            "CLOUDFLARE_API_TOKEN": self.cloudflare_api_token,
        }
        return [name for name, value in values.items() if not value]

    def startup_messages(self) -> list[str]:
        """Warnings and notes to print when the server starts."""
        messages = []
        missing = self.missing_cloudflare()
        if missing:
            messages.append(
                f"Warning: {', '.join(missing)} not set. "
                "Cloudflare image generation will fail until you add them to .env."
            )
        if not self.admin_password:
            messages.append("Warning: ADMIN_PASSWORD not set. The admin tabs are locked until you add it to .env.")
        if self.openai_api_key:
            messages.append(f"OpenAI image generation enabled (model: {self.openai_model}).")
        messages.append(f"Data folder: {self.data_dir}")
        return messages

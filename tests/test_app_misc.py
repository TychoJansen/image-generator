"""The page, the QR code, settings from the environment and starting the server."""

import pytest

from image_generator import __main__ as main_module
from image_generator.config import DEFAULT_OPENAI_MODEL, ROOT, Settings


def test_page_and_static_files(client):
    page = client.get("/")
    assert page.status_code == 200 and "Image Generator" in page.text
    assert client.get("/app.js").status_code == 200
    redirect = client.get("/generate", follow_redirects=False)
    assert redirect.status_code == 302 and redirect.headers["location"] == "/#generate"


def test_qr_code(client, admin):
    svg = admin.get("/api/qr.svg", params={"url": "https://example.trycloudflare.com/#words"})
    assert svg.status_code == 200 and svg.headers["content-type"] == "image/svg+xml"
    assert svg.text.startswith("<svg") and 'fill="white"' in svg.text
    assert admin.get("/api/qr.svg", params={"url": "javascript:alert(1)"}).json() == {
        "error": "Ongeldige link voor de QR-code."
    }
    assert admin.get("/api/qr.svg", params={"url": "https://x.nl/" + "a" * 500}).status_code == 400
    client.post("/api/logout")
    assert client.get("/api/qr.svg", params={"url": "https://x.nl"}).status_code == 401


def test_settings_from_env(monkeypatch):
    for name in ["ADMIN_PASSWORD", "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN", "OPENAI_API_KEY"]:
        monkeypatch.setenv(name, f"value-{name}")
    monkeypatch.delenv("OPENAI_IMAGE_MODEL", raising=False)
    settings = Settings.from_env()
    assert settings.admin_password == "value-ADMIN_PASSWORD"
    assert settings.openai_model == DEFAULT_OPENAI_MODEL
    # The keys never show up when the settings are printed.
    assert "value-CLOUDFLARE_API_TOKEN" not in repr(settings)
    assert "value-OPENAI_API_KEY" not in repr(settings)
    monkeypatch.setenv("OPENAI_IMAGE_MODEL", "gpt-image-2")
    assert Settings.from_env().openai_model == "gpt-image-2"


def test_startup_messages(tmp_path):
    assert Settings(data_dir=tmp_path).startup_messages() == [
        "Warning: CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN not set. "
        "Cloudflare image generation will fail until you add them to .env.",
        "Warning: ADMIN_PASSWORD not set. The admin tabs are locked until you add it to .env.",
        f"Data folder: {tmp_path}",
    ]
    complete = Settings(
        data_dir=tmp_path,
        admin_password="pw",
        cloudflare_account_id="a",
        cloudflare_api_token="t",
        openai_api_key="k",
        openai_model="m",
    )
    assert complete.startup_messages() == ["OpenAI image generation enabled (model: m).", f"Data folder: {tmp_path}"]


def test_data_dir_from_env(monkeypatch, tmp_path):
    monkeypatch.delenv("DATA_DIR", raising=False)
    assert Settings.from_env().data_dir == ROOT / "data"
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    settings = Settings.from_env()
    assert settings.data_dir == tmp_path
    assert (settings.db_path, settings.images_dir, settings.photos_dir) == (
        tmp_path / "words.db",
        tmp_path / "images",
        tmp_path / "photos",
    )


@pytest.fixture
def fake_main(monkeypatch, settings):
    calls = {}
    monkeypatch.setattr(main_module, "load_dotenv", lambda path: calls.setdefault("dotenv", path))
    monkeypatch.setattr(main_module.Settings, "from_env", classmethod(lambda cls: settings))
    monkeypatch.setattr(main_module.uvicorn, "run", lambda app, **kwargs: calls.setdefault("run", kwargs))
    return calls


def test_main_starts_uvicorn(fake_main, monkeypatch, capsys):
    monkeypatch.setenv("PORT", "3001")
    monkeypatch.delenv("HOST", raising=False)
    main_module.main()
    assert fake_main["dotenv"].name == ".env"
    assert fake_main["run"] == {"host": "127.0.0.1", "port": 3001, "access_log": False}
    assert "Open http://localhost:3001" in capsys.readouterr().out

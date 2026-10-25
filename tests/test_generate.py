"""Choosing words and photos, the prompt preview and generating with the (fake) image services."""

import base64
from dataclasses import replace

import httpx
import pytest
from conftest import JPEG, PNG, data_url

from image_generator import config, providers


def add_word(admin, text):
    admin.post("/api/words", json={"text": text})
    return next(w["id"] for w in admin.get("/api/words").json() if w["text"] == text)


def add_photo(admin, caption="", large=True):
    body = {"image": data_url(), "caption": caption}
    if large:
        body["large"] = data_url(JPEG + b"large")
    return admin.post("/api/photos", json=body).json()["id"]


def test_cloudflare_text_only(admin, settings, fake_api):
    word = add_word(admin, "taart")
    response = admin.post("/api/generate", json={"ids": [word]})
    assert response.status_code == 200
    result = response.json()
    assert result["model"] == config.CF_MODEL
    assert result["prompt"].startswith("Create one detailed, colorful illustration based on these words: taart.")
    assert result["url"] == f"/images/{result['filename']}" and result["filename"].endswith(".jpg")
    assert (settings.images_dir / result["filename"]).read_bytes() == JPEG

    request = fake_api.last
    assert str(request.url).endswith(f"/accounts/account-id/ai/run/{config.CF_MODEL}")
    assert request.headers["authorization"] == "Bearer cf-token"
    assert fake_api.last_json() == {"prompt": result["prompt"], "steps": 4}


def test_cloudflare_with_photos_uses_small_photos(admin, fake_api):
    photo = add_photo(admin, caption="Whisky")
    result = admin.post("/api/generate", json={"ids": [], "photoIds": [photo]}).json()
    assert result["model"] == config.CF_PHOTO_MODEL
    assert "image 0 shows Whisky" in result["prompt"]
    body = fake_api.last.content
    assert b'name="input_image_0"' in body and b'name="width"' in body
    assert JPEG + b"large" not in body


def test_openai_text_only_saves_png(admin, settings, fake_api):
    fake_api.reply = lambda request: httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(PNG).decode()}]})
    word = add_word(admin, "taart")
    result = admin.post("/api/generate", json={"ids": [word], "provider": "openai", "quality": "high"}).json()
    assert result["model"] == "gpt-image-1" and result["filename"].endswith(".png")
    assert str(fake_api.last.url) == "https://api.openai.com/v1/images/generations"
    assert fake_api.last.headers["authorization"] == "Bearer sk-test"
    sent = fake_api.last_json()
    assert sent["model"] == "gpt-image-1" and sent["quality"] == "high" and sent["size"] == "1024x1024"


def test_openai_with_photos_uses_large_copy_and_fidelity(admin, fake_api):
    photo = add_photo(admin, caption="Jerrel")
    old_photo = add_photo(admin, large=False)
    result = admin.post("/api/generate", json={"photoIds": [photo, old_photo], "provider": "openai"}).json()
    assert "image 1 shows Jerrel; image 2" in result["prompt"]
    body = fake_api.last.content
    assert str(fake_api.last.url) == "https://api.openai.com/v1/images/edits"
    assert body.count(b'name="image[]"') == 2
    assert JPEG + b"large" in body
    assert b'name="input_fidelity"' in body and b'name="quality"\r\n\r\nmedium' in body


def test_newer_openai_models_get_no_fidelity(make_client, settings, fake_api):
    admin = make_client(replace(settings, openai_model="gpt-image-2"))
    admin.post("/api/login", json={"password": "test-pw"})
    photo = add_photo(admin)
    admin.post("/api/generate", json={"photoIds": [photo], "provider": "openai"})
    assert b"input_fidelity" not in fake_api.last.content


def test_selection_validation(admin, monkeypatch):
    word = add_word(admin, "taart")
    assert admin.post("/api/generate", json={"ids": [word] * 21}).json() == {"error": "Selecteer maximaal 20 woorden."}
    assert admin.post("/api/generate", json={"ids": [999]}).status_code == 400
    assert admin.post("/api/generate", json={"ids": [True]}).status_code == 400
    assert admin.post("/api/generate", json={"photoIds": [1, 2, 3, 4, 5]}).json() == {
        "error": "Selecteer maximaal 4 foto's."
    }
    assert admin.post("/api/generate", json={"photoIds": ["x"]}).status_code == 400
    nothing = admin.post("/api/generate", json={"ids": "not a list"})
    assert nothing.status_code == 400 and nothing.json()["error"].startswith("Er is niets om een afbeelding")


def test_ids_may_be_numbers_or_numeric_strings(admin):
    word = add_word(admin, "taart")
    for ids in ([word], [float(word)], [str(word)]):
        assert admin.post("/api/prompt", json={"ids": ids}).status_code == 200
    for ids in ([None], [{}], [1.5]):
        assert admin.post("/api/prompt", json={"ids": ids}).status_code == 400


def test_real_http_client_waits_long_enough():
    client = providers.http_client()
    assert client.timeout.read == config.HTTP_TIMEOUT_SECONDS


def test_context_alone_is_enough(admin, fake_api):
    admin.put("/api/context", json={"context": "A wedding."})
    result = admin.post("/api/generate", json={}).json()
    assert result["prompt"].startswith("Create one detailed, colorful illustration.\n\nAlways follow")


def test_prompt_preview_uses_glossary_and_does_not_generate(admin, fake_api):
    admin.put("/api/context", json={"glossary": "Whisky: a small brown dog\nScotch: their cat"})
    word = add_word(admin, "Whisky")
    prompt = admin.post("/api/prompt", json={"ids": [word]}).json()["prompt"]
    assert "- Whisky: a small brown dog" in prompt and "Scotch" not in prompt
    assert fake_api.requests == []


def test_providers(admin, make_client, settings):
    assert admin.get("/api/providers").json() == {"cloudflare": True, "openai": True, "openaiModel": "gpt-image-1"}
    other = make_client(replace(settings, openai_api_key="", cloudflare_api_token=""))
    other.post("/api/login", json={"password": "test-pw"})
    assert other.get("/api/providers").json() == {"cloudflare": False, "openai": False, "openaiModel": "gpt-image-1"}


def test_generating_needs_login(client):
    assert client.post("/api/generate", json={}).status_code == 401
    assert client.post("/api/prompt", json={}).status_code == 401
    assert client.get("/api/providers").status_code == 401


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (401, {"errors": [{"code": 10000, "message": "Authentication error"}]}, "Cloudflare heeft de inloggegevens"),
        (429, {}, "Dagelijkse gratis limiet"),
        (400, {"success": False, "errors": [{"code": 4006, "message": "used up"}]}, "Dagelijkse gratis limiet"),
        (500, {"errors": [{"message": "boom"}]}, "Fout van de Cloudflare API (HTTP 500): boom"),
        (200, {"success": False}, "Fout van de Cloudflare API (HTTP 200): geen details"),
        (200, {"success": True, "result": {}}, "het antwoord bevatte geen afbeelding"),
    ],
)
def test_cloudflare_errors(admin, fake_api, status, body, expected):
    fake_api.reply = lambda request: httpx.Response(status, json=body)
    admin.put("/api/context", json={"context": "A wedding."})
    response = admin.post("/api/generate", json={})
    assert response.status_code == 502
    assert expected in response.json()["error"]


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (401, {"error": {"message": "Incorrect API key"}}, "OpenAI heeft de API-sleutel geweigerd"),
        (429, {"error": {"code": "insufficient_quota", "message": "quota"}}, "OpenAI-tegoed of budgetlimiet"),
        (429, {"error": {"message": "slow down"}}, "Te veel verzoeken"),
        (400, {"error": {"code": "moderation_blocked", "message": "no"}}, "veiligheidsbeleid"),
        (403, {"error": {"message": "Your organization must be verified"}}, "geen toegang tot gpt-image-1"),
        (500, {"error": "not an object"}, "Fout van de OpenAI API (HTTP 500): geen details"),
        (200, {"data": []}, "het antwoord bevatte geen afbeelding"),
        (200, {"data": ["not an object"]}, "het antwoord bevatte geen afbeelding"),
    ],
)
def test_openai_errors(admin, fake_api, status, body, expected):
    fake_api.reply = lambda request: httpx.Response(status, json=body)
    admin.put("/api/context", json={"context": "A wedding."})
    response = admin.post("/api/generate", json={"provider": "openai"})
    assert response.status_code == 502
    assert expected in response.json()["error"]


def test_service_unreachable_or_not_json(admin, fake_api):
    admin.put("/api/context", json={"context": "A wedding."})

    def unreachable(request):
        raise httpx.ConnectError("no network", request=request)

    fake_api.reply = unreachable
    assert "Kan de Cloudflare API niet bereiken: no network" in admin.post("/api/generate", json={}).json()["error"]

    fake_api.reply = lambda request: httpx.Response(502, text="<html>Bad gateway</html>")
    assert admin.post("/api/generate", json={}).json()["error"] == "Fout van de Cloudflare API (HTTP 502): geen details"


def test_invalid_image_data_from_service(admin, fake_api):
    fake_api.reply = lambda request: httpx.Response(200, json={"success": True, "result": {"image": "not base64!"}})
    admin.put("/api/context", json={"context": "A wedding."})
    response = admin.post("/api/generate", json={})
    assert response.json() == {"error": "Het antwoord van de AI-dienst bevatte geen geldige afbeelding."}


def test_missing_keys(make_client, settings, fake_api):
    admin = make_client(replace(settings, cloudflare_account_id="", openai_api_key=""))
    admin.post("/api/login", json={"password": "test-pw"})
    admin.put("/api/context", json={"context": "A wedding."})
    cloudflare = admin.post("/api/generate", json={}).json()["error"]
    assert cloudflare.startswith("Cloudflare-gegevens ontbreken: CLOUDFLARE_ACCOUNT_ID.")
    openai = admin.post("/api/generate", json={"provider": "openai"}).json()["error"]
    assert openai.startswith("OPENAI_API_KEY ontbreekt.")
    assert fake_api.requests == []


def test_time_machine(admin, fake_api):
    word = add_word(admin, "taart")
    result = admin.post("/api/generate", json={"ids": [word], "year": 2080}).json()
    assert "as it would look in the year 2080:" in result["prompt"]
    assert fake_api.last_json()["prompt"] == result["prompt"]
    assert "Time machine" not in admin.post("/api/prompt", json={"ids": [word], "year": ""}).json()["prompt"]
    assert "Time machine" not in admin.post("/api/prompt", json={"ids": [word], "year": None}).json()["prompt"]


def test_time_machine_year_must_be_in_range(admin):
    word = add_word(admin, "taart")
    too_far = admin.post("/api/generate", json={"ids": [word], "year": 20000})
    assert too_far.status_code == 400
    assert too_far.json() == {"error": "Vul een jaartal in tussen -10000 en 10000."}
    assert admin.post("/api/generate", json={"ids": [word], "year": "abc"}).json() == {"error": "Ongeldige invoer."}


def test_time_machine_with_age_uses_this_year(admin):
    from datetime import date

    word = add_word(admin, "taart")
    years = 2080 - date.today().year
    prompt = admin.post("/api/prompt", json={"ids": [word], "year": 2080, "changeAge": True}).json()["prompt"]
    assert f"everyone is {years} years older than now" in prompt
    not_ticked = admin.post("/api/prompt", json={"ids": [word], "year": 2080, "changeAge": "yes"}).json()["prompt"]
    assert "Age:" not in not_ticked  # only a real true counts

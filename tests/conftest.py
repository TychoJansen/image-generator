"""Shared fixtures: an app with temporary folders, a logged-in admin and a fake image API."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable, Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from image_generator import providers
from image_generator.app import create_app
from image_generator.config import ROOT, Settings

PASSWORD = "test-pw"
JPEG = b"\xff\xd8\xff\xe0" + b"jpeg-data" * 4
PNG = b"\x89PNG\r\n\x1a\n" + b"png-data" * 4


def data_url(data: bytes = JPEG) -> str:
    """A JPEG data URL like the browser sends for photo uploads."""
    return "data:image/jpeg;base64," + base64.b64encode(data).decode()


@pytest.fixture
def settings(tmp_path) -> Settings:
    """Settings with the real page, but a temporary data folder and fake keys."""
    return Settings(
        public_dir=ROOT / "public",
        data_dir=tmp_path / "data",
        admin_password=PASSWORD,
        cloudflare_account_id="account-id",
        cloudflare_api_token="cf-token",
        openai_api_key="sk-test",
        openai_model="gpt-image-1",
    )


@pytest.fixture
def make_client() -> Iterator[Callable[[Settings], TestClient]]:
    """Factory for started clients (startup creates the data folder and tables); stops them afterwards."""
    clients = []

    def make(settings: Settings) -> TestClient:
        client = TestClient(create_app(settings))
        client.__enter__()
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_client, settings) -> TestClient:
    """A visitor (not logged in)."""
    return make_client(settings)


@pytest.fixture
def admin(client) -> TestClient:
    """A logged-in admin."""
    assert client.post("/api/login", json={"password": PASSWORD}).status_code == 200
    return client


class FakeApi:
    """Stands in for Cloudflare and OpenAI; records requests and returns `reply(request)`."""

    def __init__(self) -> None:
        """Start with replies that contain a valid JPEG."""
        self.requests: list[httpx.Request] = []
        self.reply: Callable[[httpx.Request], httpx.Response] = self.success

    @staticmethod
    def success(request: httpx.Request) -> httpx.Response:
        """A successful answer in the format of the service that was called."""
        image = base64.b64encode(JPEG).decode()
        if request.url.host == "api.openai.com":
            return httpx.Response(200, json={"data": [{"b64_json": image}]})
        return httpx.Response(200, json={"success": True, "result": {"image": image}})

    def handle(self, request: httpx.Request) -> httpx.Response:
        """Called by the mock transport for every request."""
        request.read()
        self.requests.append(request)
        return self.reply(request)

    @property
    def last(self) -> httpx.Request:
        """The most recent request."""
        return self.requests[-1]

    def last_json(self) -> dict:
        """The JSON body of the most recent request."""
        return json.loads(self.last.content)


@pytest.fixture
def fake_api(monkeypatch) -> FakeApi:
    """Route all calls to the image services to a FakeApi."""
    fake = FakeApi()
    monkeypatch.setattr(providers, "http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake.handle)))
    return fake

"""Loading context.txt into "Altijd meesturen" at startup."""

import logging
from dataclasses import replace

from conftest import PASSWORD

from image_generator import config
from image_generator.config import ROOT, Settings
from image_generator.db import init_db
from image_generator.storage import sync_context_file


def start(make_client, settings):
    client = make_client(settings)
    client.post("/api/login", json={"password": PASSWORD})
    return client


def test_loads_file_on_start_and_keeps_app_edits_until_the_file_changes(make_client, settings, tmp_path, caplog):
    context_file = tmp_path / "context.txt"
    context_file.write_text("  A warm wedding illustration.\n", encoding="utf-8")
    settings = replace(settings, context_file=context_file)

    with caplog.at_level(logging.INFO):
        admin = start(make_client, settings)
    assert admin.get("/api/context").json()["context"] == "A warm wedding illustration."
    assert 'Loaded context.txt into "Altijd meesturen".' in caplog.text

    # An edit in the app survives a restart while the file is unchanged.
    admin.put("/api/context", json={"context": "Edited in the app."})
    assert start(make_client, settings).get("/api/context").json()["context"] == "Edited in the app."

    # When the file changes, it wins again on the next start.
    context_file.write_text("A new version.", encoding="utf-8")
    assert start(make_client, settings).get("/api/context").json()["context"] == "A new version."


def test_file_saved_with_bom(settings, tmp_path):
    context_file = tmp_path / "context.txt"
    context_file.write_bytes("﻿With BOM".encode())
    settings = replace(settings, context_file=context_file)
    init_db(settings.db_path)
    assert sync_context_file(settings) is not None
    assert sync_context_file(settings) is None  # unchanged: nothing to do


def test_too_long_file_is_not_loaded(settings, tmp_path):
    context_file = tmp_path / "context.txt"
    context_file.write_text("a" * (config.MAX_CONTEXT_LENGTH + 1), encoding="utf-8")
    settings = replace(settings, context_file=context_file)
    init_db(settings.db_path)
    message = sync_context_file(settings)
    assert message.startswith("context.txt is 1001 characters") and "Not loaded" in message


def test_no_file(settings, tmp_path):
    assert sync_context_file(settings) is None  # context_file=None in the test settings
    assert sync_context_file(replace(settings, context_file=tmp_path / "missing.txt")) is None


def test_context_file_from_env(monkeypatch):
    monkeypatch.delenv("CONTEXT_FILE", raising=False)
    assert Settings.from_env().context_file == ROOT / "context.txt"
    monkeypatch.setenv("CONTEXT_FILE", "other.txt")
    assert Settings.from_env().context_file == ROOT / "other.txt"
    monkeypatch.setenv("CONTEXT_FILE", "")
    assert Settings.from_env().context_file is None

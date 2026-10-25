"""Loading context.txt into "Altijd meesturen" and woordenlijst.txt into "Woordenlijst" at startup."""

import logging
from dataclasses import replace

from conftest import PASSWORD

from image_generator import config
from image_generator.config import ROOT, Settings
from image_generator.db import init_db
from image_generator.storage import sync_text_files


def start(make_client, settings):
    client = make_client(settings)
    client.post("/api/login", json={"password": PASSWORD})
    return client


def test_loads_files_on_start_and_keeps_app_edits_until_a_file_changes(make_client, settings, tmp_path, caplog):
    context_file = tmp_path / "context.txt"
    glossary_file = tmp_path / "woordenlijst.txt"
    context_file.write_text("  A warm wedding illustration.\n", encoding="utf-8")
    glossary_file.write_text("Whisky: a small brown dog\n", encoding="utf-8")
    settings = replace(settings, context_file=context_file, glossary_file=glossary_file)

    with caplog.at_level(logging.INFO):
        admin = start(make_client, settings)
    assert admin.get("/api/context").json() == {
        "context": "A warm wedding illustration.",
        "glossary": "Whisky: a small brown dog",
    }
    assert 'Loaded context.txt into "Altijd meesturen".' in caplog.text
    assert 'Loaded woordenlijst.txt into "Woordenlijst".' in caplog.text

    # Edits in the app survive a restart while the files are unchanged.
    admin.put("/api/context", json={"context": "Edited context.", "glossary": "Edited glossary."})
    restarted = start(make_client, settings)
    assert restarted.get("/api/context").json() == {"context": "Edited context.", "glossary": "Edited glossary."}

    # When one file changes, only that one wins again on the next start.
    glossary_file.write_text("James: a Border Collie", encoding="utf-8")
    assert start(make_client, settings).get("/api/context").json() == {
        "context": "Edited context.",
        "glossary": "James: a Border Collie",
    }


def test_file_saved_with_bom(settings, tmp_path):
    context_file = tmp_path / "context.txt"
    context_file.write_bytes("﻿With BOM".encode())
    settings = replace(settings, context_file=context_file)
    init_db(settings.db_path)
    assert sync_text_files(settings) == ['Loaded context.txt into "Altijd meesturen".']
    assert sync_text_files(settings) == []  # unchanged: nothing to do


def test_too_long_file_is_not_loaded(settings, tmp_path):
    glossary_file = tmp_path / "woordenlijst.txt"
    glossary_file.write_text("a" * (config.MAX_GLOSSARY_LENGTH + 1), encoding="utf-8")
    settings = replace(settings, glossary_file=glossary_file)
    init_db(settings.db_path)
    assert sync_text_files(settings) == [
        'woordenlijst.txt is 3001 characters; "Woordenlijst" allows 3000. Not loaded: shorten the file and restart.'
    ]


def test_no_files(settings, tmp_path):
    init_db(settings.db_path)
    assert sync_text_files(settings) == []  # both None in the test settings
    missing = replace(settings, context_file=tmp_path / "missing.txt", glossary_file=tmp_path / "missing2.txt")
    assert sync_text_files(missing) == []


def test_files_from_env(monkeypatch):
    for name in ["CONTEXT_FILE", "GLOSSARY_FILE"]:
        monkeypatch.delenv(name, raising=False)
    settings = Settings.from_env()
    assert (settings.context_file, settings.glossary_file) == (ROOT / "context.txt", ROOT / "woordenlijst.txt")
    monkeypatch.setenv("CONTEXT_FILE", "other.txt")
    monkeypatch.setenv("GLOSSARY_FILE", "")
    settings = Settings.from_env()
    assert (settings.context_file, settings.glossary_file) == (ROOT / "other.txt", None)

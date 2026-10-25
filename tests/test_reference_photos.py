"""The reference-photos folder: synced into "Foto's" at startup and ticked by default on the page."""

import io
import logging
import sqlite3
from dataclasses import replace

from conftest import PASSWORD
from PIL import Image

from image_generator import config
from image_generator.config import ROOT, Settings
from image_generator.db import init_db
from image_generator.storage import caption_from_filename, sync_reference_photos


def make_image(path, color="red", mode="RGB", size=(2000, 1500)):
    Image.new(mode, size, color).save(path)


def start(make_client, settings):
    client = make_client(settings)
    client.post("/api/login", json={"password": PASSWORD})
    return client


def size_of(data: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(data)).size


def test_folder_photos_are_added_resized_and_marked(make_client, settings, tmp_path, caplog):
    folder = tmp_path / "reference-photos"
    folder.mkdir()
    make_image(folder / "personx.jpg")
    make_image(folder / "dog.png", mode="RGBA")
    (folder / "notes.txt").write_text("not a photo")
    settings = replace(settings, reference_photos_dir=folder)

    with caplog.at_level(logging.INFO):
        admin = start(make_client, settings)
    assert "Added reference photo dog.png." in caplog.text

    photos = admin.get("/api/photos").json()
    assert sorted((p["caption"], p["fromFolder"]) for p in photos) == [
        ("personx", True),
        ("dog", True),
    ]
    small = admin.get(photos[0]["url"]).content
    assert max(size_of(small)) == config.MAX_PHOTO_SIDE
    large_name = photos[0]["url"].removeprefix("/photos/").replace(".jpg", "-large.jpg")
    assert max(size_of((settings.photos_dir / large_name).read_bytes())) == config.MAX_LARGE_PHOTO_SIDE

    refused = admin.delete(f"/api/photos/{photos[0]['id']}")
    assert refused.status_code == 400 and "map reference-photos" in refused.json()["error"]


def test_folder_photos_work_as_reference_images(make_client, settings, tmp_path, fake_api):
    folder = tmp_path / "reference-photos"
    folder.mkdir()
    make_image(folder / "dog.jpg")
    admin = start(make_client, replace(settings, reference_photos_dir=folder))
    admin.put("/api/context", json={"glossary": "dog: a small brown dog"})
    photo_id = admin.get("/api/photos").json()[0]["id"]
    prompt = admin.post("/api/prompt", json={"photoIds": [photo_id]}).json()["prompt"]
    assert "image 0 shows dog" in prompt and "- dog: a small brown dog" in prompt


def test_unchanged_changed_and_removed_files(settings, tmp_path):
    folder = tmp_path / "reference-photos"
    folder.mkdir()
    make_image(folder / "a.jpg")
    make_image(folder / "b.jpg")
    settings = replace(settings, reference_photos_dir=folder)
    init_db(settings.db_path)
    settings.photos_dir.mkdir(parents=True)

    assert len(sync_reference_photos(settings)) == 2
    files_before = sorted(p.name for p in settings.photos_dir.iterdir())
    assert sync_reference_photos(settings) == []  # nothing changed
    assert sorted(p.name for p in settings.photos_dir.iterdir()) == files_before

    make_image(folder / "a.jpg", color="blue")  # changed: replaced
    (folder / "b.jpg").unlink()  # removed: gone from the app, files deleted
    assert sync_reference_photos(settings) == [
        "Removed reference photo b.jpg (no longer in reference-photos/).",
        "Added reference photo a.jpg.",
    ]
    assert len(list(settings.photos_dir.iterdir())) == 2  # one photo: small + large copy


def test_unreadable_file_and_photo_limit(settings, tmp_path, monkeypatch):
    folder = tmp_path / "reference-photos"
    folder.mkdir()
    (folder / "broken.jpg").write_bytes(b"not an image")
    make_image(folder / "x.jpg")
    make_image(folder / "y.jpg")
    settings = replace(settings, reference_photos_dir=folder)
    init_db(settings.db_path)
    settings.photos_dir.mkdir(parents=True)
    monkeypatch.setattr(config, "MAX_PHOTOS_STORED", 1)
    assert sync_reference_photos(settings) == [
        "Skipped broken.jpg: not an image that can be read (use JPG, PNG or WebP).",
        "Added reference photo x.jpg.",
        "Skipped y.jpg: the app already has 1 photos.",
    ]


def test_no_folder(settings, tmp_path):
    assert sync_reference_photos(settings) == []  # reference_photos_dir=None in the test settings
    assert sync_reference_photos(replace(settings, reference_photos_dir=tmp_path / "missing")) == []


def test_caption_from_filename():
    assert caption_from_filename("personx.jpg") == "personx"
    assert caption_from_filename("dog.PNG") == "dog"


def test_folder_from_env(monkeypatch):
    monkeypatch.delenv("REFERENCE_PHOTOS_DIR", raising=False)
    assert Settings.from_env().reference_photos_dir == ROOT / "reference-photos"
    monkeypatch.setenv("REFERENCE_PHOTOS_DIR", "")
    assert Settings.from_env().reference_photos_dir is None


def test_older_database_gets_the_new_columns(tmp_path):
    path = tmp_path / "words.db"
    old = sqlite3.connect(path)
    old.execute(
        "CREATE TABLE photos (id INTEGER PRIMARY KEY, filename TEXT NOT NULL, caption TEXT NOT NULL DEFAULT '')"
    )
    old.close()
    init_db(path)
    columns = {row[1] for row in sqlite3.connect(path).execute("PRAGMA table_info(photos)")}
    assert {"source", "source_hash"} <= columns

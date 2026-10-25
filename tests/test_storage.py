"""Copying data from the old Node.js layout into the data folder."""

from conftest import JPEG

from image_generator.config import Settings
from image_generator.db import Database, init_db
from image_generator.storage import copy_old_data


def old_layout(root):
    (root / "public" / "images").mkdir(parents=True)
    (root / "uploads").mkdir()
    (root / "words.db").write_bytes(b"sqlite")
    (root / "public" / "images" / "100.jpg").write_bytes(JPEG)
    (root / "public" / "images" / ".gitkeep").write_bytes(b"")
    (root / "uploads" / "100-abcdef12.jpg").write_bytes(JPEG)
    (root / "uploads" / "100-abcdef12-large.jpg").write_bytes(JPEG)


def test_copies_everything_once_and_never_overwrites(tmp_path):
    old_layout(tmp_path / "old")
    settings = Settings(data_dir=tmp_path / "data")

    messages = copy_old_data(settings, tmp_path / "old")
    assert len(messages) == 3
    assert settings.db_path.read_bytes() == b"sqlite"
    assert [p.name for p in settings.images_dir.iterdir()] == ["100.jpg"]
    assert sorted(p.name for p in settings.photos_dir.iterdir()) == ["100-abcdef12-large.jpg", "100-abcdef12.jpg"]
    # The old files stay where they were (the Node.js version keeps working).
    assert (tmp_path / "old" / "words.db").exists()

    settings.db_path.write_bytes(b"newer")
    assert copy_old_data(settings, tmp_path / "old") == [
        "Nothing to copy: no old data found, or it was already copied."
    ]
    assert settings.db_path.read_bytes() == b"newer"


def test_replaces_an_empty_new_database_but_never_one_with_data(tmp_path):
    old = tmp_path / "old"
    old.mkdir()
    settings = Settings(data_dir=tmp_path / "data")
    init_db(old / "words.db")
    old_db = Database(old / "words.db")
    old_db.insert_word("from the old version")
    old_db.close()

    init_db(settings.db_path)  # the new server was started before copying: empty database
    assert copy_old_data(settings, old)[0].startswith("Copied")
    db = Database(settings.db_path)
    assert [w["text"] for w in db.list_words()] == ["from the old version"]
    db.insert_word("new")
    db.close()
    assert copy_old_data(settings, old) == ["Nothing to copy: no old data found, or it was already copied."]


def test_context_loaded_from_file_does_not_block_copying(tmp_path):
    old = tmp_path / "old"
    old.mkdir()
    init_db(old / "words.db")
    settings = Settings(data_dir=tmp_path / "data")
    init_db(settings.db_path)
    db = Database(settings.db_path)
    db.set_setting("context", "from context.txt")
    db.set_setting("context_file_hash", "abc")
    db.close()
    assert copy_old_data(settings, old)[0].startswith("Copied")

    # A context typed in the app (no file hash) or a glossary is real data: never replaced.
    db = Database(settings.db_path)
    db.set_setting("glossary", "Whisky: a dog")
    db.close()
    assert copy_old_data(settings, old) == ["Nothing to copy: no old data found, or it was already copied."]


def test_leaves_an_unreadable_database_alone(tmp_path):
    old = tmp_path / "old"
    old.mkdir()
    (old / "words.db").write_bytes(b"old")
    settings = Settings(data_dir=tmp_path / "data")
    settings.data_dir.mkdir()
    settings.db_path.write_bytes(b"not a database")
    assert copy_old_data(settings, old) == ["Nothing to copy: no old data found, or it was already copied."]
    assert settings.db_path.read_bytes() == b"not a database"


def test_nothing_to_copy(tmp_path):
    settings = Settings(data_dir=tmp_path / "data")
    assert copy_old_data(settings, tmp_path / "empty") == [
        "Nothing to copy: no old data found, or it was already copied."
    ]

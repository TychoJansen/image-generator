"""SQLite storage for words, settings and reference photos."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS words (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  text TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS photos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  filename TEXT NOT NULL,
  caption TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  source TEXT,       -- file name in the reference-photos folder; NULL for photos uploaded in the app
  source_hash TEXT   -- fingerprint of that file, to notice when it changes
);
"""

# Columns added after the first version; older databases get them at startup.
NEW_PHOTO_COLUMNS = {"source": "TEXT", "source_hash": "TEXT"}

Row = dict[str, Any]


def init_db(path: Path) -> None:
    """Create the database file and its tables if they do not exist yet (once, at startup)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    db = Database(path)
    try:
        db.conn.executescript(SCHEMA)
        existing = {row["name"] for row in db.conn.execute("PRAGMA table_info(photos)")}
        for column, kind in NEW_PHOTO_COLUMNS.items():
            if column not in existing:
                db.conn.execute(f"ALTER TABLE photos ADD COLUMN {column} {kind}")  # fixed names, no user input
    finally:
        db.close()


class Database:
    """One SQLite connection; the app opens a new one for every request (see deps.get_db)."""

    def __init__(self, path: Path) -> None:
        """Open the database file in autocommit mode."""
        # FastAPI may open the connection in one worker thread and use it in another (one request at a time),
        # so the same-thread check is switched off. SQLite itself handles concurrent requests via file locks.
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=10)
        self.conn.row_factory = sqlite3.Row

    def close(self) -> None:
        """Close the connection."""
        self.conn.close()

    def _one(self, sql: str, params: tuple = ()) -> Row | None:
        row = self.conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def _all(self, sql: str, params: tuple = ()) -> list[Row]:
        return [dict(row) for row in self.conn.execute(sql, params).fetchall()]

    # --- Words ---

    def list_words(self) -> list[Row]:
        """All words, newest first."""
        return self._all("SELECT id, text, created_at FROM words ORDER BY id DESC")

    def insert_word(self, text: str) -> Row:
        """Store a word and return it."""
        cursor = self.conn.execute("INSERT INTO words (text) VALUES (?)", (text,))
        return self.get_word(cursor.lastrowid)

    def get_word(self, word_id: int | None) -> Row | None:
        """One word, or None if it does not exist."""
        return self._one("SELECT id, text, created_at FROM words WHERE id = ?", (word_id,))

    def delete_word(self, word_id: int) -> bool:
        """Delete one word; returns whether it existed."""
        return self.conn.execute("DELETE FROM words WHERE id = ?", (word_id,)).rowcount > 0

    def delete_all_words(self) -> int:
        """Delete every word; returns how many were deleted."""
        return self.conn.execute("DELETE FROM words").rowcount

    # --- Settings (context, glossary, word cloud variants) ---

    def get_setting(self, key: str) -> str:
        """A stored setting, or an empty string."""
        row = self._one("SELECT value FROM settings WHERE key = ?", (key,))
        return row["value"] if row else ""

    def set_setting(self, key: str, value: str) -> None:
        """Store a setting, replacing any earlier value."""
        self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    # --- Reference photos ---

    def list_photos(self) -> list[Row]:
        """All reference photos, newest first."""
        return self._all("SELECT id, filename, caption, source FROM photos ORDER BY id DESC")

    def count_photos(self) -> int:
        """How many reference photos are stored."""
        return self._one("SELECT COUNT(*) AS n FROM photos")["n"]

    def photos_from_folder(self) -> list[Row]:
        """The photos that came from the reference-photos folder."""
        return self._all("SELECT id, filename, caption, source, source_hash FROM photos WHERE source IS NOT NULL")

    def insert_photo(
        self, filename: str, caption: str, source: str | None = None, source_hash: str | None = None
    ) -> Row:
        """Store a photo record and return it; `source` is set for photos from the reference-photos folder."""
        cursor = self.conn.execute(
            "INSERT INTO photos (filename, caption, source, source_hash) VALUES (?, ?, ?, ?)",
            (filename, caption, source, source_hash),
        )
        return self.get_photo(cursor.lastrowid)

    def get_photo(self, photo_id: int | None) -> Row | None:
        """One photo record, or None if it does not exist."""
        return self._one("SELECT id, filename, caption, source FROM photos WHERE id = ?", (photo_id,))

    def delete_photo(self, photo_id: int) -> None:
        """Delete a photo record (the files are removed by the caller)."""
        self.conn.execute("DELETE FROM photos WHERE id = ?", (photo_id,))

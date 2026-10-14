"""SQLite storage for the game: items and the images they use.

Every downloaded image is recorded in the `images` table with its Wikimedia
file name, source URL and SHA-256 of the bytes. All three are UNIQUE, so the
same picture can never be added twice, even under a different topic.
"""
import os
import sqlite3

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "data", "game.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS images (
    id           INTEGER PRIMARY KEY,
    source_file  TEXT UNIQUE,          -- Wikimedia file name, e.g. Pani_Puri1.JPG
    source_url   TEXT UNIQUE NOT NULL, -- URL the bytes were downloaded from
    sha256       TEXT UNIQUE NOT NULL, -- hash of the downloaded bytes
    local_path   TEXT NOT NULL,        -- relative to static/, e.g. images/ab12.jpg
    width        INTEGER,
    height       INTEGER,
    added_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS items (
    id           INTEGER PRIMARY KEY,
    wiki_title   TEXT UNIQUE NOT NULL, -- canonical English Wikipedia title
    name         TEXT NOT NULL,        -- display name
    name_bn      TEXT,                 -- Bangla name (from bn.wikipedia langlink)
    description  TEXT,
    category     TEXT,
    views        INTEGER NOT NULL,     -- median monthly views, en + bn Wikipedia
    image_id     INTEGER UNIQUE NOT NULL REFERENCES images(id),
    page_url     TEXT,
    added_at     TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Topics deliberately excluded from the game. Never added, even with --retry-skipped.
CREATE TABLE IF NOT EXISTS blocked (
    title        TEXT PRIMARY KEY,     -- requested or canonical Wikipedia title
    reason       TEXT NOT NULL,
    at           TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Topics that were tried and rejected, so re-runs don't fetch them again.
CREATE TABLE IF NOT EXISTS skipped (
    requested    TEXT PRIMARY KEY,
    reason       TEXT NOT NULL,
    at           TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def all_items(conn):
    rows = conn.execute(
        """SELECT i.id, i.name, i.name_bn, i.description, i.category, i.views,
                  i.page_url, img.local_path AS image
           FROM items i JOIN images img ON img.id = i.image_id
           WHERE i.views > 0
           ORDER BY i.id"""
    ).fetchall()
    return [dict(r) for r in rows]

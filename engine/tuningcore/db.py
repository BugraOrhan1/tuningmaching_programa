"""TuningCore database: één SQLite-bestand, WAL, minimale tabellen.

Filosofie: geen ORM, geen migratie-hel — één schema, additief, indexen op
de hot paths. Elke schrijfactie is een batch in één transactie.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS roots(
  id INTEGER PRIMARY KEY, path TEXT UNIQUE, added_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS contents(
  id INTEGER PRIMARY KEY, sha256 TEXT UNIQUE, size INTEGER, kind TEXT);
CREATE TABLE IF NOT EXISTS files(
  id INTEGER PRIMARY KEY, root_id INTEGER REFERENCES roots(id),
  path TEXT UNIQUE, name TEXT, ext TEXT, size INTEGER, mtime REAL,
  sha256 TEXT, content_id INTEGER, state TEXT DEFAULT 'NEW',
  scanned_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_files_state ON files(state);
CREATE INDEX IF NOT EXISTS idx_files_root ON files(root_id);
CREATE TABLE IF NOT EXISTS ols_projects(
  id INTEGER PRIMARY KEY, file_id INTEGER REFERENCES files(id),
  path TEXT UNIQUE, sha256 TEXT, size INTEGER, source_mtime REAL,
  signature TEXT, identity TEXT, stride INTEGER, parsed_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS ols_versions(
  id INTEGER PRIMARY KEY, project_id INTEGER REFERENCES ols_projects(id),
  vindex INTEGER, name TEXT, path TEXT, role TEXT, confidence REAL,
  stage TEXT, complete INTEGER,
  binary_offset INTEGER, binary_length INTEGER, binary_sha256 TEXT,
  UNIQUE(project_id, vindex));
CREATE INDEX IF NOT EXISTS idx_versions_role ON ols_versions(role);
CREATE TABLE IF NOT EXISTS pairs(
  id INTEGER PRIMARY KEY, project_id INTEGER REFERENCES ols_projects(id),
  original_version_id INTEGER, tuned_version_id INTEGER,
  basis TEXT, confidence REAL, state TEXT DEFAULT 'suggested',
  UNIQUE(original_version_id, tuned_version_id));
CREATE TABLE IF NOT EXISTS errors(
  id INTEGER PRIMARY KEY, path TEXT, phase TEXT, message TEXT,
  at TEXT DEFAULT CURRENT_TIMESTAMP);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open de kern-database met de juiste pragmas (WAL = snel én veilig)."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path), timeout=60)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(SCHEMA)
    db.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
               (str(SCHEMA_VERSION),))
    db.commit()
    return db


def bump_meta(db: sqlite3.Connection, key: str, value: str) -> None:
    db.execute("INSERT INTO meta(key, value) VALUES (?, ?) "
               "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def get_meta(db: sqlite3.Connection, key: str, default: str | None = None):
    row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def log_error(db: sqlite3.Connection, path: str, phase: str, message: str) -> None:
    """Fout NOOIT gooien in bulk-paden: loggen en doorgaan (nooit crashen)."""
    db.execute("INSERT INTO errors(path, phase, message) VALUES (?,?,?)",
               (str(path), phase, str(message)[:500]))

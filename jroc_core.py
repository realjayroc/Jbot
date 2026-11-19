"""SQLite-backed shared state for the J-Bot desktop runtime."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


DEFAULT_DB_PATH = Path(os.getenv("JROC_DB_PATH", Path(__file__).with_name("jroc_core.db")))


class JrocCore:
    """Thread-safe access to the local event, repository, and dispatch tables."""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self._lock = threading.RLock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path), timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._lock, self._connection() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS repositories (
                    name TEXT PRIMARY KEY,
                    path TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    discovered_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS dispatches (
                    id INTEGER PRIMARY KEY,
                    repository TEXT NOT NULL,
                    workflow TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def record_event(self, event_type: str, details: dict[str, Any]) -> None:
        if not event_type.strip() or not isinstance(details, dict):
            raise ValueError("event_type and details are required")
        encoded = json.dumps(details, sort_keys=True)
        with self._lock, self._connection() as connection:
            connection.execute(
                "INSERT INTO events(event_type, details_json, created_at) VALUES (?, ?, ?)",
                (event_type, encoded, self._now()),
            )

    def upsert_repository(self, name: str, path: str | Path, manifest: dict[str, Any]) -> None:
        if not name.strip() or not isinstance(manifest, dict):
            raise ValueError("repository name and manifest are required")
        with self._lock, self._connection() as connection:
            connection.execute(
                """INSERT INTO repositories(name, path, manifest_json, discovered_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET path = excluded.path,
                       manifest_json = excluded.manifest_json, discovered_at = excluded.discovered_at""",
                (name, str(path), json.dumps(manifest, sort_keys=True), self._now()),
            )

    def list_repositories(self) -> list[dict[str, Any]]:
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT name, path, manifest_json, discovered_at FROM repositories ORDER BY name"
            ).fetchall()
        return [
            {"name": row["name"], "path": row["path"], "manifest": json.loads(row["manifest_json"]),
             "discovered_at": row["discovered_at"]}
            for row in rows
        ]

    def record_dispatch(self, repository: str, workflow: str, status: str, error: str | None = None) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                """INSERT INTO dispatches(repository, workflow, status, error, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (repository, workflow, status, error, self._now()),
            )

    def integrity_check(self) -> str:
        with self._lock, self._connection() as connection:
            row = connection.execute("PRAGMA integrity_check").fetchone()
        return str(row[0])

    def recent_events(self, limit: int = 50) -> list[dict[str, Any]]:
        if limit < 1:
            raise ValueError("limit must be positive")
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT id, event_type, details_json, created_at FROM events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {"id": row["id"], "event_type": row["event_type"],
             "details": json.loads(row["details_json"]), "created_at": row["created_at"]}
            for row in rows
        ]

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class Store:
    def __init__(self, path: str | Path):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen (
                url_key TEXT PRIMARY KEY,
                title_key TEXT,
                url TEXT,
                title TEXT,
                first_seen TEXT,
                reported_at TEXT,
                status TEXT
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT,
                path TEXT,
                item_count INTEGER,
                mode TEXT
            )
            """
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def is_seen(self, url_key: str, title_key: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM seen WHERE url_key = ? OR (title_key = ? AND title_key != '')",
            (url_key, title_key),
        ).fetchone()
        return row is not None

    def mark(self, url_key: str, title_key: str, url: str, title: str, status: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """
            INSERT INTO seen (url_key, title_key, url, title, first_seen, reported_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url_key) DO UPDATE SET
                title_key = excluded.title_key,
                reported_at = excluded.reported_at,
                status = excluded.status
            """,
            (url_key, title_key, url, title, now, now, status),
        )
        self.conn.commit()

    def record_report(self, path: str, item_count: int, mode: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "INSERT INTO reports (created_at, path, item_count, mode) VALUES (?, ?, ?, ?)",
            (now, path, item_count, mode),
        )
        self.conn.commit()

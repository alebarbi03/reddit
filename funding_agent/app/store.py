"""SQLite record of rounds already reported.

The point of the store is that tomorrow's brief only contains rounds you
haven't seen yet — without it, a daily agent re-posts the same companies every
morning until they roll off the Explorer's front page.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .models import Round

SCHEMA = """
CREATE TABLE IF NOT EXISTS rounds (
    key            TEXT PRIMARY KEY,
    company        TEXT NOT NULL,
    amount_eur     REAL,
    amount_display TEXT,
    description    TEXT,
    lead_investor  TEXT,
    stage          TEXT,
    sector         TEXT,
    announced_on   TEXT,
    source_url     TEXT,
    source         TEXT,
    payload        TEXT,
    first_seen_at  TEXT NOT NULL,
    posted_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_rounds_first_seen ON rounds(first_seen_at);

CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ran_at       TEXT NOT NULL,
    found        INTEGER NOT NULL,
    new_rounds   INTEGER NOT NULL,
    posts        INTEGER NOT NULL,
    source       TEXT,
    note         TEXT
);
"""


class Store:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def known_keys(self) -> set[str]:
        with self._connect() as conn:
            return {row["key"] for row in conn.execute("SELECT key FROM rounds")}

    def new_rounds(self, rounds: list[Round]) -> list[Round]:
        known = self.known_keys()
        return [r for r in rounds if r.key not in known]

    def record(self, rounds: list[Round], mark_posted: bool = False) -> int:
        """Inserts rounds we haven't stored before. Returns the insert count."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        inserted = 0
        with self._connect() as conn:
            for r in rounds:
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO rounds
                        (key, company, amount_eur, amount_display, description,
                         lead_investor, stage, sector, announced_on, source_url,
                         source, payload, first_seen_at, posted_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        r.key, r.company, r.amount_eur, r.amount_display, r.description,
                        r.lead_investor, r.stage, r.sector, r.announced_on, r.source_url,
                        r.source, json.dumps(r.to_dict(), ensure_ascii=False), now,
                        now if mark_posted else None,
                    ),
                )
                inserted += cursor.rowcount
        return inserted

    def mark_posted(self, rounds: list[Round]) -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.executemany(
                "UPDATE rounds SET posted_at = ? WHERE key = ? AND posted_at IS NULL",
                [(now, r.key) for r in rounds],
            )

    def log_run(self, found: int, new_rounds: int, posts: int, source: str, note: str = "") -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO runs (ran_at, found, new_rounds, posts, source, note) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    found, new_rounds, posts, source, note,
                ),
            )

    def recent_runs(self, limit: int = 10) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(row) for row in rows]

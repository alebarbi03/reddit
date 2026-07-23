import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS subreddits (
    name TEXT PRIMARY KEY,
    display_name TEXT,
    subscribers INTEGER,
    over18 INTEGER,
    quarantined INTEGER,
    status TEXT NOT NULL,        -- ok | private | banned | quarantined | not_found | error
    status_detail TEXT,
    fetched_at TEXT,
    num_posts INTEGER DEFAULT 0,
    rules_json TEXT,             -- JSON list of {short_name, description, violation_reason}
    automod_available INTEGER DEFAULT 0,
    automod_raw TEXT,
    automod_keywords_json TEXT   -- JSON list of {pattern, kind, source_snippet}
);

CREATE TABLE IF NOT EXISTS posts (
    id TEXT PRIMARY KEY,
    subreddit TEXT NOT NULL,
    title TEXT,
    selftext TEXT,
    flair TEXT,
    created_utc REAL,
    score INTEGER,
    embedding BLOB,
    FOREIGN KEY (subreddit) REFERENCES subreddits(name)
);
CREATE INDEX IF NOT EXISTS idx_posts_subreddit ON posts(subreddit);

CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    title TEXT,
    body TEXT,
    created_at TEXT NOT NULL
);
"""


def _ensure_dir() -> None:
    Path(settings.resolved_db_path).parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    _ensure_dir()
    conn = sqlite3.connect(settings.resolved_db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def upsert_subreddit(info: dict[str, Any]) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO subreddits (
                name, display_name, subscribers, over18, quarantined,
                status, status_detail, fetched_at, num_posts,
                rules_json, automod_available, automod_raw, automod_keywords_json
            ) VALUES (
                :name, :display_name, :subscribers, :over18, :quarantined,
                :status, :status_detail, :fetched_at, :num_posts,
                :rules_json, :automod_available, :automod_raw, :automod_keywords_json
            )
            ON CONFLICT(name) DO UPDATE SET
                display_name=excluded.display_name,
                subscribers=excluded.subscribers,
                over18=excluded.over18,
                quarantined=excluded.quarantined,
                status=excluded.status,
                status_detail=excluded.status_detail,
                fetched_at=excluded.fetched_at,
                num_posts=excluded.num_posts,
                rules_json=excluded.rules_json,
                automod_available=excluded.automod_available,
                automod_raw=excluded.automod_raw,
                automod_keywords_json=excluded.automod_keywords_json
            """,
            info,
        )


def get_subreddit(name: str) -> Optional[dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM subreddits WHERE name = ?", (name.lower(),)
        ).fetchone()
        return dict(row) if row else None


def list_subreddits() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM subreddits ORDER BY fetched_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def replace_posts(subreddit: str, posts: list[dict[str, Any]]) -> None:
    subreddit = subreddit.lower()
    with get_conn() as conn:
        conn.execute("DELETE FROM posts WHERE subreddit = ?", (subreddit,))
        conn.executemany(
            """
            INSERT INTO posts (id, subreddit, title, selftext, flair, created_utc, score, embedding)
            VALUES (:id, :subreddit, :title, :selftext, :flair, :created_utc, :score, :embedding)
            """,
            [{**p, "subreddit": subreddit} for p in posts],
        )


def get_posts(subreddit: str) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM posts WHERE subreddit = ?", (subreddit.lower(),)
        ).fetchall()
        return [dict(r) for r in rows]


def save_draft(title: str, body: str, name: Optional[str] = None) -> int:
    from datetime import datetime, timezone

    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO drafts (name, title, body, created_at) VALUES (?, ?, ?, ?)",
            (name, title, body, datetime.now(timezone.utc).isoformat()),
        )
        return cur.lastrowid


def list_drafts() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM drafts ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def delete_draft(draft_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM drafts WHERE id = ?", (draft_id,))


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def loads(text: Optional[str], default: Any = None) -> Any:
    if not text:
        return default
    return json.loads(text)

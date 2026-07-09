"""SQLite-backed storage for rate-limiting and audit log."""
from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, List, Tuple

from bol_bot.config import get_settings

logger = logging.getLogger(__name__)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    username TEXT,
    file_hash TEXT,
    page_index INTEGER,
    mode TEXT,
    field_context TEXT,
    old_value TEXT,
    new_value TEXT,
    tz_from TEXT,
    tz_to TEXT,
    success INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id, ts);

CREATE TABLE IF NOT EXISTS rate_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rate_user ON rate_events(user_id, ts);
"""


def _db_path() -> Path:
    return Path(get_settings().db_path)


def _utc_now_sql() -> str:
    """UTC timestamp in SQLite's own ``datetime()`` format.

    SQLite's ``datetime('now', ...)`` produces ``YYYY-MM-DD HH:MM:SS``
    (space separator, no offset). ``datetime.isoformat()`` produces
    ``YYYY-MM-DDTHH:MM:SS.ffffff+00:00`` (``T`` separator). Comparing the
    two as plain TEXT is lexicographic: at the date/time boundary, ``"T"``
    (0x54) always sorts after ``" "`` (0x20), so any stored row from
    *today* — no matter how many hours ago — would satisfy
    ``ts > datetime('now', '-1 minutes')``. That silently broke both rate
    limiting (counts became "all of today", not "last N minutes") and the
    `/stats` "last 24h" figure. Store in SQLite's own format so the TEXT
    comparison is actually correct.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, isolation_level=None)
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        con.close()


def init_db() -> None:
    with _conn() as con:
        con.executescript(_SCHEMA)


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

def log_edit(
    *,
    user_id: int,
    username: str | None,
    file_hash: str | None,
    page_index: int,
    mode: str,
    field_context: str,
    old_value: str,
    new_value: str,
    tz_from: str | None,
    tz_to: str | None,
    success: bool = True,
) -> None:
    try:
        with _conn() as con:
            con.execute(
                """INSERT INTO audit_log
                   (ts, user_id, username, file_hash, page_index, mode,
                    field_context, old_value, new_value, tz_from, tz_to, success)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    _utc_now_sql(),
                    user_id, username, file_hash, page_index, mode,
                    field_context, old_value, new_value, tz_from, tz_to,
                    1 if success else 0,
                ),
            )
    except Exception:
        logger.exception("audit_log_failed")


def recent_edits(user_id: int, limit: int = 10) -> List[sqlite3.Row]:
    with _conn() as con:
        cur = con.execute(
            "SELECT * FROM audit_log WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )
        return cur.fetchall()


def global_stats() -> Tuple[int, int, int]:
    """Return (total_edits, unique_users, last_24h_edits)."""
    with _conn() as con:
        total = con.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        unique = con.execute(
            "SELECT COUNT(DISTINCT user_id) FROM audit_log"
        ).fetchone()[0]
        last_24h = con.execute(
            "SELECT COUNT(*) FROM audit_log "
            "WHERE ts > datetime('now', '-1 day')"
        ).fetchone()[0]
        return total, unique, last_24h


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

def record_request(user_id: int) -> None:
    with _conn() as con:
        con.execute(
            "INSERT INTO rate_events(user_id, ts) VALUES (?, ?)",
            (user_id, _utc_now_sql()),
        )
        # Garbage-collect events older than 2 days
        con.execute(
            "DELETE FROM rate_events WHERE ts < datetime('now', '-2 days')"
        )


def count_requests(user_id: int, window_minutes: int) -> int:
    with _conn() as con:
        cur = con.execute(
            "SELECT COUNT(*) FROM rate_events "
            "WHERE user_id=? AND ts > datetime('now', ?)",
            (user_id, f"-{window_minutes} minutes"),
        )
        return cur.fetchone()[0]


def is_rate_limited(user_id: int) -> tuple[bool, str]:
    """Returns (limited, reason)."""
    s = get_settings()
    per_min = count_requests(user_id, 1)
    if per_min >= s.rate_limit_per_minute:
        return True, f"daqiqada {s.rate_limit_per_minute} ta cheklov"
    per_day = count_requests(user_id, 24 * 60)
    if per_day >= s.rate_limit_per_day:
        return True, f"kunlik {s.rate_limit_per_day} ta cheklov"
    return False, ""

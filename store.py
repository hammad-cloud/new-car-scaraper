"""Remembers lots you were already alerted about, so you never get duplicates."""
import sqlite3
from datetime import datetime

DB = "seen.db"


def _conn():
    c = sqlite3.connect(DB)
    c.execute("CREATE TABLE IF NOT EXISTS seen (url TEXT PRIMARY KEY, decision TEXT, at TEXT)")
    return c


def is_seen(url: str) -> bool:
    with _conn() as c:
        return c.execute("SELECT 1 FROM seen WHERE url=?", (url,)).fetchone() is not None


def mark_seen(url: str, decision: str) -> None:
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO seen VALUES (?,?,?)",
                  (url, decision, datetime.now().isoformat(timespec="seconds")))

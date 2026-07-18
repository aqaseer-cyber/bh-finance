"""FIX-17h: the parsed-fact store — SQLite memo of expensive parse
products, keyed by content (accession/XML hash + parser version).

Warm re-analysis was dominated by re-parsing multi-megabyte XBRL
instance XMLs the HTTP cache already held. Filings are immutable, so a
parse result keyed by (parser version, content hash) never goes stale;
bumping the version constant at the parse site invalidates cleanly
when the parser itself changes.

Best-effort by design: any SQLite failure degrades to a live parse —
the store can be deleted at any time (it lives inside the cache folder
next to the HTTP cache and rebuilds itself)."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from . import config


class FactStore:
    def __init__(self, path: Optional[Path] = None):
        self.path = path or (config.cache_dir() / "facts.db")

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.execute("CREATE TABLE IF NOT EXISTS parsed ("
                     "key TEXT PRIMARY KEY, value TEXT NOT NULL, "
                     "saved_at REAL NOT NULL)")
        return conn

    def get(self, key: str) -> Optional[Any]:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT value FROM parsed WHERE key = ?",
                    (key,)).fetchone()
            return json.loads(row[0]) if row else None
        except (sqlite3.Error, OSError, ValueError):
            return None

    def put(self, key: str, obj: Any) -> None:
        try:
            payload = json.dumps(obj)
        except (TypeError, ValueError):
            return
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO parsed VALUES (?, ?, ?)",
                    (key, payload, time.time()))
        except (sqlite3.Error, OSError):
            pass

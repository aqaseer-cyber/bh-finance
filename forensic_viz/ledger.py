"""Verdict ledger (master §5.7) — SQLite, the Layer-C state store.

Every computed verdict is logged (no verdict leaves the session unlogged);
open triggers ride along for the session-start re-check ritual. Staleness
follows house §8: a price older than ~5 trading days flags the row.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path
from typing import List, Optional

from . import config

STALE_DAYS = 7  # ~5 trading days

_SCHEMA = """
CREATE TABLE IF NOT EXISTS verdicts (
    ticker TEXT PRIMARY KEY,
    company TEXT, track TEXT, method TEXT,
    rating TEXT, fv_avg REAL, mos REAL, stressed_mos REAL,
    price REAL, price_date TEXT, coherence TEXT,
    thesis TEXT, terminal_risk TEXT, optionality TEXT,
    years INTEGER, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS triggers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    trigger_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN',
    created_at TEXT, closed_at TEXT
);
"""


def default_path() -> Path:
    return config.cache_dir().parent / "ledger.db"


class Ledger:
    def __init__(self, path: Optional[str] = None):
        self.path = str(path or default_path())
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self):
        self._conn.close()

    # ------------------------------------------------------------- verdicts

    def upsert_verdict(self, d, res=None, verdict=None) -> None:
        row = {
            "ticker": d.ticker, "company": d.company, "track": d.track,
            "method": res.method if res is not None else "",
            "rating": verdict.rating if verdict is not None else "",
            "fv_avg": verdict.fv_avg if verdict is not None else None,
            "mos": verdict.mos if verdict is not None else None,
            "stressed_mos": verdict.stressed_mos if verdict is not None else None,
            "price": d.last_close,
            "price_date": d.price_dates[-1].isoformat() if d.price_dates else "",
            "coherence": verdict.coherence if verdict is not None else "",
            "thesis": d.thesis, "terminal_risk": d.terminal_risk,
            "optionality": d.optionality, "years": d.display_years,
            "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
        }
        cols = ", ".join(row)
        self._conn.execute(
            f"INSERT INTO verdicts ({cols}) VALUES ({', '.join(':' + k for k in row)}) "
            "ON CONFLICT(ticker) DO UPDATE SET "
            + ", ".join(f"{k}=excluded.{k}" for k in row if k != "ticker"),
            row)
        self._conn.commit()

    def list_verdicts(self) -> List[dict]:
        rows = self._conn.execute(
            "SELECT * FROM verdicts ORDER BY updated_at DESC").fetchall()
        out = []
        today = dt.date.today()
        for r in rows:
            rec = dict(r)
            rec["age_days"] = None
            if rec.get("updated_at"):
                try:
                    updated = dt.datetime.fromisoformat(rec["updated_at"]).date()
                    rec["age_days"] = (today - updated).days
                except ValueError:
                    pass
            rec["stale"] = rec["age_days"] is None or rec["age_days"] > STALE_DAYS
            rec["open_triggers"] = self._conn.execute(
                "SELECT COUNT(*) FROM triggers WHERE ticker=? AND status='OPEN'",
                (rec["ticker"],)).fetchone()[0]
            out.append(rec)
        return out

    def remove(self, ticker: str) -> None:
        self._conn.execute("DELETE FROM verdicts WHERE ticker=?", (ticker,))
        self._conn.execute("DELETE FROM triggers WHERE ticker=?", (ticker,))
        self._conn.commit()

    # ------------------------------------------------------------- triggers

    def add_trigger(self, ticker: str, text: str) -> None:
        self._conn.execute(
            "INSERT INTO triggers (ticker, trigger_text, created_at) VALUES (?,?,?)",
            (ticker.upper(), text,
             dt.datetime.now().isoformat(timespec="seconds")))
        self._conn.commit()

    def open_triggers(self, ticker: Optional[str] = None) -> List[dict]:
        q = "SELECT * FROM triggers WHERE status='OPEN'"
        args: tuple = ()
        if ticker:
            q += " AND ticker=?"
            args = (ticker.upper(),)
        return [dict(r) for r in self._conn.execute(q, args).fetchall()]

    def close_trigger(self, trigger_id: int) -> None:
        self._conn.execute(
            "UPDATE triggers SET status='CLOSED', closed_at=? WHERE id=?",
            (dt.datetime.now().isoformat(timespec="seconds"), trigger_id))
        self._conn.commit()

    # --------------------------------------------------------------- import

    def import_seed(self, json_path: str) -> int:
        """Best-effort import of a verdict_ledger_seed.json-style file: a list
        (or {'verdicts': [...]}) of dicts keyed loosely; ticker required.
        Imported rows keep their stated confidence caveat — verify against the
        original workbooks before trusting any number (per the manifest)."""
        with open(json_path, encoding="utf-8") as fh:
            payload = json.load(fh)
        if isinstance(payload, dict):
            payload = payload.get("verdicts") or payload.get("ledger") or []
        n = 0
        for item in payload:
            if not isinstance(item, dict):
                continue
            ticker = str(item.get("ticker") or item.get("symbol") or "").upper()
            if not ticker:
                continue
            row = {
                "ticker": ticker,
                "company": str(item.get("company") or item.get("name") or ""),
                "track": str(item.get("track") or "standard").lower(),
                "method": str(item.get("method") or item.get("basis") or ""),
                "rating": str(item.get("rating") or item.get("verdict") or ""),
                "fv_avg": item.get("fv") or item.get("fv_avg"),
                "mos": item.get("mos"),
                "stressed_mos": item.get("stressed_mos"),
                "price": item.get("price") or item.get("p0"),
                "price_date": str(item.get("price_date") or ""),
                "coherence": "imported [Likely] — verify vs original workbook",
                "thesis": str(item.get("thesis") or ""),
                "terminal_risk": str(item.get("terminal_risk") or item.get("risk") or ""),
                "optionality": str(item.get("optionality") or ""),
                "years": int(item.get("years") or 10),
                "updated_at": str(item.get("updated_at") or item.get("date")
                                  or dt.datetime.now().isoformat(timespec="seconds")),
            }
            cols = ", ".join(row)
            self._conn.execute(
                f"INSERT INTO verdicts ({cols}) VALUES ({', '.join(':' + k for k in row)}) "
                "ON CONFLICT(ticker) DO UPDATE SET "
                + ", ".join(f"{k}=excluded.{k}" for k in row if k != "ticker"),
                row)
            for trig in item.get("triggers") or []:
                self._conn.execute(
                    "INSERT INTO triggers (ticker, trigger_text, created_at) "
                    "VALUES (?,?,?)",
                    (ticker, str(trig), row["updated_at"]))
            n += 1
        self._conn.commit()
        return n

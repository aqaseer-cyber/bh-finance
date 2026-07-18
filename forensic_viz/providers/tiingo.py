"""FIX-17a: Tiingo client (token-header auth).

Role (owner-ratified): primary daily price source for FIX-17b — 30+
years of split/dividend-adjusted EOD closes behind a documented, keyed
API; Stooq demotes to fallback and the Yahoo scrape retires. Provenance
grade: aggregator (exchange-derived prices)."""
from __future__ import annotations

from typing import Optional

from .. import config
from .base import BaseClient, ProbeResult, run_check

BASE = "https://api.tiingo.com"


class TiingoClient(BaseClient):
    name = "Tiingo"
    provenance = "aggregator"

    @property
    def key(self) -> str:
        return config.TIINGO_API_KEY

    def _headers(self) -> dict:
        return {"Authorization": f"Token {self.key}",
                "Content-Type": "application/json"}

    def meta(self, symbol: str):
        return self.get_json(f"{BASE}/tiingo/daily/{symbol}")

    def daily_prices(self, symbol: str, start: Optional[str] = None,
                     end: Optional[str] = None):
        params = {}
        if start:
            params["startDate"] = start
        if end:
            params["endDate"] = end
        return self.get_json(f"{BASE}/tiingo/daily/{symbol}/prices",
                             params)


def probe(ticker: str, transport=None) -> "list[ProbeResult]":
    c = TiingoClient(transport=transport, timeout=20)
    return [
        run_check(c.name, "ticker metadata", lambda: c.meta(ticker),
                  lambda j: (f"daily history {j.get('startDate', '?')[:10]}"
                             f" -> {j.get('endDate', '?')[:10]}"
                             if isinstance(j, dict) and j else None)),
        run_check(c.name, "daily price depth",
                  lambda: c.daily_prices(ticker, start="2002-01-02"),
                  lambda j: (f"{len(j)} daily bars since "
                             f"{str(j[0].get('date', '?'))[:10]}"
                             if isinstance(j, list) and j else None)),
    ]

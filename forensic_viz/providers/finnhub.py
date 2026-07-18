"""FIX-17a: Finnhub client (X-Finnhub-Token header auth).

Roles (owner-ratified): financials-as-reported — an INDEPENDENT parse of
the same EDGAR filings we parse, the ideal cross-check for cells our
parser could not fill — plus the free analyst recommendation-trends
strip and a profile fallback. The eps/revenue-estimate endpoints are
probed so their plan status is recorded fact, not guesswork. Provenance
grade: aggregator."""
from __future__ import annotations

from .. import config
from .base import BaseClient, ProbeResult, run_check

BASE = "https://finnhub.io/api/v1"


class FinnhubClient(BaseClient):
    name = "Finnhub"
    provenance = "aggregator"

    @property
    def key(self) -> str:
        return config.FINNHUB_API_KEY

    def _headers(self) -> dict:
        return {"X-Finnhub-Token": self.key}

    def profile2(self, symbol: str):
        return self.get_json(f"{BASE}/stock/profile2", {"symbol": symbol})

    def quote(self, symbol: str):
        return self.get_json(f"{BASE}/quote", {"symbol": symbol})

    def recommendation(self, symbol: str):
        return self.get_json(f"{BASE}/stock/recommendation",
                             {"symbol": symbol})

    def eps_estimate(self, symbol: str, freq: str = "annual"):
        return self.get_json(f"{BASE}/stock/eps-estimate",
                             {"symbol": symbol, "freq": freq})

    def revenue_estimate(self, symbol: str, freq: str = "annual"):
        return self.get_json(f"{BASE}/stock/revenue-estimate",
                             {"symbol": symbol, "freq": freq})

    def financials_reported(self, symbol: str, freq: str = "annual"):
        return self.get_json(f"{BASE}/stock/financials-reported",
                             {"symbol": symbol, "freq": freq})

    def insider_transactions(self, symbol: str):
        return self.get_json(f"{BASE}/stock/insider-transactions",
                             {"symbol": symbol})


def _est(j) -> str:
    rows = j.get("data") if isinstance(j, dict) else None
    if not rows:
        return ""
    periods = sorted(str(r.get("period", "?"))[:7] for r in rows)
    return f"{len(rows)} periods {periods[0]}..{periods[-1]}"


def probe(ticker: str, transport=None) -> "list[ProbeResult]":
    c = FinnhubClient(transport=transport, timeout=20)
    return [
        run_check(c.name, "profile2", lambda: c.profile2(ticker),
                  lambda j: (f"{j.get('name', '?')} | {j.get('country', '?')}"
                             f" | {j.get('weburl', '?')}"
                             if isinstance(j, dict) and j else None)),
        run_check(c.name, "quote", lambda: c.quote(ticker),
                  lambda j: (f"last {j.get('c')}"
                             if isinstance(j, dict) and j.get("c")
                             else None)),
        run_check(c.name, "recommendation trends",
                  lambda: c.recommendation(ticker),
                  lambda j: (f"{len(j)} months; latest "
                             f"{j[0].get('period', '?')}: "
                             f"buy {j[0].get('buy', '?')} / hold "
                             f"{j[0].get('hold', '?')} / sell "
                             f"{j[0].get('sell', '?')}"
                             if isinstance(j, list) and j else None)),
        run_check(c.name, "EPS ESTIMATES (annual)",
                  lambda: c.eps_estimate(ticker), _est),
        run_check(c.name, "REVENUE ESTIMATES (annual)",
                  lambda: c.revenue_estimate(ticker), _est),
        run_check(c.name, "financials as reported",
                  lambda: c.financials_reported(ticker),
                  lambda j: (f"{len(j.get('data', []))} annual filings"
                             if isinstance(j, dict) and j.get("data")
                             else None)),
        run_check(c.name, "insider transactions",
                  lambda: c.insider_transactions(ticker),
                  lambda j: (f"{len(j.get('data', []))} rows"
                             if isinstance(j, dict) and j.get("data")
                             else None)),
    ]

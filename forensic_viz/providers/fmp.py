"""FIX-17a: Financial Modeling Prep client (stable API, header auth).

Roles (owner-ratified): recheck source for the recent fiscal years,
company profile (the DVH-style description/website/employees/country
block), and — if the free plan serves it, which the probe decides —
analyst estimates. Provenance grade: aggregator (never displayed as
audited truth)."""
from __future__ import annotations

from typing import Optional

from .. import config
from .base import BaseClient, ProbeResult, run_check

BASE = "https://financialmodelingprep.com/stable"


class FMPClient(BaseClient):
    name = "FMP"
    provenance = "aggregator"

    @property
    def key(self) -> str:
        return config.FMP_API_KEY

    def _headers(self) -> dict:
        # documented header auth — the key never appears in a URL
        return {"apikey": self.key,
                "User-Agent": f"{config.APP_NAME}/{config.APP_VERSION}"}

    def profile(self, symbol: str):
        return self.get_json(f"{BASE}/profile", {"symbol": symbol})

    def income_statement(self, symbol: str, period: str = "annual",
                         limit: int = 40):
        return self.get_json(f"{BASE}/income-statement",
                             {"symbol": symbol, "period": period,
                              "limit": limit})

    def balance_sheet_statement(self, symbol: str, period: str = "annual",
                                limit: int = 40):
        return self.get_json(f"{BASE}/balance-sheet-statement",
                             {"symbol": symbol, "period": period,
                              "limit": limit})

    def cash_flow_statement(self, symbol: str, period: str = "annual",
                            limit: int = 40):
        return self.get_json(f"{BASE}/cash-flow-statement",
                             {"symbol": symbol, "period": period,
                              "limit": limit})

    def analyst_estimates(self, symbol: str, period: str = "annual",
                          limit: int = 10):
        return self.get_json(f"{BASE}/analyst-estimates",
                             {"symbol": symbol, "period": period,
                              "limit": limit})

    def price_target_consensus(self, symbol: str):
        return self.get_json(f"{BASE}/price-target-consensus",
                             {"symbol": symbol})

    def grades_consensus(self, symbol: str):
        return self.get_json(f"{BASE}/grades-consensus",
                             {"symbol": symbol})

    def eod_prices(self, symbol: str, start: Optional[str] = None):
        params = {"symbol": symbol}
        if start:
            params["from"] = start
        return self.get_json(f"{BASE}/historical-price-eod/full", params)


def _span(rows) -> str:
    """'N records YYYY..YYYY' for FMP's newest-first statement lists."""
    if not isinstance(rows, list) or not rows:
        return ""
    def yr(row):
        d = str(row.get("date") or row.get("fiscalYear") or "?")
        return d[:4]
    return f"{len(rows)} records {yr(rows[-1])}..{yr(rows[0])}"


def probe(ticker: str, transport=None) -> "list[ProbeResult]":
    c = FMPClient(transport=transport, timeout=20)
    return [
        run_check(c.name, "profile", lambda: c.profile(ticker),
                  lambda j: (f"{j[0].get('companyName', '?')} | "
                             f"{j[0].get('country', '?')} | employees "
                             f"{j[0].get('fullTimeEmployees', '?')}")
                  if isinstance(j, list) and j else None),
        run_check(c.name, "income-statement (annual)",
                  lambda: c.income_statement(ticker), _span),
        run_check(c.name, "cash-flow-statement (annual)",
                  lambda: c.cash_flow_statement(ticker), _span),
        run_check(c.name, "balance-sheet (annual)",
                  lambda: c.balance_sheet_statement(ticker), _span),
        run_check(c.name, "ANALYST ESTIMATES (annual)",
                  lambda: c.analyst_estimates(ticker), _span),
        run_check(c.name, "price-target consensus",
                  lambda: c.price_target_consensus(ticker),
                  lambda j: (f"consensus {j[0].get('consensus', '?')}"
                             if isinstance(j, list) and j else
                             (f"consensus {j.get('consensus', '?')}"
                              if isinstance(j, dict) and j else None))),
        run_check(c.name, "grades consensus",
                  lambda: c.grades_consensus(ticker),
                  lambda j: ("served" if j else None)),
        run_check(c.name, "EOD price history",
                  lambda: c.eod_prices(ticker, start="2008-01-01"),
                  lambda j: (f"{len(j)} daily bars since "
                             f"{j[-1].get('date', '?')}"
                             if isinstance(j, list) and j else None)),
    ]

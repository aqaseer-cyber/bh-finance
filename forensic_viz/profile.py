"""FIX-17d: company profile — the DVH-style header context block.

Display-only by doctrine: profile fields NEVER feed a calculation.
Name and SIC come from what the EDGAR pipeline already established;
description, website, employees, country, exchange, sector, industry
and IPO date come from the FMP profile endpoint (aggregator grade) and
render with that provenance on the card. No FMP key -> an EDGAR-only
profile (the card shows dashes for the missing context)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from . import config


@dataclass
class CompanyProfile:
    name: str = ""
    ticker: str = ""
    description: str = ""
    website: str = ""
    employees: Optional[int] = None
    country: str = ""
    exchange: str = ""
    sector: str = ""
    industry: str = ""
    sic_code: str = ""
    ipo_date: str = ""
    sources: str = ""


def _employees(raw) -> Optional[int]:
    if raw in (None, ""):
        return None
    try:
        n = int(str(raw).replace(",", "").strip())
    except ValueError:
        return None
    return n if n > 0 else None


def build_profile(d, fmp_row: Optional[dict] = None) -> CompanyProfile:
    """Merge: EDGAR-established identity wins; FMP fills the context."""
    row = fmp_row or {}
    srcs = ["SEC EDGAR (name, SIC)"]
    if row:
        srcs.append("FMP profile (aggregator — display only)")
    return CompanyProfile(
        name=(d.company or str(row.get("companyName") or "")).strip(),
        ticker=d.ticker,
        description=str(row.get("description") or "").strip(),
        website=str(row.get("website") or "").strip(),
        employees=_employees(row.get("fullTimeEmployees")),
        country=str(row.get("country") or "").strip(),
        exchange=str(row.get("exchangeShortName")
                     or row.get("exchange") or "").strip(),
        sector=str(row.get("sector") or "").strip(),
        industry=str(row.get("industry") or "").strip(),
        sic_code=str(getattr(d, "sic_code", "") or ""),
        ipo_date=str(row.get("ipoDate") or "").strip(),
        sources=" + ".join(srcs),
    )


def fetch_profile(d, cache=None) -> CompanyProfile:
    """FMP profile (cached a week, like submissions) merged over the
    EDGAR identity; any provider failure degrades to EDGAR-only."""
    row = None
    if config.FMP_API_KEY:
        from .providers.fmp import FMPClient
        from .reconcile import _cached
        symbol = d.ticker.strip().upper().replace(".", "-")
        try:
            payload = _cached(cache, f"fmp17d://profile/{symbol}",
                              config.TTL_SUBMISSIONS,
                              lambda: FMPClient().profile(symbol))
            if isinstance(payload, list) and payload:
                row = payload[0]
        except Exception:
            row = None
    return build_profile(d, row)

"""Analyst consensus growth estimates — valuation-dialog prefill.

FIX-17f (owner-ratified): the PRIMARY source is the FMP analyst-
estimates endpoint (keyed; probe-verified on the free plan) — next-FY
consensus revenue against the LATEST EDGAR ACTUAL as the base, so the
growth anchor is grounded in the audited number:

    g_avg  = next-FY revenueAvg  / actual − 1   (consensus — Bull seed)
    g_low  = next-FY revenueLow  / actual − 1   (display-only range)
    g_high = next-FY revenueHigh / actual − 1   (display-only range)

The old Yahoo `earningsTrend` path (cookie + crumb, estimate-vs-estimate
base) remains ONLY as the keyless fallback. These are *revenue* growth
estimates feeding the FIX-14a anchor ladder: the mean seeds Bull, the
dispersion is display-only, every prefill stays editable, and failure is
silent — estimates are convenience, never a dependency.

FIX-17f also serves the Overview estimates panel: the raw FMP annual
rows (history + forward — the archive lets the card show how wrong the
street was) and the free Finnhub recommendation trends. Both are
display-only and labeled unaudited.
"""
from __future__ import annotations

from typing import Optional

import requests

from . import config
from .cache import Cache

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
CRUMB_URL = "https://query1.finance.yahoo.com/v1/test/getcrumb"
TREND_URL = ("https://query1.finance.yahoo.com/v10/finance/quoteSummary/"
             "{symbol}?modules=earningsTrend&crumb={crumb}")
TTL_ESTIMATES = 24 * 3600


def _raw(node: Optional[dict]) -> Optional[float]:
    if isinstance(node, dict):
        v = node.get("raw")
        return float(v) if isinstance(v, (int, float)) else None
    return None


def parse_earnings_trend(payload: dict) -> Optional[dict]:
    try:
        trend = payload["quoteSummary"]["result"][0]["earningsTrend"]["trend"]
    except (KeyError, IndexError, TypeError):
        return None
    by_period = {t.get("period"): t for t in trend if isinstance(t, dict)}
    cur, nxt = by_period.get("0y"), by_period.get("+1y")
    if not cur or not nxt:
        return None
    cur_avg = _raw(cur.get("revenueEstimate", {}).get("avg"))
    nxt_est = nxt.get("revenueEstimate", {})
    nxt_avg, nxt_low = _raw(nxt_est.get("avg")), _raw(nxt_est.get("low"))
    nxt_high = _raw(nxt_est.get("high"))
    n = nxt_est.get("numberOfAnalysts", {})
    n = n.get("raw") if isinstance(n, dict) else None
    if not cur_avg or cur_avg <= 0 or not nxt_avg:
        return None
    out = {
        "g_avg": nxt_avg / cur_avg - 1.0,
        "g_low": (nxt_low / cur_avg - 1.0) if nxt_low else None,
        "g_high": (nxt_high / cur_avg - 1.0) if nxt_high else None,
        "n_analysts": int(n) if n else None,
        "period": "+1y revenue vs 0y consensus",
        "source": "Yahoo Finance earningsTrend",
    }
    # sanity: reject degenerate spreads (bad payloads happen)
    if out["g_low"] is not None and out["g_high"] is not None \
            and out["g_low"] > out["g_high"]:
        return None
    return out


def _first(row: dict, *names):
    for n in names:
        if row.get(n) is not None:
            return row.get(n)
    return None


def parse_fmp_estimates(rows, actual_rev: Optional[float],
                        actual_fy_year: Optional[int]) -> Optional[dict]:
    """Next-FY consensus growth against the latest EDGAR actual (the
    audited base). Field names read defensively — FMP has renamed them
    across API generations."""
    if not rows or not actual_rev or actual_rev <= 0 \
            or not actual_fy_year:
        return None
    nxt = None
    for row in rows:
        try:
            if int(str(row.get("date"))[:4]) == actual_fy_year + 1:
                nxt = row
                break
        except (TypeError, ValueError):
            continue
    if nxt is None:
        return None
    avg = _first(nxt, "revenueAvg", "estimatedRevenueAvg")
    low = _first(nxt, "revenueLow", "estimatedRevenueLow")
    high = _first(nxt, "revenueHigh", "estimatedRevenueHigh")
    n = _first(nxt, "numAnalystsRevenue", "numAnalystRevenue",
               "numberAnalystEstimatedRevenue")
    try:
        avg = float(avg)
    except (TypeError, ValueError):
        return None
    if avg <= 0:
        return None

    def g(v):
        try:
            return float(v) / actual_rev - 1.0
        except (TypeError, ValueError):
            return None

    out = {
        "g_avg": avg / actual_rev - 1.0,
        "g_low": g(low),
        "g_high": g(high),
        "n_analysts": int(n) if n else None,
        "period": (f"FY{actual_fy_year + 1} revenue vs FY{actual_fy_year}"
                   " actual (EDGAR base)"),
        "source": "FMP consensus",
    }
    if out["g_low"] is not None and out["g_high"] is not None \
            and out["g_low"] > out["g_high"]:
        return None
    return out


def fetch_estimates_rows(ticker: str,
                         cache: Optional[Cache] = None) -> Optional[list]:
    """Raw FMP annual analyst-estimate rows (history + forward), cached
    a day — the Overview panel's substrate. None keyless / on failure."""
    if not config.FMP_API_KEY:
        return None
    cache = cache or Cache()
    symbol = ticker.strip().upper().replace(".", "-")
    key = f"fmp17f://analyst-estimates/{symbol}"
    cached = cache.get(key, TTL_ESTIMATES)
    if cached is not None:
        return cached or None
    try:
        from .providers.fmp import FMPClient
        rows = FMPClient().analyst_estimates(symbol, period="annual",
                                             limit=10)
        rows = rows if isinstance(rows, list) else []
    except Exception:
        rows = []
    cache.put(key, rows)
    return rows or None


def fetch_recommendation_trends(ticker: str,
                                cache: Optional[Cache] = None
                                ) -> Optional[list]:
    """Finnhub recommendation trends (free tier), cached a day."""
    if not config.FINNHUB_API_KEY:
        return None
    cache = cache or Cache()
    symbol = ticker.strip().upper().replace(".", "-")
    key = f"fnh17f://recommendation/{symbol}"
    cached = cache.get(key, TTL_ESTIMATES)
    if cached is not None:
        return cached or None
    try:
        from .providers.finnhub import FinnhubClient
        rows = FinnhubClient().recommendation(symbol)
        rows = rows if isinstance(rows, list) else []
    except Exception:
        rows = []
    cache.put(key, rows)
    return rows or None


def fetch_growth_estimates(ticker: str, cache: Optional[Cache] = None,
                           actual_rev: Optional[float] = None,
                           actual_fy_year: Optional[int] = None
                           ) -> Optional[dict]:
    """FMP-first (keyed, EDGAR-actual base — FIX-17f); Yahoo
    earningsTrend only as the keyless fallback."""
    cache = cache or Cache()
    if config.FMP_API_KEY:
        est = parse_fmp_estimates(
            fetch_estimates_rows(ticker, cache=cache) or [],
            actual_rev, actual_fy_year)
        if est is not None:
            return est
    symbol = ticker.strip().upper().replace(".", "-")
    key = f"estimates:{symbol}"
    cached = cache.get(key, TTL_ESTIMATES)
    if cached is not None:
        return cached or None  # {} caches a known miss
    result = None
    try:
        s = requests.Session()
        s.headers.update(_UA)
        s.get("https://fc.yahoo.com", timeout=config.HTTP_TIMEOUT)  # cookie (404 ok)
        crumb = s.get(CRUMB_URL, timeout=config.HTTP_TIMEOUT).text.strip()
        if crumb and "<" not in crumb:
            resp = s.get(TREND_URL.format(symbol=symbol, crumb=crumb),
                         timeout=config.HTTP_TIMEOUT)
            if resp.ok:
                result = parse_earnings_trend(resp.json())
    except (requests.RequestException, ValueError):
        result = None
    cache.put(key, result or {})
    return result

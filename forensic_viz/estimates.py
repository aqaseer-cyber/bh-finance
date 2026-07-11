"""Analyst consensus growth estimates — valuation-dialog prefill.

Source: Yahoo Finance `earningsTrend` (quoteSummary), which carries the
sell-side revenue estimates for the current ("0y") and next ("+1y") fiscal
years with avg / low / high and the analyst count. Forward growth rates:

    g_avg  = +1y avg  / 0y avg − 1      (consensus anchor — Bull seed)
    g_low  = +1y low  / 0y avg − 1      (display-only analyst range)
    g_high = +1y high / 0y avg − 1      (display-only analyst range)

These are *revenue* growth estimates. Since FIX-14a they feed the growth
anchor ladder (`anchors.py`): the consensus mean seeds Bull — the
optimistic decade case once a one-year estimate drives a ten-year fade —
and the low/high dispersion is display-only, never mapped to scenarios.
Every prefill stays editable, and the CLI consumes seeds solely when a
case flag is omitted. Yahoo's quoteSummary needs a session cookie + crumb;
both are fetched keylessly. Failure is silent (the dialog just loses one
anchor) — estimates are convenience, never a dependency.
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


def fetch_growth_estimates(ticker: str, cache: Optional[Cache] = None) -> Optional[dict]:
    cache = cache or Cache()
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

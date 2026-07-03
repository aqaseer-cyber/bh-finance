"""Orchestration: ticker -> DashboardData (fetch, derive, assemble)."""
from __future__ import annotations

import datetime as dt
from typing import Callable, Optional

from . import config
from .cache import Cache
from .edgar import EdgarError, fetch_fundamentals
from .metrics import DashboardData, build_fundamental_metrics, build_price_metrics
from .prices import PriceError, fetch_prices

ProgressFn = Callable[[str], None]


def _noop(_msg: str) -> None:
    pass


def build_dashboard_data(
    ticker: str,
    cache: Optional[Cache] = None,
    progress: ProgressFn = _noop,
) -> DashboardData:
    """Fetch fundamentals (required) and prices (best-effort), derive metrics.

    Raises EdgarError when the ticker cannot be resolved or has no usable
    XBRL — there is no dashboard without fundamentals. Price failures are
    recorded on the result instead of raised.
    """
    cache = cache or Cache()
    ticker = ticker.strip().upper()

    progress(f"Fetching SEC EDGAR fundamentals for {ticker}…")
    fundamentals = fetch_fundamentals(ticker, cache=cache)

    data = DashboardData(
        ticker=ticker,
        company=fundamentals.entity_name,
        subtitle="",
        generated=dt.date.today(),
    )
    build_fundamental_metrics(fundamentals, data)

    progress("Fetching 5-year price history…")
    try:
        prices = fetch_prices(ticker, cache=cache)
        build_price_metrics(prices, data)
    except PriceError as exc:
        data.price_error = str(exc)

    parts = [fundamentals.exchange_ticker or ticker]
    if fundamentals.sic_description:
        parts.append(fundamentals.sic_description)
    if data.fy_labels:
        parts.append(f"fiscal years {data.fy_labels[0]}–{data.fy_labels[-1]}")
    parts.append(f"CIK {fundamentals.cik}")
    data.subtitle = " · ".join(parts)
    return data

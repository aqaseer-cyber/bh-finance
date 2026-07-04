"""Orchestration: ticker -> DashboardData (fetch, derive, assemble)."""
from __future__ import annotations

import datetime as dt
from typing import Callable, Optional

from . import config
from .cache import Cache
from .edgar import EdgarError, fetch_fundamentals
from .metrics import (
    DashboardData, apply_track, build_fundamental_metrics, build_price_metrics,
    compute_altman,
)
from .prices import PriceError, fetch_prices

ProgressFn = Callable[[str], None]


def _noop(_msg: str) -> None:
    pass


def build_dashboard_data(
    ticker: str,
    cache: Optional[Cache] = None,
    progress: ProgressFn = _noop,
    track: str = "auto",
    years: int = config.DISPLAY_YEARS,
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
        display_years=max(1, min(int(years), config.DISPLAY_YEARS)),
    )
    data.sic_code = fundamentals.sic_code
    data.latest_10k_date = fundamentals.latest_10k_date
    data.latest_10q_date = fundamentals.latest_10q_date
    apply_track(data, track)
    build_fundamental_metrics(fundamentals, data)

    progress(f"Fetching {data.display_years}-year price history…")
    full_dates: list = []
    full_closes: list = []
    try:
        prices = fetch_prices(ticker, cache=cache)
        full_dates, full_closes = list(prices.dates), list(prices.closes)  # pre-trim
        cutoff = data.generated - dt.timedelta(days=round(data.display_years * 365.25))
        keep = [(day, c) for day, c in zip(prices.dates, prices.closes) if day >= cutoff]
        if keep:
            prices.dates, prices.closes = [k[0] for k in keep], [k[1] for k in keep]
        build_price_metrics(prices, data)
    except PriceError as exc:
        data.price_error = str(exc)
    except Exception as exc:  # prices are best-effort; never sink the dashboard
        data.price_error = f"unexpected price-data error: {exc}"
    compute_altman(data)
    if data.is_financial_sector:
        data.health_notes.append(
            f"{data.track.title()} track (SIC {data.sic_code}): Standard-track "
            "scorecard is indicative only; Altman Z replaced by the solvency panel."
        )

    progress("Building discount rate (live 10-Y UST, β vs S&P 500)…")
    try:
        from .rates import build_wacc
        # Beta uses a FIXED window off the untrimmed series, so the display
        # `--years` choice can never move WACC (FIX-3).
        beta_cutoff = data.generated - dt.timedelta(
            days=round(config.BETA_WINDOW_YEARS * 365.25))
        beta_pairs = [(x, c) for x, c in zip(full_dates, full_closes)
                      if x >= beta_cutoff]
        data.wacc_build = build_wacc(
            data, cache=cache,
            price_dates=[p[0] for p in beta_pairs] or None,
            price_closes=[p[1] for p in beta_pairs] or None)
    except Exception:
        data.wacc_build = None  # rates are best-effort; dialog accepts manual

    progress("Fetching analyst growth estimates…")
    try:
        from .estimates import fetch_growth_estimates
        data.analyst_estimates = fetch_growth_estimates(ticker, cache=cache)
    except Exception:
        data.analyst_estimates = None  # estimates are prefill sugar only

    parts = [fundamentals.exchange_ticker or ticker]
    if fundamentals.sic_description:
        parts.append(fundamentals.sic_description)
    if data.fy_labels:
        parts.append(f"fiscal years {data.fy_labels[0]}–{data.fy_labels[-1]}")
    parts.append(f"CIK {fundamentals.cik}")
    data.subtitle = " · ".join(parts)
    return data

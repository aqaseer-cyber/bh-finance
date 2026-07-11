"""Orchestration: ticker -> DashboardData (fetch, derive, assemble)."""
from __future__ import annotations

import datetime as dt
import threading
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
    cancel: Optional[threading.Event] = None,
) -> DashboardData:
    """Fetch fundamentals (required) and prices (best-effort), derive metrics.

    Raises EdgarError when the ticker cannot be resolved or has no usable
    XBRL — there is no dashboard without fundamentals. Price failures are
    recorded on the result instead of raised.

    `cancel` (FIX-12g) is checked cooperatively at stage boundaries; a set
    event raises EdgarError("cancelled by user"). Default None leaves every
    existing caller untouched.
    """
    def _check_cancel():
        if cancel is not None and cancel.is_set():
            raise EdgarError("cancelled by user")

    cache = cache or Cache()
    ticker = ticker.strip().upper()

    progress(f"Fetching SEC EDGAR fundamentals for {ticker}…")
    fundamentals = fetch_fundamentals(ticker, cache=cache)
    _check_cancel()  # boundary 1: fundamentals fetched

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
    # FIX-11a: tag-selection decisions (revenue basis coherence) surface on
    # the health page and in the audit CSV like any other health note
    data.health_notes.extend(fundamentals.selection_notes)

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
    _check_cancel()  # boundary 2: prices done (fetched or waived)
    compute_altman(data)
    if data.is_financial_sector:
        data.health_notes.append(
            f"{data.track.title()} track (SIC {data.sic_code}): Standard-track "
            "scorecard is indicative only; Altman Z replaced by the solvency panel."
        )

    progress("Fetching segment disclosures (10-K/10-Q XBRL instances)…")
    try:
        from .segments import SegmentData, fetch_segment_data
        try:
            data.segments = fetch_segment_data(fundamentals, cache=cache)
        except Exception as exc:  # enrichment only — but keep the reason
            data.segments = SegmentData(
                status=f"segment fetch failed: {type(exc).__name__}: {exc}")
    except Exception:
        data.segments = None  # segments module itself unavailable
    # Annual interest rescue: an extension-tagged IS line (MELI's
    # "Interest expense and other financial charges") never reaches the
    # companyfacts API (standard taxonomies only). Rescue the missing
    # years from the just-cached filing instances' consolidated facts and
    # refresh FCFF. Enrichment only — failure leaves the labeled
    # levered-FCF proxy exactly as before.
    try:
        from .metrics import refresh_interest_metrics
        from .segments import rescue_annual_series
        if rescue_annual_series(fundamentals, "interest_expense",
                                cache=cache):
            refresh_interest_metrics(fundamentals, data)
            data.health_notes.append(fundamentals.selection_notes[-1])
    except Exception:
        pass

    seg = data.segments
    if seg is not None and seg.n_segments >= 2:
        ax = seg.axes()[0]
        names = ", ".join(seg.members(ax)[:4])
        data.health_notes.append(
            f"Multi-segment filer — {seg.n_segments} parts on the {ax} axis "
            f"as filed ({names}): consider the SOTP method (§4); segment "
            "rows are in the Financial model export.")

    progress("Reading the as-filed statement structure (presentation linkbase)…")
    try:  # enrichment only (FIX-13d) — a failure becomes the sheet's note
        from .edgar import fetch_statement_presentation
        stmts, notes = fetch_statement_presentation(fundamentals, cache=cache)
        data.statements = stmts or None
        data.statements_note = "; ".join(notes)
    except Exception as exc:  # incl. the FIX-13a UA gate — keep the reason
        data.statements = None
        data.statements_note = f"{type(exc).__name__}: {exc}"

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
    _check_cancel()  # boundary 3: segments + rates block done

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

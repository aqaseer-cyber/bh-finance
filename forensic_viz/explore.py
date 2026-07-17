"""Explore tab — live, screen-only chart cards (FIX-15b).

Pure figure builders, one per card: ``(d, mode, dpi, width_in) -> Figure``.
No Tk imports — everything renders under Agg, which is also how the tests
exercise every card × mode. The report/PDF pipeline never sees these
figures: report pages stay static print artifacts.

Honesty rules carried over from the report pages: a card whose inputs are
missing says so in one muted line instead of drawing an empty frame, and
ratio points whose denominator is ≤ 0 are masked (a gap in the line), never
interpolated.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import List, Optional, Tuple

import matplotlib.dates as mdates
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter, MaxNLocator

from . import palette as P
from .dashboard import (
    _panel_drawdown, _panel_note, _panel_price, _panel_revenue, _panel_title,
    _pct_axis, _style_axes,
)
from .metrics import DashboardData, fmt_pct
from .quarters import step_at, ttm_series
from .valuation import (
    ValuationError, dcf_fcff, implied_return, reverse_dcf_implied_g,
)

CARD_H = 3.2      # inches — small figures keep per-card redraws instant
STACKED_H = 5.6   # the two-pane price/drawdown card

PRICE_MODES = ("Share price", "Drawdown", "Both (stacked)")
RATIO_MODES = ("P/E (TTM)", "P/S (TTM)", "P/FCF (TTM)")
REVENUE_MODES = ("None", "Gross margin", "Operating margin", "Net margin",
                 "All margins")
# PEG is excluded by owner decision: trailing PEG sign-flips through zero
# growth and forward PEG is a point, not a series — do not re-add it here.

INSUFFICIENT = "insufficient data — needs quarterly fundamentals + prices"


def _new_card(dpi: int, width_in: float, height: float = CARD_H,
              n_axes: int = 1) -> Tuple[Figure, list]:
    fig = Figure(figsize=(max(4.0, width_in), height), dpi=dpi)
    fig.patch.set_facecolor(P.PAGE)
    axes = fig.subplots(n_axes, 1, sharex=(n_axes > 1))
    axes = list(axes) if n_axes > 1 else [axes]
    fig.subplots_adjust(left=0.07, right=0.975, top=0.84, bottom=0.10,
                        hspace=0.55)
    for ax in axes:
        _style_axes(ax)
    return fig, axes


def _insufficient_card(dpi: int, width_in: float) -> Figure:
    fig, (ax,) = _new_card(dpi, width_in)
    ax.set_facecolor(P.PAGE)
    _panel_note(ax, INSUFFICIENT)
    ax.spines["bottom"].set_visible(False)
    return fig


def price_card(d: DashboardData, mode: str, dpi: int = 100,
               width_in: float = 10.0) -> Figure:
    """Modes: "Share price", "Drawdown", "Both (stacked)" (shared x)."""
    if not getattr(d, "price_dates", None) or not d.price_closes:
        return _insufficient_card(dpi, width_in)
    if mode == "Both (stacked)":
        fig, (ax1, ax2) = _new_card(dpi, width_in, height=STACKED_H, n_axes=2)
        _panel_price(ax1, fig, d)
        _panel_drawdown(ax2, fig, d)
        return fig
    fig, (ax,) = _new_card(dpi, width_in)
    if mode == "Drawdown":
        _panel_drawdown(ax, fig, d)
    else:
        _panel_price(ax, fig, d)
    return fig


def _shares_step(d: DashboardData) -> List[Tuple[dt.date, float]]:
    """Diluted shares as a fiscal-year-end step series (the market-cap leg
    of P/S and P/FCF; annual counts — same additive approximation the
    export footnotes for per-share rows)."""
    return [(e, v) for e, v in zip(getattr(d, "fy_ends", []) or [],
                                   getattr(d, "diluted_shares", []) or [])
            if v is not None and v > 0]


def ratio_series(d: DashboardData, mode: str
                 ) -> Tuple[List[dt.date], List[float]]:
    """Daily ratio values joined price-to-step-TTM; masked points (missing
    or non-positive denominator) are NaN so the line breaks instead of
    interpolating. Empty when prices or the TTM series are absent."""
    if not getattr(d, "price_dates", None):
        return [], []
    if mode == "P/E (TTM)":
        denom = ttm_series(d, "eps_diluted")
        shares = None
    elif mode == "P/S (TTM)":
        denom = ttm_series(d, "revenue")
        shares = _shares_step(d)
    else:  # P/FCF (TTM)
        denom = ttm_series(d, "fcf")
        shares = _shares_step(d)
    if not denom or (shares is not None and not shares):
        return [], []
    values: List[float] = []
    for when, price in zip(d.price_dates, d.price_closes):
        den = step_at(denom, when)
        if den is None or den <= 0:
            values.append(math.nan)
            continue
        if shares is None:  # per-share denominator (EPS)
            values.append(price / den)
        else:
            sh = step_at(shares, when)
            values.append(price * sh / den if sh else math.nan)
    if all(math.isnan(v) for v in values):
        return [], []
    return list(d.price_dates), values


def ratio_card(d: DashboardData, mode: str, dpi: int = 100,
               width_in: float = 10.0) -> Figure:
    """Modes: "P/E (TTM)", "P/S (TTM)", "P/FCF (TTM)". Latest value
    annotated; period median as a reference line; non-positive denominators
    masked, not plotted."""
    dates, values = ratio_series(d, mode)
    if not dates:
        return _insufficient_card(dpi, width_in)
    fig, (ax,) = _new_card(dpi, width_in)
    finite = [v for v in values if not math.isnan(v)]
    finite.sort()
    median = finite[len(finite) // 2] if len(finite) % 2 else \
        (finite[len(finite) // 2 - 1] + finite[len(finite) // 2]) / 2
    sub = ("daily price / step-TTM denominator; gaps = denominator ≤ 0 "
           "or not derivable")
    _panel_title(ax, mode, sub)
    ax.plot(dates, values, color=P.SERIES[0], linewidth=1.4,
            solid_capstyle="round", zorder=3)
    ax.axhline(median, color=P.INK_MUTED, linewidth=0.9,
               linestyle=(0, (4, 3)), zorder=2)
    ax.set_xlim(dates[0], dates[-1])
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.1f}×"))
    ax.annotate(f"median {median:,.1f}×",
                xy=(dates[0], median), xytext=(4, 4),
                textcoords="offset points", fontsize=7.6,
                color=P.INK_MUTED, zorder=4)
    latest = next(((dt_, v) for dt_, v in zip(reversed(dates),
                                              reversed(values))
                   if not math.isnan(v)), None)
    if latest is not None:
        ax.plot(latest[0], latest[1], "o", color=P.SERIES[0], markersize=5.6,
                markeredgecolor=P.SURFACE, markeredgewidth=1.2, zorder=4)
        ax.annotate(f"{latest[1]:,.1f}×", xy=latest, xytext=(-4, 9),
                    textcoords="offset points", ha="right", fontsize=8.2,
                    fontweight="bold", color=P.INK_PRIMARY, zorder=5)
    return fig


WACC_EXCEEDS_G = "n/a — WACC must exceed g"


def sandbox_compute(base: float, wacc: float, g0: float, g_term: float,
                    bridge: float, shares: float, sbc: float, ex_sbc: bool,
                    price: Optional[float] = None) -> dict:
    """FIX-15c: the sandbox card's pure compute — a thin wrapper over the
    PRODUCTION functions (`dcf_fcff`, the valuation's bridge,
    `reverse_dcf_implied_g` on the Track-B ex-SBC basis per FIX-2).
    Deliberately no new math: there is no parallel implementation to
    parity-test, which is what retired the JS replica.

    Returns {"fv_ps", "mos", "tv_share", "implied_g", "ev", "error"};
    on a guard failure only "error" is set (wacc ≤ g renders as a message,
    never an exception)."""
    out = {"fv_ps": None, "mos": None, "tv_share": None,
           "implied_g": None, "implied_return": None, "ev": None,
           "error": None}
    if not shares or shares <= 0:
        out["error"] = "n/a — diluted share count unavailable"
        return out
    eff_base = max(base - sbc, 0.0) if ex_sbc else base
    if eff_base <= 0:
        out["error"] = "n/a — base must be positive (normalize per §4.0)"
        return out
    if wacc <= g_term:
        out["error"] = WACC_EXCEEDS_G
        return out
    try:
        dcf = dcf_fcff(eff_base, wacc, g0, g_term)
    except ValuationError as exc:
        out["error"] = f"n/a — {exc}"
        return out
    out["ev"] = dcf["ev"]
    out["tv_share"] = dcf["tv_share"]
    out["fv_ps"] = (dcf["ev"] - bridge) / shares
    if price and price > 0:
        out["mos"] = (out["fv_ps"] - price) / price
        # the entry is always the AS-REPORTED base (the checkbox derives),
        # so the Track-B reverse-DCF basis is base − SBC (Control!B58)
        base_b = base - sbc
        if base_b > 0:
            out["implied_g"] = reverse_dcf_implied_g(
                base_b, wacc, price * shares + bridge)
        # FIX-16c: the return buying at P₀ earns under the slider fade
        out["implied_return"] = implied_return(
            price, eff_base, g0, g_term, bridge, shares)
    return out


def revenue_card(d: DashboardData, mode: str, dpi: int = 100,
                 width_in: float = 10.0) -> Figure:
    """Fiscal-year revenue bars; margin overlays on a twin percentage axis
    (screen-only card — the print pages keep the single-axis rule)."""
    if not any(v is not None for v in getattr(d, "revenue", []) or []):
        return _insufficient_card(dpi, width_in)
    fig, (ax,) = _new_card(dpi, width_in)
    _panel_revenue(ax, fig, d)
    overlays = {"Gross margin": [0], "Operating margin": [1],
                "Net margin": [2], "All margins": [0, 1, 2]}.get(mode, [])
    if not overlays:
        return fig
    margin_series = [d.gross_margin, d.operating_margin, d.net_margin]
    names = ["Gross", "Operating", "Net"]
    ax2 = ax.twinx()
    ax2.set_facecolor("none")
    for side in ("top", "left", "bottom"):
        ax2.spines[side].set_visible(False)
    ax2.spines["right"].set_color(P.BASELINE)
    ax2.tick_params(colors=P.INK_MUTED, labelsize=8.2, length=0)
    _pct_axis(ax2)
    drew = False
    for k in overlays:
        s = margin_series[k]
        xs = [i for i, v in enumerate(s) if v is not None]
        ys = [v for v in s if v is not None]
        if not xs:
            continue
        color = P.SERIES[k + 1]  # bars own SERIES[0]
        ax2.plot(xs, ys, color=color, linewidth=1.6, solid_capstyle="round",
                 zorder=4)
        ax2.annotate(f"{names[k]} {fmt_pct(ys[-1])}", xy=(xs[-1], ys[-1]),
                     xytext=(4, 4), textcoords="offset points",
                     fontsize=7.4, color=color, zorder=5)
        drew = True
    if drew:
        flat = [v for k in overlays for v in margin_series[k] if v is not None]
        lo, hi = min(flat + [0.0]), max(flat + [0.0])
        span = (hi - lo) or 0.1
        ax2.set_ylim(lo - 0.08 * span, hi + 0.35 * span)
    return fig

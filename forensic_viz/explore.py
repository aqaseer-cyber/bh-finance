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


def _kpi_text(v, kind: str) -> str:
    if v is None:
        return "–"
    if kind == "money":
        from .metrics import fmt_money
        return fmt_money(v)
    if kind == "pct":
        return f"{v * 100:.1f}%"
    if kind == "ratio":
        return f"{v:,.1f}×"
    return f"{v:,.2f}"


PROFILE_CLIP_LINES = 3


def profile_card(d: DashboardData, dpi: int = 100,
                 width_in: float = 10.0,
                 expanded: bool = False) -> Figure:
    """FIX-17d(.1): DVH-style company header — name, description,
    country, website, employees, exchange, sector, SIC. Display-only
    context: the FMP-sourced fields are aggregator-grade and NEVER feed
    a calculation; the card says so.

    17d.1 owner feedback: the card is laid out top-down with a cursor
    on a DYNAMIC figure height (no fixed positions -> nothing can
    overlap), and the description is click-expandable in the GUI —
    `expanded=True` renders every wrapped line; clipped renders
    `PROFILE_CLIP_LINES` plus a click hint."""
    import textwrap
    p = getattr(d, "profile", None)
    width_in = max(4.0, width_in)
    if p is None or not (p.name or p.description):
        fig = Figure(figsize=(width_in, 0.9), dpi=dpi)
        fig.patch.set_facecolor(P.PAGE)
        ax = fig.add_subplot(111)
        ax.set_axis_off()
        ax.text(0.01, 0.6, "Company profile unavailable — configure the "
                           "FMP key (README 'Provider keys') for "
                           "description, website and employees.",
                fontsize=8.4, color=P.INK_MUTED, transform=ax.transAxes)
        return fig

    desc = p.description.replace("$", "\\$")
    per_line = max(60, int(width_in * 13))
    lines = textwrap.wrap(desc, width=per_line) if desc else []
    clipped = len(lines) > PROFILE_CLIP_LINES
    if clipped and not expanded:
        lines = lines[:PROFILE_CLIP_LINES]
        lines[-1] = lines[-1][:per_line - 2].rstrip() + "…"
    hint = ""
    if clipped:
        hint = ("(click the card to collapse)" if expanded
                else "(click the card for the full description)")

    # top-down layout in inches — the figure grows with the content
    LINE = 0.148
    rows = []                       # (dy_in, text, style-kwargs)
    rows.append((0.28, p.name or d.company, dict(
        fontsize=13.0, fontweight="bold", color=P.INK_PRIMARY)))
    sub = " · ".join(x for x in (
        d.ticker, p.exchange, p.sector, p.industry) if x)
    if sub:
        rows.append((0.19, sub, dict(fontsize=8.2,
                                     color=P.INK_SECONDARY)))
    for ln in lines:
        rows.append((LINE, ln, dict(fontsize=7.6,
                                    color=P.INK_SECONDARY)))
    if hint:
        rows.append((0.16, hint, dict(fontsize=6.8, color=P.INK_MUTED,
                                      fontstyle="italic")))
    facts_h, foot_h, pad = 0.42, 0.18, 0.14
    height = pad + sum(r[0] for r in rows) + facts_h + foot_h

    fig = Figure(figsize=(width_in, height), dpi=dpi)
    fig.patch.set_facecolor(P.PAGE)
    ax = fig.add_subplot(111)
    ax.set_axis_off()
    y = 1.0 - (pad / 2) / height
    for dy, text, style in rows:
        ax.text(0.01, y, text.replace("$", "\\$") if "\\$" not in text
                else text, transform=ax.transAxes, va="top", **style)
        y -= dy / height
    facts = [
        ("Country", p.country or "–"),
        ("Employees", f"{p.employees:,}" if p.employees else "–"),
        ("Website", p.website or "–"),
        ("SIC", p.sic_code or "–"),
        ("IPO", p.ipo_date or "–"),
    ]
    # website gets the wide slot; the offsets leave it room to breathe
    xs = (0.01, 0.14, 0.27, 0.63, 0.75)
    y -= 0.04 / height
    y_vals = y - 0.14 / height
    for k, (label, val) in enumerate(facts):
        ax.text(xs[k], y, label, fontsize=6.8, color=P.INK_MUTED,
                transform=ax.transAxes, va="top")
        ax.text(xs[k], y_vals, str(val).replace("$", "\\$"),
                fontsize=8.0, color=P.INK_PRIMARY,
                transform=ax.transAxes, va="top")
    ax.text(0.01, 0.02, f"profile: {p.sources} — context only, feeds "
                        "no calculation", fontsize=6.4,
            color=P.INK_MUTED, transform=ax.transAxes, va="bottom")
    return fig


def overview_kpi_card(d: DashboardData, dpi: int = 100,
                      width_in: float = 10.0) -> Figure:
    """FIX-16d: the one-glance KPI strip (DVH-benchmark) — current market
    joins over the audited series. Two rows of tiles; '–' where an input
    is honestly missing."""
    fig = Figure(figsize=(max(4.0, width_in), 1.9), dpi=dpi)
    fig.patch.set_facecolor(P.PAGE)
    ax = fig.add_subplot(111)
    ax.set_axis_off()
    shares_now = next((v for v in reversed(getattr(d, "diluted_shares", [])
                                           or []) if v), None)
    mcap_now = (d.last_close * shares_now
                if getattr(d, "last_close", None) and shares_now else None)
    eps_now = next((v for v in reversed(getattr(d, "eps_diluted", []) or [])
                    if v is not None), None)
    ebit_now = next((v for v in reversed(getattr(d, "ebit_reported", [])
                                         or []) if v is not None), None)
    nd_now = next((v for v in reversed(getattr(d, "net_debt_fy", []) or [])
                   if v is not None), None)
    mi_now = next((v for v in reversed(getattr(d, "minority_interest", [])
                                       or []) if v is not None), None)
    pref_now = next((v for v in reversed(getattr(d, "preferred_equity", [])
                                         or []) if v is not None), None)
    # EV carries all four bridge legs — same definition as market.ev_fy
    ev_now = (mcap_now + nd_now + (mi_now or 0.0) + (pref_now or 0.0)
              if mcap_now is not None and nd_now is not None else None)
    roic_now = next((v for v in reversed(getattr(d, "roic", []) or [])
                     if v is not None), None)
    opm_now = next((v for v in reversed(getattr(d, "operating_margin", [])
                                        or []) if v is not None), None)
    tiles = [
        ("Last close", d.last_close, "money"),
        ("Market cap", mcap_now, "money"),
        ("P/E (latest EPS)",
         (d.last_close / eps_now
          if d.last_close and eps_now and eps_now > 0 else None), "ratio"),
        ("EV/EBIT",
         (ev_now / ebit_now
          if ev_now is not None and ebit_now and ebit_now > 0 else None),
         "ratio"),
        ("Net debt/EBIT",
         (nd_now / ebit_now
          if nd_now is not None and ebit_now and ebit_now > 0 else None),
         "ratio"),
        ("Adj FCF yield (ex-SBC)", getattr(d, "adj_fcf_yield_now", None),
         "pct"),
        ("Owner's yield*", getattr(d, "owners_yield", None), "pct"),
        ("ROIC", roic_now, "pct"),
        ("Op margin", opm_now, "pct"),
        (f"Revenue CAGR ({max(1, len(d.fy_labels) - 1)}y)",
         getattr(d, "revenue_cagr", None), "pct"),
    ]
    for k, (label, val, kind) in enumerate(tiles):
        col, row_ = k % 5, k // 5
        x, y = 0.01 + col * 0.20, 0.88 - row_ * 0.50
        ax.text(x, y, label, fontsize=7.6, color=P.INK_SECONDARY,
                transform=ax.transAxes, va="top")
        ax.text(x, y - 0.17, _kpi_text(val, kind).replace("$", "\\$"),
                fontsize=11.5, fontweight="bold", color=P.INK_PRIMARY,
                transform=ax.transAxes, va="top")
    ax.text(0.01, 0.02, "* dividends + gross buybacks / market cap — "
            "issuance not netted (see the dilution panel)",
            fontsize=6.8, color=P.INK_MUTED, transform=ax.transAxes,
            va="bottom")
    return fig


def overview_valuation_card(d: DashboardData, res, dpi: int = 100,
                            width_in: float = 10.0) -> Figure:
    """FIX-16d: FV cases vs price, the entry-price ladder and the 5y exit
    cross-check — everything already computed by the audited valuation;
    this card only renders it. Muted note until a DCF valuation exists."""
    fig, (ax,) = _new_card(dpi, width_in, height=2.6)
    if res is None or not getattr(res, "cases", None):
        _panel_note(ax, "Run Intrinsic value… — FV cases, the entry-price "
                        "ladder and the 5y exit cross-check render here.")
        ax.spines["bottom"].set_visible(False)
        return fig
    _panel_title(ax, "Intrinsic value vs price",
                 "audited valuation output — the Valuation page is the "
                 "record")
    names = [c.name for c in res.cases]
    fvs = [c.fv_ps for c in res.cases]
    xs = range(len(names))
    ax.set_xlim(-0.5, len(names) - 0.5)
    vals = [v for v in fvs if v is not None] + ([res.price] if res.price
                                                else [])
    ax.set_ylim(0, max(vals) * 1.25 if vals else 1)
    ax.set_xticks(list(xs))
    ax.set_xticklabels(names)
    colors = [P.NEGATIVE, P.SERIES[2], P.SERIES[3]]
    for x, fv, color in zip(xs, fvs, colors):
        if fv is not None:
            ax.bar(x, fv, width=0.5, color=color, zorder=3)
            ax.annotate(f"\\${fv:,.0f}", xy=(x, fv), xytext=(0, 4),
                        textcoords="offset points", ha="center",
                        fontsize=8.4, color=P.INK_PRIMARY, zorder=4)
    if res.price:
        ax.axhline(res.price, color=P.INK_MUTED, linewidth=1.0,
                   linestyle=(0, (4, 3)), zorder=2)
        ax.annotate(f"P₀ \\${res.price:,.2f}", xy=(len(names) - 0.5,
                                                   res.price),
                    xytext=(-4, 4), textcoords="offset points", ha="right",
                    fontsize=7.8, color=P.INK_MUTED, zorder=4)
    lines = []
    if getattr(res, "irr_ladder", None):
        rungs = " ".join(
            f"\\${p:,.0f}→{r * 100:.0f}%" if r is not None
            else f"\\${p:,.0f}→n/a" for p, r in res.irr_ladder[::2])
        first = (f"entry price (Base case): "
                 f"{fmt_pct(res.implied_return_now)}/yr at P₀ · {rungs}")
        if res.hurdle_price is not None:
            first += (f" · {res.hurdle_rate * 100:.0f}% hurdle ≤ "
                      f"\\${res.hurdle_price:,.2f} (ASSUMPTION)")
        lines.append(first)
    ec = getattr(res, "exit_check", None)
    if ec is not None and ec.get("fv_today") is not None:
        second = (f"5y exit cross-check: median EV/EBIT "
                  f"{ec['multiple']:.1f}× on the Base fade ⇒ "
                  f"\\${ec['fv_today']:,.2f}/sh today")
        if ec.get("return_5y") is not None:
            second += (f" · ≈ {ec['return_5y'] * 100:.1f}%/yr at P₀ "
                       "(price-only; companion frame, not in FV_avg)")
        lines.append(second)
    for k, text in enumerate(lines):
        ax.text(0.0, -0.16 - 0.13 * k, text, fontsize=7.4,
                color=P.INK_SECONDARY, transform=ax.transAxes, va="top")
    return fig


def insider_card(d: DashboardData, dpi: int = 100,
                 width_in: float = 10.0) -> Figure:
    """FIX-17e: open-market insider transactions parsed natively from
    EDGAR Form 4 (audited-filing grade — same table DVH scrapes via
    openinsider, straight from the source). Max 12 rows on screen."""
    panel = getattr(d, "insiders", None)
    fig = Figure(figsize=(max(4.0, width_in), 2.7), dpi=dpi)
    fig.patch.set_facecolor(P.PAGE)
    ax = fig.add_subplot(111)
    ax.set_axis_off()
    ax.text(0.01, 0.985, "Insider transactions (Form 4, open-market P/S "
                         "only)", fontsize=10.5, fontweight="bold",
            color=P.INK_PRIMARY, transform=ax.transAxes, va="top")
    if panel is None:
        ax.text(0.01, 0.80, "unavailable — needs a declared SEC "
                            "User-Agent (Settings…), same gate as the "
                            "segment fetch", fontsize=8.0,
                color=P.INK_MUTED, transform=ax.transAxes, va="top")
        return fig
    ax.text(0.99, 0.985, panel.summary().replace("$", "\\$"),
            fontsize=8.2, color=P.INK_SECONDARY, transform=ax.transAxes,
            va="top", ha="right")
    rows = panel.rows[:12]
    if not rows:
        ax.text(0.01, 0.80, "no open-market Form 4 transactions in the "
                            f"last {panel.window_months} months",
                fontsize=8.4, color=P.INK_MUTED, transform=ax.transAxes,
                va="top")
        return fig
    cols = ((0.01, "Date"), (0.115, "Insider"), (0.335, "Title"),
            (0.565, "Type"), (0.685, "Price"), (0.775, "Qty"),
            (0.885, "Value"))
    y = 0.865
    for x, label in cols:
        ax.text(x, y, label, fontsize=7.0, color=P.INK_MUTED,
                transform=ax.transAxes, va="top")
    y -= 0.068
    for t in rows:
        # purchases render in the house positive green; sales stay ink
        color = P.DELTA_GOOD if t.shares > 0 else P.INK_PRIMARY
        vals = (t.date.isoformat(), t.name[:24], t.title[:26],
                t.code.split(" — ")[-1],
                f"{t.price:,.2f}" if t.price is not None else "–",
                f"{t.shares:+,.0f}",
                f"\\${t.value / 1e3:+,.0f}K" if t.value is not None
                else "–")
        for (x, _), v in zip(cols, vals):
            ax.text(x, y, str(v), fontsize=7.2, color=color,
                    transform=ax.transAxes, va="top")
        y -= 0.062
    foot = ("SEC EDGAR Form 4 (audited-filing) · awards/exercises/gifts "
            "excluded — compensation mechanics, not conviction")
    if panel.note:
        foot += f" · {panel.note}"
    ax.text(0.01, 0.005, foot, fontsize=6.4, color=P.INK_MUTED,
            transform=ax.transAxes, va="bottom")
    return fig


def _latest_actuals_by_year(d: DashboardData) -> dict:
    f = getattr(d, "fundamentals", None)
    if f is None:
        return {}
    rev = f.series.get("revenue") or []
    return {fe.year: rev[i] if i < len(rev) else None
            for i, fe in enumerate(f.fy_ends)}


def estimates_card(d: DashboardData, dpi: int = 100,
                   width_in: float = 10.0) -> Figure:
    """FIX-17f: consensus panel — forward revenue estimates vs the EDGAR
    actual base, the street's PAST accuracy (actual vs archived
    consensus), and the recommendation-trends strip. Display-only and
    labeled unaudited; the Bull-seed anchor in the valuation dialog is
    the only estimate that ever reaches a calculation, and it stays
    editable."""
    panel = getattr(d, "estimates_panel", None)
    fig = Figure(figsize=(max(4.0, width_in), 1.9), dpi=dpi)
    fig.patch.set_facecolor(P.PAGE)
    ax = fig.add_subplot(111)
    ax.set_axis_off()
    ax.text(0.01, 0.97, "Analyst estimates — consensus (FMP), unaudited",
            fontsize=10.5, fontweight="bold", color=P.INK_PRIMARY,
            transform=ax.transAxes, va="top")
    if not panel:
        ax.text(0.01, 0.74, "unavailable — configure the FMP key "
                            "(README 'Provider keys')", fontsize=8.0,
                color=P.INK_MUTED, transform=ax.transAxes, va="top")
        return fig
    actuals = _latest_actuals_by_year(d)
    latest_fy = max((y for y, v in actuals.items() if v), default=None)
    rows = {}
    for row in panel.get("rows") or []:
        try:
            rows[int(str(row.get("date"))[:4])] = row
        except (TypeError, ValueError):
            continue

    def _avg(row):
        for k in ("revenueAvg", "estimatedRevenueAvg"):
            if row.get(k) is not None:
                try:
                    return float(row[k])
                except (TypeError, ValueError):
                    return None
        return None

    y = 0.74
    if latest_fy and actuals.get(latest_fy):
        base = actuals[latest_fy]
        fwd = []
        for yr in (latest_fy + 1, latest_fy + 2, latest_fy + 3):
            row = rows.get(yr)
            avg = _avg(row) if row else None
            if avg and avg > 0:
                yrs = yr - latest_fy
                g = (avg / base) ** (1.0 / yrs) - 1.0
                fwd.append(f"FY{yr} \\${avg / 1e9:,.1f}B "
                           f"({g:+.1%}/yr)")
        if fwd:
            ax.text(0.01, y, "Forward revenue vs FY"
                    f"{latest_fy} actual \\${base / 1e9:,.1f}B:  "
                    + "  ·  ".join(fwd), fontsize=8.2,
                    color=P.INK_PRIMARY, transform=ax.transAxes,
                    va="top")
            y -= 0.17
        acc = []
        for yr in sorted(rows):
            if yr > (latest_fy or 0) or not actuals.get(yr):
                continue
            est = _avg(rows[yr])
            if est and est > 0:
                acc.append(f"FY{yr} {actuals[yr] / est - 1.0:+.1%}")
        if acc:
            ax.text(0.01, y, "Street accuracy (actual vs archived "
                            "consensus): " + " · ".join(acc[-4:]),
                    fontsize=8.0, color=P.INK_SECONDARY,
                    transform=ax.transAxes, va="top")
            y -= 0.17
    trends = panel.get("trends") or []
    if trends:
        t = trends[0]
        ax.text(0.01, y, f"Street ratings ({str(t.get('period', ''))[:7]}): "
                f"{t.get('strongBuy', 0)} strong buy · {t.get('buy', 0)} "
                f"buy · {t.get('hold', 0)} hold · {t.get('sell', 0)} sell "
                f"· {t.get('strongSell', 0)} strong sell   "
                "[Finnhub, free tier]", fontsize=8.0,
                color=P.INK_SECONDARY, transform=ax.transAxes, va="top")
        y -= 0.17
    ax.text(0.01, 0.005, "display-only; never enters FV. The Bull seed "
            "in the valuation dialog uses the same consensus mean — "
            "grounded on the EDGAR actual, always editable. Accuracy "
            "compares actuals with FMP's archived consensus (archive "
            "timing approximate).", fontsize=6.4, color=P.INK_MUTED,
            transform=ax.transAxes, va="bottom")
    return fig


# ---------------------------------------------- FIX-17g hover readout

def hover_readout(lines_data, x: float, is_date: bool = False) -> str:
    """The crosshair text for a cursor at x: nearest point per plotted
    line, honest '–' on masked (NaN) stretches. Pure — the Tk layer
    only feeds it `Line2D` data and places the result.

    lines_data: [(label, xs, ys)]; mpl-internal labels ('_child0') fall
    back to a single unnamed 'value' line; at most 3 series render."""
    import math
    if not lines_data:
        return ""
    named = [(lab, xs, ys) for lab, xs, ys in lines_data
             if lab and not str(lab).startswith("_")]
    use = named if named else [
        ("value", lines_data[0][1], lines_data[0][2])]
    header = None
    parts = []
    for label, xs, ys in use[:3]:
        n = len(xs)
        if n < 2 or n != len(ys):
            continue
        idx = min(range(n), key=lambda i: abs(float(xs[i]) - x))
        if header is None:
            if is_date:
                from matplotlib.dates import num2date
                header = num2date(float(xs[idx])).date().isoformat()
            else:
                header = f"{float(xs[idx]):,.4g}"
        v = ys[idx]
        bad = v is None or (isinstance(v, float) and math.isnan(v))
        parts.append(f"{label} –" if bad else f"{label} {float(v):,.2f}")
    if header is None or not parts:
        return ""
    return header + "  ·  " + "  ·  ".join(parts)


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

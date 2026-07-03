"""Dashboard renderer: one PNG-quality matplotlib figure per ticker.

Layout (portrait):
  header  — company identity + KPI tile row
  price   — 5y split-adjusted daily close (line + wash)
  drawdown— % below rolling peak
  grid    — revenue | margins
            earnings quality (NI vs CFO vs FCF) | accruals ratio
            diluted shares | debt vs cash
  footer  — methodology + XBRL tag audit trail

Design rules honoured: single y-axis per panel (never dual-axis), categorical
hues assigned in fixed slot order per panel, thin marks with rounded data-ends,
hairline solid gridlines, selective direct labels, legends for >= 2 series.
"""
from __future__ import annotations

import datetime as dt
from typing import List, Optional, Sequence

import matplotlib
import matplotlib.dates as mdates
import matplotlib.patheffects as path_effects
from matplotlib.figure import Figure
from matplotlib.path import Path as MplPath
from matplotlib.patches import PathPatch, Rectangle
from matplotlib.ticker import FuncFormatter, MaxNLocator

from . import config
from . import palette as P
from .metrics import DashboardData, fmt_count, fmt_money, fmt_pct

DPI = 150
FIG_W, FIG_H = 12.8, 16.9
BAR_MAX_PX = 34.0  # ~24 CSS px at this dpi — bars never fill the band
BAR_GAP_PX = 2.5   # surface gap between grouped bars
CORNER_PX = 5.0    # rounded data-end radius (~4 CSS px)


# ------------------------------------------------------------------ helpers

def _style_axes(ax, y_grid: bool = True):
    ax.set_facecolor(P.SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(P.BASELINE)
    ax.spines["bottom"].set_linewidth(0.9)
    if y_grid:
        ax.grid(axis="y", color=P.GRIDLINE, linewidth=0.8, linestyle="-")
    ax.set_axisbelow(True)
    ax.tick_params(colors=P.INK_MUTED, labelsize=8.2, length=0)
    ax.margins(x=0.01)


def _panel_title(ax, title: str, subtitle: str = ""):
    ax.text(0.0, 1.14, title, transform=ax.transAxes, fontsize=10.6,
            fontweight="bold", color=P.INK_PRIMARY, va="bottom")
    if subtitle:
        ax.text(0.0, 1.045, subtitle, transform=ax.transAxes, fontsize=7.8,
                color=P.INK_SECONDARY, va="bottom")


def _panel_note(ax, text: str):
    ax.text(0.5, 0.5, text, transform=ax.transAxes, ha="center", va="center",
            fontsize=9, color=P.INK_MUTED, wrap=True)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.grid(False)


def _px_to_x(ax, fig, px: float) -> float:
    bbox = ax.get_position()
    ax_w_px = bbox.width * fig.get_size_inches()[0] * fig.dpi
    x0, x1 = ax.get_xlim()
    return px / ax_w_px * (x1 - x0)


def _px_to_y(ax, fig, px: float) -> float:
    bbox = ax.get_position()
    ax_h_px = bbox.height * fig.get_size_inches()[1] * fig.dpi
    y0, y1 = ax.get_ylim()
    return px / ax_h_px * (y1 - y0)


def _rounded_bar(ax, fig, x_center: float, value: float, width: float, color: str):
    """Vertical bar, square at the baseline, rounded at the data end."""
    if value == 0:
        return
    rx = min(_px_to_x(ax, fig, CORNER_PX), width / 2)
    ry = min(_px_to_y(ax, fig, CORNER_PX), abs(value))
    x0, x1 = x_center - width / 2, x_center + width / 2
    s = 1 if value > 0 else -1
    y_end, y_shoulder = value, value - s * ry
    verts = [
        (x0, 0), (x0, y_shoulder), (x0, y_end), (x0 + rx, y_end),   # left corner
        (x1 - rx, y_end), (x1, y_end), (x1, y_shoulder),            # right corner
        (x1, 0), (x0, 0),
    ]
    codes = [
        MplPath.MOVETO, MplPath.LINETO, MplPath.CURVE3, MplPath.CURVE3,
        MplPath.LINETO, MplPath.CURVE3, MplPath.CURVE3,
        MplPath.LINETO, MplPath.CLOSEPOLY,
    ]
    ax.add_patch(PathPatch(MplPath(verts, codes), facecolor=color, edgecolor="none",
                           zorder=3))


def _bar_geometry(ax, fig, n_series: int) -> tuple:
    """(bar width, intra-group offsets) in data units for category positions."""
    gap = _px_to_x(ax, fig, BAR_GAP_PX)
    max_w = _px_to_x(ax, fig, BAR_MAX_PX)
    budget = 0.64  # of the 1.0-wide category band; the rest stays air
    width = min(max_w, (budget - (n_series - 1) * gap) / n_series)
    group = n_series * width + (n_series - 1) * gap
    offsets = [-group / 2 + width / 2 + i * (width + gap) for i in range(n_series)]
    return width, offsets


def _cap_label(ax, x: float, y: float, text: str, above: bool, fig,
               color: str = P.INK_SECONDARY, size: float = 7.4):
    pad = _px_to_y(ax, fig, 5)
    ax.text(x, y + (pad if above else -pad), text, ha="center",
            va="bottom" if above else "top", fontsize=size, color=color, zorder=4)


def _ylim_with_headroom(values: Sequence[float], head: float = 0.22,
                        foot: float = 0.22) -> tuple:
    lo, hi = min(values), max(values)
    lo, hi = min(lo, 0.0), max(hi, 0.0)
    span = (hi - lo) or 1.0
    return (lo - foot * span if lo < 0 else 0.0,
            hi + head * span if hi > 0 else 0.0 + head * span)


def _money_axis(ax):
    ax.yaxis.set_major_locator(MaxNLocator(nbins=4, steps=[1, 2, 2.5, 5, 10]))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: fmt_money(v)))


def _pct_axis(ax, decimals: int = 0):
    ax.yaxis.set_major_locator(MaxNLocator(nbins=4))
    ax.yaxis.set_major_formatter(
        FuncFormatter(lambda v, _: f"{v * 100:.{decimals}f}%"))


def _legend(ax, handles, labels):
    leg = ax.legend(handles, labels, loc="upper left", frameon=False,
                    fontsize=7.8, handlelength=1.0, handletextpad=0.5,
                    borderaxespad=0.0, ncol=len(labels),
                    columnspacing=1.2, bbox_to_anchor=(0.0, 1.02))
    for t in leg.get_texts():
        t.set_color(P.INK_SECONDARY)
    return leg


def _series_swatch(color):
    return Rectangle((0, 0), 1, 1, facecolor=color, edgecolor="none")


# ------------------------------------------------------------------- panels

def _category_panel_setup(ax, fig, labels: List[str], values_for_ylim):
    ax.set_xlim(-0.5, len(labels) - 0.5)
    ax.set_ylim(*_ylim_with_headroom(values_for_ylim))
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels)


def _draw_bar_series(ax, fig, series: List[List[Optional[float]]], colors: List[str]):
    width, offsets = _bar_geometry(ax, fig, len(series))
    for s_idx, (vals, color) in enumerate(zip(series, colors)):
        for i, v in enumerate(vals):
            if v is not None:
                _rounded_bar(ax, fig, i + offsets[s_idx], v, width, color)
    return width, offsets


def _fy_span(d: DashboardData) -> int:
    return max(1, len(d.fy_labels) - 1)


def _price_span(d: DashboardData) -> int:
    if not d.price_dates:
        return 0
    return max(1, round((d.price_dates[-1] - d.price_dates[0]).days / 365.25))


def _panel_revenue(ax, fig, d: DashboardData):
    sub = (f"{_fy_span(d)}y CAGR {fmt_pct(d.revenue_cagr, signed=True)}"
           if d.revenue_cagr is not None else "")
    _panel_title(ax, "Revenue", sub)
    vals = [v for v in d.revenue if v is not None]
    if not vals:
        _panel_note(ax, "Revenue not reported in XBRL")
        return
    _category_panel_setup(ax, fig, d.fy_labels, vals)
    _money_axis(ax)
    _draw_bar_series(ax, fig, [d.revenue], [P.SERIES[0]])
    for i, v in enumerate(d.revenue):
        if v is not None:
            _cap_label(ax, i, v, fmt_money(v), above=v >= 0, fig=fig)


def _panel_margins(ax, fig, d: DashboardData):
    _panel_title(ax, "Margins", "gross / operating / net, % of revenue")
    series = [d.gross_margin, d.operating_margin, d.net_margin]
    names = ["Gross", "Operating", "Net"]
    keep = [(s, n, P.SERIES[k]) for k, (s, n) in enumerate(zip(series, names))
            if any(v is not None for v in s)]
    if not keep:
        _panel_note(ax, "Margin inputs not reported in XBRL")
        return
    flat = [v for s, _, _ in keep for v in s if v is not None]
    lo, hi = min(flat + [0]), max(flat + [0])
    span = (hi - lo) or 0.1
    ax.set_xlim(-0.5, len(d.fy_labels) - 0.5)
    ax.set_ylim(lo - 0.06 * span, hi + 0.3 * span)
    ax.set_xticks(range(len(d.fy_labels)))
    ax.set_xticklabels(d.fy_labels)
    _pct_axis(ax)
    label_slots = []
    for s, name, color in keep:
        xs = [i for i, v in enumerate(s) if v is not None]
        ys = [v for v in s if v is not None]
        ax.plot(xs, ys, color=color, linewidth=1.6, solid_capstyle="round",
                solid_joinstyle="round", zorder=3)
        ax.plot(xs[-1], ys[-1], "o", color=color, markersize=5.6,
                markeredgecolor=P.SURFACE, markeredgewidth=1.2, zorder=4)
        label_slots.append([xs[-1], ys[-1], f"{name} {fmt_pct(ys[-1])}"])
    # dodge end labels that would overprint when two margins finish close together
    min_gap = _px_to_y(ax, fig, 15)
    label_slots.sort(key=lambda t: t[1])
    for j in range(1, len(label_slots)):
        if label_slots[j][1] - label_slots[j - 1][1] < min_gap:
            label_slots[j][1] = label_slots[j - 1][1] + min_gap
    for x, y, text in label_slots:
        _cap_label(ax, x, y, text, above=True, fig=fig, size=7.2)
    _legend(ax, [_series_swatch(c) for _, _, c in keep], [n for _, n, _ in keep])


def _panel_earnings_quality(ax, fig, d: DashboardData):
    _panel_title(ax, "Earnings quality", "net income vs operating cash flow vs free cash flow")
    series = [d.net_income, d.cfo, d.fcf]
    names = ["Net income", "Op. cash flow", "Free cash flow"]
    keep = [(s, n, P.SERIES[k]) for k, (s, n) in enumerate(zip(series, names))
            if any(v is not None for v in s)]
    if not keep:
        _panel_note(ax, "Cash-flow data not reported in XBRL")
        return
    flat = [v for s, _, _ in keep for v in s if v is not None]
    _category_panel_setup(ax, fig, d.fy_labels, flat)
    _money_axis(ax)
    _draw_bar_series(ax, fig, [s for s, _, _ in keep], [c for _, _, c in keep])
    # values live on the y-axis and in the CSV table; per-bar labels on three
    # adjacent series collide, so identity stays with the legend
    _legend(ax, [_series_swatch(c) for _, _, c in keep], [n for _, n, _ in keep])


def _panel_accruals(ax, fig, d: DashboardData):
    _panel_title(ax, "Operating accruals",
                 "(net income − CFO) / avg total assets; above +10% = red flag")
    vals = [v for v in d.accruals_ratio if v is not None]
    if not vals:
        _panel_note(ax, "Total assets / CFO not reported in XBRL")
        return
    lo = min(vals + [-0.02])
    hi = max(vals + [0.12])
    ax.set_xlim(-0.5, len(d.fy_labels) - 0.5)
    span = hi - lo
    ax.set_ylim(lo - 0.25 * span, hi + 0.25 * span)
    ax.set_xticks(range(len(d.fy_labels)))
    ax.set_xticklabels(d.fy_labels)
    _pct_axis(ax)
    ax.axhline(0, color=P.BASELINE, linewidth=0.9, zorder=2)
    ax.axhline(0.10, color=P.INK_MUTED, linewidth=0.8, linestyle=(0, (4, 3)), zorder=2)
    ax.text(len(d.fy_labels) - 0.48, 0.10 + _px_to_y(ax, fig, 3), "+10% threshold",
            ha="right", va="bottom", fontsize=6.8, color=P.INK_MUTED)
    width, _ = _bar_geometry(ax, fig, 1)
    for i, v in enumerate(d.accruals_ratio):
        if v is None:
            continue
        color = P.DIVERGING_POS_BAD if v > 0 else P.DIVERGING_NEG
        _rounded_bar(ax, fig, i, v, width, color)
        _cap_label(ax, i, v, fmt_pct(v, signed=True), above=v >= 0, fig=fig)


def _panel_shares(ax, fig, d: DashboardData):
    sub = ""
    if d.share_change is not None:
        direction = "buyback" if d.share_change < 0 else "dilution"
        sub = f"{fmt_pct(d.share_change, signed=True)} over the window ({direction})"
    _panel_title(ax, "Diluted shares outstanding", sub)
    vals = [v for v in d.diluted_shares if v is not None]
    if not vals:
        _panel_note(ax, "Share count not reported in XBRL")
        return
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.35 or hi * 0.1
    ax.set_xlim(-0.5, len(d.fy_labels) - 0.5)
    ax.set_ylim(max(0.0, lo - pad), hi + pad)
    ax.set_xticks(range(len(d.fy_labels)))
    ax.set_xticklabels(d.fy_labels)
    ax.yaxis.set_major_locator(MaxNLocator(nbins=4))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: fmt_count(v)))
    xs = [i for i, v in enumerate(d.diluted_shares) if v is not None]
    ys = [v for v in d.diluted_shares if v is not None]
    ax.plot(xs, ys, color=P.SERIES[0], linewidth=1.6, solid_capstyle="round", zorder=3)
    ax.fill_between(xs, ys, ax.get_ylim()[0], color=P.SERIES[0], alpha=0.10, zorder=2)
    ax.plot(xs[-1], ys[-1], "o", color=P.SERIES[0], markersize=5.6,
            markeredgecolor=P.SURFACE, markeredgewidth=1.2, zorder=4)
    _cap_label(ax, xs[-1], ys[-1], fmt_count(ys[-1]), above=True, fig=fig)


def _panel_debt_cash(ax, fig, d: DashboardData):
    _panel_title(ax, "Balance sheet", "total borrowings vs cash & equivalents")
    series = [d.total_debt, d.cash]
    names = ["Total debt", "Cash"]
    keep = [(s, n, P.SERIES[k]) for k, (s, n) in enumerate(zip(series, names))
            if any(v is not None for v in s)]
    if not keep:
        _panel_note(ax, "Debt / cash not reported in XBRL")
        return
    flat = [v for s, _, _ in keep for v in s if v is not None]
    _category_panel_setup(ax, fig, d.fy_labels, flat)
    _money_axis(ax)
    _draw_bar_series(ax, fig, [s for s, _, _ in keep], [c for _, _, c in keep])
    _legend(ax, [_series_swatch(c) for _, _, c in keep], [n for _, n, _ in keep])


def _panel_price(ax, fig, d: DashboardData):
    sub = f"daily close, split-adjusted · {d.price_source}"
    if d.total_return is not None:
        sub += f" · {_price_span(d)}y total price return {fmt_pct(d.total_return, signed=True)}"
    _panel_title(ax, f"{d.ticker} share price", sub)
    ax.plot(d.price_dates, d.price_closes, color=P.SERIES[0], linewidth=1.4,
            solid_capstyle="round", zorder=3)
    lo = min(d.price_closes)
    ax.set_ylim(lo * 0.92, max(d.price_closes) * 1.06)
    ax.fill_between(d.price_dates, d.price_closes, ax.get_ylim()[0],
                    color=P.SERIES[0], alpha=0.10, zorder=2)
    ax.set_xlim(d.price_dates[0], d.price_dates[-1])
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:,.0f}"))
    ax.plot(d.price_dates[-1], d.price_closes[-1], "o", color=P.SERIES[0],
            markersize=5.6, markeredgecolor=P.SURFACE, markeredgewidth=1.2, zorder=4)
    label = ax.annotate(f"${d.price_closes[-1]:,.2f}",
                        xy=(d.price_dates[-1], d.price_closes[-1]),
                        xytext=(-4, 9), textcoords="offset points", ha="right",
                        fontsize=8.2, color=P.INK_PRIMARY, fontweight="bold",
                        zorder=5)
    label.set_path_effects(
        [path_effects.withStroke(linewidth=2.5, foreground=P.SURFACE)])


def _panel_drawdown(ax, fig, d: DashboardData):
    _panel_title(ax, "Drawdown", f"% below rolling {_price_span(d)}y peak")
    ax.plot(d.price_dates, d.drawdown, color=P.SERIES[5], linewidth=1.2, zorder=3)
    ax.fill_between(d.price_dates, d.drawdown, 0, color=P.SERIES[5], alpha=0.10,
                    zorder=2)
    ax.set_xlim(d.price_dates[0], d.price_dates[-1])
    worst = d.max_drawdown or 0.0
    ax.set_ylim(worst * 1.35 if worst < 0 else -0.05, 0.001)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    _pct_axis(ax)
    if d.max_drawdown is not None and d.max_drawdown_date is not None:
        ax.plot(d.max_drawdown_date, d.max_drawdown, "o", color=P.SERIES[5],
                markersize=5.6, markeredgecolor=P.SURFACE, markeredgewidth=1.2,
                zorder=4)
        ax.annotate(f"max {fmt_pct(d.max_drawdown)}",
                    xy=(d.max_drawdown_date, d.max_drawdown),
                    xytext=(6, -2), textcoords="offset points",
                    fontsize=7.6, color=P.INK_SECONDARY, va="top", zorder=5)


# ---------------------------------------------------------------- header/kpi

def _kpi_tiles(ax, d: DashboardData):
    ax.set_axis_off()
    last_label = d.fy_labels[-1] if d.fy_labels else "latest FY"
    fy = f"{_fy_span(d)}y"
    py = f"{_price_span(d)}y"
    tiles = []
    if d.last_close is not None:
        tiles.append(("Last close", f"${d.last_close:,.2f}",
                      f"{fmt_pct(d.total_return, signed=True)} {py}",
                      (d.total_return or 0) >= 0))
    if d.revenue and d.revenue[-1] is not None:
        tiles.append((f"Revenue ({last_label})", fmt_money(d.revenue[-1]),
                      f"{fmt_pct(d.revenue_cagr, signed=True)}/yr {fy}" if d.revenue_cagr is not None else "",
                      (d.revenue_cagr or 0) >= 0))
    if d.net_margin and d.net_margin[-1] is not None:
        delta = (f"{d.net_margin_delta_pp:+.1f}pp vs {d.fy_labels[0]}"
                 if d.net_margin_delta_pp is not None else "")
        tiles.append((f"Net margin ({last_label})", fmt_pct(d.net_margin[-1]),
                      delta, (d.net_margin_delta_pp or 0) >= 0))
    if d.fcf and d.fcf[-1] is not None:
        tiles.append((f"Free cash flow ({last_label})", fmt_money(d.fcf[-1]),
                      f"{fmt_pct(d.fcf_cagr, signed=True)}/yr {fy}" if d.fcf_cagr is not None else "",
                      (d.fcf_cagr or 0) >= 0))
    if d.share_change is not None and d.diluted_shares[-1] is not None:
        tiles.append(("Diluted shares", fmt_count(d.diluted_shares[-1]),
                      f"{fmt_pct(d.share_change, signed=True)} {fy}",
                      d.share_change <= 0))  # falling share count = good
    _draw_kpi_row(ax, tiles)


def _draw_kpi_row(ax, tiles):
    if not tiles:
        return
    n = len(tiles)
    for i, (label, value, delta, good) in enumerate(tiles):
        x0 = i / n
        ax.text(x0, 0.46, label, fontsize=8.2, color=P.INK_SECONDARY,
                transform=ax.transAxes, va="top")
        ax.text(x0, 0.30, value, fontsize=15.5, fontweight="bold",
                color=P.INK_PRIMARY, transform=ax.transAxes, va="top")
        if delta:
            ax.text(x0, 0.0, delta, fontsize=8.2,
                    color=P.DELTA_GOOD if good else P.DELTA_BAD,
                    transform=ax.transAxes, va="top")
        if i:
            ax.axvline(x0 - 0.018, ymin=-0.1, ymax=0.48, color=P.GRIDLINE,
                       linewidth=0.8)


def _header(fig, ax, d: DashboardData):
    ax.set_axis_off()
    name = d.company if d.company else d.ticker
    ax.text(0, 1.04, name, fontsize=17.5, fontweight="bold",
            color=P.INK_PRIMARY, transform=ax.transAxes, va="top")
    ax.text(0, 0.80, d.subtitle, fontsize=9, color=P.INK_SECONDARY,
            transform=ax.transAxes, va="top")
    src = f"Generated {d.generated.isoformat()}"
    parts = ["SEC EDGAR XBRL"]
    if d.price_source:
        parts.append(d.price_source)
    src += " · Sources: " + ", ".join(parts)
    ax.text(1.0, 1.04, src, fontsize=8, color=P.INK_MUTED,
            transform=ax.transAxes, va="top", ha="right")
    if d.demo:
        ax.text(1.0, 0.80, "DEMO DATA — SYNTHETIC COMPANY, NOT A REAL FILER",
                fontsize=9, fontweight="bold", color=P.DELTA_BAD,
                transform=ax.transAxes, va="top", ha="right")


def _footer(fig, d: DashboardData):
    line1 = ("FCF = operating cash flow − capex.  Accruals ratio = (net income − CFO) / "
             "average total assets; sustained readings above +10% flag earnings running ahead of cash.")
    line2 = ("Fundamentals are as filed in annual-report XBRL (latest amendment wins).  "
             "Not investment advice.")
    fig.text(0.055, 0.034, line1, fontsize=7.2, color=P.INK_MUTED, va="bottom")
    fig.text(0.055, 0.022, line2, fontsize=7.2, color=P.INK_MUTED, va="bottom")
    if d.tags_used:
        shown = ", ".join(f"{k}={v}" for k, v in sorted(d.tags_used.items()))
        if len(shown) > 210:
            shown = shown[:207] + "…"
        fig.text(0.055, 0.010, "XBRL tags: " + shown, fontsize=6.4,
                 color=P.INK_MUTED, va="bottom")


# ----------------------------------------------------- health report (page 2)

def _zone_label(ax, x: float, y: float, text: str):
    """Threshold/zone annotation that stays legible over bars."""
    t = ax.text(x, y, text, ha="left", va="bottom", fontsize=6.8,
                color=P.INK_MUTED, zorder=5)
    t.set_path_effects([path_effects.withStroke(linewidth=2.2, foreground=P.SURFACE)])


def _latest(seq):
    for v in reversed(seq or []):
        if v is not None:
            return v
    return None


def _panel_sloan(ax, fig, d: DashboardData):
    _panel_title(ax, "Sloan ratio — house variant",
                 "(net income − CFO − CFI) / avg total assets; |ratio| > 10% flagged")
    vals = [v for v in d.sloan_full if v is not None]
    if not vals:
        _panel_note(ax, "CFI / total assets not reported in XBRL")
        return
    flag = config.SLOAN_FLAG
    lo, hi = min(vals + [-flag * 1.2]), max(vals + [flag * 1.2])
    span = hi - lo
    ax.set_xlim(-0.5, len(d.fy_labels) - 0.5)
    ax.set_ylim(lo - 0.22 * span, hi + 0.22 * span)
    ax.set_xticks(range(len(d.fy_labels)))
    ax.set_xticklabels(d.fy_labels)
    _pct_axis(ax)
    ax.axhline(0, color=P.BASELINE, linewidth=0.9, zorder=2)
    for y in (flag, -flag):
        ax.axhline(y, color=P.INK_MUTED, linewidth=0.8, linestyle=(0, (4, 3)), zorder=2)
    _zone_label(ax, -0.48, flag + _px_to_y(ax, fig, 3), "±10% flag")
    width, _ = _bar_geometry(ax, fig, 1)
    for i, v in enumerate(d.sloan_full):
        if v is None:
            continue
        color = P.DIVERGING_POS_BAD if abs(v) > flag else P.SERIES[0]
        _rounded_bar(ax, fig, i, v, width, color)
        _cap_label(ax, i, v, fmt_pct(v, signed=True), above=v >= 0, fig=fig, size=6.8)


def _panel_piotroski(ax, fig, d: DashboardData):
    _panel_title(ax, "Piotroski F-score",
                 "nine signals; ≥7 strong, ≤3 weak · * = fewer than 9 evaluable")
    if not any(s is not None for s in d.piotroski_score):
        _panel_note(ax, "Insufficient XBRL inputs for the F-score")
        return
    ax.set_xlim(-0.5, len(d.fy_labels) - 0.5)
    ax.set_ylim(0, 10.2)
    ax.set_xticks(range(len(d.fy_labels)))
    ax.set_xticklabels(d.fy_labels)
    ax.set_yticks([0, 3, 7, 9])
    for y, lab in ((3, "weak ≤3"), (7, "strong ≥7")):
        ax.axhline(y, color=P.INK_MUTED, linewidth=0.8, linestyle=(0, (4, 3)), zorder=2)
        _zone_label(ax, -0.48, y + 0.15, lab)
    width, _ = _bar_geometry(ax, fig, 1)
    for i, (score, checks) in enumerate(zip(d.piotroski_score, d.piotroski_checks)):
        if score is None:
            continue
        _rounded_bar(ax, fig, i, score, width, P.SERIES[0])
        mark = "*" if checks < 9 else ""
        _cap_label(ax, i, score, f"{score}{mark}", above=True, fig=fig, size=7.0)


def _panel_altman(ax, fig, d: DashboardData):
    _panel_title(ax, "Altman Z-score",
                 "original 1968 model (Standard-Mfg); MVE = FY-end close × diluted shares")
    if d.is_financial_sector:
        _panel_note(ax, "Financial-sector filer — Altman Z is not meaningful\n"
                        "(bank/insurance solvency checks not yet ported)")
        return
    pts = [(i, v) for i, v in enumerate(d.altman_z) if v is not None]
    if not pts:
        note = "Z inputs missing (needs current assets/liabilities, retained\n" \
               "earnings, total liabilities and a FY-end price)"
        _panel_note(ax, note)
        return
    xs, ys = zip(*pts)
    lo = min(list(ys) + [config.ALTMAN_DISTRESS - 0.5])
    hi = max(list(ys) + [config.ALTMAN_SAFE + 0.5])
    span = hi - lo
    ax.set_xlim(-0.5, len(d.fy_labels) - 0.5)
    ax.set_ylim(lo - 0.15 * span, hi + 0.2 * span)
    ax.set_xticks(range(len(d.fy_labels)))
    ax.set_xticklabels(d.fy_labels)
    ax.yaxis.set_major_locator(MaxNLocator(nbins=4))
    y0, y1 = ax.get_ylim()
    ax.axhspan(y0, config.ALTMAN_DISTRESS, color="#d03b3b", alpha=0.06, zorder=1)
    ax.axhspan(config.ALTMAN_DISTRESS, config.ALTMAN_SAFE, color="#f0efec",
               alpha=0.8, zorder=1)
    for y, lab, va in ((config.ALTMAN_DISTRESS, "distress < 1.81", "top"),
                       (config.ALTMAN_SAFE, "safe > 2.99", "bottom")):
        ax.text(0.02, y + (0.03 * span if va == "bottom" else -0.03 * span), lab,
                transform=ax.get_yaxis_transform(), fontsize=6.8,
                color=P.INK_MUTED, va=va)
    ax.plot(xs, ys, color=P.SERIES[0], linewidth=1.6, solid_capstyle="round",
            zorder=3)
    ax.plot(xs[-1], ys[-1], "o", color=P.SERIES[0], markersize=5.6,
            markeredgecolor=P.SURFACE, markeredgewidth=1.2, zorder=4)
    _cap_label(ax, xs[-1], ys[-1], f"{ys[-1]:.2f}", above=True, fig=fig)


def _panel_sbc(ax, fig, d: DashboardData):
    sub = "bar = % of revenue · label = $ amount"
    if d.sbc_pct_fcf_latest is not None:
        sub += f" · latest = {fmt_pct(d.sbc_pct_fcf_latest)} of FCF"
    _panel_title(ax, "Stock-based compensation", sub)
    vals = [v for v in d.sbc_pct_revenue if v is not None]
    if not vals:
        _panel_note(ax, "SBC not reported in XBRL")
        return
    _category_panel_setup(ax, fig, d.fy_labels, vals)
    _pct_axis(ax, decimals=1)
    width, _ = _bar_geometry(ax, fig, 1)
    for i, (pct, usd) in enumerate(zip(d.sbc_pct_revenue, d.sbc)):
        if pct is None:
            continue
        _rounded_bar(ax, fig, i, pct, width, P.SERIES[0])
        _cap_label(ax, i, pct, fmt_money(usd), above=pct >= 0, fig=fig, size=6.6)


def _panel_rnd_audit(ax, fig, d: DashboardData):
    n = config.RND_LIFE_YEARS
    _panel_title(ax, "R&D capitalization audit",
                 f"EBIT as reported vs economic (R&D capitalized over n={n}y, ASSUMPTION)")
    if not d.rnd_material:
        _panel_note(ax, f"R&D below {config.RND_MATERIALITY:.0%} of revenue — "
                        "capitalization audit not applicable (house §3)")
        return
    series = [d.ebit_reported, d.ebit_economic]
    names = ["EBIT reported", "EBIT economic"]
    keep = [(s, nm, P.SERIES[k]) for k, (s, nm) in enumerate(zip(series, names))
            if any(v is not None for v in s)]
    flat = [v for s, _, _ in keep for v in s if v is not None]
    if not flat:
        _panel_note(ax, "Operating income / R&D history not reported in XBRL")
        return
    _category_panel_setup(ax, fig, d.fy_labels, flat)
    _money_axis(ax)
    _draw_bar_series(ax, fig, [s for s, _, _ in keep], [c for _, _, c in keep])
    _legend(ax, [_series_swatch(c) for _, _, c in keep], [nm for _, nm, _ in keep])


def _panel_fcf_ex_sbc(ax, fig, d: DashboardData):
    _panel_title(ax, "FCF vs FCF ex-SBC",
                 "house §2b basis: SBC treated as a real cost of the franchise")
    series = [d.fcf, d.fcf_ex_sbc]
    names = ["FCF", "FCF ex-SBC"]
    keep = [(s, nm, P.SERIES[k]) for k, (s, nm) in enumerate(zip(series, names))
            if any(v is not None for v in s)]
    flat = [v for s, _, _ in keep for v in s if v is not None]
    if not flat or len(keep) < 2:
        _panel_note(ax, "SBC or cash-flow data not reported in XBRL")
        return
    _category_panel_setup(ax, fig, d.fy_labels, flat)
    _money_axis(ax)
    _draw_bar_series(ax, fig, [s for s, _, _ in keep], [c for _, _, c in keep])
    _legend(ax, [_series_swatch(c) for _, _, c in keep], [nm for _, nm, _ in keep])


def _health_kpis(ax, d: DashboardData):
    ax.set_axis_off()
    tiles = []
    score, checks = _latest(d.piotroski_score), None
    if score is not None:
        idx = max(i for i, v in enumerate(d.piotroski_score) if v is not None)
        checks = d.piotroski_checks[idx]
        tiles.append(("Piotroski F", f"{score}/{checks}",
                      "strong ≥7 · weak ≤3", score >= 7))
    z = _latest(d.altman_z)
    if z is not None:
        zone = ("safe" if z > config.ALTMAN_SAFE
                else "distress" if z < config.ALTMAN_DISTRESS else "grey zone")
        tiles.append(("Altman Z", f"{z:.2f}", zone, z > config.ALTMAN_SAFE))
    sloan = _latest(d.sloan_full)
    if sloan is not None:
        flagged = abs(sloan) > config.SLOAN_FLAG
        tiles.append(("Sloan ratio", fmt_pct(sloan, signed=True),
                      "FLAG >|10%|" if flagged else "within ±10%", not flagged))
    sbc_pct = _latest(d.sbc_pct_revenue)
    if sbc_pct is not None:
        tiles.append(("SBC / revenue", fmt_pct(sbc_pct),
                      f"{fmt_pct(d.sbc_pct_fcf_latest)} of FCF"
                      if d.sbc_pct_fcf_latest is not None else "", sbc_pct < 0.05))
    if d.share_cagr_3y is not None:
        tiles.append(("Share CAGR 3y", fmt_pct(d.share_cagr_3y, signed=True),
                      "dilution" if d.share_cagr_3y > 0 else "buyback",
                      d.share_cagr_3y <= 0))
    fcf_ex = _latest(d.fcf_ex_sbc)
    if fcf_ex is not None:
        tiles.append(("FCF ex-SBC", fmt_money(fcf_ex), "latest FY", fcf_ex > 0))
    _draw_kpi_row(ax, tiles)


def render_health_report(d: DashboardData, out_path: Optional[str] = None,
                         dpi: int = DPI) -> Figure:
    """Page 2 — Phase-3 forensic health checks (quality scorecard)."""
    matplotlib.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": P.FONT_STACK,
        "text.color": P.INK_PRIMARY,
        "figure.facecolor": P.SURFACE,
        "savefig.facecolor": P.SURFACE,
    })
    fig = Figure(figsize=(FIG_W, 11.6), dpi=dpi)
    fig.patch.set_facecolor(P.SURFACE)
    gs = fig.add_gridspec(
        4, 2, height_ratios=[1.45, 1.9, 1.9, 1.9],
        left=0.055, right=0.965, top=0.97, bottom=0.085,
        hspace=0.62, wspace=0.16,
    )

    ax_header = fig.add_subplot(gs[0, :])
    ax_header.set_axis_off()
    ax_header.text(0, 1.04, f"{d.company} — forensic health checks",
                   fontsize=17.5, fontweight="bold", color=P.INK_PRIMARY,
                   transform=ax_header.transAxes, va="top")
    sub = f"Phase-3 quality scorecard · {d.ticker}"
    if d.fy_labels:
        sub += f" · fiscal years {d.fy_labels[0]}–{d.fy_labels[-1]}"
    if d.sic_code:
        sub += f" · SIC {d.sic_code}"
    ax_header.text(0, 0.80, sub, fontsize=9, color=P.INK_SECONDARY,
                   transform=ax_header.transAxes, va="top")
    ax_header.text(1.0, 1.04, f"Generated {d.generated.isoformat()} · SEC EDGAR XBRL",
                   fontsize=8, color=P.INK_MUTED, transform=ax_header.transAxes,
                   va="top", ha="right")
    if d.demo:
        ax_header.text(1.0, 0.80, "DEMO DATA — SYNTHETIC COMPANY, NOT A REAL FILER",
                       fontsize=9, fontweight="bold", color=P.DELTA_BAD,
                       transform=ax_header.transAxes, va="top", ha="right")
    _health_kpis(ax_header, d)

    panels = [
        (_panel_sloan, gs[1, 0]), (_panel_piotroski, gs[1, 1]),
        (_panel_altman, gs[2, 0]), (_panel_sbc, gs[2, 1]),
        (_panel_rnd_audit, gs[3, 0]), (_panel_fcf_ex_sbc, gs[3, 1]),
    ]
    for fn, spec in panels:
        ax = fig.add_subplot(spec)
        _style_axes(ax)
        if not d.fy_labels:
            _panel_note(ax, "No annual fundamentals available")
            continue
        fn(ax, fig, d)

    y = 0.052
    for note in d.health_notes:
        fig.text(0.055, y, note, fontsize=6.6, color=P.INK_MUTED, va="bottom")
        y -= 0.012
    fig.text(0.055, y, "Adjustment Burden (master §3.1) needs non-GAAP figures "
                       "from the earnings release — not in XBRL; analyst input.  "
                       "Not investment advice.",
             fontsize=6.6, color=P.INK_MUTED, va="bottom")

    if out_path:
        fig.savefig(out_path, dpi=dpi)
    return fig


# -------------------------------------------------- valuation report (page 3)

def _field_panel(ax, fig, res):
    """Football field: Bear/Base/Bull FV per share vs the current price."""
    _panel_title(ax, "Intrinsic value vs price",
                 "FV per share by case · vertical line = current price")
    cases = [c for c in res.cases if c.fv_ps is not None]
    xs = [c.fv_ps for c in cases] + [res.price]
    lo, hi = min(xs), max(xs)
    pad = (hi - lo) * 0.16 or hi * 0.1 or 1.0
    ax.set_xlim(lo - pad, hi + pad)
    ax.set_ylim(-0.7, len(cases) - 0.3)
    ax.set_yticks(range(len(cases)))
    ax.set_yticklabels([c.name for c in cases])
    ax.xaxis.set_major_locator(MaxNLocator(nbins=6))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:,.0f}"))
    ax.grid(axis="x", color=P.GRIDLINE, linewidth=0.8, linestyle="-")
    ax.grid(axis="y", visible=False)
    ax.tick_params(axis="y", labelsize=8.6)
    # bear→bull span behind the lollipops
    fvs = [c.fv_ps for c in cases]
    ax.axvspan(min(fvs), max(fvs), color=P.SERIES[0], alpha=0.07, zorder=1)
    ax.axvline(res.price, color=P.INK_SECONDARY, linewidth=1.3, zorder=3)
    label = ax.text(res.price, -0.62, f" P₀ ${res.price:,.2f}",
                    fontsize=8, color=P.INK_PRIMARY, fontweight="bold",
                    ha="left", va="bottom", zorder=6)
    label.set_path_effects(
        [path_effects.withStroke(linewidth=2.5, foreground=P.SURFACE)])
    for y, c in enumerate(cases):
        ax.plot([res.price, c.fv_ps], [y, y], color=P.BASELINE, linewidth=1.4,
                zorder=2)
        ax.plot(c.fv_ps, y, "o", color=P.SERIES[0], markersize=7.2,
                markeredgecolor=P.SURFACE, markeredgewidth=1.4, zorder=4)
        good = c.fv_ps >= res.price
        t = ax.text(c.fv_ps, y + 0.22,
                    f"${c.fv_ps:,.2f}  ({fmt_pct(c.mos, signed=True)})",
                    fontsize=8, ha="center", va="bottom",
                    color=P.DELTA_GOOD if good else P.DELTA_BAD, zorder=5)
        t.set_path_effects(
            [path_effects.withStroke(linewidth=2.2, foreground=P.SURFACE)])


def _valuation_table(ax, res):
    ax.set_axis_off()
    is_dcf = res.method == "dcf"
    cols = [("Case", 0.00), ("Assumptions", 0.09), ("FV / share", 0.46),
            ("MoS vs P₀", 0.60)]
    if is_dcf:
        cols += [("EV", 0.74), ("TV % of EV", 0.86)]
    elif res.method == "ri":
        cols += [("Equity value", 0.74), ("TV % of V₀", 0.86)]
    for label, x in cols:
        ax.text(x, 0.94, label, fontsize=8, color=P.INK_SECONDARY,
                transform=ax.transAxes, va="top")
    for r, c in enumerate(res.cases):
        y = 0.70 - r * 0.26
        good = c.fv_ps is not None and c.fv_ps >= res.price
        cells = [(0.00, c.name, P.INK_PRIMARY, "bold"),
                 (0.09, c.assumptions, P.INK_PRIMARY, "normal"),
                 (0.46, f"${c.fv_ps:,.2f}" if c.fv_ps is not None else "–",
                  P.INK_PRIMARY, "bold"),
                 (0.60, fmt_pct(c.mos, signed=True),
                  P.DELTA_GOOD if good else P.DELTA_BAD, "bold")]
        if is_dcf or res.method == "ri":
            cells += [(0.74, fmt_money(c.ev if is_dcf else c.equity),
                       P.INK_PRIMARY, "normal"),
                      (0.86, fmt_pct(c.tv_share) if c.tv_share is not None else "–",
                       P.INK_PRIMARY, "normal")]
        for x, text, color, weight in cells:
            ax.text(x, y, text, fontsize=9, color=color, fontweight=weight,
                    transform=ax.transAxes, va="top")


def render_valuation(d: DashboardData, res, out_path: Optional[str] = None,
                     dpi: int = DPI) -> Figure:
    """Page 3 — Bear/Base/Bull intrinsic value and margin of safety."""
    matplotlib.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": P.FONT_STACK,
        "text.color": P.INK_PRIMARY,
        "figure.facecolor": P.SURFACE,
        "savefig.facecolor": P.SURFACE,
    })
    fig = Figure(figsize=(FIG_W, 8.2), dpi=dpi)
    fig.patch.set_facecolor(P.SURFACE)
    gs = fig.add_gridspec(
        3, 1, height_ratios=[1.35, 1.9, 1.15],
        left=0.055, right=0.965, top=0.955, bottom=0.15, hspace=0.55,
    )

    ax_header = fig.add_subplot(gs[0])
    ax_header.set_axis_off()
    ax_header.text(0, 1.04, f"{d.company} — intrinsic value",
                   fontsize=17.5, fontweight="bold", color=P.INK_PRIMARY,
                   transform=ax_header.transAxes, va="top")
    sub = f"{res.method_label} · {res.basis_label}"
    if res.discount_rate is not None:
        rate_name = "WACC" if res.method == "dcf" else "r_e"
        sub += f" · {rate_name} {fmt_pct(res.discount_rate)}"
    ax_header.text(0, 0.80, sub, fontsize=9, color=P.INK_SECONDARY,
                   transform=ax_header.transAxes, va="top")
    ax_header.text(1.0, 1.04, f"Generated {d.generated.isoformat()}",
                   fontsize=8, color=P.INK_MUTED, transform=ax_header.transAxes,
                   va="top", ha="right")
    if d.demo:
        ax_header.text(1.0, 0.80, "DEMO DATA — SYNTHETIC COMPANY, NOT A REAL FILER",
                       fontsize=9, fontweight="bold", color=P.DELTA_BAD,
                       transform=ax_header.transAxes, va="top", ha="right")
    tiles = [("Current price (P₀)", f"${res.price:,.2f}",
              f"as of {res.price_date.isoformat()}" if res.price_date else "",
              True)]
    for c in res.cases:
        if c.fv_ps is not None:
            tiles.append((f"{c.name} FV", f"${c.fv_ps:,.2f}",
                          f"{fmt_pct(c.mos, signed=True)} MoS", c.mos >= 0))
    if res.implied_g is not None:
        tiles.append(("Reverse-DCF implied g", fmt_pct(res.implied_g),
                      "vs 3.5% GDP cap", res.implied_g <= 0.035))
    _draw_kpi_row(ax_header, tiles)

    ax_field = fig.add_subplot(gs[1])
    _style_axes(ax_field, y_grid=False)
    _field_panel(ax_field, fig, res)

    ax_table = fig.add_subplot(gs[2])
    _valuation_table(ax_table, res)

    y = 0.105
    case_warns = [f"{c.name}: {w}" for c in res.cases for w in c.warnings]
    for w in res.warnings + case_warns:
        fig.text(0.055, y, "⚠ " + w, fontsize=6.8, color=P.DELTA_BAD, va="bottom")
        y -= 0.016
    notes = ("Equity bridge simplification: net debt = total debt − cash; minority interest, "
             "preferred and non-operating investments are not yet pulled from XBRL (master §4.A). "
             "All outputs code-computed.  Not investment advice.")
    fig.text(0.055, max(y, 0.012), notes, fontsize=6.6, color=P.INK_MUTED, va="bottom")

    if out_path:
        fig.savefig(out_path, dpi=dpi)
    return fig


# ------------------------------------------------------------------- public

def render_dashboard(d: DashboardData, out_path: Optional[str] = None,
                     dpi: int = DPI) -> Figure:
    matplotlib.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": P.FONT_STACK,
        "text.color": P.INK_PRIMARY,
        "axes.edgecolor": P.BASELINE,
        "figure.facecolor": P.SURFACE,
        "savefig.facecolor": P.SURFACE,
    })
    fig = Figure(figsize=(FIG_W, FIG_H), dpi=dpi)
    fig.patch.set_facecolor(P.SURFACE)
    gs = fig.add_gridspec(
        6, 2,
        height_ratios=[1.5, 2.5, 1.1, 1.9, 1.9, 1.9],
        left=0.055, right=0.965, top=0.98, bottom=0.055,
        hspace=0.62, wspace=0.16,
    )

    ax_header = fig.add_subplot(gs[0, :])
    _header(fig, ax_header, d)
    _kpi_tiles(ax_header, d)

    ax_price = fig.add_subplot(gs[1, :])
    ax_dd = fig.add_subplot(gs[2, :])
    if d.price_dates:
        _style_axes(ax_price)
        _panel_price(ax_price, fig, d)
        _style_axes(ax_dd)
        _panel_drawdown(ax_dd, fig, d)
    else:
        for ax, what in ((ax_price, "price history"), (ax_dd, "drawdown")):
            _style_axes(ax, y_grid=False)
            note = f"No {what} available"
            if d.price_error:
                note += f"\n({d.price_error})"
            _panel_note(ax, note)

    panels = [
        (_panel_revenue, gs[3, 0]), (_panel_margins, gs[3, 1]),
        (_panel_earnings_quality, gs[4, 0]), (_panel_accruals, gs[4, 1]),
        (_panel_shares, gs[5, 0]), (_panel_debt_cash, gs[5, 1]),
    ]
    for fn, spec in panels:
        ax = fig.add_subplot(spec)
        _style_axes(ax)
        if not d.fy_labels:
            _panel_note(ax, "No annual fundamentals available")
            continue
        fn(ax, fig, d)

    _footer(fig, d)

    if out_path:
        fig.savefig(out_path, dpi=dpi)
    return fig

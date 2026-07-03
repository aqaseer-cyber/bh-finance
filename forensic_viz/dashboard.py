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


def _panel_revenue(ax, fig, d: DashboardData):
    sub = f"5y CAGR {fmt_pct(d.revenue_cagr, signed=True)}" if d.revenue_cagr is not None else ""
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
    for s, name, color in keep:
        xs = [i for i, v in enumerate(s) if v is not None]
        ys = [v for v in s if v is not None]
        ax.plot(xs, ys, color=color, linewidth=1.6, solid_capstyle="round",
                solid_joinstyle="round", zorder=3)
        ax.plot(xs[-1], ys[-1], "o", color=color, markersize=5.6,
                markeredgecolor=P.SURFACE, markeredgewidth=1.2, zorder=4)
        _cap_label(ax, xs[-1], ys[-1], f"{name} {fmt_pct(ys[-1])}", above=True,
                   fig=fig, size=7.2)
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
    _panel_title(ax, "Accruals ratio (Sloan)",
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
        sub += f" · 5y total price return {fmt_pct(d.total_return, signed=True)}"
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
    _panel_title(ax, "Drawdown", "% below rolling 5y peak")
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
    tiles = []
    if d.last_close is not None:
        tiles.append(("Last close", f"${d.last_close:,.2f}",
                      f"{fmt_pct(d.total_return, signed=True)} 5y",
                      (d.total_return or 0) >= 0))
    if d.revenue and d.revenue[-1] is not None:
        tiles.append((f"Revenue ({last_label})", fmt_money(d.revenue[-1]),
                      f"{fmt_pct(d.revenue_cagr, signed=True)}/yr 5y" if d.revenue_cagr is not None else "",
                      (d.revenue_cagr or 0) >= 0))
    if d.net_margin and d.net_margin[-1] is not None:
        delta = (f"{d.net_margin_delta_pp:+.1f}pp vs {d.fy_labels[0]}"
                 if d.net_margin_delta_pp is not None else "")
        tiles.append((f"Net margin ({last_label})", fmt_pct(d.net_margin[-1]),
                      delta, (d.net_margin_delta_pp or 0) >= 0))
    if d.fcf and d.fcf[-1] is not None:
        tiles.append((f"Free cash flow ({last_label})", fmt_money(d.fcf[-1]),
                      f"{fmt_pct(d.fcf_cagr, signed=True)}/yr 5y" if d.fcf_cagr is not None else "",
                      (d.fcf_cagr or 0) >= 0))
    if d.share_change is not None and d.diluted_shares[-1] is not None:
        tiles.append(("Diluted shares", fmt_count(d.diluted_shares[-1]),
                      f"{fmt_pct(d.share_change, signed=True)} 5y",
                      d.share_change <= 0))  # falling share count = good
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
    fig.text(0.055, 0.040, line1, fontsize=7.2, color=P.INK_MUTED, va="bottom")
    fig.text(0.055, 0.028, line2, fontsize=7.2, color=P.INK_MUTED, va="bottom")
    if d.tags_used:
        shown = ", ".join(f"{k}={v}" for k, v in sorted(d.tags_used.items()))
        if len(shown) > 210:
            shown = shown[:207] + "…"
        fig.text(0.055, 0.014, "XBRL tags: " + shown, fontsize=6.4,
                 color=P.INK_MUTED, va="bottom")


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

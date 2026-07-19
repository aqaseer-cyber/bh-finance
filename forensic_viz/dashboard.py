"""THE report — v3 R3b (docs/V3_R3_EXPORT_DESIGN.md): six A4-portrait
sections, decision-first, rendered by `render_report`:

  P1  Decision Dashboard — base-quality box above the rating, FV band vs
      P₀, MoS base & stressed, entry-price ladder, thesis/terminal risk
      (or DRAFT), open triggers, delta vs prior run, run identity
  P2  Expectations & Valuation — the expectations bridge, case table,
      sensitivity, stress, exit cross-check `trimmed (raw)`, ONE
      assumptions-and-bridge table
  P3  Business & Segments — segment stack + mix (multi-segment) or the
      unit-economics page alone; the report's ONLY revenue charts
  P4  Quality & Forensics — Piotroski, Sloan, Altman (principle-7
      suppression), SBC %rev+%FCF, accruals, R&D audit, FCF vs ex-SBC
  P5  Capital & Balance Sheet — buybacks vs SBC, dilution, debt/cash,
      capex intensity vs 5y median (FIX-14b flag drawn)
  P6  Appendix — data audit, tag map, rescue log, segment status,
      warnings register: full tables, untruncated by construction

Empty thesis/terminal-risk waters every page with DRAFT (principle 6);
ellipses in a deliverable are a defect (principle 5). Design rules
honoured: single y-axis per panel, categorical hues in fixed slot order,
thin marks with rounded data-ends, hairline gridlines, direct labels.
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
from .valuation import ValuationError, dcf_fcff, residual_income

DPI = 150
FIG_W, FIG_H = 12.8, 16.9
# FIX-12c: page heights tuned to ISO A4 so no exported page sits half-empty.
# Portrait fill height at FIG_W, and landscape fill height at FIG_W:
A4_ASPECT = 841.890 / 595.276
A4P_H = round(FIG_W * A4_ASPECT, 2)   # ≈ 18.10in — portrait-full
A4L_H = round(FIG_W / A4_ASPECT, 2)   # ≈ 9.05in — landscape-full
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


# ---------------------------------------------------------------- header/kpi


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


def _footer(fig, d: DashboardData, extra=""):
    """The one page footer (FIX-12d), shared by all five pages: page-specific
    definitional lines via `extra` (str or sequence of str), then the common
    provenance line. Line spacing is in inches so every page height reads the
    same."""
    lines = [extra] if isinstance(extra, str) else list(extra)
    lines = [ln for ln in lines if ln]
    srcs = ["SEC EDGAR XBRL (latest amendment wins)"]
    if d.price_source:
        srcs.append(d.price_source)
    lines.append(f"Generated {d.generated.isoformat()} · Sources: "
                 + ", ".join(srcs) + " · Not investment advice.")
    h = fig.get_size_inches()[1]
    y, step = 0.09 / h, 0.125 / h
    for ln in reversed(lines):
        fig.text(0.055, y, ln, fontsize=6.6, color=P.INK_MUTED, va="bottom")
        y += step


# -------------------------------------------------- unit economics (page 2)

def _fmt_days(v) -> str:
    return "–" if v is None else f"{v:.0f}d"


def _line_series(ax, fig, series, names, end_fmt=fmt_pct):
    """Shared multi-line panel body: lines, end markers, dodged end labels."""
    keep = [(s, n, P.SERIES[k]) for k, (s, n) in enumerate(zip(series, names))
            if any(v is not None for v in s)]
    if not keep:
        return None
    label_slots = []
    for s, name, color in keep:
        xs = [i for i, v in enumerate(s) if v is not None]
        ys = [v for v in s if v is not None]
        ax.plot(xs, ys, color=color, linewidth=1.6, solid_capstyle="round",
                solid_joinstyle="round", zorder=3)
        ax.plot(xs[-1], ys[-1], "o", color=color, markersize=5.6,
                markeredgecolor=P.SURFACE, markeredgewidth=1.2, zorder=4)
        label_slots.append([xs[-1], ys[-1], f"{name} {end_fmt(ys[-1])}"])
    min_gap = _px_to_y(ax, fig, 15)
    label_slots.sort(key=lambda t: t[1])
    for j in range(1, len(label_slots)):
        if label_slots[j][1] - label_slots[j - 1][1] < min_gap:
            label_slots[j][1] = label_slots[j - 1][1] + min_gap
    for x, y, text in label_slots:
        _cap_label(ax, x, y, text, above=True, fig=fig, size=7.2)
    if len(keep) > 1:
        _legend(ax, [_series_swatch(c) for _, _, c in keep], [n for _, n, _ in keep])
    return keep


def _lines_panel_setup(ax, values, n_labels, labels, head=0.30, foot=0.06):
    lo, hi = min(values + [0]), max(values + [0])
    span = (hi - lo) or 1.0
    ax.set_xlim(-0.5, n_labels - 0.5)
    ax.set_ylim(lo - foot * span, hi + head * span)
    ax.set_xticks(range(n_labels))
    ax.set_xticklabels(labels)


def _day_axis(ax):
    # integer=True keeps day ticks whole and short ("24d"), never "22.5d"
    ax.yaxis.set_major_locator(MaxNLocator(nbins=4, integer=True))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}d"))


def _panel_wc_cycle(ax, fig, d: DashboardData):
    sub = "DSI = avg inventory/COGS × 365 (§2.2) · DSO, DPO alike"
    series = [d.dsi, d.dso, d.dpo]
    flat = [v for s in series for v in s if v is not None]
    if flat and all(v is None for v in d.dpo):
        sub += " · DPO: payables not tagged in XBRL"
    _panel_title(ax, "Working-capital cycle", sub)
    if not flat:
        _panel_note(ax, "Inventory / receivables / payables not reported in XBRL")
        return
    _lines_panel_setup(ax, flat, len(d.fy_labels), d.fy_labels)
    _day_axis(ax)
    _line_series(ax, fig, series, ["DSI", "DSO", "DPO"], end_fmt=_fmt_days)


def _panel_ccc(ax, fig, d: DashboardData):
    """CCC when all three legs exist; the operating cycle (DSI + DSO) when
    payables alone are untagged — honestly labeled, never a dead panel for
    a one-leg gap."""
    vals = [v for v in d.ccc if v is not None]
    series = d.ccc
    if vals:
        _panel_title(ax, "Cash conversion cycle", "DSI + DSO − DPO, days")
    else:
        series = [a + b if a is not None and b is not None else None
                  for a, b in zip(d.dsi, d.dso)]
        vals = [v for v in series if v is not None]
        if not vals:
            _panel_title(ax, "Cash conversion cycle", "DSI + DSO − DPO, days")
            _panel_note(ax, "Needs the working-capital legs — see the left panel")
            return
        _panel_title(ax, "Operating cycle",
                     "DSI + DSO, days — payables (DPO) not tagged in XBRL, "
                     "so the full CCC can't be computed")
    _category_panel_setup(ax, fig, d.fy_labels, vals)
    _day_axis(ax)
    width, _ = _bar_geometry(ax, fig, 1)
    for i, v in enumerate(series):
        if v is not None:
            _rounded_bar(ax, fig, i, v, width, P.SERIES[0])
            _cap_label(ax, i, v, _fmt_days(v), above=v >= 0, fig=fig)


def _panel_marginal_unit(ax, fig, d: DashboardData):
    _panel_title(ax, "The marginal unit",
                 "incremental operating margin ΔEBIT/Δrevenue vs overall margin")
    flat = [v for s in (d.incremental_op_margin, d.operating_margin)
            for v in s if v is not None]
    if not flat:
        _panel_note(ax, "Operating income not reported in XBRL")
        return
    _lines_panel_setup(ax, flat, len(d.fy_labels), d.fy_labels)
    _pct_axis(ax)
    ax.axhline(0, color=P.BASELINE, linewidth=0.9, zorder=2)
    width, _ = _bar_geometry(ax, fig, 1)
    for i, v in enumerate(d.incremental_op_margin):
        if v is not None:
            _rounded_bar(ax, fig, i, v, width, P.SERIES[0])
    xs = [i for i, v in enumerate(d.operating_margin) if v is not None]
    ys = [v for v in d.operating_margin if v is not None]
    if xs:
        ax.plot(xs, ys, color=P.SERIES[1], linewidth=1.6,
                solid_capstyle="round", zorder=4)
        _cap_label(ax, xs[-1], ys[-1], f"Op margin {fmt_pct(ys[-1])}", above=True,
                   fig=fig, size=7.2)
    _legend(ax, [_series_swatch(P.SERIES[0]), _series_swatch(P.SERIES[1])],
            ["Incremental", "Overall"])


def _panel_roic(ax, fig, d: DashboardData):
    _panel_title(ax, "Return on invested capital",
                 "NOPAT / avg invested capital · spread over WACC = value creation")
    vals = [v for v in d.roic if v is not None]
    if not vals:
        _panel_note(ax, "Equity / debt inputs missing — ROIC not computable")
        return
    build = getattr(d, "wacc_build", None)
    wacc = build.wacc if build is not None and build.wacc is not None else None
    _lines_panel_setup(ax, vals + ([wacc] if wacc else []),
                       len(d.fy_labels), d.fy_labels)
    _pct_axis(ax)
    if wacc:
        ax.axhline(wacc, color=P.INK_MUTED, linewidth=0.8,
                   linestyle=(0, (4, 3)), zorder=2)
        _zone_label(ax, -0.48, wacc + _px_to_y(ax, fig, 2),
                    f"WACC {fmt_pct(wacc)}")
    _line_series(ax, fig, [d.roic], ["ROIC"])


def _panel_roe(ax, fig, d: DashboardData):
    _panel_title(ax, "Return on equity", "net income / avg book equity")
    vals = [v for v in d.roe if v is not None]
    if not vals:
        _panel_note(ax, "Book equity not reported in XBRL")
        return
    _lines_panel_setup(ax, vals, len(d.fy_labels), d.fy_labels)
    _pct_axis(ax)
    _line_series(ax, fig, [d.roe], ["ROE"])


def _panel_nim(ax, fig, d: DashboardData):
    _panel_title(ax, "Net interest margin (proxy)",
                 "NII / avg TOTAL assets — earning assets aren't tagged (§2.2)")
    vals = [v for v in d.nim_proxy if v is not None]
    if not vals:
        _panel_note(ax, "InterestIncomeExpenseNet not reported in XBRL")
        return
    _lines_panel_setup(ax, vals, len(d.fy_labels), d.fy_labels)
    _pct_axis(ax, decimals=1)
    _line_series(ax, fig, [d.nim_proxy], ["NIM"])


def _panel_pcl(ax, fig, d: DashboardData):
    _panel_title(ax, "Provision for credit losses",
                 "PCL trend (§2.2) — spikes lead the credit cycle")
    vals = [v for v in d.credit_provision if v is not None]
    if not vals:
        _panel_note(ax, "Provision not tagged in XBRL — read the credit note")
        return
    _category_panel_setup(ax, fig, d.fy_labels, vals)
    _money_axis(ax)
    width, _ = _bar_geometry(ax, fig, 1)
    for i, v in enumerate(d.credit_provision):
        if v is not None:
            _rounded_bar(ax, fig, i, v, width, P.SERIES[0])


def _panel_underwriting(ax, fig, d: DashboardData):
    _panel_title(ax, "Underwriting quality",
                 "loss ratio = benefits/NEP; combined ratio when UW expense is tagged")
    series = [d.loss_ratio, d.combined_ratio]
    flat = [v for s in series for v in s if v is not None]
    if not flat:
        _panel_note(ax, "Premiums / benefits not tagged in XBRL")
        return
    _lines_panel_setup(ax, flat + [1.0], len(d.fy_labels), d.fy_labels)
    _pct_axis(ax)
    ax.axhline(1.0, color=P.INK_MUTED, linewidth=0.8, linestyle=(0, (4, 3)),
               zorder=2)
    _zone_label(ax, -0.48, 1.0 + _px_to_y(ax, fig, 2), "100% = break-even UW")
    _line_series(ax, fig, series, ["Loss", "Combined"])


def _panel_premiums(ax, fig, d: DashboardData):
    _panel_title(ax, "Net earned premiums", "growth of the insurance book")
    vals = [v for v in d.premiums_earned if v is not None]
    if not vals:
        _panel_note(ax, "PremiumsEarnedNet not tagged in XBRL")
        return
    _category_panel_setup(ax, fig, d.fy_labels, vals)
    _money_axis(ax)
    width, _ = _bar_geometry(ax, fig, 1)
    for i, v in enumerate(d.premiums_earned):
        if v is not None:
            _rounded_bar(ax, fig, i, v, width, P.SERIES[0])


def _panel_rev_yoy(ax, fig, d: DashboardData):
    _panel_title(ax, "Revenue growth", "year over year")
    vals = [v for v in d.revenue_yoy if v is not None]
    if not vals:
        _panel_note(ax, "Not enough revenue history")
        return
    _category_panel_setup(ax, fig, d.fy_labels, vals)
    _pct_axis(ax)
    ax.axhline(0, color=P.BASELINE, linewidth=0.9, zorder=2)
    width, _ = _bar_geometry(ax, fig, 1)
    for i, v in enumerate(d.revenue_yoy):
        if v is None:
            continue
        color = P.SERIES[0] if v >= 0 else P.DIVERGING_POS_BAD
        _rounded_bar(ax, fig, i, v, width, color)
        _cap_label(ax, i, v, fmt_pct(v, signed=True), above=v >= 0, fig=fig,
                   size=6.8)


def _panel_segment_note(ax, fig, d: DashboardData):
    _panel_title(ax, "Revenue architecture (§2.1)", "not automatable — here's why")
    _panel_note(ax, "Segment, geography and customer-concentration (≥10% house\n"
                    "flag) disclosures are dimensional XBRL — the companyfacts\n"
                    "API returns only consolidated totals.\n\n"
                    "Read the segment footnote and the concentration risk\n"
                    "paragraph; organic vs acquired growth needs the deal\n"
                    "footnotes (analyst input).")


def _panel_reit_note(ax, fig, d: DashboardData):
    _panel_title(ax, "REIT marginal unit (§2.2)", "not automatable — here's why")
    _panel_note(ax, "NOI, same-store growth and the FFO→AFFO bridge are\n"
                    "non-GAAP measures — not in XBRL. Take them from the\n"
                    "supplemental package (analyst input), then use the\n"
                    "AFFO-yield method on the valuation page.")


_UNIT_PANELS = {
    "standard": (_panel_wc_cycle, _panel_ccc, _panel_marginal_unit, _panel_roic),
    "bank": (_panel_nim, _panel_pcl, _panel_roe, _panel_segment_note),
    "insurance": (_panel_underwriting, _panel_premiums, _panel_roe,
                  _panel_segment_note),
    "reit": (_panel_rev_yoy, _panel_roe, _panel_reit_note, _panel_segment_note),
    "sotp": (_panel_rev_yoy, _panel_roic, _panel_marginal_unit,
             _panel_segment_note),
}


def _unit_kpis(ax, d: DashboardData):
    ax.set_axis_off()
    tiles = []
    if d.track == "bank":
        nim = _latest(d.nim_proxy)
        if nim is not None:
            tiles.append(("NIM (proxy)", fmt_pct(nim, decimals=2), "on avg assets", True))
        pcl = _latest(d.credit_provision)
        if pcl is not None:
            tiles.append(("Provision (latest)", fmt_money(pcl), "PCL trend", True))
    elif d.track == "insurance":
        lr = _latest(d.loss_ratio)
        if lr is not None:
            tiles.append(("Loss ratio", fmt_pct(lr), "benefits / NEP", lr < 0.75))
        cr = _latest(d.combined_ratio)
        if cr is not None:
            tiles.append(("Combined ratio", fmt_pct(cr),
                          "UW profit <100%", cr < 1.0))
    else:
        ccc = _latest(d.ccc)
        if ccc is not None:
            first = next((v for v in d.ccc if v is not None), None)
            delta = (f"{ccc - first:+.0f}d vs {d.fy_labels[0]}"
                     if first is not None and d.fy_labels else "")
            tiles.append(("Cash conversion", _fmt_days(ccc), delta,
                          first is None or ccc <= first))
        inc = _latest(d.incremental_op_margin)
        if inc is not None:
            om = _latest(d.operating_margin)
            tiles.append(("Incremental margin", fmt_pct(inc),
                          f"vs overall {fmt_pct(om)}" if om is not None else "",
                          om is None or inc >= om))
    roic = _latest(d.roic)
    build = getattr(d, "wacc_build", None)
    wacc = build.wacc if build is not None else None
    if roic is not None:
        tiles.append(("ROIC", fmt_pct(roic),
                      f"vs WACC {fmt_pct(wacc)}" if wacc is not None else "NOPAT/avg IC",
                      wacc is None or roic > wacc))
    roe = _latest(d.roe)
    if roe is not None:
        tiles.append(("ROE", fmt_pct(roe), "NI / avg equity", roe > 0.10))
    if d.revenue_cagr is not None:
        tiles.append((f"Revenue CAGR {_fy_span(d)}y", fmt_pct(d.revenue_cagr, signed=True),
                      "", d.revenue_cagr > 0))
    _draw_kpi_row(ax, tiles[:6])


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


def _panel_solvency(ax, fig, d: DashboardData):
    """Banks/insurance replacement for Altman Z (master §3.3 CET1/solvency)."""
    _panel_title(ax, "Solvency — regulatory capital",
                 "CET1 / Tier-1 / leverage ratios as filed; equity/assets fallback")
    series = [(d.cet1_ratio, "CET1"), (d.tier1_ratio, "Tier 1"),
              (d.leverage_ratio, "Tier-1 leverage")]
    keep = [(s, n, P.SERIES[k]) for k, (s, n) in enumerate(series)
            if any(v is not None for v in s)]
    fallback = False
    if not keep:
        if any(v is not None for v in d.equity_to_assets):
            keep = [(d.equity_to_assets, "Equity / assets", P.SERIES[0])]
            fallback = True
        else:
            _panel_note(ax, "No regulatory-capital tags or equity/assets inputs "
                            "in XBRL — check the filing's capital section")
            return
    flat = [v for s, _, _ in keep for v in s if v is not None]
    hi = max(flat + [0.10])
    ax.set_xlim(-0.5, len(d.fy_labels) - 0.5)
    ax.set_ylim(0, hi * 1.3)
    ax.set_xticks(range(len(d.fy_labels)))
    ax.set_xticklabels(d.fy_labels)
    _pct_axis(ax, decimals=1)
    if not fallback:  # Basel III reference lines only for regulatory ratios
        for y, lab in ((0.045, "CET1 min 4.5%"), (0.07, "+ buffer 7.0%")):
            ax.axhline(y, color=P.INK_MUTED, linewidth=0.8,
                       linestyle=(0, (4, 3)), zorder=2)
            _zone_label(ax, -0.48, y + _px_to_y(ax, fig, 2), lab)
    for s, name, color in keep:
        xs = [i for i, v in enumerate(s) if v is not None]
        ys = [v for v in s if v is not None]
        ax.plot(xs, ys, color=color, linewidth=1.6, solid_capstyle="round", zorder=3)
        ax.plot(xs[-1], ys[-1], "o", color=color, markersize=5.6,
                markeredgecolor=P.SURFACE, markeredgewidth=1.2, zorder=4)
        _cap_label(ax, xs[-1], ys[-1], f"{name} {fmt_pct(ys[-1])}", above=True,
                   fig=fig, size=7.2)
    if len(keep) > 1:
        _legend(ax, [_series_swatch(c) for _, _, c in keep], [n for _, n, _ in keep])


def _panel_credit_reserves(ax, fig, d: DashboardData):
    """Banks capitalization audit (§3.2): is a reserve release flattering
    earnings? Allowance level vs annual provision."""
    _panel_title(ax, "Credit reserves (banks)",
                 "allowance for credit losses vs annual provision; falling both = release")
    series = [(d.credit_allowance, "Allowance"), (d.credit_provision, "Provision")]
    keep = [(s, n, P.SERIES[k]) for k, (s, n) in enumerate(series)
            if any(v is not None for v in s)]
    if not keep:
        _panel_note(ax, "Allowance/provision not tagged in XBRL —\n"
                        "read the credit-quality note (analyst input)")
        return
    flat = [v for s, _, _ in keep for v in s if v is not None]
    _category_panel_setup(ax, fig, d.fy_labels, flat)
    _money_axis(ax)
    _draw_bar_series(ax, fig, [s for s, _, _ in keep], [c for _, _, c in keep])
    if len(keep) > 1:
        _legend(ax, [_series_swatch(c) for _, _, c in keep], [n for _, n, _ in keep])


def _panel_altman(ax, fig, d: DashboardData):
    # R3b principle 7: a financial-signature filer (a1 — finance SIC or a
    # material receivable book) gets the suppression note, never a
    # manufacturer-calibrated Z presented as if it applied
    from .anchors import assess_base_quality

    _panel_title(ax, "Altman Z-score",
                 "original 1968 model (Standard-Mfg); MVE = FY-end close × diluted shares")
    if assess_base_quality(d).financial_signature:
        _panel_note(ax, "Altman Standard-Mfg suppressed — financial-signature\n"
                        "filer (credit float on the balance sheet); the 1968\n"
                        "coefficients were fit on manufacturers and mislead\n"
                        "here (design principle 7)")
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
    ax.axhspan(y0, config.ALTMAN_DISTRESS, color=P.NEGATIVE, alpha=0.06, zorder=1)
    ax.axhspan(config.ALTMAN_DISTRESS, config.ALTMAN_SAFE, color=P.GRIDLINE,
               alpha=0.55, zorder=1)
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
    """R3b P4: SBC as % of revenue (bars) AND % of FCF (line) — the two
    denominators the design demands; the a3 stale guard replaces any
    relic 'latest' figure with the staleness note."""
    from .kpi import stale_note

    sub = "bar = % of revenue · line = % of FCF · label = $ amount"
    stale = stale_note(d.sbc, d.fy_labels)
    if stale:
        sub += f" · {stale}"
    elif d.sbc_pct_fcf_latest is not None:
        sub += f" · latest = {fmt_pct(d.sbc_pct_fcf_latest)} of FCF"
    _panel_title(ax, "Stock-based compensation", sub)
    vals = [v for v in d.sbc_pct_revenue if v is not None]
    if not vals:
        _panel_note(ax, "SBC not reported in XBRL")
        return
    pct_fcf = [s / f if s is not None and f is not None and f > 0 else None
               for s, f in zip(d.sbc, d.fcf)]
    _category_panel_setup(ax, fig, d.fy_labels,
                          vals + [v for v in pct_fcf if v is not None])
    _pct_axis(ax, decimals=1)
    width, _ = _bar_geometry(ax, fig, 1)
    for i, (pct, usd) in enumerate(zip(d.sbc_pct_revenue, d.sbc)):
        if pct is None:
            continue
        _rounded_bar(ax, fig, i, pct, width, P.SERIES[0])
        _cap_label(ax, i, pct, fmt_money(usd), above=pct >= 0, fig=fig, size=6.6)
    xs = [i for i, v in enumerate(pct_fcf) if v is not None]
    if xs:
        ys = [pct_fcf[i] for i in xs]
        ax.plot(xs, ys, color=P.BROWN, linewidth=1.4,
                solid_capstyle="round", zorder=4)
        _cap_label(ax, xs[-1], ys[-1], f"{fmt_pct(ys[-1])} of FCF",
                   above=True, fig=fig, size=6.6, color=P.BROWN)
        _legend(ax, [_series_swatch(P.SERIES[0]), _series_swatch(P.BROWN)],
                ["% of revenue", "% of FCF"])


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
    from .kpi import stale_note

    sub = "house §2b basis: SBC treated as a real cost of the franchise"
    stale = stale_note(d.fcf_ex_sbc, d.fy_labels)
    if stale:  # a3: the adjusted series died early — say so, on the chart
        sub += f" · ex-SBC {stale}"
    _panel_title(ax, "FCF vs FCF ex-SBC", sub)
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
    if d.adjustment_burden is not None:  # fluff filter (§3.1), analyst input
        flagged = d.adjustment_burden > 0.20
        tiles.append(("Adjustment burden", fmt_pct(d.adjustment_burden),
                      "FLAG >20%" if flagged else "non-GAAP vs GAAP NI",
                      not flagged))
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
        ax.text(x, 0.96, label, fontsize=8, color=P.INK_SECONDARY,
                transform=ax.transAxes, va="top")
    for r, c in enumerate(res.cases):
        y = 0.76 - r * 0.22
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
    # R3b: the reverse-DCF read lives on the expectations bridge (P2) and
    # the entry-price ladder is its own P1 panel — no duplicates here


# ----------------------------------------------------- verdict page (page 5)

def _panel_stress(ax, fig, res, v):
    _panel_title(ax, "Stress test (§5.1)",
                 f"{v.shock_label} · like-for-like per-share FV, base vs stressed")
    cats = [(v.track_a_label.split(" — ")[0], v.fv_a),
            (v.track_b_label.split(" — ")[0], v.fv_b),
            ("FV average", v.fv_avg)]
    stressed = {0: v.stressed_fv_a, 1: v.stressed_fv_b, 2: v.stressed_fv_avg}
    labels = [c[0] for c in cats]
    base_vals = [c[1] for c in cats]
    flat = [x for x in base_vals + list(stressed.values()) + [res.price]
            if x is not None]
    if not any(x is not None for x in base_vals):
        _panel_note(ax, "FV unavailable — see the notes below")
        return
    ax.set_xlim(-0.5, len(labels) - 0.5)
    lo, hi = min(flat), max(flat)
    span = (hi - lo) or hi or 1.0
    ax.set_ylim(max(0, lo - 0.25 * span), hi + 0.3 * span)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels)
    ax.yaxis.set_major_locator(MaxNLocator(nbins=4))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax.axhline(res.price, color=P.INK_SECONDARY, linewidth=1.2, zorder=2)
    _zone_label(ax, -0.48, res.price + _px_to_y(ax, fig, 3),
                f"P₀ ${res.price:,.2f}")
    width, offsets = _bar_geometry(ax, fig, 2)
    for i, val in enumerate(base_vals):
        if val is None:
            continue
        sv = stressed.get(i)
        if sv is not None:
            _rounded_bar(ax, fig, i + offsets[0], val, width, P.SERIES[0])
            _rounded_bar(ax, fig, i + offsets[1], sv, width, P.NEGATIVE)
            # dodge the pair of cap labels horizontally so they never collide
            _cap_label(ax, i + offsets[0] - _px_to_x(ax, fig, 14), val,
                       f"${val:,.2f}", above=True, fig=fig, size=6.8)
            _cap_label(ax, i + offsets[1] + _px_to_x(ax, fig, 14), sv,
                       f"${sv:,.2f}", above=True, fig=fig, size=6.8,
                       color=P.DELTA_BAD)
        else:
            _rounded_bar(ax, fig, i, val, width, P.SERIES[0])
            _cap_label(ax, i, val, f"${val:,.2f}", above=True, fig=fig, size=6.8)
    _legend(ax, [_series_swatch(P.SERIES[0]), _series_swatch(P.NEGATIVE)],
            ["Base", "Stressed"])


# FIX-12d sensitivity shocks (decision-dashboard grid on the verdict page)
_RATE_SHOCKS = (-0.01, 0.0, 0.01)    # WACC / ROE rows: ±100bp
_G_SHOCKS = (-0.005, 0.0, 0.005)     # terminal-g columns: ±50bp
_YIELD_SHOCKS = (-0.01, 0.0, 0.01)   # AFFO target yield: ±100bp


def _mm(val) -> str:
    # \$ so two of these in one string never pair into a mathtext span
    return "–" if val is None else f"\\${val / 1e6:,.0f}mm"


def _dcf_track_bases(res, v):
    """Per-track FCFF bases recovered through engine linearity (ev = base·K),
    so the grid reprices the exact bases behind fv_a / fv_b — Track A
    as-reported, Track B ex-SBC — without re-deriving them from raw series."""
    inputs, rate, shares = res._inputs, res.discount_rate, res.shares
    if inputs is None or rate is None or not shares:
        return None, None
    bridge = res.bridge if res.bridge is not None else (res.net_debt or 0.0)
    bases = []
    for fv, c in ((v.fv_a, inputs.cases.get("Bear")),
                  (v.fv_b, inputs.cases.get("Base"))):
        if fv is None or c is None or c.g0 is None or c.g_term is None:
            bases.append(None)
            continue
        try:
            k = dcf_fcff(1.0, rate, c.g0, c.g_term)["ev"]
        except ValuationError:
            bases.append(None)
            continue
        bases.append((fv * shares + bridge) / k)
    return tuple(bases)


def verdict_sensitivity(res, v):
    """FIX-12d: the verdict page's FV-average sensitivity grid — pure math,
    no rendering, recomputed with the page's own engines and equity bridge.

    DCF: 3×3 over WACC ±100bp × terminal g ±50bp (per-track g_term, Track A
    Bear / Track B Base, same bases and bridge as fv_a / fv_b). RI: ROE
    ±100bp × terminal g ±50bp at the page's r_e. AFFO: one row over target
    yield ±100bp. Manual/SOTP: None — external model, no sensitivity.

    Cells are FV-average per share, or None where the shocked rates make the
    terminal value undefined (WACC/r_e ≤ g — printed as "—"). The center cell
    reproduces the page's FV average exactly."""
    inputs = res._inputs
    if inputs is None or res.method == "manual":
        return None
    bear, base_c = inputs.cases.get("Bear"), inputs.cases.get("Base")
    if bear is None or base_c is None:
        return None
    rate, shares = res.discount_rate, res.shares

    if res.method == "dcf":
        base_a, base_b = _dcf_track_bases(res, v)
        tracks = [(b, c.g0, c.g_term)
                  for b, c in ((base_a, bear), (base_b, base_c))
                  if b is not None]
        if not tracks:
            return None
        bridge = res.bridge if res.bridge is not None else (res.net_debt or 0.0)
        cells = []
        for dr in _RATE_SHOCKS:
            row = []
            for dg in _G_SHOCKS:
                try:
                    fvs = [(dcf_fcff(b, rate + dr, g0, gt + dg)["ev"] - bridge)
                           / shares for b, g0, gt in tracks]
                except ValuationError:
                    row.append(None)
                    continue
                row.append(sum(fvs) / len(fvs))
            cells.append(row)
        return {
            "kind": "dcf",
            "title": "WACC ±100bp × terminal g ±50bp · same bases & bridge",
            "row_hdr": "WACC", "col_hdr": "Δ terminal g",
            "row_labels": [fmt_pct(rate + dr) for dr in _RATE_SHOCKS],
            "col_labels": ["g −50bp", "g (case)", "g +50bp"],
            "cells": cells, "center": (1, 1),
        }

    if res.method == "ri":
        bv0 = res.base_value
        if rate is None or not shares or not bv0 or bv0 <= 0:
            return None
        tracks = [(c.roe, c.g0, c.g_term)
                  for fv, c in ((v.fv_a, bear), (v.fv_b, base_c))
                  if fv is not None
                  and None not in (c.roe, c.g0, c.g_term)]
        if not tracks:
            return None
        cells = []
        for droe in _RATE_SHOCKS:
            row = []
            for dg in _G_SHOCKS:
                try:
                    fvs = [residual_income(bv0, rate, roe + droe, g0, gt + dg)
                           ["value"] / shares for roe, g0, gt in tracks]
                except ValuationError:
                    row.append(None)
                    continue
                row.append(sum(fvs) / len(fvs))
            cells.append(row)
        return {
            "kind": "ri",
            "title": f"ROE ±100bp × terminal g ±50bp at r_e {fmt_pct(rate)}",
            "row_hdr": "ROE", "col_hdr": "Δ terminal g",
            "row_labels": ["ROE −100bp", "ROE (case)", "ROE +100bp"],
            "col_labels": ["g −50bp", "g (case)", "g +50bp"],
            "cells": cells, "center": (1, 1),
        }

    if res.method == "affo":
        tracks = [(c.affo_ps, c.target_yield)
                  for fv, c in ((v.fv_a, bear), (v.fv_b, base_c))
                  if fv is not None and c.affo_ps and c.target_yield]
        if not tracks:
            return None
        row = []
        for dy in _YIELD_SHOCKS:
            fvs = [a / (yy + dy) for a, yy in tracks if (yy + dy) > 0]
            row.append(sum(fvs) / len(fvs) if len(fvs) == len(tracks) else None)
        return {
            "kind": "affo",
            "title": "target AFFO yield ±100bp",
            "row_hdr": "", "col_hdr": "Δ yield",
            "row_labels": ["FV avg"],
            "col_labels": ["yield −100bp", "target", "yield +100bp"],
            "cells": [row], "center": (0, 1),
        }
    return None


def _panel_sensitivity(ax, res, v):
    """FIX-12d row-2 right: the FV-average grid; green cells clear P₀."""
    ax.set_axis_off()
    grid = verdict_sensitivity(res, v)
    if grid is None:
        _panel_title(ax, "Sensitivity (§5.4)", "")
        _panel_note(ax, "external model — no sensitivity")
        return
    _panel_title(ax, "Sensitivity — FV average per share", grid["title"])
    rows, cols, cells = grid["row_labels"], grid["col_labels"], grid["cells"]
    n_r, n_c = len(rows), len(cols)
    xs = [0.24 + (j + 0.5) * (0.76 / n_c) for j in range(n_c)]
    ys = [0.52] if n_r == 1 else [0.68 - i * 0.26 for i in range(n_r)]
    ax.text(0.0, 0.88, grid["row_hdr"], fontsize=7.2, color=P.INK_MUTED,
            transform=ax.transAxes, va="center")
    for j, cl in enumerate(cols):
        ax.text(xs[j], 0.88, cl, fontsize=7.6, color=P.INK_SECONDARY,
                transform=ax.transAxes, va="center", ha="center")
    ci, cj = grid["center"]
    cw = 0.76 / n_c
    ax.add_patch(Rectangle((xs[cj] - cw / 2 + 0.012, ys[ci] - 0.11),
                           cw - 0.024, 0.22, transform=ax.transAxes,
                           facecolor=P.AMBER, alpha=0.22,
                           edgecolor=P.BASELINE, linewidth=0.8, zorder=1))
    for i, rl in enumerate(rows):
        ax.text(0.0, ys[i], rl, fontsize=7.8, color=P.INK_PRIMARY,
                transform=ax.transAxes, va="center")
        for j in range(n_c):
            val = cells[i][j]
            if val is None:
                txt, color, weight = "—", P.INK_MUTED, "normal"
            else:
                txt = f"${val:,.2f}"
                color = P.DELTA_GOOD if val >= res.price else P.DELTA_BAD
                weight = "bold" if (i, j) == (ci, cj) else "normal"
            ax.text(xs[j], ys[i], txt, fontsize=8.6, color=color,
                    fontweight=weight, transform=ax.transAxes,
                    va="center", ha="center", zorder=3)
    ax.text(0.0, 0.02, f"green ≥ P₀ ${res.price:,.2f} · center = page inputs "
                       "· — = terminal value undefined (rate ≤ g)",
            fontsize=6.6, color=P.INK_MUTED, transform=ax.transAxes,
            va="bottom")


def _panel_assumptions(ax, d: DashboardData, res, v):
    """FIX-12d row-3 left: per-case assumptions, discount rate, per-track
    bases and the equity-bridge legs — the whole model on one panel."""
    import textwrap

    ax.set_axis_off()
    # R3b: the ONE assumptions-and-bridge table — the per-case rows live in
    # the case table above it, NEVER here again (the Valuation/Verdict
    # duplication the design kills); a long track label wraps, not clips
    sub = textwrap.fill(f"{v.track_a_label}  ·  {v.track_b_label}", width=118)
    _panel_title(ax, "Assumptions & bridge (§4.0)", sub)
    if res.method == "dcf":
        base_a, base_b = _dcf_track_bases(res, v)
        rate_line = (f"WACC {fmt_pct(res.discount_rate)} · base A "
                     f"(as-reported) {_mm(base_a)} · base B (ex-SBC) "
                     f"{_mm(base_b)}")
    elif res.method == "ri":
        rate_line = f"r_e {fmt_pct(res.discount_rate)} · BV₀ {_mm(res.base_value)}"
    elif res.method == "affo":
        rate_line = "AFFO per share and target yields are analyst-supplied (§4.C)"
    else:
        rate_line = "external model — values carried from the analyst's SOTP"
    ax.text(0.0, 0.56, rate_line, fontsize=8.4, color=P.INK_PRIMARY,
            transform=ax.transAxes, va="top")
    if res.method == "dcf":
        mi = _latest(d.minority_interest) or 0.0
        pref = _latest(d.preferred_equity) or 0.0
        nonop = d.non_op_investments or 0.0
        bridge = res.bridge if res.bridge is not None else (res.net_debt or 0.0)
        bridge_line = _tex(
            f"Bridge (EV→equity): net debt "
            f"{fmt_money(res.net_debt or 0.0)} + MI {fmt_money(mi)} "
            f"+ preferred {fmt_money(pref)} − non-op "
            f"{fmt_money(nonop)} = {fmt_money(bridge)}")
    else:
        bridge_line = "No EV→equity bridge — this method values equity directly."
    ax.text(0.0, 0.34, bridge_line, fontsize=8.4, color=P.INK_SECONDARY,
            transform=ax.transAxes, va="top")
    if v.optionality:
        ax.text(0.0, 0.12, textwrap.fill(
            f"Named optionality (§4.D): {v.optionality}", width=150),
            fontsize=8.2, color=P.INK_SECONDARY, transform=ax.transAxes,
            va="top")


def _panel_triggers(ax, d: DashboardData, v, open_triggers):
    """FIX-12d row-3 right: rating-gate verdict, stress sentence, and the
    open ledger triggers (passed in — rendering never touches ledger.py)."""
    import textwrap

    ax.set_axis_off()
    _panel_title(ax, "Triggers & rating gate (§5.3 · §5.7)", v.shock_label)
    gate_bad = v.coherence.startswith("CHECK")
    entries = [(f"Gate: {v.coherence} — {v.coherence_detail}",
                P.DELTA_BAD if gate_bad else P.INK_PRIMARY,
                "bold" if gate_bad else "normal")]
    if v.stressed_mos is not None and v.stressed_fv_avg is not None:
        entries.append((f"Stressed: FV avg ${v.stressed_fv_avg:,.2f} → MoS "
                        f"{fmt_pct(v.stressed_mos, signed=True)}",
                        P.INK_SECONDARY, "normal"))
    else:
        entries.append(("Stressed MoS n/a — see the notes below.",
                        P.INK_MUTED, "normal"))
    if v.optionality:
        entries.append((f"Named optionality (§4.D): {v.optionality}",
                        P.INK_SECONDARY, "normal"))
    if d.terminal_risk:
        entries.append((f"Terminal risk (§2.3): {d.terminal_risk}",
                        P.DELTA_BAD, "normal"))
    for note in v.notes:
        # R3b: the exit cross-check has its own P2 panel — never twice
        if note.startswith("5y exit cross-check"):
            continue
        entries.append((f"Note: {note}", P.INK_MUTED, "normal"))
    if open_triggers:
        entries.append(("Open triggers:", P.INK_PRIMARY, "bold"))
        entries.extend(("•  " + str(t), P.INK_SECONDARY, "normal")
                       for t in open_triggers)
    else:
        entries.append(("No open triggers — add via --ledger or the watchlist.",
                        P.INK_MUTED, "normal"))
    y, skipped = 0.92, 0
    for idx, (text, color, weight) in enumerate(entries):
        wrapped = textwrap.fill(text, width=74)
        n = wrapped.count("\n") + 1
        if y - 0.075 * n < 0.06:      # keep room for the overflow line
            skipped = len(entries) - idx
            break
        ax.text(0, y, wrapped, fontsize=7.6, color=color, fontweight=weight,
                transform=ax.transAxes, va="top", linespacing=1.3)
        y -= 0.075 * n + 0.03
    if skipped:
        ax.text(0, y, f"+{skipped} more — see the watchlist / ledger history",
                fontsize=7.2, color=P.INK_MUTED, transform=ax.transAxes,
                va="top")


# ------------------------------------------------------------------- public


def _tex(s: str) -> str:
    """Escape $ for matplotlib text — two bare $ in one string open a
    mathtext span and silently italicize everything between them."""
    return str(s).replace("$", "\\$")


def _rc():
    matplotlib.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": P.FONT_STACK,
        "text.color": P.INK_PRIMARY,
        "axes.edgecolor": P.BASELINE,
        "figure.facecolor": P.SURFACE,
        "savefig.facecolor": P.SURFACE,
    })


def _is_draft(d: DashboardData) -> bool:
    """Principle 6: no thesis or no terminal risk -> the report is a DRAFT."""
    return not (d.thesis and d.terminal_risk)


def _watermark(fig):
    fig.text(0.5, 0.5, "DRAFT", fontsize=118, fontweight="bold",
             color=P.BASELINE, alpha=0.16, rotation=36,
             ha="center", va="center", zorder=0)


def _finish(fig, d: DashboardData, extra="", out_path=None, dpi=DPI):
    _footer(fig, d, extra)
    if _is_draft(d):
        _watermark(fig)
    if out_path:
        fig.savefig(out_path, dpi=dpi)
    return fig


def _new_page(dpi: int):
    _rc()
    fig = Figure(figsize=(FIG_W, A4P_H), dpi=dpi)
    fig.patch.set_facecolor(P.SURFACE)
    return fig


def _page_header(fig, ax, d: DashboardData, page_title: str):
    ax.set_axis_off()
    ax.text(0, 1.10, f"{d.company} — {page_title}", fontsize=17.5,
            fontweight="bold", color=P.INK_PRIMARY,
            transform=ax.transAxes, va="top")
    sub = f"{d.ticker} · {d.track.title()} track"
    if d.fy_labels:
        sub += f" · fiscal years {d.fy_labels[0]}-{d.fy_labels[-1]}"
    ax.text(0, 0.56, sub, fontsize=9, color=P.INK_SECONDARY,
            transform=ax.transAxes, va="top")
    ax.text(1.0, 1.04, f"Generated {d.generated.isoformat()} · SEC EDGAR XBRL",
            fontsize=8, color=P.INK_MUTED, transform=ax.transAxes,
            va="top", ha="right")
    if d.demo:
        ax.text(1.0, 0.80, "DEMO DATA — SYNTHETIC COMPANY, NOT A REAL FILER",
                fontsize=9, fontweight="bold", color=P.DELTA_BAD,
                transform=ax.transAxes, va="top", ha="right")


# ------------------------------------------------ P1 — Decision Dashboard

def _panel_base_quality(ax, d: DashboardData):
    """The base-quality gate (R3a a1) — ABOVE the rating, red-keyed when
    challenged: a report challenges its own base before presenting a
    verdict on it (principle 3)."""
    import textwrap

    from .anchors import assess_base_quality

    ax.set_axis_off()
    q = assess_base_quality(d)
    if q.challenged:
        ax.add_patch(Rectangle((0.0, 0.02), 1.0, 0.96, transform=ax.transAxes,
                               facecolor=P.SURFACE, edgecolor=P.NEGATIVE,
                               linewidth=1.6, zorder=1))
        ax.text(0.012, 0.88, "BASE QUALITY — CHALLENGED", fontsize=9.6,
                fontweight="bold", color=P.NEGATIVE,
                transform=ax.transAxes, va="top", zorder=3)
        ax.text(0.012, 0.60, textwrap.fill(q.text, width=150), fontsize=8.2,
                color=P.INK_PRIMARY, transform=ax.transAxes, va="top",
                linespacing=1.35, zorder=3)
    else:
        acc = (fmt_pct(q.accruals_median_3y, signed=True)
               if q.accruals_median_3y is not None else "n/a")
        ratio = (f"{q.cfo_ni_ratio:.1f}x"
                 if q.cfo_ni_ratio is not None else "n/a")
        ax.text(0, 0.80, "Base quality: unchallenged", fontsize=9.2,
                fontweight="bold", color=P.INK_PRIMARY,
                transform=ax.transAxes, va="top")
        ax.text(0, 0.44, f"3y median accruals {acc} · CFO/NI {ratio} · "
                         "no financial signature — the Standard-track base "
                         "carries no known distortion",
                fontsize=8.2, color=P.INK_SECONDARY,
                transform=ax.transAxes, va="top")


def _delta_vs_prior(v, prior) -> tuple:
    """(text, color) for the P1 delta line — a report that doesn't know
    its predecessor invites anchoring."""
    if v is None or v.fv_avg is None:
        return ("Delta vs prior run: n/a — no FV on this run", P.INK_MUTED)
    if not prior or prior.get("fv_avg") is None:
        return ("Delta vs prior run: first recorded run — no predecessor "
                "on the ledger", P.INK_MUTED)
    prev = float(prior["fv_avg"])
    when = str(prior.get("recorded_at", ""))[:10] or "unknown date"
    if prev <= 0:
        return (f"Delta vs prior run: prior FV_avg non-positive on {when}",
                P.INK_MUTED)
    delta = v.fv_avg / prev - 1.0
    return ((f"FV_avg \\${v.fv_avg:,.2f} vs \\${prev:,.2f} on {when} · "
             f"Δ{delta:+.1%}"),
            P.INK_SECONDARY if abs(delta) < 0.10 else P.DELTA_BAD)


def _panel_rating(ax, d: DashboardData, v, prior):
    """P1 rating strip — tiles, coherence gate and the delta-vs-prior
    line, all drawn inside the axes (nothing bleeds into the next row)."""
    import textwrap

    ax.set_axis_off()
    if v is None:
        ax.text(0, 0.92, "No valuation attached", fontsize=15,
                fontweight="bold", color=P.INK_MUTED,
                transform=ax.transAxes, va="top")
        ax.text(0, 0.52, "Run Intrinsic value (Valuation screen or --value) "
                         "to print the rating, FV band, MoS and ladder.",
                fontsize=8.6, color=P.INK_SECONDARY,
                transform=ax.transAxes, va="top")
        return
    gate_ok = v.coherence.startswith("ok")
    tiles = [("Rating", v.rating or "—",
              "coherent with MoS" if gate_ok else v.coherence, gate_ok)]
    if v.fv_avg is not None:
        tiles.append(("FV average", f"${v.fv_avg:,.2f}",
                      "average(Track A, Track B)", True))
    if v.mos is not None:
        tiles.append(("MoS at P₀", fmt_pct(v.mos, signed=True),
                      "base", v.mos >= 0))
    if v.stressed_mos is not None:
        tiles.append(("Stressed MoS", fmt_pct(v.stressed_mos, signed=True),
                      v.shock_label.split("(")[0].strip(),
                      v.stressed_mos >= 0))
    n = len(tiles)
    for i, (label, value, delta, good) in enumerate(tiles):
        x0 = i / n
        ax.text(x0, 0.97, label, fontsize=8.2, color=P.INK_SECONDARY,
                transform=ax.transAxes, va="top")
        ax.text(x0, 0.83, value, fontsize=15.5, fontweight="bold",
                color=P.INK_PRIMARY, transform=ax.transAxes, va="top")
        if delta:
            ax.text(x0, 0.56, delta, fontsize=8.2,
                    color=P.DELTA_GOOD if good else P.DELTA_BAD,
                    transform=ax.transAxes, va="top")
        if i:
            ax.axvline(x0 - 0.018, ymin=0.55, ymax=0.98, color=P.GRIDLINE,
                       linewidth=0.8)
    gate_bad = v.coherence.startswith("CHECK")
    gate = textwrap.fill(f"Gate: {v.coherence} — {v.coherence_detail}",
                         width=165)
    ax.text(0, 0.36, gate, fontsize=8.0, linespacing=1.3,
            color=P.DELTA_BAD if gate_bad else P.INK_SECONDARY,
            fontweight="bold" if gate_bad else "normal",
            transform=ax.transAxes, va="top")
    text, color = _delta_vs_prior(v, prior)
    ax.text(0, 0.02, text, fontsize=8.0, color=color,
            transform=ax.transAxes, va="bottom")


def _panel_ladder(ax, fig, res):
    """P1: the entry-price ladder as a drawn curve — what buying at each
    price earns under the Base-case fade (FIX-16c arithmetic)."""
    _panel_title(ax, "Entry-price ladder (Base case)",
                 "implied annual return buying at each price · "
                 "vertical line = P₀ · dashed = hurdle (ASSUMPTION)")
    ladder = [(p, r) for p, r in (getattr(res, "irr_ladder", None) or [])
              if r is not None]
    if not ladder:
        _panel_note(ax, "ladder unavailable — needs a Base-case DCF with "
                        "a positive base")
        return
    xs, ys = [p for p, _ in ladder], [r for _, r in ladder]
    ax.set_xlim(min(xs) * 0.98, max(xs) * 1.02)
    lo, hi = min(ys), max(ys)
    span = (hi - lo) or 0.02
    ax.set_ylim(lo - 0.30 * span, hi + 0.35 * span)
    _pct_axis(ax, decimals=1)
    ax.xaxis.set_major_locator(MaxNLocator(nbins=6))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:,.0f}"))
    ax.plot(xs, ys, color=P.SERIES[0], linewidth=1.7,
            solid_capstyle="round", zorder=3)
    ax.axvline(res.price, color=P.INK_SECONDARY, linewidth=1.2, zorder=2)
    if res.implied_return_now is not None:
        ax.plot(res.price, res.implied_return_now, "o", color=P.SERIES[0],
                markersize=6.4, markeredgecolor=P.SURFACE,
                markeredgewidth=1.3, zorder=4)
        _cap_label(ax, res.price, res.implied_return_now,
                   f"P₀ {fmt_pct(res.implied_return_now)}/yr", above=True,
                   fig=fig)
    if res.hurdle_rate is not None:
        ax.axhline(res.hurdle_rate, color=P.INK_MUTED, linewidth=0.8,
                   linestyle=(0, (4, 3)), zorder=2)
        _zone_label(ax, min(xs) * 0.985,
                    res.hurdle_rate + _px_to_y(ax, fig, 2),
                    f"hurdle {fmt_pct(res.hurdle_rate, decimals=0)}")
    if res.hurdle_price is not None:
        _cap_label(ax, res.hurdle_price, res.hurdle_rate or 0.0,
                   f"buys at ≤ ${res.hurdle_price:,.2f}", above=False,
                   fig=fig, size=6.8)


def _panel_thesis(ax, d: DashboardData):
    """P1: thesis + terminal risk verbatim — or the red-lined DRAFT box
    that makes the absence impossible to ignore (principle 6)."""
    import textwrap

    ax.set_axis_off()
    if _is_draft(d):
        ax.add_patch(Rectangle((0.0, 0.04), 1.0, 0.92, transform=ax.transAxes,
                               facecolor=P.SURFACE, edgecolor=P.NEGATIVE,
                               linewidth=1.8, zorder=1))
        missing = [name for name, val in (("thesis", d.thesis),
                                          ("terminal risk", d.terminal_risk))
                   if not val]
        ax.text(0.012, 0.82, "DRAFT — analyst inputs missing: "
                + " and ".join(missing), fontsize=10,
                fontweight="bold", color=P.NEGATIVE,
                transform=ax.transAxes, va="top", zorder=3)
        ax.text(0.012, 0.46,
                "The thesis (§2.4) and terminal risk (§2.3) anchor the "
                "Phase-5 rating. Until both are entered (--thesis / "
                "--terminal-risk or the Valuation screen) every page of "
                "this report carries the DRAFT watermark.",
                fontsize=8.2, color=P.INK_PRIMARY, transform=ax.transAxes,
                va="top", linespacing=1.35, zorder=3)
        y = 0.46 - 0.30
    else:
        y = 0.90
    if d.thesis:
        text = textwrap.fill("Thesis (§2.4): " + d.thesis, width=150)
        ax.text(0.012, y, text, fontsize=8.2, color=P.INK_SECONDARY,
                transform=ax.transAxes, va="top", linespacing=1.35, zorder=3)
        y -= 0.17 * (text.count("\n") + 1) + 0.06
    if d.terminal_risk:
        text = textwrap.fill("Terminal risk (§2.3, anchors the rating): "
                             + d.terminal_risk, width=150)
        ax.text(0.012, y, text, fontsize=8.2, color=P.DELTA_BAD,
                transform=ax.transAxes, va="top", linespacing=1.35, zorder=3)


def _panel_no_verdict(ax, what: str):
    ax.set_axis_off()
    _panel_note(ax, f"{what} unavailable — no valuation attached to this run")


def render_decision(d: DashboardData, res=None, v=None,
                    open_triggers: Optional[Sequence[str]] = None,
                    prior: Optional[dict] = None,
                    out_path: Optional[str] = None,
                    dpi: int = DPI) -> Figure:
    """P1 — everything an IC needs on one page (design R3b)."""
    from .runid import provider_set, run_identity

    fig = _new_page(dpi)
    gs = fig.add_gridspec(
        7, 1, height_ratios=[0.62, 0.72, 1.35, 2.30, 1.75, 1.30, 2.40],
        left=0.055, right=0.965, top=0.975, bottom=0.065, hspace=0.55,
    )
    ax = fig.add_subplot(gs[0])
    _page_header(fig, ax, d, "decision dashboard")

    _panel_base_quality(fig.add_subplot(gs[1]), d)
    _panel_rating(fig.add_subplot(gs[2]), d, v, prior)

    ax_field = fig.add_subplot(gs[3])
    _style_axes(ax_field, y_grid=False)
    if res is not None and any(c.fv_ps is not None for c in res.cases):
        _field_panel(ax_field, fig, res)
    else:
        _panel_no_verdict(ax_field, "Intrinsic value vs price")

    ax_ladder = fig.add_subplot(gs[4])
    _style_axes(ax_ladder)
    if res is not None:
        _panel_ladder(ax_ladder, fig, res)
    else:
        _panel_no_verdict(ax_ladder, "Entry-price ladder")

    _panel_thesis(fig.add_subplot(gs[5]), d)

    ax_trig = fig.add_subplot(gs[6])
    if v is not None:
        _panel_triggers(ax_trig, d, v, open_triggers)
    else:
        ax_trig.set_axis_off()
        _panel_title(ax_trig, "Triggers & rating gate (§5.3 · §5.7)", "")
        entries = list(open_triggers or [])
        if entries:
            y = 0.80
            for t in entries[:14]:
                ax_trig.text(0, y, "•  " + str(t), fontsize=7.6,
                             color=P.INK_SECONDARY,
                             transform=ax_trig.transAxes, va="top")
                y -= 0.065
        else:
            _panel_note(ax_trig, "No open triggers — add via the watchlist "
                                 "or --ledger")

    rid, ihash = run_identity(d, res)
    extra = [f"Run {rid} · inputs {ihash} · providers: {provider_set(d)}",
             "FV_avg = average(Track A, Track B); the coherence gate mirrors "
             "the workbook (Control!B67). Sizing (§5.6) stays with the "
             "analyst."]
    return _finish(fig, d, extra, out_path, dpi)


# ------------------------------------------ P2 — Expectations & Valuation

def _panel_bridge(ax, fig, d: DashboardData, res):
    """The expectations bridge — the report's argument on one horizontal
    growth scale: what the market pays for, what the anchors support, and
    what the cases assume."""
    from .anchors import build_growth_anchors

    _panel_title(ax, "Expectations bridge",
                 "market-implied g (reverse DCF) vs the three anchors vs "
                 "the case g₀ seeds · dashed = GDP cap")
    a = build_growth_anchors(d)
    rows = []  # (y, label) — bottom-up
    marks = []  # (g, text, color, row_y)
    if res is not None and res.implied_g is not None:
        over = res.implied_g > config.GDP_CAP
        marks.append((res.implied_g,
                      f"market implies {fmt_pct(res.implied_g)}",
                      P.NEGATIVE if over else P.INK_PRIMARY, 0.0))
        rows.append((0.0, "Market pays for"))
    anchor_marks = [
        (a.consensus, "consensus"
         + (f" (n={a.n_analysts})" if a.n_analysts else ""), P.SERIES[1]),
        (a.hist_cagr, "5y revenue CAGR", P.SERIES[3]),
        (a.fundamental, "ROIC × reinvestment", P.SERIES[5]),
    ]
    if any(g is not None for g, _, _ in anchor_marks):
        rows.append((1.0, "Anchors (§4)"))
        for g, label, color in anchor_marks:
            if g is not None:
                marks.append((g, f"{label} {fmt_pct(g)}", color, 1.0))
    inputs = getattr(res, "_inputs", None) if res is not None else None
    if inputs is not None:
        seeds = [(name, c.g0) for name, c in inputs.cases.items()
                 if c.g0 is not None]
        if seeds:
            rows.append((2.0, "Case seeds g₀"))
            for name, g0 in seeds:
                marks.append((g0, f"{name} {fmt_pct(g0)}", P.SERIES[0], 2.0))
    if not marks:
        _panel_note(ax, "no growth marks available — needs anchors or a "
                        "computed valuation")
        return
    gs_ = [g for g, _, _, _ in marks] + [config.GDP_CAP, 0.0]
    lo, hi = min(gs_), max(gs_)
    pad = (hi - lo) * 0.18 or 0.01
    ax.set_xlim(lo - pad, hi + pad)
    ax.set_ylim(-0.7, 2.7)
    ax.set_yticks([y for y, _ in rows])
    ax.set_yticklabels([label for _, label in rows], fontsize=8.2)
    ax.grid(axis="x", color=P.GRIDLINE, linewidth=0.8)
    ax.grid(axis="y", visible=False)
    ax.xaxis.set_major_locator(MaxNLocator(nbins=7))
    ax.xaxis.set_major_formatter(
        FuncFormatter(lambda v, _: f"{v * 100:.0f}%"))
    ax.axvline(config.GDP_CAP, color=P.INK_MUTED, linewidth=0.9,
               linestyle=(0, (4, 3)), zorder=2)
    _zone_label(ax, config.GDP_CAP, 2.52,
                f"GDP cap {fmt_pct(config.GDP_CAP)}")
    for k, (g, text, color, row_y) in enumerate(marks):
        ax.plot(g, row_y, "o", color=color, markersize=7.0,
                markeredgecolor=P.SURFACE, markeredgewidth=1.3, zorder=4)
        above = (k % 2 == 0)
        t = ax.text(g, row_y + (0.24 if above else -0.24), text,
                    fontsize=7.4, color=color, ha="center",
                    va="bottom" if above else "top", zorder=5)
        t.set_path_effects(
            [path_effects.withStroke(linewidth=2.2, foreground=P.SURFACE)])


def _panel_exit_check(ax, res, v):
    """P2: the 5y exit cross-check, `trimmed (raw)` — with the mandatory
    a2 divergence note when either frame sits >20% from FV_avg."""
    ax.set_axis_off()
    _panel_title(ax, "5y exit cross-check (companion — never in FV_avg)",
                 "Base-fade EBIT₅ × historical EV/EBIT − bridge, "
                 "discounted at the valuation rate")
    ec = getattr(res, "exit_check", None) if res is not None else None
    if not ec:
        _panel_note(ax, "unavailable — needs reported EBIT and ≥3 years "
                        "of FY-end EV/EBIT")
        return
    mt, mr = ec.get("multiple_trimmed"), ec["multiple"]
    ft, fr = ec.get("fv_today_trimmed"), ec.get("fv_today")
    rt, rr = ec.get("return_5y_trimmed"), ec.get("return_5y")
    def _ps(x):
        return f"\\${x:,.2f}/sh" if x is not None else "n/a"
    line = (f"EV/EBIT {mt:.1f}x trimmed ({mr:.1f}x raw median) ⇒ FV today "
            f"{_ps(ft)} trimmed ({_ps(fr)} raw)"
            if mt is not None else
            f"EV/EBIT {mr:.1f}x raw median ⇒ FV today {_ps(fr)}")
    if rt is not None or rr is not None:
        line += (f" · ≈ {fmt_pct(rt) if rt is not None else 'n/a'}/yr trimmed"
                 f" ({fmt_pct(rr) if rr is not None else 'n/a'} raw) "
                 "buying at P₀ (price-only)")
    ax.text(0, 0.52, line, fontsize=8.4, color=P.INK_PRIMARY,
            transform=ax.transAxes, va="top")
    fv_avg = v.fv_avg if v is not None else None
    if fv_avg:
        worst = None
        for leg in (ft, fr):
            if leg is not None:
                dev = leg / fv_avg - 1.0
                if worst is None or abs(dev) > abs(worst):
                    worst = dev
        if worst is not None and abs(worst) > 0.20:
            ax.text(0, 0.16,
                    f"Divergence: the exit frame sits {worst:+.0%} vs "
                    f"FV_avg — the multiple regime and the DCF disagree; "
                    "reconcile before sizing (a2 mandatory note).",
                    fontsize=8.4, fontweight="bold", color=P.DELTA_BAD,
                    transform=ax.transAxes, va="top")


def render_expectations(d: DashboardData, res=None, v=None,
                        out_path: Optional[str] = None,
                        dpi: int = DPI) -> Figure:
    """P2 — the expectations bridge IS the argument; evidence follows."""
    fig = _new_page(dpi)
    if res is None:
        gs = fig.add_gridspec(2, 1, height_ratios=[0.9, 9.0],
                              left=0.055, right=0.965, top=0.975,
                              bottom=0.065)
        ax = fig.add_subplot(gs[0])
        _page_header(fig, ax, d, "expectations & valuation")
        ax2 = fig.add_subplot(gs[1])
        ax2.set_axis_off()
        _panel_note(ax2, "No valuation attached — the expectations bridge, "
                         "case table, sensitivity and stress need a computed "
                         "valuation.\nRun Intrinsic value (Valuation screen "
                         "or --value).")
        return _finish(fig, d, "", out_path, dpi)
    gs = fig.add_gridspec(
        6, 2, height_ratios=[0.90, 1.95, 1.50, 2.30, 0.85, 1.10],
        left=0.055, right=0.965, top=0.975, bottom=0.065,
        hspace=0.58, wspace=0.16,
    )
    ax = fig.add_subplot(gs[0, :])
    _page_header(fig, ax, d, "expectations & valuation")
    sub = f"{res.method_label} · {res.basis_label}"
    if res.discount_rate is not None:
        sub += (f" · {'WACC' if res.method == 'dcf' else 'r_e'} "
                f"{fmt_pct(res.discount_rate)}")
    ax.text(0, 0.10, sub, fontsize=9, color=P.INK_SECONDARY,
            transform=ax.transAxes, va="top")

    ax_bridge = fig.add_subplot(gs[1, :])
    _style_axes(ax_bridge, y_grid=False)
    _panel_bridge(ax_bridge, fig, d, res)

    _valuation_table(fig.add_subplot(gs[2, :]), res)

    ax_sens = fig.add_subplot(gs[3, 0])
    if v is not None:
        _panel_sensitivity(ax_sens, res, v)
    else:
        ax_sens.set_axis_off()
        _panel_no_verdict(ax_sens, "Sensitivity")
    ax_stress = fig.add_subplot(gs[3, 1])
    _style_axes(ax_stress)
    if v is not None:
        _panel_stress(ax_stress, fig, res, v)
    else:
        _panel_no_verdict(ax_stress, "Stress test")

    _panel_exit_check(fig.add_subplot(gs[4, :]), res, v)

    ax_assume = fig.add_subplot(gs[5, :])
    if v is not None:
        _panel_assumptions(ax_assume, d, res, v)
    else:
        ax_assume.set_axis_off()
        _panel_no_verdict(ax_assume, "Assumptions & bridge")

    extra = []
    if res.rate_build:
        extra.append("Rate build (§4.0): " + res.rate_build)
    if res.implied_g is not None:
        extra.append(
            f"Reverse DCF (§4.D): market EV {fmt_money(res.market_ev)} at "
            f"{fmt_pct(res.discount_rate)} implies g ≈ "
            f"{fmt_pct(res.implied_g)} on the same base — drawn on the "
            "bridge above.")
    extra.append(
        "Equity bridge: net debt + minority interest + preferred − "
        "non-operating investments; MI/preferred from XBRL (0 when "
        "untagged).")
    return _finish(fig, d, extra, out_path, dpi)


# -------------------------------------------- P3 — Business & Segments

def _segment_revenue_lines(d: DashboardData):
    """Revenue lines on the primary axis with their annual (year, value)
    points — the P3 stack's data. [] when no dimensional data."""
    seg = getattr(d, "segments", None)
    if seg is None or not seg.lines:
        return []
    axis = seg.axes()[0]
    out = []
    for ln in seg.lines:
        if ln.axis != axis or ln.group != "Revenue":
            continue
        pts = {e.isoformat()[:4]: v for s, e, v in ln.entries
               if 330 <= (e - s).days <= 400}
        if pts:
            out.append((ln.member, pts, ln))
    return out


def _panel_segment_stack(ax, fig, d: DashboardData):
    seg = d.segments
    axis = seg.axes()[0]
    _panel_title(ax, f"Segment revenue — by {axis}",
                 "stacked as filed (dimensional XBRL) · the report's "
                 "revenue chart")
    lines = _segment_revenue_lines(d)
    if not lines:
        _panel_note(ax, "no annual segment revenue spans parsed")
        return
    years = sorted({y for _, pts, _ in lines for y in pts})[-8:]
    # >6 members: top-5 by latest value + an honest 'All other' sum
    lines = sorted(lines, key=lambda t: -(t[2].latest() or 0.0))
    shown, other = lines[:5], lines[5:]
    series = [(m, [pts.get(y) for y in years]) for m, pts, _ in shown]
    if other:
        series.append((f"All other ({len(other)})",
                       [sum(p.get(y) or 0.0 for _, p, _ in other) or None
                        for y in years]))
    totals = [sum(v or 0.0 for _, vals in series for v in [vals[i]])
              for i in range(len(years))]
    ax.set_xlim(-0.5, len(years) - 0.5)
    ax.set_ylim(0, (max(totals) or 1.0) * 1.22)
    ax.set_xticks(range(len(years)))
    ax.set_xticklabels([f"FY{y}" for y in years])
    _money_axis(ax)
    bottoms = [0.0] * len(years)
    width = 0.62
    for k, (name, vals) in enumerate(series):
        color = P.SERIES[k % len(P.SERIES)]
        for i, val in enumerate(vals):
            if val is None:
                continue
            ax.bar(i, val, width=width, bottom=bottoms[i], color=color,
                   edgecolor=P.SURFACE, linewidth=0.6, zorder=3)
            bottoms[i] += val
    for i, tot in enumerate(totals):
        if tot:
            _cap_label(ax, i, bottoms[i], fmt_money(tot), above=True,
                       fig=fig, size=6.6)
    _legend(ax, [_series_swatch(P.SERIES[k % len(P.SERIES)])
                 for k in range(len(series))], [n for n, _ in series])


def _panel_segment_mix(ax, fig, d: DashboardData):
    _panel_title(ax, "Mix shift", "share of segment-sum revenue per year")
    lines = _segment_revenue_lines(d)
    if not lines:
        _panel_note(ax, "no annual segment revenue spans parsed")
        return
    years = sorted({y for _, pts, _ in lines for y in pts})[-8:]
    totals = {y: sum(pts.get(y) or 0.0 for _, pts, _ in lines)
              for y in years}
    lines = sorted(lines, key=lambda t: -(t[2].latest() or 0.0))[:6]
    ax.set_xlim(-0.5, len(years) - 0.5)
    shares_flat = []
    series = []
    for m, pts, _ in lines:
        shares = [(pts.get(y) / totals[y])
                  if pts.get(y) is not None and totals[y] else None
                  for y in years]
        series.append((m, shares))
        shares_flat += [s for s in shares if s is not None]
    ax.set_ylim(0, (max(shares_flat) if shares_flat else 1.0) * 1.30)
    ax.set_xticks(range(len(years)))
    ax.set_xticklabels([f"FY{y}" for y in years])
    _pct_axis(ax)
    for k, (name, shares) in enumerate(series):
        xs = [i for i, s in enumerate(shares) if s is not None]
        ys = [s for s in shares if s is not None]
        if not xs:
            continue
        color = P.SERIES[k % len(P.SERIES)]
        ax.plot(xs, ys, color=color, linewidth=1.5,
                solid_capstyle="round", zorder=3)
        _cap_label(ax, xs[-1], ys[-1], f"{name} {fmt_pct(ys[-1])}",
                   above=(k % 2 == 0), fig=fig, size=6.4, color=color)


def _panel_segment_econ(ax, fig, d: DashboardData):
    """Per-segment latest YoY growth; direct-contribution margin labeled
    where the filer discloses segment operating income."""
    seg = d.segments
    axis = seg.axes()[0]
    _panel_title(ax, "Per-segment growth (latest FY)",
                 "bar = revenue YoY · label adds direct margin where filed")
    lines = _segment_revenue_lines(d)
    if not lines:
        _panel_note(ax, "no annual segment revenue spans parsed")
        return
    op_by_member = {}
    for ln in seg.lines:
        if ln.axis == axis and ln.group == "Operating income":
            pts = {e.isoformat()[:4]: v for s, e, v in ln.entries
                   if 330 <= (e - s).days <= 400}
            op_by_member[ln.member] = pts
    rows = []
    for m, pts, _ in sorted(lines, key=lambda t: -(t[2].latest() or 0.0))[:6]:
        ys = sorted(pts)
        if len(ys) < 2 or not pts[ys[-2]]:
            continue
        growth = pts[ys[-1]] / pts[ys[-2]] - 1.0
        margin = None
        op = op_by_member.get(m, {}).get(ys[-1])
        if op is not None and pts[ys[-1]]:
            margin = op / pts[ys[-1]]
        rows.append((m, growth, margin))
    if not rows:
        _panel_note(ax, "fewer than two annual spans per member — growth "
                        "not computable")
        return
    ax.set_ylim(-0.6, len(rows) - 0.4)
    vals = [g for _, g, _ in rows]
    lo, hi = min(vals + [0.0]), max(vals + [0.0])
    pad = (hi - lo) * 0.35 or 0.05
    ax.set_xlim(lo - pad, hi + pad * 2.2)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([m for m, _, _ in rows], fontsize=7.8)
    ax.xaxis.set_major_locator(MaxNLocator(nbins=5))
    ax.xaxis.set_major_formatter(
        FuncFormatter(lambda v, _: f"{v * 100:+.0f}%"))
    ax.grid(axis="x", color=P.GRIDLINE, linewidth=0.8)
    ax.grid(axis="y", visible=False)
    ax.axvline(0, color=P.BASELINE, linewidth=0.9, zorder=2)
    for i, (m, g, margin) in enumerate(rows):
        color = P.SERIES[0] if g >= 0 else P.NEGATIVE
        ax.barh(i, g, height=0.52, color=color, zorder=3)
        label = fmt_pct(g, signed=True)
        if margin is not None:
            label += f" · margin {fmt_pct(margin)}"
        ax.text(g + (pad * 0.08 if g >= 0 else -pad * 0.08), i, " " + label,
                fontsize=7.2, color=P.INK_PRIMARY, va="center",
                ha="left" if g >= 0 else "right", zorder=4)


def _panel_segment_status(ax, d: DashboardData):
    """The tie row + recast/break count — full logs live in the Appendix."""
    import textwrap

    ax.set_axis_off()
    seg = d.segments
    _panel_title(ax, "Segment tie & provenance",
                 getattr(seg, "source", "") or "latest filings")
    lines = _segment_revenue_lines(d)
    entries = []
    cons = {e.isoformat()[:4]: v for e, v in
            zip(getattr(getattr(d, "fundamentals", None), "fy_ends", []) or [],
                (getattr(getattr(d, "fundamentals", None), "series", {})
                 or {}).get("revenue", []) or []) if v is not None}
    if lines and cons:
        years = sorted({y for _, pts, _ in lines for y in pts} & set(cons))
        if years:
            y = years[-1]
            sums = sum(pts.get(y) or 0.0 for _, pts, _ in lines)
            gap = sums / cons[y] - 1.0 if cons[y] else None
            if gap is not None:
                ok = abs(gap) <= config.SEGMENT_TIE_TOL
                entries.append((
                    f"Tie FY{y}: Σ segments {_tex(fmt_money(sums))} vs "
                    f"consolidated {_tex(fmt_money(cons[y]))} — gap "
                    f"{fmt_pct(gap, signed=True)} "
                    + ("(within tolerance)" if ok else "(BREACH — check "
                       "eliminations/other)"),
                    P.INK_PRIMARY if ok else P.DELTA_BAD))
    recasts = list(getattr(seg, "recast_log", None) or [])
    breaks = list(getattr(seg, "breaks", None) or [])
    if recasts:
        entries.append((f"{len(recasts)} restated segment value(s) across "
                        "filings — full log in the Appendix", P.DELTA_BAD))
    if breaks:
        entries.append((f"{len(breaks)} membership break(s) — a recast is "
                        "never auto-spliced; full log in the Appendix",
                        P.DELTA_BAD))
    if getattr(seg, "status", ""):
        entries.append((str(seg.status), P.INK_MUTED))
    if not entries:
        entries.append(("segment lines parsed clean — no ties, recasts or "
                        "breaks to report", P.INK_MUTED))
    y = 0.74
    for text, color in entries:
        wrapped = textwrap.fill(text, width=76)
        ax.text(0, y, wrapped, fontsize=7.6, color=color,
                transform=ax.transAxes, va="top", linespacing=1.3)
        y -= 0.115 * (wrapped.count("\n") + 1) + 0.04


def render_business(d: DashboardData, out_path: Optional[str] = None,
                    dpi: int = DPI) -> Figure:
    """P3 — segments (multi-segment filers) + the track's unit economics;
    the ONLY place a revenue chart appears (design R3b)."""
    fig = _new_page(dpi)
    seg = getattr(d, "segments", None)
    multi = seg is not None and seg.n_segments >= 2
    panel_fns = list(_UNIT_PANELS.get(d.track, _UNIT_PANELS["standard"]))
    if multi:
        # the segment band replaces the note panel; dedupe accordingly
        panel_fns = [f for f in panel_fns if f is not _panel_segment_note]
        while len(panel_fns) < 4:
            pad = next(f for f in (_panel_rev_yoy, _panel_ccc,
                                   _panel_wc_cycle, _panel_roic)
                       if f not in panel_fns)
            panel_fns.append(pad)
        gs = fig.add_gridspec(
            5, 2, height_ratios=[1.05, 1.95, 1.95, 1.95, 1.95],
            left=0.055, right=0.965, top=0.975, bottom=0.065,
            hspace=0.55, wspace=0.16,
        )
        band = [(_panel_segment_stack, gs[1, 0]),
                (_panel_segment_mix, gs[1, 1]),
                (_panel_segment_econ, gs[2, 0]),
                (_panel_segment_status, gs[2, 1])]
        unit_slots = (gs[3, 0], gs[3, 1], gs[4, 0], gs[4, 1])
    else:
        gs = fig.add_gridspec(
            4, 2, height_ratios=[1.05, 1.95, 1.95, 1.95],
            left=0.055, right=0.965, top=0.975, bottom=0.065,
            hspace=0.55, wspace=0.16,
        )
        band = [(_panel_revenue, gs[1, 0]), (_panel_rev_yoy, gs[1, 1])]
        panel_fns = [f for f in panel_fns
                     if f not in (_panel_rev_yoy, _panel_segment_note)]
        while len(panel_fns) < 4:
            pad = next(f for f in (_panel_marginal_unit, _panel_ccc,
                                   _panel_wc_cycle, _panel_roic, _panel_roe)
                       if f not in panel_fns)
            panel_fns.append(pad)
        unit_slots = (gs[2, 0], gs[2, 1], gs[3, 0], gs[3, 1])

    ax = fig.add_subplot(gs[0, :])
    _page_header(fig, ax, d, "business & segments")
    _unit_kpis(ax, d)

    seg_fns = (_panel_segment_stack, _panel_segment_mix, _panel_segment_econ)
    for fn, spec in band:
        ax_p = fig.add_subplot(spec)
        if fn is _panel_segment_status:
            fn(ax_p, d)
            continue
        _style_axes(ax_p)
        if not d.fy_labels and fn not in seg_fns:
            _panel_note(ax_p, "No annual fundamentals available")
            continue
        fn(ax_p, fig, d)
    for fn, spec in zip(panel_fns, unit_slots):
        ax_p = fig.add_subplot(spec)
        _style_axes(ax_p)
        if not d.fy_labels:
            _panel_note(ax_p, "No annual fundamentals available")
            continue
        fn(ax_p, fig, d)

    return _finish(
        fig, d,
        "Working-capital days on average balances (§2.2). Segment history "
        "depth = as reported in the fetched filings; recast boundaries are "
        "never auto-spliced (Appendix carries the full logs).",
        out_path, dpi)


# ------------------------------------------- P4 — Quality & Forensics

def render_quality(d: DashboardData, out_path: Optional[str] = None,
                   dpi: int = DPI) -> Figure:
    """P4 — the forensic scorecard; each chart exactly once."""
    fig = _new_page(dpi)
    gs = fig.add_gridspec(
        5, 2, height_ratios=[1.15, 1.9, 1.9, 1.9, 1.9],
        left=0.055, right=0.965, top=0.975, bottom=0.065,
        hspace=0.55, wspace=0.16,
    )
    ax = fig.add_subplot(gs[0, :])
    _page_header(fig, ax, d, "quality & forensics")
    _health_kpis(ax, d)

    slot_a = _panel_solvency if d.is_financial_sector else _panel_altman
    slot_b = _panel_credit_reserves if d.track == "bank" else _panel_rnd_audit
    panels = [
        (_panel_sloan, gs[1, 0]), (_panel_piotroski, gs[1, 1]),
        (_panel_accruals, gs[2, 0]), (slot_a, gs[2, 1]),
        (_panel_sbc, gs[3, 0]), (slot_b, gs[3, 1]),
        (_panel_fcf_ex_sbc, gs[4, 0]), (_panel_earnings_quality, gs[4, 1]),
    ]
    for fn, spec in panels:
        ax_p = fig.add_subplot(spec)
        _style_axes(ax_p)
        if not d.fy_labels:
            _panel_note(ax_p, "No annual fundamentals available")
            continue
        fn(ax_p, fig, d)

    return _finish(
        fig, d,
        ["Accruals ratio = (net income − CFO) / average total assets; "
         "sustained readings above +10% flag earnings running ahead of "
         "cash. Adjustment Burden (§3.1) needs non-GAAP figures from the "
         "earnings release — analyst input.",
         "The full warnings register (untruncated) is in the Appendix."],
        out_path, dpi)


# --------------------------------------- P5 — Capital & Balance Sheet

def _panel_buybacks_sbc(ax, fig, d: DashboardData):
    """Gross buybacks vs SBC per FY — the net shareholder return on comp."""
    from .anchors import _series

    _panel_title(ax, "Buybacks vs SBC",
                 "gross repurchases vs stock comp — how much of the "
                 "buyback just mops up issuance")
    bb = _series(d, "buybacks")
    n = len(d.fy_labels)
    bb = ([None] * (n - len(bb)) + list(bb))[-n:] if bb else [None] * n
    sbc = list(d.sbc or [None] * n)
    keep = [(s, name, color) for s, name, color in
            ((bb, "Buybacks (gross)", P.SERIES[0]),
             (sbc, "SBC", P.SERIES[1]))
            if any(v is not None for v in s)]
    flat = [abs(v) for s, _, _ in keep for v in s if v is not None]
    if not flat:
        _panel_note(ax, "Buybacks / SBC not reported in XBRL")
        return
    absd = [[abs(v) if v is not None else None for v in s]
            for s, _, _ in keep]
    _category_panel_setup(ax, fig, d.fy_labels, flat)
    _money_axis(ax)
    _draw_bar_series(ax, fig, absd, [c for _, _, c in keep])
    _legend(ax, [_series_swatch(c) for _, _, c in keep],
            [nm for _, nm, _ in keep])
    b_last = next((v for v in reversed(bb) if v is not None), None)
    s_last = next((v for v in reversed(sbc) if v is not None), None)
    if b_last is not None and s_last is not None and s_last:
        ax.set_title(f"latest: buybacks cover {abs(b_last) / s_last:,.1f}x "
                     "the SBC issued", loc="right", fontsize=7.0,
                     color=P.INK_MUTED, pad=2)


def _panel_capex_intensity(ax, fig, d: DashboardData):
    """Capex/revenue vs its 5y median — the FIX-14b peak/trough flag
    drawn, not just noted."""
    from .anchors import CAPEX_DEVIATION, capex_intensity, _series, _at

    _panel_title(ax, "Capex intensity",
                 "capex / revenue · dashed = 5y median · flag when the "
                 f"latest sits ±{CAPEX_DEVIATION:.0%} off it (FIX-14b)")
    capex_s, rev_s = _series(d, "capex"), _series(d, "revenue")
    n = len(d.fy_labels)
    vals = []
    for i in range(-n, 0):
        c, r = _at(capex_s, i), _at(rev_s, i)
        vals.append(c / r if c is not None and r else None)
    pts = [v for v in vals if v is not None]
    if not pts:
        _panel_note(ax, "Capex / revenue not reported in XBRL")
        return
    pair = capex_intensity(d)
    _lines_panel_setup(ax, pts + ([pair[0]] if pair else []),
                       n, d.fy_labels)
    _pct_axis(ax, decimals=1)
    xs = [i for i, v in enumerate(vals) if v is not None]
    ys = [v for v in vals if v is not None]
    ax.plot(xs, ys, color=P.SERIES[0], linewidth=1.6,
            solid_capstyle="round", zorder=3)
    _cap_label(ax, xs[-1], ys[-1], fmt_pct(ys[-1]), above=True, fig=fig)
    if pair:
        med, latest = pair
        ax.axhline(med, color=P.INK_MUTED, linewidth=0.8,
                   linestyle=(0, (4, 3)), zorder=2)
        _zone_label(ax, -0.48, med + _px_to_y(ax, fig, 2),
                    f"5y median {fmt_pct(med)}")
        if med and abs(latest / med - 1.0) > CAPEX_DEVIATION:
            ax.plot(xs[-1], ys[-1], "o", color=P.NEGATIVE, markersize=7.4,
                    markeredgecolor=P.SURFACE, markeredgewidth=1.3,
                    zorder=5)
            _cap_label(ax, xs[-1], ys[-1],
                       f"peak/trough year ({latest / med - 1.0:+.0%} vs "
                       "median) — normalize the base", above=False,
                       fig=fig, size=6.8, color=P.NEGATIVE)


def render_capital(d: DashboardData, out_path: Optional[str] = None,
                   dpi: int = DPI) -> Figure:
    """P5 — what management does with the cash."""
    fig = _new_page(dpi)
    gs = fig.add_gridspec(
        3, 2, height_ratios=[1.05, 2.35, 2.35],
        left=0.055, right=0.965, top=0.975, bottom=0.065,
        hspace=0.55, wspace=0.16,
    )
    ax = fig.add_subplot(gs[0, :])
    _page_header(fig, ax, d, "capital & balance sheet")
    tiles = []
    if d.share_change is not None:
        direction = "buyback" if d.share_change < 0 else "dilution"
        tiles.append(("Share count", fmt_pct(d.share_change, signed=True),
                      f"{direction} over the window", d.share_change <= 0))
    if d.owners_yield is not None:
        tiles.append(("Owner's yield", fmt_pct(d.owners_yield),
                      "divs + gross buybacks / mcap", True))
    net_debt = None
    debt_now = _latest(d.total_debt)
    cash_now = _latest(d.cash)
    if debt_now is not None and cash_now is not None:
        net_debt = debt_now - cash_now
        tiles.append(("Net debt", fmt_money(net_debt), "debt − cash",
                      net_debt <= 0))
    _draw_kpi_row(ax, tiles)

    panels = [
        (_panel_shares, gs[1, 0]), (_panel_buybacks_sbc, gs[1, 1]),
        (_panel_debt_cash, gs[2, 0]), (_panel_capex_intensity, gs[2, 1]),
    ]
    for fn, spec in panels:
        ax_p = fig.add_subplot(spec)
        _style_axes(ax_p)
        if not d.fy_labels:
            _panel_note(ax_p, "No annual fundamentals available")
            continue
        fn(ax_p, fig, d)

    f = getattr(d, "fundamentals", None)
    maturity = ""
    if f is not None:
        cur = next((v for v in reversed(f.series.get("lt_debt_current")
                                        or []) if v is not None), None)
        noncur = next((v for v in reversed(f.series.get("lt_debt_noncurrent")
                                           or []) if v is not None), None)
        if cur is not None and noncur is not None:
            maturity = (f"Maturity posture: LT debt current "
                        f"{_tex(fmt_money(cur))} vs noncurrent "
                        f"{_tex(fmt_money(noncur))} at the latest FY end.")
    return _finish(
        fig, d,
        [ln for ln in
         (maturity,
          "Buybacks are gross repurchases as filed (issuance NOT netted); "
          "the dilution panel carries the net share-count path.") if ln],
        out_path, dpi)


# ------------------------------------------------------ P6 — Appendix

_APX_LINES_PER_PAGE = 96
_APX_WRAP = 148


def _appendix_sections(d: DashboardData, res=None, v=None):
    """(title, [(text, color, bold)]) — FULL content, never truncated."""
    from .reconcile import fmt_val

    sections = []

    rep = getattr(d, "audit_report", None)
    rows = []
    if rep is None:
        rows.append(("provider recheck off — no FMP/Finnhub keys "
                     "configured for this run", P.INK_MUTED, False))
    else:
        rows.append((rep.summary(), P.INK_PRIMARY, True))
        if rep.entries:
            rows.append((f"{'Item':<22}{'FY':<8}{'EDGAR':>14}"
                         f"{'Provider':>14}   {'Source':<10}Status",
                         P.INK_SECONDARY, True))
            status = {"divergent": "DIVERGENT",
                      "restated": "RESTATED (EDGAR carries the recast; "
                                  "provider carries the original)",
                      "rescuable": "RESCUABLE (EDGAR empty)"}
            for e in rep.entries:
                rows.append((
                    f"{e.item:<22}{e.fy:<8}{fmt_val(e.ours, e.unit):>14}"
                    f"{fmt_val(e.theirs, e.unit):>14}   {e.source:<10}"
                    + status.get(e.kind, e.kind),
                    P.DELTA_BAD if e.kind == "divergent" else P.INK_MUTED,
                    False))
        else:
            rows.append(("every compared item-year matches within "
                         "tolerance", P.INK_MUTED, False))
    sections.append(("Data audit — EDGAR vs providers (match / restated / "
                     "divergent / rescuable)", rows))

    rows = []
    tags = getattr(d, "tags_used", None) or {}
    if tags:
        for concept in sorted(tags):
            rows.append((f"{concept}: {tags[concept]}", P.INK_MUTED, False))
    else:
        rows.append(("no tag audit available", P.INK_MUTED, False))
    sections.append(("XBRL tag map — concept: winning tag (coverage; "
                     "gap fills; amendments)", rows))

    rows = []
    f = getattr(d, "fundamentals", None)
    for note in (getattr(f, "selection_notes", None) or []):
        rows.append((str(note), P.INK_MUTED, False))
    if getattr(d, "statements_note", ""):
        rows.append((f"Statements: {d.statements_note}", P.INK_MUTED, False))
    if getattr(d, "price_error", ""):
        rows.append((f"Prices: {d.price_error}", P.DELTA_BAD, False))
    if not rows:
        rows.append(("no substitutions or rescues this run", P.INK_MUTED,
                     False))
    sections.append(("Gap-rescue & selection log", rows))

    rows = []
    seg = getattr(d, "segments", None)
    if seg is None or not seg.lines:
        rows.append(("no dimensional segment data parsed", P.INK_MUTED,
                     False))
    else:
        rows.append((f"source: {seg.source}", P.INK_MUTED, False))
        if seg.status:
            rows.append((f"status: {seg.status}", P.INK_MUTED, False))
        for label, count in (seg.coverage or []):
            rows.append((f"coverage: {label} — {count} facts", P.INK_MUTED,
                         False))
        for r in (seg.recast_log or []):
            rows.append((f"recast: {r}", P.DELTA_BAD, False))
        for b in (seg.breaks or []):
            rows.append((f"break: {b}", P.DELTA_BAD, False))
    sections.append(("Segments — status as diagnosed", rows))

    rows = []
    for note in (d.health_notes or []):
        rows.append((str(note), P.INK_PRIMARY, False))
    if res is not None:
        for w in res.warnings:
            rows.append((f"valuation: {w}", P.DELTA_BAD, False))
        for c in res.cases:
            for w in c.warnings:
                rows.append((f"{c.name}: {w}", P.DELTA_BAD, False))
    if v is not None:
        for note in v.notes:
            rows.append((f"verdict: {note}", P.INK_MUTED, False))
    if not rows:
        rows.append(("no warnings this run", P.INK_MUTED, False))
    sections.append(("Warnings register", rows))
    return sections


def render_appendix(d: DashboardData, res=None, v=None,
                    dpi: int = DPI) -> List[Figure]:
    """P6 — formatted tables, untruncated by construction: content flows
    onto as many appendix pages as it needs (principle 5)."""
    import textwrap

    flow = []  # (text, color, bold, is_heading)
    for title, rows in _appendix_sections(d, res, v):
        flow.append((title, P.INK_PRIMARY, True, True))
        for text, color, bold in rows:
            wrapped = textwrap.wrap(str(text), width=_APX_WRAP) or [""]
            for j, line in enumerate(wrapped):
                flow.append((("   " if j else "") + line, color, bold,
                             False))
        flow.append(("", P.INK_MUTED, False, False))

    pages, page = [], []
    for entry in flow:
        if len(page) >= _APX_LINES_PER_PAGE:
            pages.append(page)
            page = []
        page.append(entry)
    if page:
        pages.append(page)

    figs = []
    for pno, page in enumerate(pages, start=1):
        fig = _new_page(dpi)
        gs = fig.add_gridspec(2, 1, height_ratios=[0.62, 9.38],
                              left=0.055, right=0.965, top=0.975,
                              bottom=0.055, hspace=0.04)
        ax = fig.add_subplot(gs[0])
        suffix = f" ({pno}/{len(pages)})" if len(pages) > 1 else ""
        _page_header(fig, ax, d, f"appendix{suffix}")
        body = fig.add_subplot(gs[1])
        body.set_axis_off()
        step = 1.0 / _APX_LINES_PER_PAGE
        y = 1.0
        mono = ["DejaVu Sans Mono", "monospace"]  # ships with matplotlib
        for text, color, bold, is_heading in page:
            if is_heading:
                body.text(0, y, text, fontsize=8.6, fontweight="bold",
                          color=color, transform=body.transAxes, va="top")
            elif text:
                body.text(0, y, _tex(text), fontsize=6.9, color=color,
                          fontweight="bold" if bold else "normal",
                          fontfamily=mono, transform=body.transAxes,
                          va="top")
            y -= step
        _finish(fig, d, "Appendix content is complete by construction — "
                        "nothing on the previous pages was truncated into "
                        "it.", None, dpi)
        figs.append(fig)
    return figs


# ------------------------------------------------------------- assembly

def render_report(d: DashboardData, res=None, v=None,
                  open_triggers: Optional[Sequence[str]] = None,
                  prior: Optional[dict] = None,
                  dpi: int = DPI) -> List[Figure]:
    """The six-section report (P1..P6) as a list of A4-portrait figures —
    the single assembly every caller uses (design R3b)."""
    figs = [
        render_decision(d, res, v, open_triggers, prior, dpi=dpi),
        render_expectations(d, res, v, dpi=dpi),
        render_business(d, dpi=dpi),
        render_quality(d, dpi=dpi),
        render_capital(d, dpi=dpi),
    ]
    figs += render_appendix(d, res, v, dpi=dpi)
    return figs

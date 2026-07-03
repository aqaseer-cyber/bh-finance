"""Side-by-side ticker comparison — interactive HTML.

Color follows the entity: each ticker takes its palette slot in the order
entered and keeps it on every chart (the dataviz recolor-on-filter rule).
Different-scale series are indexed to a common base (=100), never dual-axed.
"""
from __future__ import annotations

import html as _html
from typing import Dict, List, Optional

from . import palette as P
from .metrics import DashboardData, fmt_money, fmt_pct

MAX_TICKERS = 4  # color-alone comfort ends at ~4 series (dataviz ladder)


def _color(i: int) -> str:
    return P.SERIES[i % len(P.SERIES)]


def _indexed(vals: List[Optional[float]]) -> List[Optional[float]]:
    base = next((v for v in vals if v is not None and v > 0), None)
    if base is None:
        return [None] * len(vals)
    return [v / base * 100 if v is not None else None for v in vals]


def _latest(seq):
    for v in reversed(seq or []):
        if v is not None:
            return v
    return None


def build_compare_html(datas: List[DashboardData], path: str,
                       ledger_rows: Optional[Dict[str, dict]] = None) -> str:
    import plotly.graph_objects as go

    datas = datas[:MAX_TICKERS]
    ledger_rows = ledger_rows or {}

    layout = dict(
        template="plotly_white",
        font=dict(family="Segoe UI, system-ui, sans-serif", size=12,
                  color=P.INK_PRIMARY),
        paper_bgcolor=P.SURFACE, plot_bgcolor=P.SURFACE,
        margin=dict(l=60, r=30, t=48, b=40), hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )

    def fig(title, height=380):
        f = go.Figure()
        f.update_layout(title=dict(text=title, font=dict(size=15)),
                        height=height, **layout)
        f.update_yaxes(gridcolor=P.GRIDLINE)
        f.update_xaxes(gridcolor=P.GRIDLINE)
        return f

    figs = []

    # 1) price, indexed to 100 at each ticker's first close in the window
    f = fig("Price — indexed to 100 (common-base, one axis)", 420)
    for i, d in enumerate(datas):
        if not d.price_dates:
            continue
        base = d.price_closes[0]
        f.add_trace(go.Scatter(
            x=d.price_dates, y=[c / base * 100 for c in d.price_closes],
            name=d.ticker, line=dict(color=_color(i), width=2),
            hovertemplate="%{y:.0f}<extra>" + d.ticker + "</extra>"))
    figs.append(f)

    # 2) revenue indexed; 3) net margin; 4) ROIC; 5) FCF margin
    def per_fy(title, getter, tickformat=".0%", indexed=False):
        f = fig(title)
        for i, d in enumerate(datas):
            vals = getter(d)
            if indexed:
                vals = _indexed(vals)
            if not any(v is not None for v in vals):
                continue
            f.add_trace(go.Scatter(
                x=d.fy_labels, y=vals, name=d.ticker, mode="lines+markers",
                line=dict(color=_color(i), width=2),
                marker=dict(size=7, line=dict(color=P.SURFACE, width=1.5)),
                hovertemplate=("%{y:.0f}" if indexed else "%{y:.1%}")
                + "<extra>" + d.ticker + "</extra>"))
        f.update_yaxes(tickformat=None if indexed else tickformat)
        return f

    figs.append(per_fy("Revenue — indexed to 100 at each first year",
                       lambda d: d.revenue, indexed=True))
    figs.append(per_fy("Net margin", lambda d: d.net_margin))
    figs.append(per_fy("ROIC — NOPAT / avg invested capital", lambda d: d.roic))
    figs.append(per_fy(
        "FCF margin — free cash flow / revenue",
        lambda d: [(fc / r if fc is not None and r else None)
                   for fc, r in zip(d.fcf, d.revenue)]))

    # ------------------------------------------------------------- KPI table
    def row(label, fn):
        cells = "".join(f"<td>{fn(d)}</td>" for d in datas)
        return f"<tr><th>{label}</th>{cells}</tr>"

    def led(d, key, fmt):
        rec = ledger_rows.get(d.ticker)
        return fmt(rec[key]) if rec and rec.get(key) is not None else "–"

    header = "".join(
        f"<th><span style='color:{_color(i)}'>●</span> {_html.escape(d.ticker)}</th>"
        for i, d in enumerate(datas))
    table = f"""
<table><tr><th>Metric</th>{header}</tr>
{row("Company", lambda d: _html.escape(d.company[:38]))}
{row("Track", lambda d: d.track.title())}
{row(f"Revenue (latest FY)", lambda d: fmt_money(_latest(d.revenue)))}
{row("Revenue CAGR (window)", lambda d: fmt_pct(d.revenue_cagr, signed=True)
     if d.revenue_cagr is not None else "–")}
{row("Net margin", lambda d: fmt_pct(_latest(d.net_margin))
     if _latest(d.net_margin) is not None else "–")}
{row("ROIC", lambda d: fmt_pct(_latest(d.roic))
     if _latest(d.roic) is not None else "–")}
{row("Cash conversion cycle", lambda d: f"{_latest(d.ccc):.0f}d"
     if _latest(d.ccc) is not None else "–")}
{row("SBC / revenue", lambda d: fmt_pct(_latest(d.sbc_pct_revenue))
     if _latest(d.sbc_pct_revenue) is not None else "–")}
{row("Piotroski F", lambda d: _latest(d.piotroski_score) if
     _latest(d.piotroski_score) is not None else "–")}
{row("Altman Z", lambda d: f"{_latest(d.altman_z):.2f}"
     if _latest(d.altman_z) is not None else "–")}
{row("Sloan ratio", lambda d: fmt_pct(_latest(d.sloan_full), signed=True)
     if _latest(d.sloan_full) is not None else "–")}
{row("Ledger rating", lambda d: led(d, "rating", str) or "–")}
{row("Ledger FV_avg", lambda d: led(d, "fv_avg", lambda v: f"${v:,.2f}"))}
{row("Ledger MoS", lambda d: led(d, "mos", lambda v: f"{v * 100:+.1f}%"))}
</table>"""

    names = " vs ".join(d.ticker for d in datas)
    parts = [f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Compare — {_html.escape(names)}</title>
<style>
 body{{font-family:'Segoe UI',system-ui,sans-serif;background:{P.PAGE};
      color:{P.INK_PRIMARY};margin:0;padding:24px 32px}}
 h1{{font-size:22px;margin:0 0 4px}} .sub{{color:{P.INK_SECONDARY};font-size:13px}}
 .chart{{background:{P.SURFACE};border:1px solid {P.GRIDLINE};border-radius:8px;
        margin:14px 0;padding:6px}}
 table{{border-collapse:collapse;background:{P.SURFACE};border:1px solid {P.GRIDLINE};
        border-radius:8px;font-size:13px;margin:14px 0}}
 th,td{{padding:6px 14px;text-align:left;border-bottom:1px solid {P.GRIDLINE}}}
 tr th:first-child{{color:{P.INK_SECONDARY};font-weight:400}}
 .note{{color:{P.INK_MUTED};font-size:11.5px;margin-top:18px}}
</style></head><body>
<h1>Side-by-side — {_html.escape(names)}</h1>
<div class="sub">Colors are fixed per ticker across every chart (color follows
 the entity). Generated {datas[0].generated.isoformat()} ·
 {datas[0].display_years}-year window.</div>"""]
    parts.append(table)
    for i, f in enumerate(figs):
        parts.append("<div class='chart'>"
                     + f.to_html(full_html=False, include_plotlyjs=(i == 0),
                                 config={"displaylogo": False})
                     + "</div>")
    parts.append("<div class='note'>Sources: SEC EDGAR XBRL, Stooq/Yahoo. "
                 "Ledger rows come from your local verdict ledger (§5.7). "
                 "Not investment advice.</div></body></html>")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("".join(parts))
    return path

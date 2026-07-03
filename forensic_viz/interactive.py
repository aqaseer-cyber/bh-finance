"""Interactive HTML report — plotly, self-contained single file.

Hover tooltips, zoom/pan, and legend series-toggling on every chart; the file
embeds plotly.js so it opens offline in any browser. The matplotlib pages
remain the print/PDF (A4) rendition; this is the on-screen rendition.
"""
from __future__ import annotations

import html as _html
from typing import List, Optional

from . import palette as P
from .metrics import DashboardData, fmt_money, fmt_pct

_LAYOUT = dict(
    template="plotly_white",
    font=dict(family="Segoe UI, system-ui, sans-serif", size=12,
              color=P.INK_PRIMARY),
    paper_bgcolor=P.SURFACE, plot_bgcolor=P.SURFACE,
    margin=dict(l=60, r=30, t=48, b=40),
    hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    colorway=P.SERIES,
)


def _fig(title: str, height: int = 380):
    import plotly.graph_objects as go
    f = go.Figure()
    f.update_layout(title=dict(text=title, font=dict(size=15)), height=height,
                    **_LAYOUT)
    f.update_yaxes(gridcolor=P.GRIDLINE, zerolinecolor=P.BASELINE)
    f.update_xaxes(gridcolor=P.GRIDLINE)
    return f


def _bars(f, x, series, names):
    import plotly.graph_objects as go
    for vals, name in zip(series, names):
        f.add_trace(go.Bar(x=x, y=vals, name=name))


def _lines(f, x, series, names, pct=True):
    import plotly.graph_objects as go
    for vals, name in zip(series, names):
        f.add_trace(go.Scatter(
            x=x, y=vals, name=name, mode="lines+markers",
            line=dict(width=2), marker=dict(size=7,
                                            line=dict(color=P.SURFACE, width=1.5)),
            hovertemplate="%{y:.1%}<extra>" + name + "</extra>" if pct
            else "%{y:,.2f}<extra>" + name + "</extra>"))


def _kpi_row(pairs) -> str:
    cells = "".join(
        f"<div class='kpi'><div class='kpi-label'>{_html.escape(label)}</div>"
        f"<div class='kpi-value'>{_html.escape(value)}</div>"
        f"<div class='kpi-delta' style='color:{color}'>{_html.escape(delta)}</div></div>"
        for label, value, delta, color in pairs)
    return f"<div class='kpi-row'>{cells}</div>"


def build_html(d: DashboardData, path: str, res=None, verdict=None) -> str:
    """Write the interactive report; returns the path."""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    figs: List = []
    fy = d.fy_labels

    if d.price_dates:  # price + drawdown, shared zoom
        f = make_subplots(rows=2, cols=1, shared_xaxes=True,
                          row_heights=[0.7, 0.3], vertical_spacing=0.06)
        f.add_trace(go.Scatter(x=d.price_dates, y=d.price_closes,
                               name="Close", line=dict(color=P.SERIES[0], width=2),
                               fill="tozeroy",
                               fillcolor="rgba(42,120,214,0.08)"), row=1, col=1)
        f.add_trace(go.Scatter(x=d.price_dates, y=d.drawdown, name="Drawdown",
                               line=dict(color=P.SERIES[5], width=1.6),
                               fill="tozeroy", fillcolor="rgba(227,73,72,0.08)",
                               hovertemplate="%{y:.1%}<extra>Drawdown</extra>"),
                    row=2, col=1)
        f.update_layout(title=dict(
            text=f"Price & drawdown — split-adjusted daily close ({d.price_source})",
            font=dict(size=15)), height=520, **_LAYOUT)
        f.update_yaxes(tickformat="$,.0f", row=1, col=1, gridcolor=P.GRIDLINE)
        f.update_yaxes(tickformat=".0%", row=2, col=1, gridcolor=P.GRIDLINE)
        figs.append(f)

    if fy:
        f = make_subplots(rows=2, cols=1, shared_xaxes=True,
                          row_heights=[0.65, 0.35], vertical_spacing=0.08)
        f.add_trace(go.Bar(x=fy, y=d.revenue, name="Revenue",
                           marker_color=P.SERIES[0],
                           hovertemplate="%{y:$,.3s}<extra>Revenue</extra>"),
                    row=1, col=1)
        f.add_trace(go.Scatter(x=fy, y=d.revenue_yoy, name="YoY growth",
                               mode="lines+markers",
                               line=dict(color=P.SERIES[1], width=2),
                               hovertemplate="%{y:.1%}<extra>YoY</extra>"),
                    row=2, col=1)
        f.update_layout(title=dict(text="Revenue & growth", font=dict(size=15)),
                        height=460, **_LAYOUT)
        f.update_yaxes(tickformat="$,.3s", row=1, col=1, gridcolor=P.GRIDLINE)
        f.update_yaxes(tickformat=".0%", row=2, col=1, gridcolor=P.GRIDLINE)
        figs.append(f)

        f = _fig("Margins — gross / operating / net")
        _lines(f, fy, [d.gross_margin, d.operating_margin, d.net_margin],
               ["Gross", "Operating", "Net"])
        f.update_yaxes(tickformat=".0%")
        figs.append(f)

        f = _fig("Earnings quality — net income vs cash flows")
        _bars(f, fy, [d.net_income, d.cfo, d.fcf],
              ["Net income", "Op. cash flow", "Free cash flow"])
        f.update_layout(barmode="group", yaxis=dict(tickformat="$,.3s"))
        figs.append(f)

        f = _fig("Operating accruals & Sloan ratio (flag > |10%|)")
        f.add_trace(go.Bar(x=fy, y=d.accruals_ratio, name="(NI−CFO)/avg assets",
                           marker_color=[P.SERIES[5] if v and v > 0.10 else P.SERIES[0]
                                         for v in d.accruals_ratio],
                           hovertemplate="%{y:.1%}<extra>Operating accruals</extra>"))
        f.add_trace(go.Scatter(x=fy, y=d.sloan_full, name="Sloan (NI−CFO−CFI)/avg TA",
                               mode="lines+markers", line=dict(color=P.SERIES[4], width=2),
                               hovertemplate="%{y:.1%}<extra>Sloan</extra>"))
        f.add_hline(y=0.10, line_dash="dash", line_color=P.INK_MUTED,
                    annotation_text="+10% flag")
        f.update_yaxes(tickformat=".0%")
        figs.append(f)

        if d.track in ("bank", "insurance"):
            f = _fig("Solvency & track metrics")
            if any(v is not None for v in d.cet1_ratio):
                _lines(f, fy, [d.cet1_ratio, d.tier1_ratio, d.leverage_ratio],
                       ["CET1", "Tier 1", "Leverage"])
            else:
                _lines(f, fy, [d.equity_to_assets], ["Equity/assets"])
            if any(v is not None for v in d.nim_proxy):
                _lines(f, fy, [d.nim_proxy], ["NIM (proxy)"])
            if any(v is not None for v in d.loss_ratio):
                _lines(f, fy, [d.loss_ratio, d.combined_ratio],
                       ["Loss ratio", "Combined ratio"])
            f.update_yaxes(tickformat=".1%")
            figs.append(f)
        else:
            f = _fig("Unit economics — working-capital days")
            _lines(f, fy, [d.dsi, d.dso, d.dpo, d.ccc],
                   ["DSI", "DSO", "DPO", "CCC"], pct=False)
            f.update_yaxes(ticksuffix="d")
            figs.append(f)

            f = _fig("Returns — ROIC / ROE vs WACC")
            _lines(f, fy, [d.roic, d.roe], ["ROIC", "ROE"])
            build = getattr(d, "wacc_build", None)
            if build is not None and build.wacc:
                f.add_hline(y=build.wacc, line_dash="dash", line_color=P.INK_MUTED,
                            annotation_text=f"WACC {fmt_pct(build.wacc)}")
            f.update_yaxes(tickformat=".0%")
            figs.append(f)

        f = _fig("Health scorecard — Piotroski F / Altman Z")
        f.add_trace(go.Bar(x=fy, y=d.piotroski_score, name="Piotroski F (0–9)",
                           marker_color=P.SERIES[0]))
        if any(z is not None for z in d.altman_z):
            f.add_trace(go.Scatter(x=fy, y=d.altman_z, name="Altman Z",
                                   mode="lines+markers",
                                   line=dict(color=P.SERIES[2], width=2)))
        figs.append(f)

        f = make_subplots(rows=2, cols=1, shared_xaxes=True,
                          row_heights=[0.4, 0.6], vertical_spacing=0.08)
        f.add_trace(go.Scatter(x=fy, y=d.diluted_shares, name="Diluted shares",
                               mode="lines+markers",
                               line=dict(color=P.SERIES[0], width=2),
                               hovertemplate="%{y:,.3s}<extra>Diluted shares</extra>"),
                    row=1, col=1)
        f.add_trace(go.Bar(x=fy, y=d.total_debt, name="Total debt",
                           marker_color=P.SERIES[0],
                           hovertemplate="%{y:$,.3s}<extra>Total debt</extra>"),
                    row=2, col=1)
        f.add_trace(go.Bar(x=fy, y=d.cash, name="Cash",
                           marker_color=P.SERIES[1],
                           hovertemplate="%{y:$,.3s}<extra>Cash</extra>"),
                    row=2, col=1)
        f.update_layout(title=dict(text="Dilution & balance sheet",
                                   font=dict(size=15)),
                        height=480, barmode="group", **_LAYOUT)
        f.update_yaxes(tickformat=",.3s", row=1, col=1, gridcolor=P.GRIDLINE)
        f.update_yaxes(tickformat="$,.3s", row=2, col=1, gridcolor=P.GRIDLINE)
        figs.append(f)

    if res is not None:
        f = _fig("Intrinsic value vs price — Bear / Base / Bull", height=340)
        names = [c.name for c in res.cases]
        fvs = [c.fv_ps for c in res.cases]
        f.add_trace(go.Bar(
            y=names, x=fvs, orientation="h", name="FV / share",
            marker_color=[P.DELTA_GOOD if v is not None and v >= res.price
                          else "#d03b3b" for v in fvs],
            hovertemplate="$%{x:,.2f}<extra>%{y}</extra>"))
        f.add_vline(x=res.price, line_color=P.INK_SECONDARY,
                    annotation_text=f"P₀ ${res.price:,.2f}")
        f.update_xaxes(tickformat="$,.0f")
        figs.append(f)

    # ------------------------------------------------------------- assemble
    kpis = []
    if d.last_close is not None:
        kpis.append(("Last close", f"${d.last_close:,.2f}",
                     f"{fmt_pct(d.total_return, signed=True)} {d.display_years}y"
                     if d.total_return is not None else "",
                     P.DELTA_GOOD if (d.total_return or 0) >= 0 else P.DELTA_BAD))
    if d.revenue and d.revenue[-1] is not None:
        kpis.append((f"Revenue ({fy[-1]})", fmt_money(d.revenue[-1]),
                     f"{fmt_pct(d.revenue_cagr, signed=True)}/yr"
                     if d.revenue_cagr is not None else "", P.DELTA_GOOD))
    if verdict is not None and verdict.fv_avg is not None:
        kpis.append(("FV average (§5.2)", f"${verdict.fv_avg:,.2f}",
                     f"{fmt_pct(verdict.mos, signed=True)} MoS",
                     P.DELTA_GOOD if (verdict.mos or 0) >= 0 else P.DELTA_BAD))
        kpis.append(("Rating gate", verdict.rating or "—", verdict.coherence,
                     P.DELTA_GOOD if verdict.coherence.startswith("ok")
                     else P.DELTA_BAD))

    parts = [f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>{_html.escape(d.ticker)} — forensic report</title>
<style>
 body{{font-family:'Segoe UI',system-ui,sans-serif;background:{P.PAGE};
      color:{P.INK_PRIMARY};margin:0;padding:24px 32px}}
 h1{{font-size:22px;margin:0 0 4px}} .sub{{color:{P.INK_SECONDARY};font-size:13px}}
 .warn{{color:{P.DELTA_BAD};font-weight:600;font-size:13px}}
 .kpi-row{{display:flex;gap:28px;margin:18px 0;flex-wrap:wrap}}
 .kpi-label{{font-size:12px;color:{P.INK_SECONDARY}}}
 .kpi-value{{font-size:22px;font-weight:700}} .kpi-delta{{font-size:12px}}
 .chart{{background:{P.SURFACE};border:1px solid {P.GRIDLINE};border-radius:8px;
        margin:14px 0;padding:6px}}
 .note{{color:{P.INK_MUTED};font-size:11.5px;margin-top:18px}}
</style></head><body>
<h1>{_html.escape(d.company)}</h1>
<div class="sub">{_html.escape(d.subtitle)} · generated {d.generated.isoformat()}
 · {d.display_years}-year window · interactive rendition (PDF is the print copy)</div>"""]
    if d.thesis:
        parts.append(f"<div class='sub' style='margin-top:8px'><b>Thesis (§2.4):</b> "
                     f"{_html.escape(d.thesis)}</div>")
    if d.terminal_risk:
        parts.append(f"<div class='warn' style='margin-top:4px'>Terminal risk (§2.3): "
                     f"{_html.escape(d.terminal_risk)}</div>")
    parts.append(_kpi_row(kpis))
    for i, f in enumerate(figs):
        parts.append("<div class='chart'>"
                     + f.to_html(full_html=False, include_plotlyjs=(i == 0),
                                 config={"displaylogo": False})
                     + "</div>")
    parts.append("<div class='note'>Sources: SEC EDGAR XBRL (as filed), "
                 "Stooq/Yahoo prices. All values also in the CSV audit trail. "
                 "Not investment advice.</div></body></html>")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("".join(parts))
    return path

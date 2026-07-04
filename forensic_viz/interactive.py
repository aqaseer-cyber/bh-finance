"""Interactive HTML report — plotly, self-contained single file.

Hover tooltips, zoom/pan, and legend series-toggling on every chart; the file
embeds plotly.js so it opens offline in any browser. The matplotlib pages
remain the print/PDF (A4) rendition; this is the on-screen rendition.
"""
from __future__ import annotations

import html as _html
from typing import List, Optional

from . import config
from . import palette as P
from .metrics import DashboardData, fmt_money, fmt_pct

# The sandbox's DCF engine — a line-for-line JS replica of valuation.dcf_fcff
# (§4.A: 10-year linear fade, Gordon TV). Extracted so a test can execute it in
# a JS engine and assert numeric parity against the Python model. Plain string
# (single braces): interpolated into the sandbox <script> via {SANDBOX_DCF_JS}.
SANDBOX_DCF_JS = """
  function dcf(base, wacc, g0, g) {
    if (wacc <= g) return null;
    let f = base, pv = 0;
    for (let i = 1; i <= 10; i++) {
      const gi = g0 + (g - g0) * (i - 1) / 9;
      f *= 1 + gi;
      pv += f / Math.pow(1 + wacc, i);
    }
    const tv = f * (1 + g) / (wacc - g);
    return { ev: pv + tv / Math.pow(1 + wacc, 10),
             tvShare: (tv / Math.pow(1 + wacc, 10)) / (pv + tv / Math.pow(1 + wacc, 10)) };
  }
"""

_LAYOUT = dict(
    template="plotly_white",
    font=dict(family="Segoe UI, system-ui, sans-serif", size=12,
              color=P.INK_PRIMARY),
    paper_bgcolor=P.SURFACE, plot_bgcolor=P.SURFACE,
    # top margin fits a (two-line) title above the horizontal legend
    margin=dict(l=60, r=30, t=88, b=40),
    hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    title_y=0.985, title_yanchor="top",
    colorway=P.SERIES,
)


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    return (f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},"
            f"{int(h[4:6], 16)},{alpha})")


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


def _yoy(vals) -> List[Optional[float]]:
    """YoY % change; None where the prior year is missing or non-positive."""
    out: List[Optional[float]] = [None]
    for prev, cur in zip(vals, vals[1:]):
        out.append(cur / prev - 1.0
                   if (prev is not None and prev > 0 and cur is not None)
                   else None)
    return out


def _display_chart(fy, vals, label: str):
    """Fiscal.ai-style display chart: value bars with $ labels plus a
    %-change line with point labels on a hidden secondary axis. The bar's
    legend entry carries Total Change and CAGR over the window; clicking
    the %-change legend entry toggles the line off/on."""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    idx = [i for i, v in enumerate(vals) if v is not None]
    name = label
    if idx and vals[idx[0]] and vals[idx[0]] > 0:
        f0, l0, yrs = vals[idx[0]], vals[idx[-1]], idx[-1] - idx[0]
        extras = []
        if l0 is not None:
            extras.append(f"Total Change: {(l0 / f0 - 1) * 100:,.2f}%")
        if l0 is not None and l0 > 0 and yrs > 0:
            extras.append(f"CAGR: {((l0 / f0) ** (1 / yrs) - 1) * 100:.2f}%")
        if extras:
            name = f"{label} (" + ") (".join(extras) + ")"

    f = make_subplots(specs=[[{"secondary_y": True}]])
    f.add_trace(go.Bar(
        x=fy, y=vals, name=name, marker_color=P.SERIES[0],
        text=[fmt_money(v) if v is not None else "" for v in vals],
        textposition="outside", cliponaxis=False,
        textfont=dict(size=11, color=P.INK_PRIMARY),
        hovertemplate="%{y:$,.3s}<extra>" + label + "</extra>"),
        secondary_y=False)
    pct = _yoy(vals)
    f.add_trace(go.Scatter(
        x=fy, y=pct, name=f"{label} Change (%)", mode="lines+markers+text",
        line=dict(color=P.SERIES[2], width=2.5),
        marker=dict(size=8, line=dict(color=P.SERIES[0], width=1.2)),
        text=[f"{v * 100:.1f}%" if v is not None else "" for v in pct],
        textposition="top center",
        textfont=dict(size=10.5, color=P.INK_SECONDARY),
        hovertemplate="%{y:.1%}<extra>YoY change</extra>"),
        secondary_y=True)
    f.update_layout(title=dict(
        text=f"{label}<br><sup>bars = $ value · line = YoY % change · "
             "click the legend to toggle the line</sup>",
        font=dict(size=15)), height=440, **_LAYOUT)
    # template style: no axes/grid — the direct labels carry every value.
    # Bars fill the lower band; the %-line floats in the top band so its
    # point labels always sit on the cream surface, never on a dark bar.
    vmax = max([v for v in vals if v is not None] + [0.0])
    vmin = min([v for v in vals if v is not None] + [0.0])
    f.update_yaxes(visible=False, showgrid=False, secondary_y=False,
                   range=[vmin * 1.25 if vmin < 0 else 0, (vmax * 1.55) or 1.0])
    ps = [v for v in pct if v is not None] or [0.0]
    pmin, pmax = min(ps), max(ps)
    span = (pmax - pmin) or max(abs(pmax), 0.01)
    f.update_yaxes(visible=False, showgrid=False, secondary_y=True,
                   range=[pmin - 3.6 * span, pmax + 0.4 * span])
    f.update_xaxes(showgrid=False)
    return f


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
                               fillcolor=_rgba(P.SERIES[0], 0.08)), row=1, col=1)
        f.add_trace(go.Scatter(x=d.price_dates, y=d.drawdown, name="Drawdown",
                               line=dict(color=P.NEGATIVE, width=1.6),
                               fill="tozeroy", fillcolor=_rgba(P.NEGATIVE, 0.08),
                               hovertemplate="%{y:.1%}<extra>Drawdown</extra>"),
                    row=2, col=1)
        f.update_layout(title=dict(
            text=f"Price & drawdown — split-adjusted daily close ({d.price_source})",
            font=dict(size=15)), height=520, **_LAYOUT)
        f.update_yaxes(tickformat="$,.0f", row=1, col=1, gridcolor=P.GRIDLINE)
        f.update_yaxes(tickformat=".0%", row=2, col=1, gridcolor=P.GRIDLINE)
        figs.append(f)

    if fy:
        # Revenue / Operating Profit display charts (house template):
        # value bars + toggleable %-change line, Total Change & CAGR in legend
        figs.append(_display_chart(fy, d.revenue, "Revenue"))
        if any(v is not None for v in d.ebit_reported):
            figs.append(_display_chart(fy, d.ebit_reported, "Operating Profit"))

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
                           marker_color=[P.NEGATIVE if v and v > 0.10 else P.SERIES[0]
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
            wc_series = [d.dsi, d.dso, d.dpo, d.ccc]
            wc_names = ["DSI", "DSO", "DPO", "CCC"]
            if all(v is None for v in d.ccc) and all(v is None for v in d.dpo):
                # payables untagged: show the operating cycle instead of
                # silently dropping the cycle line (matches the PDF page)
                oc = [a + b if a is not None and b is not None else None
                      for a, b in zip(d.dsi, d.dso)]
                wc_series, wc_names = [d.dsi, d.dso, oc], \
                    ["DSI", "DSO", "Operating cycle (DSI+DSO; DPO untagged)"]
            _lines(f, fy, wc_series, wc_names, pct=False)
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
                                   line=dict(color=P.SERIES[5], width=2)))
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
                          else P.NEGATIVE for v in fvs],
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
      color:{P.INK_PRIMARY};margin:0;padding:0 0 24px}}
 .band{{background:{P.GUI_SIDEBAR_BG};color:{P.GUI_SIDEBAR_FG};
       padding:20px 32px 16px;border-bottom:4px solid {P.GUI_ACCENT}}}
 .band .sub{{color:{P.GUI_SIDEBAR_MUTED}}}
 .band .warn{{color:{P.GUI_ACCENT}}}
 main{{padding:0 32px}}
 h1{{font-size:22px;margin:0 0 4px}} .sub{{color:{P.INK_SECONDARY};font-size:13px}}
 .warn{{color:{P.DELTA_BAD};font-weight:600;font-size:13px}}
 .kpi-row{{display:flex;gap:28px;margin:18px 0;flex-wrap:wrap}}
 .kpi-label{{font-size:12px;color:{P.INK_SECONDARY}}}
 .kpi-value{{font-size:22px;font-weight:700}} .kpi-delta{{font-size:12px}}
 .chart{{background:{P.SURFACE};border:1px solid {P.GRIDLINE};border-radius:8px;
        margin:14px 0;padding:6px}}
 .note{{color:{P.INK_MUTED};font-size:11.5px;margin-top:18px}}
</style></head><body>
<div class="band">
<h1>{_html.escape(d.company)}</h1>
<div class="sub">{_html.escape(d.subtitle)} · generated {d.generated.isoformat()}
 · {d.display_years}-year window · interactive rendition (PDF is the print copy)</div>"""]
    if d.thesis:
        parts.append(f"<div class='sub' style='margin-top:8px'><b>Thesis (§2.4):</b> "
                     f"{_html.escape(d.thesis)}</div>")
    if d.terminal_risk:
        parts.append(f"<div class='warn' style='margin-top:4px'>Terminal risk (§2.3): "
                     f"{_html.escape(d.terminal_risk)}</div>")
    parts.append("</div><main>")
    parts.append(_kpi_row(kpis))
    for i, f in enumerate(figs):
        parts.append("<div class='chart'>"
                     + f.to_html(full_html=False, include_plotlyjs=(i == 0),
                                 config={"displaylogo": False})
                     + "</div>")
    sandbox = _sandbox_html(d, res)
    if sandbox:
        parts.append(sandbox)
    parts.append("<div class='note'>Sources: SEC EDGAR XBRL (as filed), "
                 "Stooq/Yahoo prices. All values also in the financial-model "
                 "export (XLSX) and the CLI CSV audit trail. "
                 "Not investment advice.</div></main></body></html>")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("".join(parts))
    return path


def _latest(seq):
    for v in reversed(seq or []):
        if v is not None:
            return v
    return None


def _sandbox_html(d: DashboardData, res=None) -> str:
    """Live DCF sandbox: sliders drive an in-browser replica of the §4.A
    2-stage model (fade, TV, equity bridge, reverse DCF). The Python engine
    stays the source of truth for every export — this is exploration only."""
    base_a = _latest(d.fcff)
    shares = _latest(d.diluted_shares)
    if d.last_close is None or not shares or base_a is None or base_a <= 0 \
            or d.track in ("bank", "insurance"):
        return ""  # DCF sandbox only where an FCFF base exists
    sbc = _latest(d.sbc) or 0.0
    base_b = max(base_a - sbc, 0.0)
    if res is not None and res.bridge is not None:
        bridge = res.bridge  # audited bridge from the valuation run
    else:  # recompute: net debt + MI + pref − non-op (FCFF_DCF!B31 legs)
        debt, cash = _latest(d.total_debt), _latest(d.cash)
        bridge = ((debt or 0.0) - (cash or 0.0)
                  + (_latest(d.minority_interest) or 0.0)
                  + (_latest(d.preferred_equity) or 0.0)
                  - (d.non_op_investments or 0.0))
    build = getattr(d, "wacc_build", None)
    wacc0 = build.wacc if build is not None and build.wacc else 0.09
    est = d.analyst_estimates or {}
    g0_0, g_t0 = est.get("g_avg", 0.05) or 0.05, 0.02
    if res is not None and res.method == "dcf" and res._inputs is not None:
        base_case = res._inputs.cases.get("Base")
        if base_case and base_case.g0 is not None:
            g0_0, g_t0 = base_case.g0, base_case.g_term
        if res.discount_rate:
            wacc0 = res.discount_rate

    return f"""
<div class="chart" style="padding:18px">
<h2 style="font-size:16px;margin:0 0 2px">Valuation sandbox — live DCF (§4.A)</h2>
<div class="sub">Drag to test rates; the app's valuation page and exports stay
 the audited record. FCFF 2-stage, 10-year linear fade; equity bridge
 (net debt + MI + pref − non-op) = ${bridge / 1e6:,.0f}mm;
 {shares / 1e6:,.1f}mm diluted shares; P₀ ${d.last_close:,.2f}.</div>
<div style="display:flex;gap:36px;flex-wrap:wrap;margin-top:12px">
 <div style="min-width:330px">
  <label>WACC <b id="waccv"></b></label><br>
  <input id="wacc" type="range" min="3" max="18" step="0.1" value="{wacc0 * 100:.1f}" style="width:300px"><br>
  <label>Stage-1 growth g₀ <b id="g0v"></b></label><br>
  <input id="g0" type="range" min="-10" max="30" step="0.5" value="{g0_0 * 100:.1f}" style="width:300px"><br>
  <label>Terminal growth g <b id="gtv"></b></label><br>
  <input id="gt" type="range" min="0" max="4" step="0.1" value="{g_t0 * 100:.1f}" style="width:300px"><br>
  <label>Base FCFF ($mm) <input id="basemm" type="number" step="50"
     value="{base_a / 1e6:.0f}" style="width:110px"></label>
  <label style="margin-left:14px"><input id="exsbc" type="checkbox">
     ex-SBC (−${sbc / 1e6:,.0f}mm, house §2b)</label>
 </div>
 <div style="min-width:260px">
  <div class="kpi"><div class="kpi-label">Fair value / share</div>
    <div class="kpi-value" id="fv">–</div>
    <div class="kpi-delta" id="mos"></div></div>
  <div style="font-size:12.5px;color:{P.INK_SECONDARY};margin-top:8px" id="detail"></div>
  <div style="font-size:12px;color:{P.DELTA_BAD};margin-top:6px" id="warn"></div>
 </div>
 <div id="sandbox-chart" style="width:380px;height:190px"></div>
</div>
<script>
(function() {{
  const SHARES={shares:.6g}, PRICE={d.last_close:.6g}, BRIDGE={bridge:.6g},
        BASE_A={base_a:.6g}, SBC={sbc:.6g}, CAP={config.GDP_CAP:.6g};
  const el = id => document.getElementById(id);
{SANDBOX_DCF_JS}
  function fmtPct(x) {{ return (x >= 0 ? "+" : "") + (100 * x).toFixed(1) + "%"; }}
  function update() {{
    const wacc = +el("wacc").value / 100, g0 = +el("g0").value / 100,
          g = +el("gt").value / 100;
    let base = (+el("basemm").value || 0) * 1e6;
    if (el("exsbc").checked) base = Math.max(base - SBC, 0);
    el("waccv").textContent = (wacc * 100).toFixed(1) + "%";
    el("g0v").textContent = (g0 * 100).toFixed(1) + "%";
    el("gtv").textContent = (g * 100).toFixed(1) + "%";
    const warn = [];
    if (g > CAP) warn.push("terminal g above the 3.5% GDP cap (§4.A)");
    const out = (base > 0) ? dcf(base, wacc, g0, g) : null;
    if (!out) {{
      el("fv").textContent = "–";
      el("mos").textContent = "";
      el("warn").textContent = base > 0 ? "WACC must exceed terminal g" :
                                          "base FCFF must be positive";
      return;
    }}
    const equity = out.ev - BRIDGE, fv = equity / SHARES,
          mos = fv / PRICE - 1;
    // reverse DCF on the Track-B ex-SBC base over full market EV (Control!B58)
    const baseB = el("exsbc").checked ? base : Math.max(base - SBC, 0);
    const impliedG = baseB > 0 ? wacc - baseB / (PRICE * SHARES + BRIDGE) : null;
    el("fv").textContent = "$" + fv.toFixed(2);
    el("mos").textContent = fmtPct(mos) + " MoS vs P\\u2080";
    el("mos").style.color = mos >= 0 ? "{P.DELTA_GOOD}" : "{P.DELTA_BAD}";
    el("detail").textContent = "EV $" + (out.ev / 1e9).toFixed(1) + "B \\u00b7 TV " +
      (100 * out.tvShare).toFixed(0) + "% of EV \\u00b7 reverse-DCF implied g " +
      (impliedG === null ? "n/a (ex-SBC base \\u2264 0)" :
        fmtPct(impliedG) + (impliedG > CAP ? " (market pays for optionality, \\u00a74.D)" : ""));
    el("warn").textContent = warn.join("; ");
    Plotly.react("sandbox-chart", [{{
      type: "bar", orientation: "h", y: ["FV"], x: [fv],
      marker: {{ color: mos >= 0 ? "{P.DELTA_GOOD}" : "{P.DELTA_BAD}" }},
      hovertemplate: "$%{{x:,.2f}}<extra>FV</extra>"
    }}], {{
      margin: {{ l: 30, r: 10, t: 8, b: 28 }}, height: 190, width: 380,
      xaxis: {{ tickformat: "$,.0f",
               range: [0, Math.max(fv, PRICE) * 1.25] }},
      shapes: [{{ type: "line", x0: PRICE, x1: PRICE, y0: -0.5, y1: 0.5,
                 line: {{ color: "{P.INK_SECONDARY}", width: 2 }} }}],
      annotations: [{{ x: PRICE, y: 0.5, yanchor: "bottom",
                      text: "P\\u2080 $" + PRICE.toFixed(2), showarrow: false }}],
      paper_bgcolor: "{P.SURFACE}", plot_bgcolor: "{P.SURFACE}"
    }}, {{ displayModeBar: false }});
  }}
  ["wacc", "g0", "gt", "basemm", "exsbc"].forEach(id =>
    el(id).addEventListener("input", update));
  update();
}})();
</script></div>"""

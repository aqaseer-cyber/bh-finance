"""Derived metrics: margins, FCF, growth, drawdown, and forensic ratios.

Forensic definitions used here:
- operating accruals = (NI - CFO) / average total assets. Persistently positive
  and large (> ~10%) means reported earnings run ahead of cash collection.
- Sloan ratio (house variant, master prompt §3.3) = (NI - CFO - CFI) / average
  total assets; |ratio| > 10% is flagged.
- cash conversion = CFO / NI (meaningful only when NI > 0).
- Piotroski F-score: the nine classic signals. Proxies: diluted share count for
  the equity-issuance check; end-of-year assets in the turnover signal.
- Altman Z: original 1968 (Standard-Mfg) model; MVE = FY-end close x diluted
  shares. Not meaningful for financial-sector filers.
- R&D capitalization audit (master §3.2): EBIT_econ = EBIT_rep + R&D_t - Amort,
  Amort_t = sum_{k=1..n-1} R&D_{t-k}/n, straight-line life n.
"""
from __future__ import annotations

import bisect
import datetime as dt
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import config
from .edgar import AnnualFundamentals
from .prices import PriceSeries


def _div(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    return a / b


def _sub(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    return a - b


@dataclass
class DashboardData:
    """Everything the renderer needs, fully precomputed."""

    ticker: str
    company: str
    subtitle: str
    generated: dt.date
    demo: bool = False
    display_years: int = config.GUI_DEFAULT_YEARS

    # Analyst consensus growth estimates (Yahoo) — one anchor on the
    # FIX-14a growth ladder (anchors.py): the mean seeds Bull, the low/high
    # dispersion is display-only. Always editable.
    analyst_estimates: Optional[dict] = None

    # Untrimmed as-filed fundamentals (incl. the raw companyfacts payload),
    # kept so the financial-model export can consolidate annual + quarterly
    # without a second fetch.
    fundamentals: Optional[AnnualFundamentals] = field(default=None, repr=False)

    # Segment disclosures (dimensional XBRL from the latest 10-K/10-Q
    # instances) — drives the SEGMENTS section of the financial model, the
    # Phase-2 revenue architecture fill and the SOTP hint. None when the
    # instances are unreachable (offline) or the filer reports one segment.
    segments: Optional[object] = field(default=None, repr=False)

    # As-filed statement structure (FIX-13d): the latest 10-K's presentation
    # linkbase, {'income'/'balance'/'cashflow': [edgar.PresRow, ...]} plus a
    # '_short_names' meta key — drives the per-statement export sheets.
    # None when unreachable; statements_note keeps the reason.
    statements: Optional[dict] = field(default=None, repr=False)
    statements_note: str = ""

    # Fundamentals (aligned lists, oldest -> newest, DISPLAY_YEARS long)
    fy_labels: List[str] = field(default_factory=list)
    fy_ends: List[dt.date] = field(default_factory=list)
    revenue: List[Optional[float]] = field(default_factory=list)
    revenue_yoy: List[Optional[float]] = field(default_factory=list)
    gross_margin: List[Optional[float]] = field(default_factory=list)
    operating_margin: List[Optional[float]] = field(default_factory=list)
    net_margin: List[Optional[float]] = field(default_factory=list)
    net_income: List[Optional[float]] = field(default_factory=list)
    cfo: List[Optional[float]] = field(default_factory=list)
    fcf: List[Optional[float]] = field(default_factory=list)
    accruals_ratio: List[Optional[float]] = field(default_factory=list)
    cash_conversion: List[Optional[float]] = field(default_factory=list)
    diluted_shares: List[Optional[float]] = field(default_factory=list)
    total_debt: List[Optional[float]] = field(default_factory=list)
    cash: List[Optional[float]] = field(default_factory=list)
    tags_used: Dict[str, str] = field(default_factory=dict)

    # Phase-3 health checks (aligned with fy_labels)
    sloan_full: List[Optional[float]] = field(default_factory=list)
    piotroski_score: List[Optional[int]] = field(default_factory=list)
    piotroski_checks: List[int] = field(default_factory=list)  # evaluable of 9
    altman_z: List[Optional[float]] = field(default_factory=list)
    sbc: List[Optional[float]] = field(default_factory=list)
    sbc_pct_revenue: List[Optional[float]] = field(default_factory=list)
    fcf_ex_sbc: List[Optional[float]] = field(default_factory=list)
    rnd: List[Optional[float]] = field(default_factory=list)
    rnd_pct_revenue: List[Optional[float]] = field(default_factory=list)
    ebit_reported: List[Optional[float]] = field(default_factory=list)
    ebit_economic: List[Optional[float]] = field(default_factory=list)
    share_cagr_3y: Optional[float] = None
    sbc_pct_fcf_latest: Optional[float] = None
    rnd_material: bool = False
    sic_code: str = ""
    is_financial_sector: bool = False
    health_notes: List[str] = field(default_factory=list)

    # Phase-4 valuation inputs
    book_equity: List[Optional[float]] = field(default_factory=list)
    fcff: List[Optional[float]] = field(default_factory=list)  # FCF + after-tax interest
    interest_expense: List[Optional[float]] = field(default_factory=list)
    effective_tax_rate: Optional[float] = None
    wacc_build: Optional[object] = None  # rates.WaccBuild (typed loosely: no cycle)

    # Logic track (master Phase 1): standard / bank / insurance / reit / sotp
    track: str = "standard"

    # Banks/insurance solvency + credit-reserve audit (master §3.2/3.3)
    cet1_ratio: List[Optional[float]] = field(default_factory=list)
    tier1_ratio: List[Optional[float]] = field(default_factory=list)
    leverage_ratio: List[Optional[float]] = field(default_factory=list)
    equity_to_assets: List[Optional[float]] = field(default_factory=list)
    credit_allowance: List[Optional[float]] = field(default_factory=list)
    credit_provision: List[Optional[float]] = field(default_factory=list)

    # Fluff filter (master §3.1) — analyst-supplied non-GAAP figure
    adjusted_ni: Optional[float] = None
    adjustment_burden: Optional[float] = None
    # FIX-11d: analyst SBC override (annual $, from the comp note) — for
    # filers whose SBC series dies under every candidate tag, or whose
    # compensation is cash-settled (LTRP-style)
    sbc_override: Optional[float] = None

    # Phase-2 unit economics (aligned with fy_labels)
    dsi: List[Optional[float]] = field(default_factory=list)   # days inventory
    dso: List[Optional[float]] = field(default_factory=list)   # days sales out.
    dpo: List[Optional[float]] = field(default_factory=list)   # days payables
    ccc: List[Optional[float]] = field(default_factory=list)   # cash conv. cycle
    incremental_op_margin: List[Optional[float]] = field(default_factory=list)
    roic: List[Optional[float]] = field(default_factory=list)
    roe: List[Optional[float]] = field(default_factory=list)
    nim_proxy: List[Optional[float]] = field(default_factory=list)   # banks
    loss_ratio: List[Optional[float]] = field(default_factory=list)  # insurance
    combined_ratio: List[Optional[float]] = field(default_factory=list)
    premiums_earned: List[Optional[float]] = field(default_factory=list)
    # raw series the workbook exporter writes verbatim
    cogs: List[Optional[float]] = field(default_factory=list)
    inventory: List[Optional[float]] = field(default_factory=list)
    nii: List[Optional[float]] = field(default_factory=list)
    policy_benefits: List[Optional[float]] = field(default_factory=list)
    uw_expense: List[Optional[float]] = field(default_factory=list)

    # Phase-2 analyst inputs (§2.3/§2.4): judgment, printed on the report
    thesis: str = ""
    terminal_risk: str = ""
    non_op_investments: Optional[float] = None  # Phase1_Anchor!B19, analyst ($)

    # Workbook ties & bridge legs (Control / Phase1_Anchor tabs)
    eps_diluted: List[Optional[float]] = field(default_factory=list)
    dna: List[Optional[float]] = field(default_factory=list)
    basic_shares: List[Optional[float]] = field(default_factory=list)
    dividends_paid: List[Optional[float]] = field(default_factory=list)
    minority_interest: List[Optional[float]] = field(default_factory=list)
    preferred_equity: List[Optional[float]] = field(default_factory=list)
    latest_10k_date: str = ""
    latest_10q_date: str = ""

    # Phase-5 analyst verdict inputs (§5.3): judgment, gated for coherence
    rating: str = ""
    optionality: str = ""

    # Altman inputs held until FY-end prices are known (see compute_altman)
    _z_parts: List[Optional[dict]] = field(default_factory=list)
    fy_prices: List[Optional[float]] = field(default_factory=list)

    # FIX-16a: market-joined per-FY ratio series (market.py; empty until
    # prices attach — every ratio masks on a non-positive denominator)
    market_cap_fy: List[Optional[float]] = field(default_factory=list)
    ev_fy: List[Optional[float]] = field(default_factory=list)
    pe_fy: List[Optional[float]] = field(default_factory=list)
    ev_ebit_fy: List[Optional[float]] = field(default_factory=list)
    net_debt_fy: List[Optional[float]] = field(default_factory=list)
    net_debt_ebit_fy: List[Optional[float]] = field(default_factory=list)
    adj_fcf_yield_fy: List[Optional[float]] = field(default_factory=list)
    tangible_book: List[Optional[float]] = field(default_factory=list)
    owners_yield: Optional[float] = None       # (divs + gross buybacks)/mcap
    adj_fcf_yield_now: Optional[float] = None  # latest FCF ex-SBC / mcap
    # FIX-17c: provider recheck result (reconcile.AuditReport) — None when
    # no provider keys are configured; EDGAR numbers are never mutated
    audit_report: Optional[object] = None
    # FIX-17d: company profile (profile.CompanyProfile) — display-only
    # context, never feeds a calculation
    profile: Optional[object] = None
    # FIX-17e: insider transactions (insiders.InsiderPanel) — EDGAR Form 4
    insiders: Optional[object] = None
    # FIX-17f: estimates panel substrate {"rows": FMP annual analyst
    # estimates, "trends": Finnhub recommendation trends} — display-only,
    # unaudited; the Bull-seed anchor is the ONLY estimate that reaches
    # the valuation dialog, and it stays editable
    estimates_panel: Optional[dict] = None

    # Prices
    price_dates: List[dt.date] = field(default_factory=list)
    price_closes: List[float] = field(default_factory=list)
    drawdown: List[float] = field(default_factory=list)  # <= 0, fraction
    max_drawdown: Optional[float] = None
    max_drawdown_date: Optional[dt.date] = None
    total_return: Optional[float] = None
    price_source: str = ""
    price_error: str = ""

    # Headline aggregates
    revenue_cagr: Optional[float] = None
    fcf_cagr: Optional[float] = None
    net_margin_delta_pp: Optional[float] = None  # vs first displayed year
    share_change: Optional[float] = None  # fraction over the window
    last_close: Optional[float] = None


def fy_label(end: dt.date) -> str:
    return f"FY{end.year}" if end.month >= 6 else f"FY{end.year - 1}/{end.year % 100:02d}"


def _cagr(first: Optional[float], last: Optional[float], years: int) -> Optional[float]:
    if first is None or last is None or first <= 0 or last <= 0 or years <= 0:
        return None
    return (last / first) ** (1.0 / years) - 1.0


def build_fundamental_metrics(f: AnnualFundamentals, data: DashboardData) -> None:
    """Reduce FETCH_YEARS as-filed years to `data.display_years` of series."""
    data.fundamentals = f  # untrimmed source, for the financial-model export
    n_all = len(f.fy_ends)
    show = min(max(1, data.display_years), config.DISPLAY_YEARS, n_all)
    off = n_all - show  # index of the first displayed year in the full arrays

    def full(concept: str) -> List[Optional[float]]:
        return f.series.get(concept) or [None] * n_all

    revenue_all = full("revenue")
    ni_all = full("net_income")
    cfo_all = full("cfo")
    capex_all = full("capex")
    assets_all = full("total_assets")
    cor_all = full("cost_of_revenue")
    gp_all = [
        gp if gp is not None else _sub(rev, cor)
        for gp, rev, cor in zip(full("gross_profit"), revenue_all, cor_all)
    ]
    debt_all = []
    for i in range(n_all):
        parts = [full("lt_debt_noncurrent")[i], full("lt_debt_current")[i], full("st_borrowings")[i]]
        if all(p is None for p in parts):
            debt_all.append(full("lt_debt_total")[i])
        else:
            debt_all.append(sum(p for p in parts if p is not None))

    data.fy_ends = f.fy_ends[off:]
    data.fy_labels = [fy_label(e) for e in data.fy_ends]
    data.tags_used = dict(f.tags_used)

    # Effective tax rate for the FCFF bridge (master §4.0), from the most recent
    # year with positive pre-tax income; falls back to a labeled 21% ASSUMPTION.
    interest_all = full("interest_expense")
    tax_all, pretax_all = full("tax_expense"), full("pretax_income")
    eff_tax = None
    for j in range(n_all - 1, -1, -1):
        t, p = tax_all[j], pretax_all[j]
        if t is not None and p is not None and p > 0:
            r = t / p
            if 0.0 <= r <= 0.5:
                eff_tax = r
                break
    if eff_tax is None:
        eff_tax = 0.21
    data.effective_tax_rate = eff_tax

    for i in range(off, n_all):
        rev, ni, cfo, capex = revenue_all[i], ni_all[i], cfo_all[i], capex_all[i]
        data.revenue.append(rev)
        data.net_income.append(ni)
        data.cfo.append(cfo)
        fcf = _sub(cfo, capex) if capex is not None else cfo
        data.fcf.append(fcf)
        # FCFF = levered FCF + after-tax interest (master §4.0). CFO is already
        # net of interest paid, so the add-back un-levers it before the WACC
        # discount + net-debt bridge. No interest tag -> keep levered FCF and
        # flag it as a proxy (data.fcff_is_levered_proxy).
        interest = interest_all[i]
        data.interest_expense.append(interest)
        if fcf is not None and interest is not None:
            data.fcff.append(fcf + interest * (1 - eff_tax))
        else:
            data.fcff.append(fcf)
        # margins are meaningless against non-positive revenue (a negative
        # numerator over negative revenue would render as a healthy margin)
        pos_rev = rev if rev is not None and rev > 0 else None
        data.gross_margin.append(_div(gp_all[i], pos_rev))
        data.operating_margin.append(_div(full("operating_income")[i], pos_rev))
        data.net_margin.append(_div(ni, pos_rev))
        data.diluted_shares.append(full("diluted_shares")[i])
        data.total_debt.append(debt_all[i])
        data.cash.append(full("cash")[i])
        data.book_equity.append(full("equity")[i])

        # Solvency (regulatory ratios are tagged either as decimals or percent)
        for concept, dest in (("cet1_ratio", data.cet1_ratio),
                              ("tier1_ratio", data.tier1_ratio),
                              ("leverage_ratio", data.leverage_ratio)):
            v = full(concept)[i]
            if v is not None and v > 1.0:  # 13.2 filed for 13.2%
                v /= 100.0
            dest.append(v)
        eq, ta_i = full("equity")[i], assets_all[i]
        data.equity_to_assets.append(
            eq / ta_i if eq is not None and ta_i and ta_i > 0 else None)
        data.credit_allowance.append(full("credit_allowance")[i])
        data.credit_provision.append(full("credit_provision")[i])
        data.eps_diluted.append(full("eps_diluted")[i])
        data.dna.append(full("dna")[i])
        data.basic_shares.append(full("basic_shares")[i])
        data.dividends_paid.append(full("dividends_paid")[i])
        data.minority_interest.append(full("minority_interest")[i])
        data.preferred_equity.append(full("preferred_equity")[i])

        prev_rev = revenue_all[i - 1] if i > 0 else None
        data.revenue_yoy.append(
            _div(_sub(rev, prev_rev), prev_rev) if prev_rev and prev_rev > 0 else None
        )

        accr = _sub(ni, cfo)
        assets, prev_assets = assets_all[i], assets_all[i - 1] if i > 0 else None
        avg_assets = (
            (assets + prev_assets) / 2.0
            if assets is not None and prev_assets is not None
            else assets
        )
        data.accruals_ratio.append(_div(accr, avg_assets))
        data.cash_conversion.append(_div(cfo, ni) if ni is not None and ni > 0 else None)

        _health_year(data, f, i, avg_assets)
        _unit_economics_year(data, f, i, avg_assets, eff_tax)

    data.rnd_material = _rnd_is_material(data)
    if not data.rnd_material:  # audit applies only where R&D is material
        data.ebit_economic = [None] * len(data.fy_ends)
    if len(data.diluted_shares) >= 4 and data.diluted_shares[-4] and data.diluted_shares[-1]:
        data.share_cagr_3y = (data.diluted_shares[-1] / data.diluted_shares[-4]) ** (1 / 3) - 1
    if data.sbc and data.fcf and data.sbc[-1] is not None and data.fcf[-1] and data.fcf[-1] > 0:
        data.sbc_pct_fcf_latest = data.sbc[-1] / data.fcf[-1]
    data.health_notes = [
        "Sloan variant: (NI − CFO − CFI) / avg total assets; |ratio| > "
        f"{config.SLOAN_FLAG:.0%} flagged (master §3.3)",
        f"ASSUMPTION: R&D life n={config.RND_LIFE_YEARS}y straight-line, "
        f"materiality {config.RND_MATERIALITY:.0%} of revenue (house §3 file not attached)",
        "Piotroski proxies: diluted share count for the issuance signal; "
        "end-of-year assets in the turnover signal",
        "Altman Z: original 1968 Standard-Mfg model; MVE = FY-end close × diluted shares",
    ]

    span = len(data.fy_ends) - 1
    data.revenue_cagr = _cagr(data.revenue[0] if data.revenue else None,
                              data.revenue[-1] if data.revenue else None, span)
    data.fcf_cagr = _cagr(data.fcf[0] if data.fcf else None,
                          data.fcf[-1] if data.fcf else None, span)
    if data.net_margin and data.net_margin[0] is not None and data.net_margin[-1] is not None:
        data.net_margin_delta_pp = (data.net_margin[-1] - data.net_margin[0]) * 100
    first_sh = data.diluted_shares[0] if data.diluted_shares else None
    last_sh = data.diluted_shares[-1] if data.diluted_shares else None
    if first_sh and last_sh:
        data.share_change = last_sh / first_sh - 1.0


def _health_year(data: DashboardData, f: AnnualFundamentals, i: int,
                 avg_assets: Optional[float]) -> None:
    """Phase-3 health metrics for one fiscal year (index into the full arrays)."""
    n_all = len(f.fy_ends)

    def g(concept: str, j: int) -> Optional[float]:
        s = f.series.get(concept)
        return s[j] if s is not None and 0 <= j < n_all else None

    rev, ni, cfo, cfi = g("revenue", i), g("net_income", i), g("cfo", i), g("cfi", i)
    ta, ta_prev = g("total_assets", i), g("total_assets", i - 1)
    sbc, rnd, opinc = g("sbc", i), g("rnd", i), g("operating_income", i)
    capex = g("capex", i)
    fcf = _sub(cfo, capex) if capex is not None else cfo
    pos_rev = rev if rev is not None and rev > 0 else None

    # Sloan ratio, house variant (master §3.3): (NI − CFO − CFI) / avg TA
    sloan = None
    if ni is not None and cfo is not None and cfi is not None:
        sloan = _div(ni - cfo - cfi, avg_assets)
    data.sloan_full.append(sloan)

    # SBC & dilution line (master §3.4)
    data.sbc.append(sbc)
    data.sbc_pct_revenue.append(_div(sbc, pos_rev))
    data.fcf_ex_sbc.append(_sub(fcf, sbc))
    data.rnd.append(rnd)
    data.rnd_pct_revenue.append(_div(rnd, pos_rev))

    # R&D capitalization audit (master §3.2): EBIT_econ = EBIT + R&D_t − Amort
    data.ebit_reported.append(opinc)
    n = config.RND_LIFE_YEARS
    prior = [g("rnd", i - k) for k in range(1, n)]
    if opinc is not None and rnd is not None and all(p is not None for p in prior):
        amort = sum(prior) / n
        data.ebit_economic.append(opinc + rnd - amort)
    else:
        data.ebit_economic.append(None)

    # Piotroski F-score — nine classic signals; None = not evaluable
    def gross_margin(j: int) -> Optional[float]:
        gp = g("gross_profit", j)
        if gp is None:
            gp = _sub(g("revenue", j), g("cost_of_revenue", j))
        r = g("revenue", j)
        return _div(gp, r if r is not None and r > 0 else None)

    def ltd(j: int) -> Optional[float]:
        v = g("lt_debt_noncurrent", j)
        return v if v is not None else g("lt_debt_total", j)

    roa, roa_prev = _div(ni, ta), _div(g("net_income", i - 1), ta_prev)
    lev, lev_prev = _div(ltd(i), ta), _div(ltd(i - 1), ta_prev)
    ac, lc = g("assets_current", i), g("liabilities_current", i)
    cr = _div(ac, lc)
    cr_prev = _div(g("assets_current", i - 1), g("liabilities_current", i - 1))
    sh, sh_prev = g("diluted_shares", i), g("diluted_shares", i - 1)
    gm, gm_prev = gross_margin(i), gross_margin(i - 1)
    turn, turn_prev = _div(rev, ta), _div(g("revenue", i - 1), ta_prev)

    signals = [
        roa > 0 if roa is not None else None,
        cfo > 0 if cfo is not None else None,
        roa > roa_prev if roa is not None and roa_prev is not None else None,
        cfo > ni if cfo is not None and ni is not None else None,
        lev < lev_prev if lev is not None and lev_prev is not None else None,
        cr > cr_prev if cr is not None and cr_prev is not None else None,
        sh <= sh_prev if sh is not None and sh_prev is not None else None,
        gm > gm_prev if gm is not None and gm_prev is not None else None,
        turn > turn_prev if turn is not None and turn_prev is not None else None,
    ]
    evaluable = [s for s in signals if s is not None]
    data.piotroski_checks.append(len(evaluable))
    data.piotroski_score.append(sum(evaluable) if evaluable else None)

    # Altman Z inputs — finished by compute_altman once FY-end prices exist
    tl, re_ = g("liabilities_total", i), g("retained_earnings", i)
    if (ta is not None and ta > 0 and ac is not None and lc is not None
            and tl is not None and tl > 0 and re_ is not None
            and opinc is not None and rev is not None and sh):
        data._z_parts.append({
            "wc_ta": (ac - lc) / ta, "re_ta": re_ / ta, "ebit_ta": opinc / ta,
            "sales_ta": rev / ta, "tl": tl, "shares": sh,
        })
    else:
        data._z_parts.append(None)


def _unit_economics_year(data: DashboardData, f: AnnualFundamentals, i: int,
                         avg_assets: Optional[float], eff_tax: float) -> None:
    """Phase-2 marginal-unit metrics for one fiscal year (full-array index).

    Working-capital days use average balances over (t-1, t), per the master's
    DSI definition. NIM uses average TOTAL assets as the earning-assets proxy
    (interest-earning assets aren't reliably tagged) — labeled on the panel.
    """
    n_all = len(f.fy_ends)

    def g(concept: str, j: int) -> Optional[float]:
        s = f.series.get(concept)
        return s[j] if s is not None and 0 <= j < n_all else None

    def avg(concept: str) -> Optional[float]:
        now, prev = g(concept, i), g(concept, i - 1)
        if now is None:
            return None
        return (now + prev) / 2.0 if prev is not None else now

    rev, cogs = g("revenue", i), g("cost_of_revenue", i)
    pos_rev = rev if rev is not None and rev > 0 else None
    pos_cogs = cogs if cogs is not None and cogs > 0 else None

    dsi = _div(avg("inventory"), pos_cogs)
    dso = _div(avg("accounts_receivable"), pos_rev)
    dpo = _div(avg("accounts_payable"), pos_cogs)
    data.dsi.append(dsi * 365 if dsi is not None else None)
    data.dso.append(dso * 365 if dso is not None else None)
    data.dpo.append(dpo * 365 if dpo is not None else None)
    data.ccc.append(
        data.dsi[-1] + data.dso[-1] - data.dpo[-1]
        if None not in (data.dsi[-1], data.dso[-1], data.dpo[-1]) else None)

    # The marginal unit, Standard track: incremental operating margin
    # ΔEBIT/ΔRevenue — only meaningful when revenue actually moved.
    opinc, opinc_prev = g("operating_income", i), g("operating_income", i - 1)
    rev_prev = g("revenue", i - 1)
    inc = None
    if (None not in (opinc, opinc_prev, rev, rev_prev) and rev_prev > 0
            and abs(rev - rev_prev) >= 0.02 * rev_prev):
        inc = (opinc - opinc_prev) / (rev - rev_prev)
    data.incremental_op_margin.append(inc)

    # Capital efficiency: ROIC = NOPAT / avg invested capital; ROE = NI / avg BV
    ni, eq, eq_prev = g("net_income", i), g("equity", i), g("equity", i - 1)

    def invested(j: int) -> Optional[float]:
        e = g("equity", j)
        if e is None or e <= 0:
            return None
        # same debt rule as debt_all in build_fundamental_metrics: the
        # LongTermDebt total is a fallback ONLY when every component is
        # untagged, never additive (it already includes the current portion)
        parts = [g("lt_debt_noncurrent", j), g("lt_debt_current", j),
                 g("st_borrowings", j)]
        if all(p is None for p in parts):
            debt = g("lt_debt_total", j) or 0.0
        else:
            debt = sum(p for p in parts if p is not None)
        return e + debt - (g("cash", j) or 0.0)

    ic_now, ic_prev = invested(i), invested(i - 1)
    avg_ic = ((ic_now + ic_prev) / 2.0 if ic_now is not None and ic_prev is not None
              else ic_now)
    data.roic.append(
        _div(opinc * (1 - eff_tax), avg_ic)
        if opinc is not None and avg_ic is not None and avg_ic > 0 else None)
    avg_eq = ((eq + eq_prev) / 2.0 if eq is not None and eq_prev is not None else eq)
    data.roe.append(_div(ni, avg_eq if avg_eq is not None and avg_eq > 0 else None))

    # Banks: NIM on the avg-total-assets proxy (master §2.2)
    data.nim_proxy.append(_div(g("net_interest_income", i), avg_assets))

    # Insurance: loss / combined ratio on net earned premiums (master §2.2)
    nep = g("premiums_earned", i)
    pos_nep = nep if nep is not None and nep > 0 else None
    benefits, uw = g("policy_benefits", i), g("underwriting_expense", i)
    data.premiums_earned.append(nep)
    data.loss_ratio.append(_div(benefits, pos_nep))
    data.combined_ratio.append(
        _div(benefits + uw, pos_nep)
        if benefits is not None and uw is not None else None)

    # raw series for the workbook exporter
    data.cogs.append(cogs)
    data.inventory.append(g("inventory", i))
    data.nii.append(g("net_interest_income", i))
    data.policy_benefits.append(benefits)
    data.uw_expense.append(uw)


TRACKS = ("auto", "standard", "bank", "insurance", "reit", "sotp")


def resolve_track(selection: str, sic_code: str) -> str:
    """Logic-track selection (master Phase 1): explicit choice wins; otherwise
    map the SIC code. Select by economic engine — override when they differ."""
    if selection and selection != "auto":
        return selection
    sic = sic_code or ""
    if sic == "6798":
        return "reit"
    if sic[:2] in ("63", "64"):
        return "insurance"
    if sic.startswith("6"):
        return "bank"
    return "standard"


def apply_track(data: DashboardData, selection: str) -> None:
    data.track = resolve_track(selection, data.sic_code)
    data.is_financial_sector = data.track in ("bank", "insurance")


def refresh_interest_metrics(f: AnnualFundamentals,
                             data: DashboardData) -> None:
    """Recompute the interest-dependent displayed series after an
    instance rescue patched ``f.series["interest_expense"]`` — the same
    FCFF = FCF + after-tax-interest arithmetic as the original build
    (master §4.0), so the auto valuation base un-levers correctly."""
    interest_all = f.series.get("interest_expense") or []
    n_all = len(f.fy_ends)
    off = n_all - len(data.fy_ends)
    eff_tax = (data.effective_tax_rate
               if data.effective_tax_rate is not None else 0.21)
    for i in range(off, n_all):
        j = i - off
        interest = interest_all[i] if i < len(interest_all) else None
        data.interest_expense[j] = interest
        fcf = data.fcf[j]
        if fcf is not None and interest is not None:
            data.fcff[j] = fcf + interest * (1 - eff_tax)
        else:
            data.fcff[j] = fcf


def set_adjusted_ni(data: DashboardData, adjusted: Optional[float]) -> None:
    """Fluff filter (master §3.1): burden = |Adjusted − GAAP| / |GAAP|."""
    data.adjusted_ni = adjusted
    data.adjustment_burden = None
    if adjusted is None:
        return
    gaap = None
    for v in reversed(data.net_income):
        if v is not None:
            gaap = v
            break
    if gaap:
        data.adjustment_burden = abs(adjusted - gaap) / abs(gaap)


def _rnd_is_material(data: DashboardData) -> bool:
    vals = [v for v in data.rnd_pct_revenue if v is not None]
    return bool(vals) and sum(vals) / len(vals) >= config.RND_MATERIALITY


def attach_fy_prices(data: DashboardData) -> None:
    """Closest daily close within 10 days of each fiscal-year end."""
    data.fy_prices = [None] * len(data.fy_ends)
    if not data.price_dates:
        return
    for idx, end in enumerate(data.fy_ends):
        j = bisect.bisect_left(data.price_dates, end)
        best = None
        for k in (j - 1, j):
            if 0 <= k < len(data.price_dates):
                gap = abs((data.price_dates[k] - end).days)
                if gap <= 10 and (best is None or gap < best[0]):
                    best = (gap, data.price_closes[k])
        if best is not None:
            data.fy_prices[idx] = best[1]


def compute_altman(data: DashboardData) -> None:
    """Altman Z per fiscal year (original 1968 model). Requires FY-end prices;
    suppressed for financial-sector filers, where Z is not meaningful."""
    if not data.fy_prices:
        attach_fy_prices(data)
    data.altman_z = []
    for parts, price in zip(data._z_parts, data.fy_prices):
        if parts is None or price is None or data.is_financial_sector:
            data.altman_z.append(None)
            continue
        mve = price * parts["shares"]
        data.altman_z.append(
            1.2 * parts["wc_ta"] + 1.4 * parts["re_ta"] + 3.3 * parts["ebit_ta"]
            + 0.6 * mve / parts["tl"] + 1.0 * parts["sales_ta"]
        )


def build_price_metrics(p: PriceSeries, data: DashboardData) -> None:
    data.price_dates = list(p.dates)
    data.price_closes = list(p.closes)
    data.price_source = p.source
    peak = float("-inf")
    dd: List[float] = []
    worst, worst_i = 0.0, 0
    for i, c in enumerate(p.closes):
        peak = max(peak, c)
        d = c / peak - 1.0
        dd.append(d)
        if d < worst:
            worst, worst_i = d, i
    data.drawdown = dd
    if p.closes:
        data.max_drawdown = worst
        data.max_drawdown_date = p.dates[worst_i]
        data.total_return = p.closes[-1] / p.closes[0] - 1.0
        data.last_close = p.closes[-1]


# ---------------------------------------------------------------- formatting

def fmt_money(v: Optional[float], currency: str = "$") -> str:
    """Compact money: $394.3B, -$1.2B, $845M, $12.5K."""
    if v is None:
        return "–"
    sign = "-" if v < 0 else ""
    a = abs(v)
    for cut, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= cut:
            return f"{sign}{currency}{a / cut:.1f}{suf}"
    return f"{sign}{currency}{a:,.0f}"


def fmt_count(v: Optional[float]) -> str:
    if v is None:
        return "–"
    a = abs(v)
    for cut, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= cut:
            return f"{v / cut:.2f}{suf}"
    return f"{v:,.0f}"


def fmt_pct(v: Optional[float], signed: bool = False, decimals: int = 1) -> str:
    if v is None:
        return "–"
    s = "+" if signed and v > 0 else ""
    return f"{s}{v * 100:.{decimals}f}%"

"""Derived metrics: margins, FCF, growth, drawdown, and forensic ratios.

Forensic definitions used here:
- accruals ratio (balance-sheet Sloan proxy) = (NI - CFO) / average total assets.
  Persistently positive and large (> ~10%) means reported earnings run ahead of
  cash collection — the classic low-earnings-quality signal.
- cash conversion = CFO / NI (meaningful only when NI > 0).
"""
from __future__ import annotations

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
    """Reduce FETCH_YEARS as-filed years to DISPLAY_YEARS of derived series."""
    n_all = len(f.fy_ends)
    show = min(config.DISPLAY_YEARS, n_all)
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

    for i in range(off, n_all):
        rev, ni, cfo, capex = revenue_all[i], ni_all[i], cfo_all[i], capex_all[i]
        data.revenue.append(rev)
        data.net_income.append(ni)
        data.cfo.append(cfo)
        data.fcf.append(_sub(cfo, capex) if capex is not None else cfo)
        data.gross_margin.append(_div(gp_all[i], rev))
        data.operating_margin.append(_div(full("operating_income")[i], rev))
        data.net_margin.append(_div(ni, rev))
        data.diluted_shares.append(full("diluted_shares")[i])
        data.total_debt.append(debt_all[i])
        data.cash.append(full("cash")[i])

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

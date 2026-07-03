"""Offline demo: a synthetic company with deliberate forensic red flags.

Eleven fiscal years are synthesized and pushed through the SAME metrics
pipeline as real EDGAR data, so every panel — including the Phase-3 health
checks — renders from production code paths. Planted story: a mid-window
year where net income sprints ahead of operating cash (accruals + Sloan
flags fire), an acquisition-driven CFI spike, persistent dilution, rising
SBC, and a leverage build that dents the Altman Z during the price crash.
"""
from __future__ import annotations

import datetime as dt
import math
import random
from typing import Dict, List, Optional

from . import config
from .edgar import AnnualFundamentals
from .metrics import (
    DashboardData, build_fundamental_metrics, build_price_metrics, compute_altman,
)
from .prices import PriceSeries


def demo_dashboard_data(today: Optional[dt.date] = None) -> DashboardData:
    today = today or dt.date.today()
    last_fy = today.year - 1
    n = config.FETCH_YEARS  # 11 synthetic fiscal years
    years = list(range(last_fy - n + 1, last_fy + 1))
    FLAG = n - 3  # the planted red-flag year (third from last)

    rev = [8.1e9 * 1.13**i for i in range(n)]
    op_margin = [min(0.13 + 0.006 * i, 0.19) for i in range(n)]
    op_margin[FLAG] = 0.205  # suspiciously strong print in the flag year
    opinc = [r * m for r, m in zip(rev, op_margin)]
    ni = [o - 0.035 * r for o, r in zip(opinc, rev)]
    cfo_factor = [1.25] * n
    cfo_factor[FLAG] = 0.28          # earnings far ahead of cash
    cfo_factor[FLAG + 1] = 0.95      # partial normalization
    cfo = [x * f for x, f in zip(ni, cfo_factor)]
    capex = [0.05 * r for r in rev]
    cfi = [-(c + 0.03 * r) for c, r in zip(capex, rev)]
    cfi[FLAG] = -0.20 * rev[FLAG]    # acquisition spike (organic vs acquired)
    sbc = [r * (0.02 + 0.004 * i) for i, r in enumerate(rev)]
    rnd = [0.09 * r for r in rev]
    shares = [500e6 * 1.03**i for i in range(n)]
    lev = [0.20 + (0.10 * max(0, i - FLAG + 1) / 3 if i >= FLAG - 1 else 0)
           for i in range(n)]

    series: Dict[str, List[Optional[float]]] = {
        "revenue": rev,
        "cost_of_revenue": [0.54 * r for r in rev],
        "gross_profit": [None] * n,  # derived, like a filer with no GrossProfit tag
        "operating_income": opinc,
        "net_income": ni,
        "cfo": cfo,
        "capex": capex,
        "cfi": cfi,
        "sbc": sbc,
        "rnd": rnd,
        "diluted_shares": shares,
        "total_assets": [0.95 * r for r in rev],
        "assets_current": [0.42 * r for r in rev],
        "liabilities_current": [0.25 * r for r in rev],
        "liabilities_total": [(0.50 + l) * r for l, r in zip(lev, rev)],
        "retained_earnings": [(0.28 + 0.01 * i) * r for i, r in enumerate(rev)],
        "equity": [(0.45 - l) * r for l, r in zip(lev, rev)],  # assets − liabilities
        "cash": [(0.18 if i not in (FLAG, FLAG + 1) else 0.10) * r
                 for i, r in enumerate(rev)],
        "lt_debt_noncurrent": [l * r for l, r in zip(lev, rev)],
        "lt_debt_current": [0.02 * r for r in rev],
        "st_borrowings": [None] * n,
        "lt_debt_total": [None] * n,
    }
    fundamentals = AnnualFundamentals(
        cik=0,
        entity_name="DEMOCO Industries (synthetic)",
        fy_ends=[dt.date(y, 12, 31) for y in years],
        series=series,
        tags_used={"all_series": "synthetic demo values"},
    )

    d = DashboardData(
        ticker="DEMO",
        company="DEMOCO Industries (synthetic)",
        subtitle=(f"DEMO · synthetic mid-cap · fiscal years FY{years[1]}–FY{years[-1]} · "
                  f"red flags planted in FY{years[FLAG]}"),
        generated=today,
        demo=True,
    )
    build_fundamental_metrics(fundamentals, d)

    # Deterministic weekly price path: growth, a crash aligned with the flag
    # year, partial recovery.
    rng = random.Random(20260703)
    n_weeks = 52 * config.PRICE_YEARS + 1
    start = today - dt.timedelta(weeks=n_weeks - 1)
    crash_lo = (dt.date(years[FLAG], 6, 1) - start).days / (7 * n_weeks)
    dates, raw = [], []
    price = 22.0
    for i in range(n_weeks):
        t = i / n_weeks
        drift = 0.0032 if not crash_lo < t < crash_lo + 0.09 else -0.024
        price *= math.exp(drift + rng.gauss(0, 0.027))
        dates.append(start + dt.timedelta(weeks=i))
        raw.append(price)
    # Rescale (shape- and drawdown-preserving) to a price level coherent with
    # the fundamentals: ~$85 last close on ~672M shares ≈ a $57B market cap,
    # so the DCF cases bracket the price sensibly rather than showing +800% MoS.
    scale = 85.0 / raw[-1]
    closes = [round(p * scale, 2) for p in raw]
    build_price_metrics(
        PriceSeries(symbol="DEMO", dates=dates, closes=closes, source="synthetic"), d
    )
    compute_altman(d)

    # Synthetic §4.0 rate build so the offline demo exercises auto-WACC.
    from .rates import WaccBuild, blume_adjust
    beta_raw = 1.18
    b = WaccBuild(r_f=0.042, r_f_date=today, r_f_source="synthetic 10-Y UST",
                  beta_raw=beta_raw, beta=blume_adjust(beta_raw),
                  tax=d.effective_tax_rate or 0.21)
    b.r_e = b.r_f + b.beta * b.erp
    b.r_d = 0.055
    e_val = closes[-1] * d.diluted_shares[-1]
    d_val = d.total_debt[-1] or 0.0
    b.e_weight = e_val / (e_val + d_val)
    b.d_weight = 1 - b.e_weight
    b.wacc = b.e_weight * b.r_e + b.d_weight * b.r_d * (1 - b.tax)
    b.notes = ["synthetic demo rates — live sources used for real tickers"]
    d.wacc_build = b
    return d

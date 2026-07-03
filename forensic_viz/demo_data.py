"""Offline demo: a synthetic company with a deliberate forensic red flag.

DEMOCO's FY4 shows net income growing while operating cash flow stalls — the
accruals ratio breaches +10% so you can see what the warning panels look like
when they fire. Everything is generated deterministically; no network needed.
"""
from __future__ import annotations

import datetime as dt
import math
import random

from .metrics import DashboardData, build_price_metrics
from .prices import PriceSeries


def _fy_end(year: int) -> dt.date:
    return dt.date(year, 12, 31)


def demo_dashboard_data(today: dt.date | None = None) -> DashboardData:
    today = today or dt.date.today()
    last_fy = today.year - 1
    years = [last_fy - i for i in range(5, -1, -1)]  # 6 FYs, oldest first

    revenue = [8.10e9, 9.50e9, 10.90e9, 12.60e9, 14.90e9, 16.40e9]
    gross = [0.44, 0.45, 0.455, 0.46, 0.47, 0.465]
    op = [0.135, 0.15, 0.16, 0.17, 0.185, 0.175]
    net = [0.09, 0.10, 0.11, 0.12, 0.145, 0.125]
    ni = [r * m for r, m in zip(revenue, net)]
    # FY index 4: earnings sprint ahead of cash — the planted red flag
    cfo = [n * c for n, c in zip(ni, [1.25, 1.22, 1.18, 1.05, 0.28, 0.95])]
    capex = [r * 0.05 for r in revenue]
    assets = [r * 0.9 for r in revenue]  # asset-light, so the ratio bites
    shares = [500e6, 512e6, 528e6, 549e6, 571e6, 594e6]  # steady dilution
    debt = [2.2e9, 2.1e9, 2.4e9, 3.1e9, 3.9e9, 4.4e9]
    cash = [1.5e9, 1.9e9, 2.2e9, 1.9e9, 1.4e9, 1.6e9]

    d = DashboardData(
        ticker="DEMO",
        company="DEMOCO Industries (synthetic)",
        subtitle=(f"DEMO · synthetic mid-cap · fiscal years FY{years[1]}–FY{years[-1]} · "
                  "planted red flag: FY accruals spike + persistent dilution"),
        generated=today,
        demo=True,
    )

    show = slice(1, 6)  # display 5 of the 6 years
    d.fy_ends = [_fy_end(y) for y in years[show]]
    d.fy_labels = [f"FY{y}" for y in years[show]]
    d.revenue = revenue[show]
    d.revenue_yoy = [revenue[i] / revenue[i - 1] - 1 for i in range(1, 6)]
    d.gross_margin = gross[show]
    d.operating_margin = op[show]
    d.net_margin = net[show]
    d.net_income = ni[show]
    d.cfo = cfo[show]
    d.fcf = [c - x for c, x in zip(cfo[show], capex[show])]
    d.accruals_ratio = [
        (ni[i] - cfo[i]) / ((assets[i] + assets[i - 1]) / 2) for i in range(1, 6)
    ]
    d.cash_conversion = [c / n for c, n in zip(cfo[show], ni[show])]
    d.diluted_shares = shares[show]
    d.total_debt = debt[show]
    d.cash = cash[show]
    d.tags_used = {"all_series": "synthetic demo values"}

    d.revenue_cagr = (d.revenue[-1] / d.revenue[0]) ** 0.25 - 1
    d.fcf_cagr = None if d.fcf[0] <= 0 or d.fcf[-1] <= 0 else (d.fcf[-1] / d.fcf[0]) ** 0.25 - 1
    d.net_margin_delta_pp = (d.net_margin[-1] - d.net_margin[0]) * 100
    d.share_change = d.diluted_shares[-1] / d.diluted_shares[0] - 1

    # Deterministic 5y weekly price path: growth, a mid-window crash, recovery.
    rng = random.Random(20260703)
    n_weeks = 261
    start = today - dt.timedelta(weeks=n_weeks - 1)
    dates, closes = [], []
    price = 40.0
    for i in range(n_weeks):
        t = i / n_weeks
        drift = 0.0035 if not 0.55 < t < 0.68 else -0.022  # crash window
        price *= math.exp(drift + rng.gauss(0, 0.028))
        dates.append(start + dt.timedelta(weeks=i))
        closes.append(round(price, 2))
    build_price_metrics(
        PriceSeries(symbol="DEMO", dates=dates, closes=closes, source="synthetic"), d
    )
    return d

"""CSV export — the table-view twin of the dashboard (and the audit trail)."""
from __future__ import annotations

import csv
from typing import Optional

from .metrics import DashboardData


def export_fundamentals_csv(d: DashboardData, path: str) -> None:
    rows = [
        ("revenue_usd", d.revenue),
        ("revenue_yoy", d.revenue_yoy),
        ("gross_margin", d.gross_margin),
        ("operating_margin", d.operating_margin),
        ("net_margin", d.net_margin),
        ("net_income_usd", d.net_income),
        ("operating_cash_flow_usd", d.cfo),
        ("free_cash_flow_usd", d.fcf),
        ("accruals_ratio", d.accruals_ratio),
        ("cash_conversion_cfo_over_ni", d.cash_conversion),
        ("diluted_shares", d.diluted_shares),
        ("total_debt_usd", d.total_debt),
        ("cash_and_equivalents_usd", d.cash),
    ]

    def cell(v: Optional[float]) -> str:
        return "" if v is None else repr(v)

    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([f"# {d.company} ({d.ticker}) — generated {d.generated.isoformat()}"])
        if d.demo:
            w.writerow(["# DEMO DATA — synthetic company, not a real filer"])
        w.writerow(["# Source: SEC EDGAR XBRL annual filings; latest amendment wins"])
        for concept, tag in sorted(d.tags_used.items()):
            w.writerow([f"# xbrl_tag {concept} = {tag}"])
        w.writerow(["metric"] + d.fy_labels)
        w.writerow(["fiscal_year_end"] + [e.isoformat() for e in d.fy_ends])
        for name, series in rows:
            w.writerow([name] + [cell(v) for v in series])


def export_prices_csv(d: DashboardData, path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([f"# {d.ticker} daily close (split-adjusted) — {d.price_source}"])
        w.writerow(["date", "close", "drawdown"])
        for date, close, dd in zip(d.price_dates, d.price_closes, d.drawdown):
            w.writerow([date.isoformat(), repr(close), f"{dd:.6f}"])

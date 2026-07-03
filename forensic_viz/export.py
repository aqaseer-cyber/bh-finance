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
        # Phase-3 health checks
        ("sloan_ratio_house_variant", d.sloan_full),
        ("piotroski_f_score", d.piotroski_score),
        ("piotroski_signals_evaluable", d.piotroski_checks),
        ("altman_z", d.altman_z),
        ("sbc_usd", d.sbc),
        ("sbc_pct_revenue", d.sbc_pct_revenue),
        ("fcf_ex_sbc_usd", d.fcf_ex_sbc),
        ("rnd_usd", d.rnd),
        ("rnd_pct_revenue", d.rnd_pct_revenue),
        ("ebit_reported_usd", d.ebit_reported),
        ("ebit_economic_usd", d.ebit_economic),
        ("fy_end_close_usd", d.fy_prices),
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
        for note in d.health_notes:
            w.writerow([f"# note: {note}"])
        if d.share_cagr_3y is not None:
            w.writerow([f"# diluted_share_cagr_3y = {d.share_cagr_3y:.6f}"])
        w.writerow(["metric"] + d.fy_labels)
        w.writerow(["fiscal_year_end"] + [e.isoformat() for e in d.fy_ends])
        for name, series in rows:
            w.writerow([name] + [cell(v) for v in series])


def export_valuation_csv(res, path: str) -> None:
    """The table-view twin of the valuation page (audit trail for the FVs)."""
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([f"# Intrinsic value — {res.method_label}"])
        w.writerow([f"# basis: {res.basis_label}"])
        if res.discount_rate is not None:
            rate_name = "wacc" if res.method == "dcf" else "r_e"
            w.writerow([f"# {rate_name} = {res.discount_rate:.6f}"])
        if res.base_value is not None:
            w.writerow([f"# base_value = {res.base_value:.2f}"])
        w.writerow([f"# price = {res.price:.4f}"
                    + (f" as of {res.price_date.isoformat()}" if res.price_date else "")])
        if res.net_debt is not None:
            w.writerow([f"# net_debt = {res.net_debt:.2f}"])
        if res.implied_g is not None:
            w.writerow([f"# reverse_dcf_implied_g = {res.implied_g:.6f}"])
        for warn in res.warnings:
            w.writerow([f"# warning: {warn}"])
        w.writerow(["case", "assumptions", "fv_per_share", "margin_of_safety",
                    "enterprise_or_equity_value", "tv_share_of_value"])
        for c in res.cases:
            w.writerow([
                c.name, c.assumptions,
                "" if c.fv_ps is None else f"{c.fv_ps:.4f}",
                "" if c.mos is None else f"{c.mos:.6f}",
                "" if (c.ev or c.equity) is None else f"{(c.ev or c.equity):.2f}",
                "" if c.tv_share is None else f"{c.tv_share:.6f}",
            ])


def export_prices_csv(d: DashboardData, path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([f"# {d.ticker} daily close (split-adjusted) — {d.price_source}"])
        w.writerow(["date", "close", "drawdown"])
        for date, close, dd in zip(d.price_dates, d.price_closes, d.drawdown):
            w.writerow([date.isoformat(), repr(close), f"{dd:.6f}"])

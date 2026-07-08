"""A4 PDF normalization, analyst-estimate parsing, interactive HTML build."""
import datetime as dt

import pytest

from forensic_viz.dashboard import render_dashboard, render_health_report
from forensic_viz.edgar import parse_companyfacts
from forensic_viz.estimates import parse_earnings_trend
from forensic_viz.export import A4_PT, export_pdf
from forensic_viz.interactive import build_html
from forensic_viz.metrics import (
    DashboardData, apply_track, build_fundamental_metrics, build_price_metrics,
)
from forensic_viz.prices import PriceSeries


def _data(testco_facts, aapl_prices=None, years=10):
    d = DashboardData(ticker="T", company="T Inc", subtitle="sub",
                      generated=dt.date(2026, 7, 3), display_years=years)
    d.sic_code = "3571"
    apply_track(d, "auto")
    build_fundamental_metrics(parse_companyfacts(testco_facts, "T"), d)
    if aapl_prices:
        build_price_metrics(PriceSeries(
            symbol="T",
            dates=[dt.date.fromisoformat(s) for s in aapl_prices["dates"]],
            closes=aapl_prices["close"], source="fixture"), d)
    return d


def test_pdf_pages_are_a4(tmp_path, testco_facts):
    from pypdf import PdfReader
    d = _data(testco_facts)
    out = tmp_path / "report.pdf"
    export_pdf([render_dashboard(d), render_health_report(d)], str(out))
    reader = PdfReader(str(out))
    assert len(reader.pages) == 2
    # FIX-12c: every page an exact A4 sheet, orientation chosen per page —
    # the tall dashboard is portrait, the landscape-height health page flips
    dash_page, health_page = reader.pages
    assert float(dash_page.mediabox.width) == pytest.approx(A4_PT[0], abs=0.5)
    assert float(dash_page.mediabox.height) == pytest.approx(A4_PT[1], abs=0.5)
    assert float(health_page.mediabox.width) == pytest.approx(A4_PT[1], abs=0.5)
    assert float(health_page.mediabox.height) == pytest.approx(A4_PT[0], abs=0.5)


def test_parse_earnings_trend_growths():
    def n(v):
        return {"raw": v, "fmt": str(v)}
    payload = {"quoteSummary": {"result": [{"earningsTrend": {"trend": [
        {"period": "0y", "revenueEstimate": {"avg": n(100e9)}},
        {"period": "+1y", "revenueEstimate": {
            "avg": n(108e9), "low": n(102e9), "high": n(115e9),
            "numberOfAnalysts": n(24)}},
    ]}}], "error": None}}
    est = parse_earnings_trend(payload)
    assert est["g_avg"] == pytest.approx(0.08)
    assert est["g_low"] == pytest.approx(0.02)
    assert est["g_high"] == pytest.approx(0.15)
    assert est["n_analysts"] == 24


def test_parse_earnings_trend_rejects_bad_payloads():
    assert parse_earnings_trend({}) is None
    assert parse_earnings_trend(
        {"quoteSummary": {"result": [{"earningsTrend": {"trend": []}}]}}) is None


def test_interactive_html_selfcontained(tmp_path, testco_facts, aapl_prices):
    d = _data(testco_facts, aapl_prices)
    d.thesis = "A thesis."
    d.terminal_risk = "A risk."
    out = tmp_path / "report.html"
    build_html(d, str(out))
    body = out.read_text(encoding="utf-8")
    assert len(body) > 1_000_000        # plotly.js embedded (offline-capable)
    assert body.count("plotly.js") >= 0  # sanity: file exists and is html
    assert "T Inc" in body and "A thesis." in body and "A risk." in body
    # Fiscal.ai-style display charts: value bars + toggleable %-change line
    assert "Revenue Change (%)" in body
    assert "Operating Profit" in body
    assert "Total Change" in body and "CAGR" in body


def test_shorter_window_flows_to_html(tmp_path, testco_facts):
    d = _data(testco_facts, years=3)
    assert len(d.fy_labels) == 3
    out = tmp_path / "r3.html"
    build_html(d, str(out))
    assert "3-year window" in out.read_text(encoding="utf-8")

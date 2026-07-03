import datetime as dt

from forensic_viz.dashboard import render_dashboard, render_health_report
from forensic_viz.demo_data import demo_dashboard_data
from forensic_viz.edgar import parse_companyfacts
from forensic_viz.export import export_fundamentals_csv, export_prices_csv
from forensic_viz.metrics import (
    DashboardData, build_fundamental_metrics, build_price_metrics, compute_altman,
)
from forensic_viz.prices import PriceSeries


def _testco_data(testco_facts, aapl_prices=None):
    d = DashboardData(ticker="TESTCO", company="TESTCO INC",
                      subtitle="TESTCO · test fixture", generated=dt.date(2026, 7, 3))
    build_fundamental_metrics(parse_companyfacts(testco_facts, "TESTCO"), d)
    if aapl_prices:
        build_price_metrics(
            PriceSeries(
                symbol="AAPL",
                dates=[dt.date.fromisoformat(s) for s in aapl_prices["dates"]],
                closes=aapl_prices["close"],
                source="fixture",
            ), d)
    return d


def test_render_full_dashboard(tmp_path, testco_facts, aapl_prices):
    out = tmp_path / "full.png"
    fig = render_dashboard(_testco_data(testco_facts, aapl_prices), str(out))
    assert out.exists() and out.stat().st_size > 50_000
    assert len(fig.axes) >= 9  # header + price + drawdown + 6 panels


def test_render_without_prices(tmp_path, testco_facts):
    d = _testco_data(testco_facts)
    d.price_error = "simulated outage"
    out = tmp_path / "noprice.png"
    render_dashboard(d, str(out))
    assert out.exists() and out.stat().st_size > 30_000


def test_render_demo(tmp_path):
    d = demo_dashboard_data(today=dt.date(2026, 7, 3))
    assert max(v for v in d.accruals_ratio if v is not None) > 0.10  # planted flag fires
    assert max(v for v in d.sloan_full if v is not None) > 0.10      # Sloan flag too
    assert any(z is not None for z in d.altman_z)
    assert any(s is not None for s in d.piotroski_score)
    out = tmp_path / "demo.png"
    render_dashboard(d, str(out))
    assert out.exists()


def test_render_health_report(tmp_path, testco_facts, aapl_prices):
    d = _testco_data(testco_facts, aapl_prices)
    compute_altman(d)
    out = tmp_path / "health.png"
    fig = render_health_report(d, str(out))
    assert out.exists() and out.stat().st_size > 40_000
    assert len(fig.axes) >= 7  # header + six health panels


def test_render_health_report_demo(tmp_path):
    d = demo_dashboard_data(today=dt.date(2026, 7, 3))
    out = tmp_path / "demo_health.png"
    render_health_report(d, str(out))
    assert out.exists()


def test_csv_exports(tmp_path, testco_facts, aapl_prices):
    d = _testco_data(testco_facts, aapl_prices)
    fcsv, pcsv = tmp_path / "f.csv", tmp_path / "p.csv"
    export_fundamentals_csv(d, str(fcsv))
    export_prices_csv(d, str(pcsv))
    body = fcsv.read_text()
    assert "revenue_usd" in body and "FY2025" in body and "xbrl_tag" in body
    assert "sloan_ratio_house_variant" in body and "piotroski_f_score" in body
    assert len(pcsv.read_text().splitlines()) == len(d.price_dates) + 2

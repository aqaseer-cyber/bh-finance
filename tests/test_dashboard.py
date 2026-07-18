import datetime as dt

from forensic_viz.dashboard import (
    render_dashboard, render_health_report, render_valuation,
)
from forensic_viz.edgar import parse_companyfacts
from forensic_viz.metrics import (
    DashboardData, build_fundamental_metrics, build_price_metrics, compute_altman,
)
from forensic_viz.prices import PriceSeries
from forensic_viz.valuation import CaseInputs, ValuationInputs, build_valuation


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


def test_render_health_report(tmp_path, testco_facts, aapl_prices):
    d = _testco_data(testco_facts, aapl_prices)
    compute_altman(d)
    out = tmp_path / "health.png"
    fig = render_health_report(d, str(out))
    assert out.exists() and out.stat().st_size > 40_000
    assert len(fig.axes) >= 7  # header + six health panels


def _valuation(d):
    return build_valuation(d, ValuationInputs(
        method="dcf", discount_rate=0.09,
        cases={"Bear": CaseInputs(g0=0.02, g_term=0.02),
               "Base": CaseInputs(g0=0.05, g_term=0.025),
               "Bull": CaseInputs(g0=0.09, g_term=0.03)}))


def test_render_valuation_page(tmp_path, testco_facts, aapl_prices):
    d = _testco_data(testco_facts, aapl_prices)
    res = _valuation(d)
    out = tmp_path / "val.png"
    fig = render_valuation(d, res, str(out))
    assert out.exists() and out.stat().st_size > 30_000
    assert len(fig.axes) >= 3  # header + field + table

import datetime as dt

from forensic_viz.dashboard import (
    render_decision, render_expectations, render_quality, render_report,
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


def test_render_decision_page(tmp_path, testco_facts, aapl_prices):
    d = _testco_data(testco_facts, aapl_prices)
    res = _valuation(d)
    from forensic_viz.verdict import build_verdict
    v = build_verdict(d, res._inputs, res, rating="Hold")
    out = tmp_path / "p1.png"
    fig = render_decision(d, res, v, out_path=str(out))
    assert out.exists() and out.stat().st_size > 50_000
    assert len(fig.axes) >= 6  # header, base quality, rating, field, ladder…
    texts = " ".join(t.get_text() for ax in fig.axes for t in ax.texts)
    assert "Base quality" in texts


def test_render_without_prices(tmp_path, testco_facts):
    """v3 R3b: a price outage degrades to declared absence, all six
    sections still render."""
    d = _testco_data(testco_facts)
    d.price_error = "simulated outage"
    figs = render_report(d)
    assert len(figs) >= 6
    texts = " ".join(t.get_text() for fig in figs
                     for ax in fig.axes for t in ax.texts)
    assert "simulated outage" in texts   # the appendix declares it


def test_render_quality_page(tmp_path, testco_facts, aapl_prices):
    d = _testco_data(testco_facts, aapl_prices)
    compute_altman(d)
    out = tmp_path / "p4.png"
    fig = render_quality(d, str(out))
    assert out.exists() and out.stat().st_size > 40_000
    assert len(fig.axes) >= 9  # header + eight quality panels


def _valuation(d):
    return build_valuation(d, ValuationInputs(
        method="dcf", discount_rate=0.09,
        cases={"Bear": CaseInputs(g0=0.02, g_term=0.02),
               "Base": CaseInputs(g0=0.05, g_term=0.025),
               "Bull": CaseInputs(g0=0.09, g_term=0.03)}))


def test_render_expectations_page(tmp_path, testco_facts, aapl_prices):
    d = _testco_data(testco_facts, aapl_prices)
    res = _valuation(d)
    from forensic_viz.verdict import build_verdict
    v = build_verdict(d, res._inputs, res)
    out = tmp_path / "p2.png"
    fig = render_expectations(d, res, v, out_path=str(out))
    assert out.exists() and out.stat().st_size > 30_000
    assert len(fig.axes) >= 5  # header + bridge + table + sens + stress

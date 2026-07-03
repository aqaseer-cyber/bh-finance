import datetime as dt

import pytest

from forensic_viz.edgar import parse_companyfacts
from forensic_viz.metrics import (
    DashboardData, build_fundamental_metrics, build_price_metrics,
    fmt_count, fmt_money, fmt_pct,
)
from forensic_viz.prices import PriceSeries
from tests.conftest import ASSETS, CAPEX, CFO, COST, NI, REVENUE


@pytest.fixture
def data(testco_facts):
    d = DashboardData(ticker="TESTCO", company="TESTCO INC", subtitle="",
                      generated=dt.date(2026, 7, 3))
    build_fundamental_metrics(parse_companyfacts(testco_facts, "TESTCO"), d)
    return d


def test_displays_five_years_keeps_sixth_for_derivations(data):
    assert data.fy_labels == [f"FY{y}" for y in range(2021, 2026)]
    assert data.revenue == [REVENUE[y] for y in range(2021, 2026)]


def test_first_displayed_yoy_uses_prior_fetched_year(data):
    expected = REVENUE[2021] / REVENUE[2020] - 1
    assert data.revenue_yoy[0] == pytest.approx(expected)


def test_gross_margin_derived_from_cost_of_revenue(data):
    assert data.gross_margin[0] == pytest.approx(
        (REVENUE[2021] - COST[2021]) / REVENUE[2021])


def test_fcf_is_cfo_minus_capex(data):
    assert data.fcf[-1] == pytest.approx(CFO[2025] - CAPEX[2025])


def test_accruals_ratio_uses_average_assets(data):
    expected = (NI[2025] - CFO[2025]) / ((ASSETS[2025] + ASSETS[2024]) / 2)
    assert data.accruals_ratio[-1] == pytest.approx(expected)
    assert all(r < 0 for r in data.accruals_ratio)  # CFO > NI throughout


def test_total_debt_sums_current_and_noncurrent(data):
    assert data.total_debt == [350e6] * 5


def test_revenue_cagr(data):
    expected = (REVENUE[2025] / REVENUE[2021]) ** 0.25 - 1
    assert data.revenue_cagr == pytest.approx(expected)


def test_drawdown_and_total_return():
    d = DashboardData(ticker="X", company="X", subtitle="",
                      generated=dt.date(2026, 7, 3))
    dates = [dt.date(2024, 1, i + 1) for i in range(5)]
    build_price_metrics(
        PriceSeries(symbol="X", dates=dates, closes=[100, 120, 90, 96, 110],
                    source="test"), d)
    assert d.drawdown[0] == 0
    assert d.max_drawdown == pytest.approx(90 / 120 - 1)
    assert d.max_drawdown_date == dates[2]
    assert d.total_return == pytest.approx(0.10)


def test_formatters():
    assert fmt_money(394.33e9) == "$394.3B"
    assert fmt_money(-1.25e9) == "-$1.2B"
    assert fmt_money(None) == "–"
    assert fmt_count(15.4e9) == "15.40B"
    assert fmt_pct(0.1234) == "12.3%"
    assert fmt_pct(0.05, signed=True) == "+5.0%"

import datetime as dt

import pytest

from forensic_viz.edgar import parse_companyfacts
from forensic_viz.metrics import (
    DashboardData, build_fundamental_metrics, build_price_metrics,
    compute_altman, fmt_count, fmt_money, fmt_pct,
)
from forensic_viz.prices import PriceSeries
from tests.conftest import (
    AC, ASSETS, CAPEX, CFI, CFO, COST, LC, NI, OPINC, RE, REVENUE, RND, SBC,
    SHARES, TL,
)


@pytest.fixture
def data(testco_facts):
    d = DashboardData(ticker="TESTCO", company="TESTCO INC", subtitle="",
                      generated=dt.date(2026, 7, 3))
    build_fundamental_metrics(parse_companyfacts(testco_facts, "TESTCO"), d)
    return d


def test_displays_ten_years_keeps_eleventh_for_derivations(data):
    assert data.fy_labels == [f"FY{y}" for y in range(2016, 2026)]
    assert data.revenue == [REVENUE[y] for y in range(2016, 2026)]


def test_first_displayed_yoy_uses_prior_fetched_year(data):
    expected = REVENUE[2016] / REVENUE[2015] - 1
    assert data.revenue_yoy[0] == pytest.approx(expected)


def test_gross_margin_derived_from_cost_of_revenue(data):
    assert data.gross_margin[0] == pytest.approx(
        (REVENUE[2016] - COST[2016]) / REVENUE[2016])


def test_fcf_is_cfo_minus_capex(data):
    assert data.fcf[-1] == pytest.approx(CFO[2025] - CAPEX[2025])


def test_accruals_ratio_uses_average_assets(data):
    expected = (NI[2025] - CFO[2025]) / ((ASSETS[2025] + ASSETS[2024]) / 2)
    assert data.accruals_ratio[-1] == pytest.approx(expected)
    assert all(r < 0 for r in data.accruals_ratio)  # CFO > NI throughout


def test_total_debt_sums_current_and_noncurrent(data):
    assert data.total_debt == [350e6] * 10


def test_revenue_cagr(data):
    expected = (REVENUE[2025] / REVENUE[2016]) ** (1 / 9) - 1
    assert data.revenue_cagr == pytest.approx(expected)


# ------------------------------------------------------- Phase-3 health checks

def test_sloan_house_variant(data):
    expected = (NI[2025] - CFO[2025] - CFI[2025]) / ((ASSETS[2025] + ASSETS[2024]) / 2)
    assert data.sloan_full[-1] == pytest.approx(expected)


def test_piotroski_score_on_steady_grower(data):
    # TESTCO: ROA>0 (1), CFO>0 (1), flat ROA (0), CFO>NI (1), falling leverage
    # as assets grow (1), flat current ratio (0), rising share count (0),
    # flat gross margin (0), flat asset turnover (0) -> 4 of 9
    assert data.piotroski_checks[-1] == 9
    assert data.piotroski_score[-1] == 4


def test_sbc_and_dilution_line(data):
    assert data.sbc_pct_revenue[-1] == pytest.approx(0.05)
    assert data.fcf_ex_sbc[-1] == pytest.approx(CFO[2025] - CAPEX[2025] - SBC[2025])
    expected_cagr = (SHARES[2025] / SHARES[2022]) ** (1 / 3) - 1
    assert data.share_cagr_3y == pytest.approx(expected_cagr)


def test_rnd_capitalization_audit(data):
    assert data.rnd_material  # 8% of revenue > 5% threshold
    amort = sum(RND[y] for y in range(2021, 2025)) / 5
    assert data.ebit_economic[-1] == pytest.approx(OPINC[2025] + RND[2025] - amort)
    # first displayed years lack the 4-year R&D history in the fetched window
    assert data.ebit_economic[0] is None
    assert data.ebit_reported[-1] == pytest.approx(OPINC[2025])


def test_altman_z_with_fy_prices(data):
    data.fy_prices = [10.0] * len(data.fy_labels)
    compute_altman(data)
    r = REVENUE[2025]
    expected = (1.2 * (AC[2025] - LC[2025]) / ASSETS[2025]
                + 1.4 * RE[2025] / ASSETS[2025]
                + 3.3 * OPINC[2025] / ASSETS[2025]
                + 0.6 * (10.0 * SHARES[2025]) / TL[2025]
                + 1.0 * r / ASSETS[2025])
    assert data.altman_z[-1] == pytest.approx(expected)


def test_altman_suppressed_for_financials(data):
    data.is_financial_sector = True
    data.fy_prices = [10.0] * len(data.fy_labels)
    compute_altman(data)
    assert all(z is None for z in data.altman_z)


def test_fy_prices_attach_from_price_series(data):
    dates, closes = [], []
    day = dt.date(2015, 6, 1)
    while day <= dt.date(2026, 1, 15):
        if day.weekday() < 5:
            dates.append(day)
            closes.append(50.0)
        day += dt.timedelta(days=1)
    build_price_metrics(PriceSeries("T", dates, closes, "test"), data)
    compute_altman(data)
    assert all(p == 50.0 for p in data.fy_prices)
    assert all(z is not None for z in data.altman_z)


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

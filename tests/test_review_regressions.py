"""Regression tests for defects found in the adversarial review."""
import datetime as dt

import pytest

from forensic_viz.edgar import parse_companyfacts
from forensic_viz.metrics import DashboardData, build_fundamental_metrics
from forensic_viz.prices import PriceError, parse_yahoo_chart
from tests.conftest import FY_YEARS, REVENUE, _annual, _usd


def test_revenue_total_beats_606_subtotal_on_coverage_tie(testco_facts):
    """Lessor/bank pattern: both tags cover every year; the larger total must
    win, not the ASC-606 subtotal that happens to sit first in the list."""
    total = [_annual(y, REVENUE[y] * 4) for y in FY_YEARS]
    testco_facts["facts"]["us-gaap"]["Revenues"] = _usd(total)
    f = parse_companyfacts(testco_facts, "URI")
    assert f.tags_used["revenue"] == "Revenues"  # full coverage, no fill note
    assert f.series["revenue"][-1] == REVENUE[2025] * 4


def test_newest_fiscal_year_survives_tag_migration(testco_facts):
    """First 10-K after a tag migration: the union spine must include the
    just-filed year even though the old (still better-covered) tag lacks it,
    and the gap-fill must pull the year's value from the new tag."""
    gaap = testco_facts["facts"]["us-gaap"]
    gaap["Revenues"] = _usd([_annual(y, REVENUE[y]) for y in range(2014, 2025)])
    gaap["RevenueFromContractWithCustomerExcludingAssessedTax"] = _usd(
        [_annual(y, REVENUE[y]) for y in (2024, 2025)])
    f = parse_companyfacts(testco_facts, "TESTCO")
    assert f.fy_ends[-1] == dt.date(2025, 12, 31)
    assert f.series["net_income"][-1] is not None
    assert f.series["revenue"][-1] == REVENUE[2025]  # filled from the new tag
    assert "FY2025 from RevenueFromContractWithCustomerExcludingAssessedTax" \
        in f.tags_used["revenue"]


def test_yahoo_zero_closes_are_dropped():
    n = 40
    closes = [0.0] + [100.0 + i for i in range(1, n)]  # leading Yahoo glitch row
    payload = {"chart": {"result": [{
        "timestamp": [1700000000 + i * 86400 for i in range(n)],
        "indicators": {"quote": [{"close": closes}]},
    }], "error": None}}
    series = parse_yahoo_chart(payload, "TEST")
    assert len(series.closes) == n - 1
    assert min(series.closes) > 0


def test_yahoo_all_zero_closes_raise():
    payload = {"chart": {"result": [{
        "timestamp": [1700000000 + i * 86400 for i in range(40)],
        "indicators": {"quote": [{"close": [0.0] * 40}]},
    }], "error": None}}
    with pytest.raises(PriceError):
        parse_yahoo_chart(payload, "TEST")


def test_negative_revenue_year_yields_no_margins(testco_facts):
    gaap = testco_facts["facts"]["us-gaap"]
    rows = gaap["RevenueFromContractWithCustomerExcludingAssessedTax"]["units"]["USD"]
    for row in rows:  # flip the FY2025 total negative (fair-value-loss pattern)
        if row["end"] == "2025-12-31" and row["form"] == "10-K":
            row["val"] = -50e6
    d = DashboardData(ticker="T", company="T", subtitle="",
                      generated=dt.date(2026, 7, 3))
    build_fundamental_metrics(parse_companyfacts(testco_facts, "T"), d)
    assert d.gross_margin[-1] is None
    assert d.operating_margin[-1] is None
    assert d.net_margin[-1] is None
    assert d.revenue[-1] == -50e6  # the raw value still shows in the bar/CSV

import datetime as dt

import pytest

from forensic_viz.edgar import EdgarError, parse_companyfacts
from tests.conftest import ASSETS, CFO, NI, REVENUE, SHARES


def test_fiscal_year_spine_takes_last_eleven_years(testco_facts):
    f = parse_companyfacts(testco_facts, "TESTCO")
    assert f.entity_name == "TESTCO INC"
    assert f.fy_ends == [dt.date(y, 12, 31) for y in range(2015, 2026)]


def test_revenue_tag_migration_prefers_recent_coverage(testco_facts):
    f = parse_companyfacts(testco_facts, "TESTCO")
    # the ASC-606 tag wins on recency; pre-migration years come from Revenues,
    # and the mixed-tag fill is recorded in the audit string
    assert f.tags_used["revenue"].startswith(
        "RevenueFromContractWithCustomerExcludingAssessedTax")
    assert "from Revenues" in f.tags_used["revenue"]
    assert f.series["revenue"] == [REVENUE[y] for y in range(2015, 2026)]


def test_amended_10ka_value_wins(testco_facts):
    f = parse_companyfacts(testco_facts, "TESTCO")
    fy2023 = f.fy_ends.index(dt.date(2023, 12, 31))
    assert f.series["revenue"][fy2023] == REVENUE[2023]  # not the original value


def test_quarterly_rows_are_excluded(testco_facts):
    f = parse_companyfacts(testco_facts, "TESTCO")
    # If 10-Q rows leaked in, FY2025 would be a quarter's value
    assert f.series["revenue"][-1] == REVENUE[2025]


def test_flows_shares_and_instants_align(testco_facts):
    f = parse_companyfacts(testco_facts, "TESTCO")
    years = range(2015, 2026)
    assert f.series["net_income"] == [NI[y] for y in years]
    assert f.series["cfo"] == [CFO[y] for y in years]
    assert f.series["diluted_shares"] == [SHARES[y] for y in years]
    assert f.series["total_assets"] == [ASSETS[y] for y in years]
    assert f.series["lt_debt_noncurrent"] == [300e6] * 11
    assert f.series["lt_debt_current"] == [50e6] * 11


def test_missing_gross_profit_leaves_none(testco_facts):
    f = parse_companyfacts(testco_facts, "TESTCO")
    assert f.series["gross_profit"] == [None] * 11  # derived later in metrics


def test_ifrs_only_filer_is_rejected():
    with pytest.raises(EdgarError, match="IFRS"):
        parse_companyfacts(
            {"entityName": "X", "facts": {"ifrs-full": {}}}, "XFRS")

"""Phase-2 unit economics: working-capital days, marginal unit, ROIC/ROE,
bank NIM, insurance ratios, and the unit-economics page render."""
import datetime as dt

import pytest

from forensic_viz.dashboard import render_unit_economics
from forensic_viz.edgar import parse_companyfacts
from forensic_viz.metrics import (
    DashboardData, apply_track, build_fundamental_metrics,
)
from tests.conftest import (
    AP, AR, ASSETS, CASH, COST, EQUITY, INV, NI, OPINC, REVENUE, _annual, _usd,
)


def _metrics(testco_facts, track="standard", sic="3571"):
    d = DashboardData(ticker="T", company="T Inc", subtitle="",
                      generated=dt.date(2026, 7, 3))
    d.sic_code = sic
    apply_track(d, track)
    build_fundamental_metrics(parse_companyfacts(testco_facts, "T"), d)
    return d


def test_working_capital_days(testco_facts):
    d = _metrics(testco_facts)
    avg_inv = (INV[2025] + INV[2024]) / 2
    avg_ar = (AR[2025] + AR[2024]) / 2
    avg_ap = (AP[2025] + AP[2024]) / 2
    assert d.dsi[-1] == pytest.approx(avg_inv / COST[2025] * 365)
    assert d.dso[-1] == pytest.approx(avg_ar / REVENUE[2025] * 365)
    assert d.dpo[-1] == pytest.approx(avg_ap / COST[2025] * 365)
    assert d.ccc[-1] == pytest.approx(d.dsi[-1] + d.dso[-1] - d.dpo[-1])


def test_incremental_margin_matches_linear_fixture(testco_facts):
    # OPINC is exactly 18% of revenue every year -> ΔEBIT/ΔRev = 18% exactly.
    d = _metrics(testco_facts)
    assert d.incremental_op_margin[-1] == pytest.approx(0.18)


def test_incremental_margin_none_when_revenue_flat(testco_facts):
    gaap = testco_facts["facts"]["us-gaap"]
    rows = gaap["RevenueFromContractWithCustomerExcludingAssessedTax"]["units"]["USD"]
    for row in rows:  # make FY2025 revenue == FY2024 (flat year)
        if row["end"] == "2025-12-31" and row["form"] == "10-K":
            row["val"] = REVENUE[2024]
    d = _metrics(testco_facts)
    assert d.incremental_op_margin[-1] is None  # |ΔRev| below the 2% gate


def test_roic_and_roe(testco_facts):
    d = _metrics(testco_facts)

    def invested(y):
        return EQUITY[y] + 350e6 - CASH[y]  # LTD_NC + LTD_C = 350e6 in fixture

    avg_ic = (invested(2025) + invested(2024)) / 2
    assert d.roic[-1] == pytest.approx(OPINC[2025] * (1 - 0.21) / avg_ic)
    avg_eq = (EQUITY[2025] + EQUITY[2024]) / 2
    assert d.roe[-1] == pytest.approx(NI[2025] / avg_eq)


def test_bank_nim_proxy(testco_facts):
    gaap = testco_facts["facts"]["us-gaap"]
    gaap["InterestIncomeExpenseNet"] = _usd(
        [_annual(y, REVENUE[y] * 0.04) for y in range(2014, 2026)])
    d = _metrics(testco_facts, track="bank", sic="6022")
    avg_assets = (ASSETS[2025] + ASSETS[2024]) / 2
    assert d.nim_proxy[-1] == pytest.approx(REVENUE[2025] * 0.04 / avg_assets)


def test_insurance_loss_and_combined_ratio(testco_facts):
    gaap = testco_facts["facts"]["us-gaap"]
    years = list(range(2014, 2026))
    gaap["PremiumsEarnedNet"] = _usd([_annual(y, REVENUE[y] * 0.9) for y in years])
    gaap["PolicyholderBenefitsAndClaimsIncurredNet"] = _usd(
        [_annual(y, REVENUE[y] * 0.60) for y in years])
    gaap["OtherUnderwritingExpense"] = _usd(
        [_annual(y, REVENUE[y] * 0.27) for y in years])
    d = _metrics(testco_facts, track="insurance", sic="6311")
    assert d.loss_ratio[-1] == pytest.approx(0.60 / 0.9)
    assert d.combined_ratio[-1] == pytest.approx((0.60 + 0.27) / 0.9)


def test_render_unit_economics_all_tracks(tmp_path, testco_facts):
    for track in ("standard", "bank", "insurance", "reit", "sotp"):
        d = _metrics(testco_facts, track=track)
        d.thesis = "A thesis sentence."
        d.terminal_risk = "A terminal risk sentence."
        out = tmp_path / f"unit_{track}.png"
        fig = render_unit_economics(d, str(out))
        assert out.exists() and out.stat().st_size > 30_000
        assert len(fig.axes) >= 5  # header + four panels


def test_display_years_window(testco_facts):
    d = DashboardData(ticker="T", company="T Inc", subtitle="",
                      generated=dt.date(2026, 7, 3), display_years=5)
    d.sic_code = "3571"
    apply_track(d, "auto")
    build_fundamental_metrics(parse_companyfacts(testco_facts, "T"), d)
    assert d.fy_labels == [f"FY{y}" for y in range(2021, 2026)]
    assert len(d.revenue) == 5
    assert d.dsi[-1] is not None  # derived series follow the window


def test_ccc_panel_degrades_to_operating_cycle(testco_facts):
    """Payables untagged (no DPO): the CCC panel must show the operating
    cycle (DSI + DSO) with an honest label instead of a dead placeholder."""
    d = _metrics(testco_facts)
    d.dpo = [None] * len(d.fy_labels)
    d.ccc = [None] * len(d.fy_labels)
    fig = render_unit_economics(d)
    texts = [t.get_text() for ax in fig.axes for t in ax.texts]
    texts += [t.get_text() for t in fig.texts]
    joined = " ".join(texts)
    assert "Operating cycle" in joined
    assert "payables (DPO) not tagged" in joined
    assert "Needs the working-capital legs" not in joined
    # the left panel's subtitle explains the missing leg too
    assert "DPO: payables not tagged in XBRL" in joined


def test_ccc_placeholder_only_when_no_legs_at_all(testco_facts):
    d = _metrics(testco_facts)
    for name in ("dsi", "dso", "dpo", "ccc"):
        setattr(d, name, [None] * len(d.fy_labels))
    fig = render_unit_economics(d)
    joined = " ".join(t.get_text() for ax in fig.axes for t in ax.texts)
    joined += " ".join(t.get_text() for t in fig.texts)
    assert "Needs the working-capital legs" in joined

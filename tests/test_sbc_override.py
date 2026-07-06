"""FIX-11d: SBC/interest tag rotation + the analyst SBC override lever."""
import datetime as dt

import pytest

from conftest import FY_YEARS, SBC, build_testco_companyfacts, _annual, _usd
from forensic_viz.edgar import parse_companyfacts
from forensic_viz.metrics import DashboardData, apply_track, build_fundamental_metrics
from forensic_viz.valuation import (
    CaseInputs, ValuationInputs, build_valuation, effective_sbc,
    reverse_dcf_implied_g, sbc_series_warning,
)
from forensic_viz.verdict import build_verdict


def _data(facts) -> DashboardData:
    d = DashboardData(ticker="T", company="T Inc", subtitle="",
                      generated=dt.date(2026, 7, 3))
    d.sic_code = "3571"
    apply_track(d, "auto")
    build_fundamental_metrics(parse_companyfacts(facts, "T"), d)
    d.last_close = 100.0
    d.price_dates = [dt.date(2026, 7, 1)]
    d.price_closes = [100.0]
    return d


def _vi():
    return ValuationInputs(method="dcf", discount_rate=0.09, cases={
        "Bear": CaseInputs(g0=0.02, g_term=0.01),
        "Base": CaseInputs(g0=0.05, g_term=0.02),
        "Bull": CaseInputs(g0=0.08, g_term=0.025)})


def test_interest_rotation_candidate_is_selected():
    """MELI-style: interest lives only under the …AndOtherFinancialCharges
    tag — it must be picked up instead of degrading to the spread proxy."""
    facts = build_testco_companyfacts()
    facts["facts"]["us-gaap"]["InterestExpenseAndOtherFinancialCharges"] = \
        _usd([_annual(y, 160e6) for y in FY_YEARS])
    f = parse_companyfacts(facts, "T")
    assert f.series["interest_expense"][-1] == pytest.approx(160e6)
    assert "InterestExpenseAndOtherFinancialCharges" in \
        f.tags_used["interest_expense"]


def _dead_sbc_facts():
    facts = build_testco_companyfacts()
    facts["facts"]["us-gaap"]["ShareBasedCompensation"] = _usd(
        [_annual(y, SBC[y]) for y in FY_YEARS if y <= 2018])  # dies FY2018
    return facts


def test_dead_sbc_series_warns_and_override_silences():
    d = _data(_dead_sbc_facts())
    assert d.sbc[-1] is None and any(v is not None for v in d.sbc)
    warn = sbc_series_warning(d)
    assert warn is not None and "SBC series ends FY2018" in warn
    res = build_valuation(d, _vi())
    assert any("SBC series ends FY2018" in w for w in res.warnings)
    d.sbc_override = 120e6
    assert sbc_series_warning(d) is None
    assert effective_sbc(d) == 120e6


def test_override_drives_track_b_in_valuation_and_verdict():
    d = _data(_dead_sbc_facts())
    d.sbc_override = 50e6
    vi = _vi()
    res = build_valuation(d, vi)
    # reverse-DCF basis (FIX-2) = Track B ex-SBC base over market EV
    base_a = [v for v in d.fcff if v is not None][-1]
    expected_g = reverse_dcf_implied_g(base_a - 50e6, 0.09, res.market_ev)
    assert res.implied_g == pytest.approx(expected_g)
    v = build_verdict(d, vi, res)
    # the verdict's Track B rides the same override: shifting it moves fv_b
    d2 = _data(_dead_sbc_facts())
    d2.sbc_override = 100e6
    res2 = build_valuation(d2, vi)
    v2 = build_verdict(d2, vi, res2)
    assert v.fv_b is not None and v2.fv_b is not None
    assert v2.fv_b < v.fv_b        # bigger SBC -> smaller ex-SBC base
    assert v.fv_a == pytest.approx(v2.fv_a)  # Track A untouched


def test_alive_series_without_override_is_unchanged(testco_facts):
    d = _data(testco_facts)
    assert effective_sbc(d) == pytest.approx(SBC[2025])
    assert sbc_series_warning(d) is None
    res = build_valuation(d, _vi())
    assert not any("SBC series ends" in w for w in res.warnings)

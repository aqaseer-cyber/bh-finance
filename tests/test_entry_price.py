"""FIX-16c: entry-price discipline — implied annual return via bisection
over the PRODUCTION dcf_fcff (no parallel math), the ±40% price ladder,
and the hurdle-price inverse."""
import datetime as dt

import pytest

from forensic_viz.explore import sandbox_compute
from forensic_viz.metrics import DashboardData
from forensic_viz.valuation import (
    HURDLE_RATE, CaseInputs, ValuationInputs, build_valuation, dcf_fcff,
    implied_return, price_for_return, price_irr_ladder,
)

BASE, G0, GT, BRIDGE, SHARES = 500e6, 0.06, 0.02, 6e8, 100e6


def _fv(r):
    return (dcf_fcff(BASE, r, G0, GT)["ev"] - BRIDGE) / SHARES


def test_implied_return_round_trips_the_discount_rate():
    for r_true in (0.07, 0.10, 0.15, 0.25, 0.45):
        price = _fv(r_true)
        got = implied_return(price, BASE, G0, GT, BRIDGE, SHARES)
        assert got == pytest.approx(r_true, abs=1e-5)


def test_implied_return_monotone_and_guarded():
    hi = implied_return(_fv(0.20), BASE, G0, GT, BRIDGE, SHARES)
    lo = implied_return(_fv(0.08), BASE, G0, GT, BRIDGE, SHARES)
    assert hi > lo                       # cheaper price -> higher return
    # outside the bracket / unusable inputs -> None, never an exception
    assert implied_return(_fv(0.61) * 0.5, BASE, G0, GT, BRIDGE, SHARES) is None
    assert implied_return(None, BASE, G0, GT, BRIDGE, SHARES) is None
    assert implied_return(50.0, 0.0, G0, GT, BRIDGE, SHARES) is None
    assert implied_return(50.0, BASE, G0, GT, BRIDGE, 0.0) is None


def test_price_for_return_inverts_implied_return():
    p15 = price_for_return(0.15, BASE, G0, GT, BRIDGE, SHARES)
    assert p15 == pytest.approx(_fv(0.15))
    assert implied_return(p15, BASE, G0, GT, BRIDGE, SHARES) == \
        pytest.approx(0.15, abs=1e-5)
    assert price_for_return(GT, BASE, G0, GT, BRIDGE, SHARES) is None
    assert price_for_return(0.15, None, G0, GT, BRIDGE, SHARES) is None


def test_price_irr_ladder_shape_and_endpoints():
    price = _fv(0.12)
    ladder = price_irr_ladder(price, BASE, G0, GT, BRIDGE, SHARES)
    assert len(ladder) == 9
    assert ladder[0][0] == pytest.approx(price * 0.6)
    assert ladder[-1][0] == pytest.approx(price * 1.4)
    mid_price, mid_r = ladder[4]
    assert mid_price == pytest.approx(price)
    assert mid_r == pytest.approx(0.12, abs=1e-5)
    # returns fall as the entry price rises (None rungs allowed at edges)
    rs = [r for _, r in ladder if r is not None]
    assert rs == sorted(rs, reverse=True)
    assert price_irr_ladder(None, BASE, G0, GT, BRIDGE, SHARES) == []


def _val_data():
    d = DashboardData(ticker="T", company="T Inc", subtitle="",
                      generated=dt.date(2026, 7, 12))
    d.last_close = 40.0
    d.price_dates = [dt.date(2026, 7, 10)]
    d.diluted_shares = [SHARES]
    d.fcf = [BASE]
    d.fcf_ex_sbc = [BASE - 50e6]
    d.effective_tax_rate = 0.21
    d.interest_expense = [None]
    d.fcff = [BASE]
    d.sbc = [50e6]
    d.total_debt = [1e9]
    d.cash = [4e8]
    d.book_equity = [2e9]
    d.sic_code = "3571"
    return d


def test_build_valuation_populates_the_ladder():
    inputs = ValuationInputs(
        method="dcf", discount_rate=0.09,
        cases={"Bear": CaseInputs(g0=0.02, g_term=0.02),
               "Base": CaseInputs(g0=G0, g_term=GT),
               "Bull": CaseInputs(g0=0.09, g_term=0.03)})
    res = build_valuation(_val_data(), inputs)
    assert res.hurdle_rate == HURDLE_RATE
    assert len(res.irr_ladder) == 9
    assert res.irr_ladder[4][0] == pytest.approx(40.0)
    # implied return at P₀ matches a direct call on the same legs
    direct = implied_return(40.0, res.base_value, G0, GT, res.bridge,
                            res.shares)
    assert res.implied_return_now == pytest.approx(direct)
    assert res.hurdle_price == pytest.approx(price_for_return(
        HURDLE_RATE, res.base_value, G0, GT, res.bridge, res.shares))


def test_sandbox_implied_return_matches_valuation_function():
    out = sandbox_compute(BASE, 0.09, G0, GT, BRIDGE, SHARES, 0.0, False,
                          price=40.0)
    assert out["implied_return"] == pytest.approx(
        implied_return(40.0, BASE, G0, GT, BRIDGE, SHARES))


# ------------------------------------------- FIX-16e exit-multiple check

def test_exit_multiple_check_hand_computed():
    from forensic_viz.valuation import HORIZON, exit_multiple_check
    d = DashboardData(ticker="T", company="T", subtitle="",
                      generated=dt.date(2026, 7, 12))
    d.ebit_reported = [380e6, 400e6]
    d.ev_ebit_fy = [10.0, 12.0, 14.0, None]     # median 12.0
    out = exit_multiple_check(d, base_g0=0.06, g_term=0.02, rate=0.10,
                              bridge=6e8, shares=100e6, price=40.0)
    ebit5 = 400e6
    for i in range(1, 6):
        ebit5 *= 1 + (0.06 + (0.02 - 0.06) * (i - 1) / (HORIZON - 1))
    assert out["multiple"] == pytest.approx(12.0)
    assert out["ebit5"] == pytest.approx(ebit5)
    eq5 = (12.0 * ebit5 - 6e8) / 100e6
    assert out["eq5_ps"] == pytest.approx(eq5)
    assert out["fv_today"] == pytest.approx(eq5 / 1.1 ** 5)
    assert out["return_5y"] == pytest.approx((eq5 / 40.0) ** 0.2 - 1)
    # < 3 usable multiples or non-positive EBIT -> None
    d.ev_ebit_fy = [10.0, 12.0]
    assert exit_multiple_check(d, 0.06, 0.02, 0.10, 6e8, 100e6, 40.0) is None
    d.ev_ebit_fy = [10.0, 12.0, 14.0]
    d.ebit_reported = [-5e6]
    assert exit_multiple_check(d, 0.06, 0.02, 0.10, 6e8, 100e6, 40.0) is None


def test_exit_check_note_fires_without_moving_verdict_numerics():
    from forensic_viz.verdict import build_verdict
    inputs = ValuationInputs(
        method="dcf", discount_rate=0.09,
        cases={"Bear": CaseInputs(g0=0.02, g_term=0.02),
               "Base": CaseInputs(g0=G0, g_term=GT),
               "Bull": CaseInputs(g0=0.09, g_term=0.03)})

    def verdict_for(with_mults):
        d = _val_data()
        d.ebit_reported = [400e6]
        if with_mults:
            d.ev_ebit_fy = [10.0, 12.0, 14.0]
        res = build_valuation(d, inputs)
        return res, build_verdict(d, inputs, res)

    res1, v1 = verdict_for(True)
    res2, v2 = verdict_for(False)
    assert res1.exit_check is not None and res2.exit_check is None
    assert any("5y exit cross-check" in n for n in v1.notes)
    assert not any("5y exit cross-check" in n for n in v2.notes)
    # companion frame only: every verdict numeric identical
    assert v1.fv_avg == pytest.approx(v2.fv_avg)
    assert v1.mos == pytest.approx(v2.mos)
    assert v1.coherence == v2.coherence

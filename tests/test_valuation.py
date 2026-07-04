import datetime as dt

import pytest

from forensic_viz.metrics import DashboardData
from forensic_viz.valuation import (
    CaseInputs, ValuationError, ValuationInputs, build_valuation, dcf_fcff,
    reverse_dcf_implied_g, residual_income, suggest_method,
)


# ------------------------------------------------------------- pure math

def test_dcf_flat_growth_matches_closed_form():
    # g0 == g_term == g: every year grows at g, so EV has a clean closed form.
    base, wacc, g = 100.0, 0.10, 0.02
    out = dcf_fcff(base, wacc, g, g)
    pv = 0.0
    f = base
    for i in range(1, 11):
        f *= 1 + g
        pv += f / (1 + wacc) ** i
    tv = f * (1 + g) / (wacc - g)
    pv += tv / (1 + wacc) ** 10
    assert out["ev"] == pytest.approx(pv)
    assert 0 < out["tv_share"] < 1


def test_dcf_rejects_wacc_not_above_terminal_g():
    with pytest.raises(ValuationError, match="must exceed terminal"):
        dcf_fcff(100.0, 0.03, 0.05, 0.03)


def test_higher_growth_raises_value():
    lo = dcf_fcff(100, 0.10, 0.02, 0.02)["ev"]
    hi = dcf_fcff(100, 0.10, 0.08, 0.03)["ev"]
    assert hi > lo


def test_reverse_dcf_implied_g():
    # EV = FCFF/(WACC-g)  =>  g = WACC - FCFF/EV
    assert reverse_dcf_implied_g(100.0, 0.10, 2000.0) == pytest.approx(0.05)
    assert reverse_dcf_implied_g(100.0, 0.10, 0) is None


def test_residual_income_zero_when_roe_equals_re():
    out = residual_income(1000.0, 0.10, 0.10, 0.0, 0.0)
    assert out["value"] == pytest.approx(1000.0)  # no excess return -> V0 = BV0


def test_residual_income_premium_for_excess_roe():
    out = residual_income(1000.0, 0.10, 0.15, 0.02, 0.02)
    assert out["value"] > 1000.0


def test_track_resolution_and_method_suggestion():
    from forensic_viz.metrics import resolve_track
    assert resolve_track("auto", "3571") == "standard"   # electronic computers
    assert resolve_track("auto", "6022") == "bank"       # state commercial bank
    assert resolve_track("auto", "6311") == "insurance"  # life insurance
    assert resolve_track("auto", "6798") == "reit"
    assert resolve_track("auto", "") == "standard"
    assert resolve_track("sotp", "3571") == "sotp"       # explicit override wins
    assert suggest_method("standard") == "dcf"
    assert suggest_method("bank") == "ri"
    assert suggest_method("insurance") == "ri"
    assert suggest_method("reit") == "affo"
    assert suggest_method("sotp") == "manual"


def test_auto_discount_rate_from_wacc_build():
    from forensic_viz.rates import WaccBuild
    d = _data()
    d.wacc_build = WaccBuild(r_f=0.04, r_e=0.095, wacc=0.088, tax=0.21)
    cases = _cases(Bear=CaseInputs(g0=0.02, g_term=0.02),
                   Base=CaseInputs(g0=0.05, g_term=0.025),
                   Bull=CaseInputs(g0=0.08, g_term=0.03))
    res = build_valuation(d, ValuationInputs("dcf", cases))  # no rate given
    assert res.discount_rate == pytest.approx(0.088)
    assert res.rate_build  # the §4.0 build audit string is carried
    override = build_valuation(d, ValuationInputs("dcf", cases, discount_rate=0.12))
    assert override.discount_rate == pytest.approx(0.12)  # manual wins
    assert override.rate_build == ""


# --------------------------------------------------------- end-to-end cases

def _data(price=100.0, fcf=500e6, debt=1e9, cash=400e6, shares=100e6,
          equity=2e9, sic="3571", interest=0.0, sbc=50e6):
    d = DashboardData(ticker="T", company="T Inc", subtitle="",
                      generated=dt.date(2026, 7, 3))
    d.last_close = price
    d.price_dates = [dt.date(2026, 7, 1)]
    d.diluted_shares = [shares]
    d.fcf = [fcf]
    d.fcf_ex_sbc = [fcf - sbc]
    d.effective_tax_rate = 0.21
    d.interest_expense = [interest if interest else None]
    d.fcff = [fcf + interest * (1 - 0.21)]  # FCFF = FCF + after-tax interest
    d.sbc = [sbc]
    d.total_debt = [debt]
    d.cash = [cash]
    d.book_equity = [equity]
    d.sic_code = sic
    return d


def _cases(**per):  # per = {"Bear": CaseInputs, ...}
    return {n: per[n] for n in ("Bear", "Base", "Bull")}


def test_dcf_end_to_end_bear_base_bull():
    d = _data()
    inp = ValuationInputs(
        method="dcf", discount_rate=0.09,
        cases=_cases(
            Bear=CaseInputs(g0=0.02, g_term=0.02),
            Base=CaseInputs(g0=0.05, g_term=0.025),
            Bull=CaseInputs(g0=0.09, g_term=0.03)))
    res = build_valuation(d, inp)
    assert [c.name for c in res.cases] == ["Bear", "Base", "Bull"]
    fvs = [c.fv_ps for c in res.cases]
    assert fvs[0] < fvs[1] < fvs[2]           # monotone in growth
    assert res.net_debt == pytest.approx(6e8)  # 1e9 - 4e8
    for c in res.cases:                        # MoS = FV/P0 - 1
        assert c.mos == pytest.approx(c.fv_ps / 100.0 - 1)
    assert res.implied_g is not None           # reverse-DCF frame present


def test_dcf_ex_sbc_uses_lower_base():
    d = _data(fcf=500e6, sbc=50e6)
    cases = _cases(Bear=CaseInputs(g0=0.03, g_term=0.02),
                   Base=CaseInputs(g0=0.03, g_term=0.02),
                   Bull=CaseInputs(g0=0.03, g_term=0.02))
    full = build_valuation(d, ValuationInputs("dcf", cases, discount_rate=0.09))
    exsbc = build_valuation(d, ValuationInputs("dcf", cases, discount_rate=0.09,
                                               ex_sbc=True))
    assert full.base_value == pytest.approx(500e6)          # FCFF (no interest)
    assert exsbc.base_value == pytest.approx(500e6 - 50e6)  # minus SBC
    assert exsbc.cases[1].fv_ps < full.cases[1].fv_ps


def test_dcf_fcff_adds_after_tax_interest():
    # A levered firm: FCFF base = FCF + interest*(1-tax); FV should exceed the
    # levered-FCF-only base because EV rises while net debt is unchanged.
    lev = _data(fcf=400e6, interest=0.0)      # no interest tag -> levered proxy
    fcff = _data(fcf=400e6, interest=100e6)   # $100M interest, tax 21%
    cases = _cases(Bear=CaseInputs(g0=0.03, g_term=0.02),
                   Base=CaseInputs(g0=0.03, g_term=0.02),
                   Bull=CaseInputs(g0=0.03, g_term=0.02))
    r_lev = build_valuation(lev, ValuationInputs("dcf", cases, discount_rate=0.09))
    r_fcff = build_valuation(fcff, ValuationInputs("dcf", cases, discount_rate=0.09))
    assert r_lev.base_value == pytest.approx(400e6)
    assert r_fcff.base_value == pytest.approx(400e6 + 100e6 * 0.79)
    assert r_fcff.cases[1].fv_ps > r_lev.cases[1].fv_ps
    assert any("levered FCF" in w for w in r_lev.warnings)  # proxy disclosed


def test_levered_proxy_flagged_when_latest_interest_missing():
    """FIX-1b: interest tagged in EARLY years only — fcff[-1] is levered FCF,
    so the levered-proxy warning must fire (staleness must not suppress it)."""
    d = _data(fcf=400e6)
    d.interest_expense = [80e6, 80e6, None]      # stale tag, absent latest FY
    d.fcff = [400e6 + 80e6 * 0.79, 400e6 + 80e6 * 0.79, 400e6]  # per-year rule
    d.fcf = [400e6] * 3
    d.fcf_ex_sbc = [350e6] * 3
    d.sbc = [50e6] * 3
    cases = _cases(Bear=CaseInputs(g0=0.03, g_term=0.02),
                   Base=CaseInputs(g0=0.03, g_term=0.02),
                   Bull=CaseInputs(g0=0.03, g_term=0.02))
    res = build_valuation(d, ValuationInputs("dcf", cases, discount_rate=0.09))
    assert res.base_value == pytest.approx(400e6)  # latest-year fcff, levered
    assert any("levered FCF" in w for w in res.warnings)


def test_dcf_negative_base_is_rejected():
    d = _data(fcf=-100e6)
    with pytest.raises(ValuationError, match="Base FCFF must be positive"):
        build_valuation(d, ValuationInputs(
            "dcf", _cases(Bear=CaseInputs(g0=0.02, g_term=0.02),
                          Base=CaseInputs(g0=0.02, g_term=0.02),
                          Bull=CaseInputs(g0=0.02, g_term=0.02)),
            discount_rate=0.09))


def test_terminal_g_over_cap_warns():
    d = _data()
    res = build_valuation(d, ValuationInputs(
        "dcf", _cases(Bear=CaseInputs(g0=0.02, g_term=0.02),
                      Base=CaseInputs(g0=0.03, g_term=0.02),
                      Bull=CaseInputs(g0=0.06, g_term=0.05)),  # 5% > 3.5%
        discount_rate=0.09))
    assert any("GDP cap" in w for w in res.cases[-1].warnings)


def test_ri_end_to_end():
    d = _data(sic="6022", equity=2e9)
    res = build_valuation(d, ValuationInputs(
        "ri", _cases(Bear=CaseInputs(roe=0.08, g0=0.02, g_term=0.02),
                     Base=CaseInputs(roe=0.12, g0=0.04, g_term=0.025),
                     Bull=CaseInputs(roe=0.16, g0=0.06, g_term=0.03)),
        discount_rate=0.10))
    fvs = [c.fv_ps for c in res.cases]
    assert fvs[0] < fvs[1] < fvs[2]
    assert res.base_value == pytest.approx(2e9)  # BV0 = latest equity


def test_affo_and_manual():
    d = _data(sic="6798")
    affo = build_valuation(d, ValuationInputs(
        "affo", _cases(Bear=CaseInputs(affo_ps=5, target_yield=0.06),
                       Base=CaseInputs(affo_ps=5, target_yield=0.05),
                       Bull=CaseInputs(affo_ps=5, target_yield=0.04))))
    # lower target yield -> higher implied value
    assert affo.cases[0].fv_ps < affo.cases[2].fv_ps
    assert affo.cases[1].fv_ps == pytest.approx(100.0)  # 5 / 0.05

    manual = build_valuation(d, ValuationInputs(
        "manual", _cases(Bear=CaseInputs(fv_ps=80), Base=CaseInputs(fv_ps=110),
                         Bull=CaseInputs(fv_ps=140))))
    assert manual.cases[1].mos == pytest.approx(0.10)  # 110/100 - 1


def test_net_cash_raises_equity_and_fv():
    # Same EV inputs, net cash vs net debt: net cash must give the higher FV.
    cases = _cases(Bear=CaseInputs(g0=0.03, g_term=0.02),
                   Base=CaseInputs(g0=0.03, g_term=0.02),
                   Bull=CaseInputs(g0=0.03, g_term=0.02))
    net_debt = build_valuation(_data(debt=2e9, cash=0.0),
                               ValuationInputs("dcf", cases, discount_rate=0.09))
    net_cash = build_valuation(_data(debt=0.0, cash=2e9),
                               ValuationInputs("dcf", cases, discount_rate=0.09))
    assert net_cash.net_debt == pytest.approx(-2e9)
    assert net_cash.cases[1].fv_ps > net_debt.cases[1].fv_ps


def test_one_sided_net_debt_warns():
    d = _data()
    d.total_debt = [None]   # cash present, debt tag missing
    res = build_valuation(d, ValuationInputs(
        "dcf", _cases(Bear=CaseInputs(g0=0.03, g_term=0.02),
                      Base=CaseInputs(g0=0.03, g_term=0.02),
                      Bull=CaseInputs(g0=0.03, g_term=0.02)), discount_rate=0.09))
    assert any("one-sided" in w for w in res.warnings)


def test_non_positive_price_rejected():
    for bad in (0.0, -5.0):
        d = _data()
        d.last_close = bad
        with pytest.raises(ValuationError, match="price"):
            build_valuation(d, ValuationInputs(
                "manual", _cases(Bear=CaseInputs(fv_ps=1), Base=CaseInputs(fv_ps=1),
                                 Bull=CaseInputs(fv_ps=1))))


def test_non_positive_affo_rejected():
    d = _data(sic="6798")
    with pytest.raises(ValuationError, match="AFFO per share must be positive"):
        build_valuation(d, ValuationInputs(
            "affo", _cases(Bear=CaseInputs(affo_ps=0.0, target_yield=0.05),
                           Base=CaseInputs(affo_ps=5, target_yield=0.05),
                           Bull=CaseInputs(affo_ps=5, target_yield=0.05))))


def test_short_horizon_rejected():
    from forensic_viz.valuation import dcf_fcff, residual_income
    with pytest.raises(ValuationError):
        dcf_fcff(100.0, 0.09, 0.05, 0.03, years=1)
    with pytest.raises(ValuationError):
        residual_income(1000.0, 0.10, 0.12, 0.03, 0.02, years=1)


def test_valuation_requires_price():
    d = _data()
    d.last_close = None
    with pytest.raises(ValuationError, match="current price"):
        build_valuation(d, ValuationInputs(
            "manual", _cases(Bear=CaseInputs(fv_ps=1), Base=CaseInputs(fv_ps=1),
                             Bull=CaseInputs(fv_ps=1))))


def test_missing_case_field_raises():
    d = _data()
    with pytest.raises(ValuationError, match="terminal g"):
        build_valuation(d, ValuationInputs(
            "dcf", _cases(Bear=CaseInputs(g0=0.02),  # no g_term
                          Base=CaseInputs(g0=0.02, g_term=0.02),
                          Bull=CaseInputs(g0=0.02, g_term=0.02)),
            discount_rate=0.09))

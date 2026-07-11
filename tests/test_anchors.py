"""FIX-14a growth anchor ladder — hand-computed fixtures.

`build_growth_anchors` is the tested surface (dialog logic stays out);
each pure function gets its own arithmetic fixtures.
"""
import datetime as dt
from types import SimpleNamespace

import pytest

from forensic_viz.anchors import (
    anchor_readout, build_growth_anchors, capex_intensity, capex_peak_flag,
    fundamental_growth, normalized_base, operating_nwc, reinvestment_rate,
    revenue_cagr,
)
from forensic_viz.metrics import DashboardData


def _d(**attrs):
    d = DashboardData(ticker="T", company="T Inc", subtitle="",
                      generated=dt.date(2026, 7, 10))
    for k, v in attrs.items():
        setattr(d, k, v)
    return d


# ------------------------------------------------------------ revenue_cagr

def test_revenue_cagr_trailing_window():
    # 10%/yr over the trailing 6 points; the older 50 stays outside the window
    d = _d(revenue=[50, 100, 110, 121, 133.1, 146.41, 161.051])
    assert revenue_cagr(d, years=5) == pytest.approx(0.10)
    # widening the window pulls in the 50 -> a different, larger CAGR
    assert revenue_cagr(d, years=6) == pytest.approx((161.051 / 50) ** (1 / 6) - 1)


def test_revenue_cagr_skips_none_endpoints():
    # first/last non-None inside the window: 100 (idx1) -> 121 (idx5), span 4
    d = _d(revenue=[None, 100, None, 110, None, 121])
    assert revenue_cagr(d) == pytest.approx(1.21 ** 0.25 - 1)


def test_revenue_cagr_needs_three_points_and_positive_endpoints():
    assert revenue_cagr(_d(revenue=[None, None, 100, None, None, 121])) is None
    assert revenue_cagr(_d(revenue=[100, 110])) is None
    assert revenue_cagr(_d(revenue=[-5, 100, 110, 120, 130, 140])) is None
    assert revenue_cagr(_d(revenue=[100, 90, 80, 60, 30, -10])) is None
    assert revenue_cagr(_d(revenue=[])) is None


def test_revenue_cagr_prefers_untrimmed_fundamentals():
    # the anchor must not change with the user's display trim: the trimmed
    # DashboardData view is flat, the untrimmed source grows
    d = _d(revenue=[100.0, 100.0, 100.0],
           fundamentals=SimpleNamespace(series={
               "revenue": [100, 110, 121, 133.1, 146.41, 161.051]}))
    assert revenue_cagr(d) == pytest.approx(0.10)


# ----------------------------------------------------------- operating_nwc

def test_operating_nwc_full_and_missing_components():
    d = _d(accounts_receivable=[10, 20], inventory=[5, 6],
           accounts_payable=[8, 9])
    assert operating_nwc(d, -1) == pytest.approx(20 + 6 - 9)
    assert operating_nwc(d, 0) == pytest.approx(10 + 5 - 8)

    notes = []
    d2 = _d(accounts_receivable=[10, 20], inventory=[5, 6])  # no AP series
    assert operating_nwc(d2, -1, notes) == pytest.approx(26)
    assert any("AP" in n and "treated as 0" in n for n in notes)


def test_operating_nwc_none_when_all_missing():
    assert operating_nwc(_d(), -1) is None
    d = _d(accounts_receivable=[10], inventory=[5], accounts_payable=[8])
    assert operating_nwc(d, -5) is None  # out of range


# ------------------------------------------------------- reinvestment_rate

def _rr_fixture(capex=(None, 90, 90, 90), ebit=(400, 400, 400, 400),
                dna=(None, 30, 30, 30), ar=(100, 115, 130, 145), tau=0.25):
    # NWC = AR only (inventory/AP omitted -> 0 with notes); dNWC = 15/yr
    return _d(capex=list(capex), operating_income=list(ebit), dna=list(dna),
              accounts_receivable=list(ar), effective_tax_rate=tau)


def test_reinvestment_rate_hand_computed():
    # NOPAT = 400 x 0.75 = 300; each year (90 + 15 - 30) / 300 = 0.25
    assert reinvestment_rate(_rr_fixture()) == pytest.approx(0.25)


def test_reinvestment_rate_clamps():
    # two peak years: (900 + 15 - 30)/300 = 2.95 clamps to 1.5 -> median 1.5
    high = _rr_fixture(capex=(None, 900, 900, 90))
    assert reinvestment_rate(high) == pytest.approx(1.5)
    # divestment year: (10 + 15 - 100)/300 < 0 clamps to 0.0
    low = _rr_fixture(capex=(None, 10, 10, 10), dna=(None, 100, 100, 100))
    assert reinvestment_rate(low) == pytest.approx(0.0)


def test_reinvestment_rate_skips_nonpositive_nopat():
    notes = []
    d = _rr_fixture(ebit=(400, -50, 400, 400))  # one loss year skipped
    assert reinvestment_rate(d, notes) == pytest.approx(0.25)
    assert any("NOPAT" in n for n in notes)
    # only one usable year -> None
    assert reinvestment_rate(_rr_fixture(ebit=(400, -50, -50, 400))) is None


def test_reinvestment_rate_needs_capex_and_two_years():
    assert reinvestment_rate(
        _rr_fixture(capex=(None, None, 90, 90))) == pytest.approx(0.25)
    assert reinvestment_rate(_rr_fixture(capex=(None, None, None, 90))) is None
    assert reinvestment_rate(_d()) is None


# ------------------------------------------------------ fundamental_growth

def test_fundamental_growth_median_roic_times_rr():
    d = _rr_fixture()
    d.roic = [0.30, 0.40, 0.35]  # median 0.35; RR 0.25 -> g = 0.0875
    assert fundamental_growth(d) == pytest.approx(0.0875)


def test_fundamental_growth_clamps_at_40pct():
    d = _rr_fixture(capex=(None, 900, 900, 900))  # RR clamps to 1.5
    d.roic = [0.50, 0.50, 0.50]                   # 0.5 x 1.5 = 0.75 -> 0.40
    assert fundamental_growth(d) == pytest.approx(0.40)


def test_fundamental_growth_none_when_leg_missing():
    d = _rr_fixture()  # RR fine, no ROIC series
    assert fundamental_growth(d) is None
    d2 = _d(roic=[0.30, 0.35, 0.40])  # ROIC fine, no RR legs
    assert fundamental_growth(d2) is None


# ---------------------------------------------------- build_growth_anchors

_EST = {"g_avg": 0.20, "g_low": 0.12, "g_high": 0.30, "n_analysts": 25,
        "period": "+1y revenue vs 0y consensus",
        "source": "Yahoo Finance earningsTrend"}


def test_seeding_all_anchors_min_binds_base():
    d = _rr_fixture()
    d.analyst_estimates = dict(_EST)
    d.revenue = [100, 110, 121, 133.1, 146.41, 161.051]   # 5y CAGR 10%
    d.roic = [0.30, 0.40, 0.35]                           # fundamental 8.75%
    a = build_growth_anchors(d)
    assert a.consensus == pytest.approx(0.20)
    assert a.hist_cagr == pytest.approx(0.10)
    assert a.fundamental == pytest.approx(0.0875)
    assert a.consensus_range == (pytest.approx(0.12), pytest.approx(0.30))
    assert a.n_analysts == 25
    assert a.binding == "fundamental"
    assert a.seeds["Bull"] == pytest.approx(0.20)   # consensus IS the Bull case
    assert a.seeds["Base"] == pytest.approx(0.0875)
    assert a.seeds["Bear"] == pytest.approx(0.04375)
    assert "consensus" in a.details and "fundamental" in a.details
    out = anchor_readout(a)
    assert "Base = fundamental (binding)" in out
    assert "+20.0%" in out and "Rung 4" in out and "analyst range" in out


def test_seeding_consensus_only_takes_haircut():
    d = _d(analyst_estimates=dict(_EST))  # no history, no fundamentals
    a = build_growth_anchors(d)
    assert a.hist_cagr is None and a.fundamental is None
    assert a.seeds["Base"] == pytest.approx(0.15)   # 0.20 x 0.75
    assert a.seeds["Bull"] == pytest.approx(0.20)
    assert a.seeds["Bear"] == pytest.approx(0.075)
    assert "single-anchor" in a.binding and "25%" in a.binding
    assert a.binding in anchor_readout(a)


def test_seeding_history_only_no_consensus():
    d = _d(revenue=[100, 110, 121, 133.1, 146.41, 161.051])
    a = build_growth_anchors(d)
    assert a.binding == "5y CAGR"
    assert a.seeds["Bull"] == pytest.approx(0.10)   # falls back to hist
    assert a.seeds["Base"] == pytest.approx(0.10)
    assert a.seeds["Bear"] == pytest.approx(0.05)
    assert a.consensus_range is None


def test_seeding_bear_floors_at_zero():
    d = _d(revenue=[100, 95, 90, 85, 80, 75])  # negative 5y CAGR
    a = build_growth_anchors(d)
    assert a.seeds["Base"] < 0
    assert a.seeds["Bear"] == 0.0


def test_seeding_empty_keeps_silent_no_prefill():
    a = build_growth_anchors(_d())
    assert a.seeds == {}
    assert a.binding == ""
    assert anchor_readout(a) == ""


# ---------------------------------------------- FIX-14b capex normalization

def test_capex_intensity_median_and_latest():
    # intensities .10, .1091, .4167, .10, .10 — the FY-3 peak does not drag
    # the median; latest is the most recent usable pair
    d = _d(capex=[10, 12, 50, 13, 14], revenue=[100, 110, 120, 130, 140])
    med, latest = capex_intensity(d)
    assert med == pytest.approx(0.10)
    assert latest == pytest.approx(0.10)


def test_capex_intensity_needs_three_usable_pairs():
    assert capex_intensity(
        _d(capex=[10, None, 12], revenue=[100, 110, 120])) is None
    assert capex_intensity(
        _d(capex=[10, 11, 12], revenue=[100, -5, 120])) is None
    assert capex_intensity(_d()) is None


def test_capex_peak_flag_both_sides_of_30pct():
    rev = [100.0] * 5
    # 29% off the median stays inside the band (the rule is strict >30%)
    assert capex_peak_flag(_d(capex=[10, 10, 10, 10, 12.9], revenue=rev)) is False
    # +40% -> peak; -40% -> trough
    assert capex_peak_flag(_d(capex=[10, 10, 10, 10, 14], revenue=rev)) is True
    assert capex_peak_flag(_d(capex=[10, 10, 10, 10, 6], revenue=rev)) is True
    assert capex_peak_flag(_d()) is False  # no history -> silent


def test_normalized_base_arithmetic():
    d = _d(capex=[10, 12, 50, 13, 14], revenue=[100, 110, 120, 130, 140],
           cfo=[None, None, None, None, 50])
    base, med = normalized_base(d)
    assert med == pytest.approx(0.10)
    assert base == pytest.approx(50 - 0.10 * 140)
    # no CFO -> None even with good intensity history
    assert normalized_base(
        _d(capex=[10, 12, 13], revenue=[100, 110, 120])) is None


def _val_data(capex_latest=150e6):
    return _d(last_close=100.0, price_dates=[dt.date(2026, 7, 1)],
              diluted_shares=[100e6], fcf=[500e6], fcf_ex_sbc=[450e6],
              effective_tax_rate=0.21, interest_expense=[None],
              fcff=[500e6], sbc=[50e6], total_debt=[1e9], cash=[4e8],
              book_equity=[2e9], sic_code="3571",
              revenue=[1e9] * 5, cfo=[600e6] * 5,
              capex=[100e6, 100e6, 100e6, 100e6, capex_latest])


# ------------------------------- FIX-14c growth–reinvestment coherence note

def _verdict_for(base_g0=0.05, with_legs=True):
    from forensic_viz.valuation import (
        CaseInputs, ValuationInputs, build_valuation,
    )
    from forensic_viz.verdict import build_verdict
    cases = {"Bear": CaseInputs(g0=min(0.01, base_g0), g_term=0.01),
             "Base": CaseInputs(g0=base_g0, g_term=0.02),
             "Bull": CaseInputs(g0=0.09, g_term=0.03)}
    inputs = ValuationInputs(method="dcf", discount_rate=0.09, cases=cases)
    d = _val_data(capex_latest=100e6)  # flat capex — no 14b warning noise
    if with_legs:
        # NOPAT = 400 × 0.79 = 316; RR years (100−50)/316, ditto, ditto
        # -> median RR ≈ 15.8%; median ROIC 10%
        d.operating_income = [400e6] * 5
        d.dna = [50e6] * 5
        d.roic = [0.10, 0.10, 0.10]
    res = build_valuation(d, inputs)
    return build_verdict(d, inputs, res)


def test_growth_reinvestment_note_fires_above_threshold():
    # implied RR = 5% / 10% = 50% of NOPAT vs 15.8% history -> x3.2, fires
    v = _verdict_for(base_g0=0.05)
    assert any("franchise capacity" in n for n in v.notes)


def test_growth_reinvestment_note_silent_below_and_without_legs():
    # implied RR = 1.5% / 10% = 15% < 1.25 x 15.8% -> silent
    v = _verdict_for(base_g0=0.015)
    assert not any("franchise capacity" in n for n in v.notes)
    # legs missing (no ROIC / EBIT history) -> silent
    v2 = _verdict_for(base_g0=0.05, with_legs=False)
    assert not any("franchise capacity" in n for n in v2.notes)


def test_growth_reinvestment_note_never_moves_verdict_numerics():
    v_note, v_bare = _verdict_for(0.05, True), _verdict_for(0.05, False)
    assert v_note.fv_avg == pytest.approx(v_bare.fv_avg)
    assert v_note.mos == pytest.approx(v_bare.mos)
    assert v_note.stressed_mos == pytest.approx(v_bare.stressed_mos)
    assert v_note.coherence == v_bare.coherence  # Control!B67 field untouched


def test_capex_warning_only_on_auto_base_path():
    from forensic_viz.valuation import (
        CaseInputs, ValuationInputs, build_valuation,
    )
    cases = {"Bear": CaseInputs(g0=0.02, g_term=0.02),
             "Base": CaseInputs(g0=0.05, g_term=0.025),
             "Bull": CaseInputs(g0=0.09, g_term=0.03)}
    # latest intensity 15% vs median 10% -> +50% deviation, auto base
    res = build_valuation(_val_data(), ValuationInputs(
        method="dcf", discount_rate=0.09, cases=cases))
    assert any("capex peak/trough" in w for w in res.warnings)
    # explicit base: the analyst already normalized -> no warning
    res2 = build_valuation(_val_data(), ValuationInputs(
        method="dcf", discount_rate=0.09, cases=cases, base_value=500e6))
    assert not any("capex peak/trough" in w for w in res2.warnings)
    # flat intensity on the auto path -> below the line, no warning
    res3 = build_valuation(_val_data(capex_latest=100e6), ValuationInputs(
        method="dcf", discount_rate=0.09, cases=cases))
    assert not any("capex peak/trough" in w for w in res3.warnings)

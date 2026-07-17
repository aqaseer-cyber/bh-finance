"""FIX-15b: Explore chart cards — Agg smoke renders (every card × every
mode), the insufficient-data path, and ratio masking on a negative-TTM-EPS
stretch. Dialog/Tk logic stays out; the pure figure builders are the
tested surface."""
import datetime as dt
import math
from types import SimpleNamespace

import matplotlib
matplotlib.use("Agg")

import pytest
from matplotlib.figure import Figure

from forensic_viz.explore import (
    INSUFFICIENT, PRICE_MODES, RATIO_MODES, REVENUE_MODES, WACC_EXCEEDS_G,
    price_card, ratio_card, ratio_series, revenue_card, sandbox_compute,
)
from forensic_viz.edgar import parse_companyfacts
from forensic_viz.metrics import DashboardData, apply_track, build_fundamental_metrics
from test_model_export import _facts_with_quarters

FY24, FY25 = dt.date(2024, 12, 31), dt.date(2025, 12, 31)


def _weekly(start, end):
    days, cur = [], start
    while cur <= end:
        days.append(cur)
        cur += dt.timedelta(days=7)
    return days


def _with_prices(d):
    d.price_dates = _weekly(dt.date(2025, 1, 3), dt.date(2026, 8, 7))
    d.price_closes = [100.0 + 0.5 * i for i in range(len(d.price_dates))]
    peak = 0.0
    d.drawdown = []
    for p in d.price_closes:
        peak = max(peak, p)
        d.drawdown.append(p / peak - 1.0)
    d.max_drawdown = min(d.drawdown)
    d.max_drawdown_date = d.price_dates[d.drawdown.index(d.max_drawdown)]
    d.price_source = "fixture"
    d.total_return = d.price_closes[-1] / d.price_closes[0] - 1.0
    return d


def _testco():
    d = DashboardData(ticker="TESTCO", company="TESTCO Inc", subtitle="",
                      generated=dt.date(2026, 8, 10))
    d.sic_code = "3571"
    apply_track(d, "auto")
    build_fundamental_metrics(
        parse_companyfacts(_facts_with_quarters(), "TESTCO"), d)
    return _with_prices(d)


def _texts(fig):
    return [t.get_text() for ax in fig.axes for t in ax.texts]


def test_every_card_and_mode_smoke_renders():
    d = _testco()
    expected_axes = {"Both (stacked)": 2, "None": 1}
    for builder, modes in ((price_card, PRICE_MODES),
                           (ratio_card, RATIO_MODES),
                           (revenue_card, REVENUE_MODES)):
        for mode in modes:
            fig = builder(d, mode, dpi=80, width_in=8.0)
            assert isinstance(fig, Figure), (builder.__name__, mode)
            assert len(fig.axes) >= expected_axes.get(mode, 1)
    # specific shapes: the stacked price card is two panes; margin overlays
    # add the twin percentage axis
    assert len(price_card(d, "Both (stacked)", 80, 8.0).axes) == 2
    assert len(revenue_card(d, "All margins", 80, 8.0).axes) == 2
    assert len(revenue_card(d, "None", 80, 8.0).axes) == 1


def test_ps_ttm_has_a_real_line_and_median_annotation():
    d = _testco()  # quarterly revenue exists -> TTM P/S is a real series
    dates, values = ratio_series(d, "P/S (TTM)")
    assert dates and any(not math.isnan(v) for v in values)
    fig = ratio_card(d, "P/S (TTM)", dpi=80, width_in=8.0)
    assert any("median" in t for t in _texts(fig))
    assert not any(INSUFFICIENT in t for t in _texts(fig))


def test_insufficient_data_cards_say_so():
    bare = DashboardData(ticker="T", company="T Inc", subtitle="",
                         generated=dt.date(2026, 8, 10))
    for builder, mode in ((price_card, PRICE_MODES[0]),
                          (ratio_card, RATIO_MODES[0]),
                          (revenue_card, REVENUE_MODES[-1])):
        fig = builder(bare, mode, dpi=80, width_in=8.0)
        assert any(INSUFFICIENT in t for t in _texts(fig)), builder.__name__
    # prices but no quarterly fundamentals -> ratio card still honest
    priced = _with_prices(DashboardData(ticker="T", company="T", subtitle="",
                                        generated=dt.date(2026, 8, 10)))
    fig = ratio_card(priced, "P/E (TTM)", dpi=80, width_in=8.0)
    assert any(INSUFFICIENT in t for t in _texts(fig))


def test_ratio_masks_negative_ttm_eps_stretch():
    """Loss year: TTM EPS goes negative at FY25 (Q4 = FY − 9M = −5) and
    recovers at Q1'26 — the masked stretch is NaN (a gap), never plotted
    or interpolated."""
    def q(y, qi, val):
        sm, em, ed = {1: (1, 3, 31), 2: (4, 6, 30),
                      3: (7, 9, 30)}[qi]
        return (dt.date(y, sm, 1), dt.date(y, em, ed), val)

    eps = [q(2025, 1, 1.0), q(2025, 2, 1.0), q(2025, 3, 1.0),
           (dt.date(2025, 1, 1), dt.date(2025, 9, 30), 3.0),   # 9M YTD
           q(2026, 1, 5.0)]
    d = _with_prices(DashboardData(ticker="T", company="T", subtitle="",
                                   generated=dt.date(2026, 8, 10)))
    d.fundamentals = SimpleNamespace(fy_ends=[FY24, FY25],
                                     series={"eps_diluted": [3.0, -2.0]},
                                     raw_facts=None)
    d._qdata_cache = SimpleNamespace(duration={"eps_diluted": eps},
                                     instant={})
    dates, values = ratio_series(d, "P/E (TTM)")
    by_date = dict(zip(dates, values))

    def at(when):
        return next(v for dt_, v in by_date.items() if dt_ >= when)

    assert math.isnan(at(dt.date(2025, 6, 1)))    # before any TTM point
    assert math.isnan(at(dt.date(2026, 1, 15)))   # negative-TTM stretch
    recovered = at(dt.date(2026, 4, 15))          # TTM back to +2.0
    assert not math.isnan(recovered)
    when = next(dt_ for dt_ in dates if dt_ >= dt.date(2026, 4, 15))
    assert recovered == pytest.approx(by_date[when])
    assert recovered == pytest.approx(
        (100.0 + 0.5 * dates.index(when)) / 2.0)
    # the figure renders the masked series without raising
    fig = ratio_card(d, "P/E (TTM)", dpi=80, width_in=8.0)
    assert not any(INSUFFICIENT in t for t in _texts(fig))


# ------------------------------------------------- FIX-15c sandbox compute

def test_sandbox_compute_equals_production_pipeline_across_grid():
    """The card is a thin UI over the production functions — assert the
    dict against a hand-composed dcf_fcff + bridge + implied-g pipeline."""
    from forensic_viz.valuation import dcf_fcff, reverse_dcf_implied_g
    bridge, shares, sbc, price = 6e8, 100e6, 5e7, 80.0
    for base in (4e8, 9e8):
        for wacc in (0.07, 0.11):
            for g0 in (-0.02, 0.06, 0.18):
                for ex_sbc in (False, True):
                    got = sandbox_compute(base, wacc, g0, 0.02, bridge,
                                          shares, sbc, ex_sbc, price=price)
                    eff = base - sbc if ex_sbc else base
                    ref = dcf_fcff(eff, wacc, g0, 0.02)
                    fv = (ref["ev"] - bridge) / shares
                    assert got["error"] is None
                    assert got["fv_ps"] == pytest.approx(fv)
                    assert got["mos"] == pytest.approx((fv - price) / price)
                    assert got["tv_share"] == pytest.approx(ref["tv_share"])
                    assert got["implied_g"] == pytest.approx(
                        reverse_dcf_implied_g(base - sbc, wacc,
                                              price * shares + bridge))


def test_sandbox_compute_guards():
    # wacc ≤ terminal g renders a message, never raises
    out = sandbox_compute(5e8, 0.02, 0.05, 0.03, 0.0, 100e6, 0.0, False,
                          price=50.0)
    assert out["error"] == WACC_EXCEEDS_G
    assert out["fv_ps"] is None and out["mos"] is None
    # equality is still undefined (TV division by zero)
    assert sandbox_compute(5e8, 0.03, 0.05, 0.03, 0.0, 100e6, 0.0,
                           False)["error"] == WACC_EXCEEDS_G
    # ex-SBC base clamped to zero -> honest refusal, no crash
    out2 = sandbox_compute(4e7, 0.09, 0.05, 0.02, 0.0, 100e6, 5e7, True)
    assert out2["error"] and "positive" in out2["error"]
    # missing shares
    assert sandbox_compute(5e8, 0.09, 0.05, 0.02, 0.0, 0.0, 0.0,
                           False)["error"]
    # no price -> FV computed, market-dependent outputs stay None
    out3 = sandbox_compute(5e8, 0.09, 0.05, 0.02, 1e8, 100e6, 0.0, False)
    assert out3["error"] is None and out3["fv_ps"] is not None
    assert out3["mos"] is None and out3["implied_g"] is None


# ------------------------------------------------ FIX-16d Overview cards

def test_overview_kpi_card_renders_with_and_without_market_join():
    from forensic_viz.explore import overview_kpi_card
    from forensic_viz.market import compute_market_ratios
    d = _testco()
    compute_market_ratios(d)
    fig = overview_kpi_card(d, dpi=80, width_in=8.0)
    texts = _texts(fig)
    assert any("Owner's yield" in t for t in texts)
    assert any("issuance not netted" in t for t in texts)
    # bare data never crashes the tiles — everything renders as dashes
    bare = DashboardData(ticker="T", company="T", subtitle="",
                         generated=dt.date(2026, 8, 10))
    fig2 = overview_kpi_card(bare, dpi=80, width_in=8.0)
    assert any(t == "–" for t in _texts(fig2))


def test_overview_kpi_ev_carries_all_bridge_legs():
    """Regression: the KPI EV/EBIT tile computed EV as mcap + net debt
    only — the house EV (market.ev_fy) adds minority interest and
    preferred as well."""
    from forensic_viz.explore import overview_kpi_card
    d = DashboardData(ticker="T", company="T", subtitle="",
                      generated=dt.date(2026, 8, 10))
    d.last_close = 80.0
    d.diluted_shares = [100e6]
    d.net_debt_fy = [8e8]
    d.minority_interest = [50e6]
    d.preferred_equity = [150e6]
    d.ebit_reported = [640e6]
    texts = _texts(overview_kpi_card(d, dpi=80, width_in=8.0))
    assert "14.1×" in texts       # (8e9+8e8+50e6+150e6)/640e6 = 14.0625
    assert "13.8×" not in texts   # mcap + net debt only would print 13.75


def test_overview_valuation_card_with_and_without_result():
    from forensic_viz.explore import overview_valuation_card
    from forensic_viz.valuation import (
        CaseInputs, ValuationInputs, build_valuation,
    )
    d = _testco()
    fig = overview_valuation_card(d, None, dpi=80, width_in=8.0)
    assert any("Run Intrinsic value" in t for t in _texts(fig))

    d.last_close = d.price_closes[-1]
    d.ev_ebit_fy = [10.0, 12.0, 14.0]   # arms the exit cross-check
    inputs = ValuationInputs(
        method="dcf", discount_rate=0.09,
        cases={"Bear": CaseInputs(g0=0.02, g_term=0.02),
               "Base": CaseInputs(g0=0.05, g_term=0.025),
               "Bull": CaseInputs(g0=0.09, g_term=0.03)})
    res = build_valuation(d, inputs)
    fig2 = overview_valuation_card(d, res, dpi=80, width_in=8.0)
    texts = _texts(fig2)
    assert any("entry price (Base case)" in t for t in texts)
    assert any("5y exit cross-check" in t for t in texts)
    # the 15% hurdle is a house ASSUMPTION and every rendering says so
    assert any("hurdle" in t and "(ASSUMPTION)" in t for t in texts)

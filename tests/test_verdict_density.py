"""FIX-12d: sensitivity-grid math (pure, engine-checked), dense verdict &
valuation pages, unified footer."""
import datetime as dt

import pytest

from forensic_viz.dashboard import (
    A4L_H, render_dashboard, render_health_report, render_unit_economics,
    render_valuation, render_verdict, verdict_sensitivity,
)
from forensic_viz.metrics import DashboardData
from forensic_viz.valuation import (
    CaseInputs, ValuationInputs, build_valuation, dcf_fcff,
)
from forensic_viz.verdict import build_verdict


def _data(price=100.0, fcf=500e6, sbc=50e6):
    d = DashboardData(ticker="T", company="T Inc", subtitle="",
                      generated=dt.date(2026, 7, 3))
    d.last_close = price
    d.price_dates = [dt.date(2026, 7, 1)]
    d.price_closes = [price]
    d.diluted_shares = [100e6]
    d.fcf = [fcf]
    d.fcf_ex_sbc = [fcf - sbc]
    d.effective_tax_rate = 0.21
    d.interest_expense = [None]
    d.fcff = [fcf]
    d.sbc = [sbc]
    d.total_debt = [1e9]
    d.cash = [4e8]
    d.book_equity = [2e9]
    d.net_income = [3e8]
    d.sic_code = "3571"
    return d


def _dcf(d, rate=0.09, bear=(0.02, 0.02), base=(0.05, 0.025),
         bull=(0.09, 0.03), rating=""):
    inputs = ValuationInputs(
        method="dcf", discount_rate=rate,
        cases={"Bear": CaseInputs(g0=bear[0], g_term=bear[1]),
               "Base": CaseInputs(g0=base[0], g_term=base[1]),
               "Bull": CaseInputs(g0=bull[0], g_term=bull[1])})
    res = build_valuation(d, inputs)
    v = build_verdict(d, inputs, res, rating=rating)
    return inputs, res, v


# --------------------------------------------------------- sensitivity math

def test_sensitivity_center_reproduces_fv_avg():
    d = _data()
    _, res, v = _dcf(d)
    grid = verdict_sensitivity(res, v)
    ci, cj = grid["center"]
    assert grid["cells"][ci][cj] == pytest.approx(v.fv_avg)
    assert grid["kind"] == "dcf"
    assert len(grid["cells"]) == 3 and len(grid["cells"][0]) == 3


def test_sensitivity_cells_match_dcf_engine():
    """Every cell = FV average recomputed with dcf_fcff on the recovered
    per-track bases (A as-reported 500mm, B ex-SBC 450mm) and same bridge."""
    d = _data()
    inputs, res, v = _dcf(d)
    grid = verdict_sensitivity(res, v)
    rate, shares, bridge = res.discount_rate, res.shares, res.bridge
    bases = []
    for fv, c in ((v.fv_a, inputs.cases["Bear"]),
                  (v.fv_b, inputs.cases["Base"])):
        k = dcf_fcff(1.0, rate, c.g0, c.g_term)["ev"]
        bases.append(((fv * shares + bridge) / k, c.g0, c.g_term))
    assert bases[0][0] == pytest.approx(500e6)   # Track A as-reported FCFF
    assert bases[1][0] == pytest.approx(450e6)   # Track B ex-SBC
    for i, dr in enumerate((-0.01, 0.0, 0.01)):
        for j, dg in enumerate((-0.005, 0.0, 0.005)):
            want = [(dcf_fcff(b, rate + dr, g0, gt + dg)["ev"] - bridge)
                    / shares for b, g0, gt in bases]
            assert grid["cells"][i][j] == pytest.approx(sum(want) / 2)


def test_sensitivity_dash_where_wacc_le_g():
    """Cells where a shocked WACC ≤ a shocked terminal g are None (drawn as
    em-dash) — the engine's undefined-TV guard is honoured, not averaged over."""
    d = _data()
    _, res, v = _dcf(d, rate=0.055, bear=(0.02, 0.05), base=(0.05, 0.025),
                     bull=(0.06, 0.05))
    grid = verdict_sensitivity(res, v)
    ci, cj = grid["center"]
    assert grid["cells"][ci][cj] is not None            # page inputs valid
    # WACC −100bp (row 0) with bear g_term +50bp: 4.5% ≤ 5.5% → undefined
    assert grid["cells"][0][2] is None
    # WACC −100bp with bear g_term −50bp: 4.5% ≤ 4.5% → still undefined
    assert grid["cells"][0][0] is None


def test_sensitivity_manual_is_none():
    d = _data()
    inputs = ValuationInputs(
        method="manual",
        cases={"Bear": CaseInputs(fv_ps=80.0), "Base": CaseInputs(fv_ps=100.0),
               "Bull": CaseInputs(fv_ps=120.0)})
    res = build_valuation(d, inputs)
    v = build_verdict(d, inputs, res)
    assert verdict_sensitivity(res, v) is None


# ------------------------------------------------------------- page renders

def test_verdict_page_dense_with_and_without_triggers(tmp_path):
    d = _data()
    d.terminal_risk = "A terminal risk."
    _, res, v = _dcf(d, rating="Buy")
    fig = render_verdict(d, res, v, str(tmp_path / "v1.png"),
                         open_triggers=["margin < 20% two quarters",
                                        "FX exposure passes 30% of revenue"])
    assert fig.get_size_inches()[1] == pytest.approx(A4L_H)
    assert len(fig.axes) >= 5    # header, stress, sensitivity, assumptions, triggers
    texts = " ".join(t.get_text() for ax in fig.axes for t in ax.texts)
    assert "margin < 20% two quarters" in texts
    assert "Assumptions & bridge" in texts and "Sensitivity" in texts
    fig2 = render_verdict(d, res, v)     # no triggers → honest empty state
    texts2 = " ".join(t.get_text() for ax in fig2.axes for t in ax.texts)
    assert "No open triggers" in texts2
    assert fig2.get_size_inches()[1] == pytest.approx(A4L_H)


def test_valuation_page_warnings_callout():
    d = _data()
    _, res, v = _dcf(d)
    assert res.warnings                  # this fixture carries caveats
    fig = render_valuation(d, res)
    assert fig.get_size_inches()[1] == pytest.approx(A4L_H)
    assert len(fig.axes) == 4            # header, field, table, callout
    texts = " ".join(t.get_text() for ax in fig.axes for t in ax.texts)
    assert "Warnings & assumptions" in texts and "⚠" in texts


def test_valuation_callout_caps_at_six_with_overflow_line():
    d = _data()
    _, res, v = _dcf(d)
    res.warnings = [f"warning number {i}" for i in range(9)]
    for c in res.cases:
        c.warnings.clear()
    fig = render_valuation(d, res)
    texts = " ".join(t.get_text() for ax in fig.axes for t in ax.texts)
    assert "+3 more — see the CSV audit trail" in texts
    assert "warning number 5" in texts and "warning number 6" not in texts


# ------------------------------------------------------------ unified footer

def test_every_page_has_exactly_one_advice_line():
    d = _data()
    _, res, v = _dcf(d, rating="Hold")
    d2 = _data()                      # fundamentals pages: no price series
    d2.price_dates, d2.price_closes = [], []
    figs = [render_dashboard(d2), render_unit_economics(d2),
            render_health_report(d2), render_valuation(d, res),
            render_verdict(d, res, v, open_triggers=["t1"])]
    for fig in figs:
        all_texts = [t.get_text() for t in fig.texts]
        all_texts += [t.get_text() for ax in fig.axes for t in ax.texts]
        n = sum(t.count("Not investment advice") for t in all_texts)
        assert n == 1, f"expected exactly one advice line, got {n}"
        joined = " ".join(all_texts)
        assert f"Generated {d.generated.isoformat()}" in joined

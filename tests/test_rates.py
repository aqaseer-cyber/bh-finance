import datetime as dt

import pytest

from forensic_viz.metrics import DashboardData
from forensic_viz.rates import (
    WaccBuild, blume_adjust, build_wacc, compute_beta, parse_fred_csv,
    parse_stooq_yield_csv,
)

FRED_CSV = """DATE,DGS10
2026-06-29,4.31
2026-06-30,4.28
2026-07-01,.
2026-07-02,4.35
"""

STOOQ_CSV = """Date,Open,High,Low,Close,Volume
2026-07-01,4.30,4.36,4.28,4.33,0
2026-07-02,4.33,4.40,4.31,4.37,0
"""


def test_parse_fred_skips_holidays_takes_latest():
    rate, date = parse_fred_csv(FRED_CSV)
    assert rate == pytest.approx(0.0435)
    assert date == dt.date(2026, 7, 2)


def test_parse_stooq_yield():
    rate, date = parse_stooq_yield_csv(STOOQ_CSV)
    assert rate == pytest.approx(0.0437)
    assert date == dt.date(2026, 7, 2)


def test_beta_of_scaled_series_is_two():
    # Stock returns exactly 2x the index returns -> beta 2.
    start = dt.date(2020, 1, 1)
    dates, idx = [], {}
    stock = []
    level_m, level_s = 100.0, 50.0
    moves = [0.01, -0.008, 0.012, -0.005, 0.007, -0.011, 0.009, 0.004] * 80
    for i, m in enumerate(moves):
        day = start + dt.timedelta(days=i)
        level_m *= 1 + m
        level_s *= 1 + 2 * m
        dates.append(day)
        idx[day] = level_m
        stock.append(level_s)
    raw = compute_beta(dates, stock, idx)
    assert raw == pytest.approx(2.0, abs=0.05)
    assert blume_adjust(1.0) == pytest.approx(1.0)
    assert blume_adjust(2.0) == pytest.approx(0.67 * 2 + 0.33)


def test_beta_insufficient_overlap_returns_none():
    dates = [dt.date(2026, 1, 1) + dt.timedelta(days=i) for i in range(30)]
    assert compute_beta(dates, [100.0] * 30, {}) is None


def test_beta_window_independent_of_display_trim(monkeypatch):
    """FIX-3: WACC must not move with the --years display trim. Two data
    objects trimmed to 3y and 10y still get identical beta when passed the
    same explicit beta slice; a different slice does move beta."""
    import forensic_viz.rates as rates

    start = dt.date(2016, 1, 1)
    dates, idx, closes = [], {}, []
    lvl_m, lvl_s = 100.0, 50.0
    moves = [0.01, -0.008, 0.012, -0.005, 0.007, -0.011, 0.009, 0.004] * 130
    n = len(moves)
    for i, m in enumerate(moves):
        day = start + dt.timedelta(days=i)
        lvl_m *= 1 + m
        # stock beta drifts from 1.4 (early) to 2.4 (recent) so the window
        # choice genuinely changes the regression slope
        beta_t = 1.4 + 1.0 * i / n
        lvl_s *= 1 + beta_t * m
        dates.append(day)
        idx[day] = lvl_m
        closes.append(lvl_s)

    monkeypatch.setattr(rates, "fetch_risk_free",
                        lambda cache=None: (0.04, dt.date(2026, 7, 2), "stub"))
    monkeypatch.setattr(rates, "fetch_index_closes", lambda cache=None: idx)

    d3 = DashboardData(ticker="T", company="T", subtitle="",
                       generated=dt.date(2026, 7, 3))
    d3.price_dates, d3.price_closes = dates[-120:], closes[-120:]  # ~3y trim
    d10 = DashboardData(ticker="T", company="T", subtitle="",
                        generated=dt.date(2026, 7, 3))
    d10.price_dates, d10.price_closes = dates, closes                # full

    beta_slice = (dates[-400:], closes[-400:])
    b3 = rates.build_wacc(d3, price_dates=beta_slice[0], price_closes=beta_slice[1])
    b10 = rates.build_wacc(d10, price_dates=beta_slice[0], price_closes=beta_slice[1])
    assert b3.beta == pytest.approx(b10.beta)  # identical slice -> identical beta

    other = rates.build_wacc(d10, price_dates=dates[-120:], price_closes=closes[-120:])
    assert other.beta != pytest.approx(b10.beta)  # different slice -> beta moves
    assert any("β window" in n for n in b10.notes)


def _wacc_with_debt(monkeypatch, interest, debt):
    import forensic_viz.rates as rates
    monkeypatch.setattr(rates, "fetch_risk_free",
                        lambda cache=None: (0.04, dt.date(2026, 7, 2), "stub"))
    monkeypatch.setattr(rates, "fetch_index_closes", lambda cache=None: None)
    d = DashboardData(ticker="T", company="T", subtitle="",
                      generated=dt.date(2026, 7, 3))
    d.last_close = 100.0
    d.diluted_shares = [1e9]
    d.total_debt = [debt, debt]
    d.interest_expense = [interest]
    d.effective_tax_rate = 0.21
    return rates.build_wacc(d)


def test_rd_clamp_binds_notes(monkeypatch):
    """FIX-4: interest/avg-debt ≈ 45% must clamp to 20% with a labeled note."""
    b = _wacc_with_debt(monkeypatch, interest=0.45e9, debt=1e9)
    assert b.r_d == pytest.approx(0.20)
    assert any("r_d clamped" in n for n in b.notes)


def test_rd_no_clamp_note_when_sane(monkeypatch):
    b = _wacc_with_debt(monkeypatch, interest=0.05e9, debt=1e9)  # 5%
    assert b.r_d == pytest.approx(0.05)
    assert not any("r_d clamped" in n for n in b.notes)


def test_build_wacc_offline_degrades_to_manual():
    d = DashboardData(ticker="T", company="T", subtitle="",
                      generated=dt.date(2026, 7, 3))
    b = build_wacc(d, offline=True)
    assert b.wacc is None and b.r_e is None
    assert any("manually" in n for n in b.notes)


def test_wacc_summary_readable():
    b = WaccBuild(r_f=0.043, r_f_date=dt.date(2026, 7, 2), r_f_source="FRED DGS10",
                  beta_raw=1.2, beta=1.13, r_e=0.095, r_d=0.05, tax=0.21,
                  e_weight=0.9, d_weight=0.1, wacc=0.089)
    s = b.summary()
    assert "r_f 4.3%" in s and "WACC 8.9%" in s and "FRED DGS10" in s

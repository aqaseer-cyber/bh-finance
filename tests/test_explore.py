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
    INSUFFICIENT, PRICE_MODES, RATIO_MODES, REVENUE_MODES, price_card,
    ratio_card, ratio_series, revenue_card,
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

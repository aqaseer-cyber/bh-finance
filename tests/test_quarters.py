"""FIX-15a: shared quarter/TTM machinery.

The extraction itself is behavior-frozen — the export suite is its
regression. These tests cover the new surfaces: `ttm_series` (gap
skipping, Q4 = FY − 9M inside the window, the per-point FCF two-leg
rule) and `step_at` boundaries.
"""
import datetime as dt
from types import SimpleNamespace

import pytest

from conftest import REVENUE
from forensic_viz.edgar import parse_companyfacts
from forensic_viz.quarters import step_at, ttm_series
from test_model_export import Q1_REV, Q2_REV, Q_2025, _facts_with_quarters

FY24, FY25 = dt.date(2024, 12, 31), dt.date(2025, 12, 31)


def _q(y, qi, val):
    """One filed discrete calendar quarter: (start, end, val)."""
    sm, em, ed = {1: (1, 3, 31), 2: (4, 6, 30),
                  3: (7, 9, 30), 4: (10, 12, 31)}[qi]
    return (dt.date(y, sm, 1), dt.date(y, em, ed), val)


def _d(series, duration, fy_ends=(FY24, FY25)):
    annual = SimpleNamespace(fy_ends=list(fy_ends), series=series,
                             raw_facts=None)
    qdata = SimpleNamespace(duration=duration, instant={})
    return SimpleNamespace(fundamentals=annual, _qdata_cache=qdata)


def test_ttm_q4_derived_inside_window():
    # Q1..Q3 filed discrete, Q4 never filed: Q4 = FY 480 − 9M YTD 330 = 150.
    # The only complete window IS the fiscal year -> TTM equals it exactly.
    rev = [_q(2025, 1, 100.0), _q(2025, 2, 110.0), _q(2025, 3, 120.0),
           (dt.date(2025, 1, 1), dt.date(2025, 9, 30), 330.0)]
    d = _d({"revenue": [400.0, 480.0]}, {"revenue": rev})
    assert ttm_series(d, "revenue") == [(FY25, pytest.approx(480.0))]


def test_ttm_skips_spine_gaps_and_missing_legs():
    rev = [_q(2025, 1, 100.0), _q(2025, 2, 110.0), _q(2025, 3, 120.0),
           (dt.date(2025, 1, 1), dt.date(2025, 9, 30), 330.0),
           _q(2026, 1, 130.0), _q(2026, 3, 140.0)]  # Q2'26 never filed
    d = _d({"revenue": [400.0, 480.0]}, {"revenue": rev})
    out = dict(ttm_series(d, "revenue"))
    assert out[FY25] == pytest.approx(480.0)
    # the window that straddles the FY boundary uses the derived Q4'25
    assert out[dt.date(2026, 3, 31)] == pytest.approx(110 + 120 + 150 + 130)
    # 2026-09-30's window spans the Q2'26 hole -> skipped, not interpolated
    assert dt.date(2026, 9, 30) not in out

    # a quarter present on the spine (via revenue) but missing THIS
    # concept's leg: no CFO window ever completes
    cfo = [_q(2025, 1, 50.0), _q(2025, 3, 55.0),  # no Q2'25 CFO anywhere
           (dt.date(2025, 1, 1), dt.date(2025, 9, 30), 160.0)]
    d2 = _d({"revenue": [400.0, 480.0], "cfo": [200.0, 220.0]},
            {"revenue": rev, "cfo": cfo})
    assert ttm_series(d2, "cfo") == []


def test_ttm_fcf_requires_both_legs_per_quarter():
    cfo = [_q(2025, 1, 50.0), _q(2025, 2, 50.0), _q(2025, 3, 50.0),
           (dt.date(2025, 1, 1), dt.date(2025, 9, 30), 150.0)]
    capex_gap = [_q(2025, 1, 10.0), _q(2025, 3, 10.0),
                 (dt.date(2025, 1, 1), dt.date(2025, 9, 30), 30.0)]
    series = {"cfo": [200.0, 220.0], "capex": [35.0, 40.0]}
    # Q2'25 capex unresolvable -> that quarter has one FCF leg -> no point,
    # even though every CFO quarter (incl. Q4 = 220 − 150) resolves
    d = _d(series, {"cfo": cfo, "capex": capex_gap})
    assert ttm_series(d, "fcf") == []
    # an H1 YTD span closes the gap (Q2 = 20 − 10): all four combine
    capex_full = capex_gap + [(dt.date(2025, 1, 1), dt.date(2025, 6, 30),
                               20.0)]
    d2 = _d(series, {"cfo": cfo, "capex": capex_full})
    # Σ cfo = 50+50+50+70 = 220; Σ capex = 10+10+10+10 = 40
    assert ttm_series(d2, "fcf") == [(FY25, pytest.approx(180.0))]


def test_step_at_boundaries():
    s = [(dt.date(2025, 3, 31), 1.0), (dt.date(2025, 6, 30), 2.0)]
    assert step_at(s, dt.date(2025, 3, 30)) is None  # before the first point
    assert step_at(s, dt.date(2025, 3, 31)) == 1.0   # exactly on a point
    assert step_at(s, dt.date(2025, 5, 1)) == 1.0    # between points
    assert step_at(s, dt.date(2025, 6, 30)) == 2.0
    assert step_at(s, dt.date(2030, 1, 1)) == 2.0    # after the last point
    assert step_at([], dt.date(2025, 1, 1)) is None


def test_ttm_matches_export_ltm_on_the_shared_fixture():
    """Same trailing twelve months, two derivation routes: the export's
    FY + YTD − prior-YTD and the TTM four-quarter sum must agree."""
    facts = _facts_with_quarters()
    annual = parse_companyfacts(facts, "TESTCO")
    d = SimpleNamespace(fundamentals=annual)  # exercises the raw_facts path
    out = ttm_series(d, "revenue")
    assert out[-1] == (dt.date(2026, 6, 30),
                       pytest.approx(REVENUE[2025] + Q1_REV + Q2_REV
                                     - 2 * Q_2025))
    # the FY-end TTM point is the fiscal year itself (Q4 derived)
    assert dict(out)[FY25] == pytest.approx(REVENUE[2025])
    assert getattr(d, "_qdata_cache", None) is not None  # memo took

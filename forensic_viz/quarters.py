"""Shared fiscal-quarter machinery (FIX-15a extraction).

The quarter spine, per-quarter discrete/YTD derivation (incl. the
Q4 = FY − 9-month-YTD rule) and the LTM flow logic used to live inside
``model_export.py``; the Explore ratio charts need the same derivations
for TTM series, and two copies would drift. The functions here moved
**verbatim** — the export test suite is the behavior-freeze regression.

Quarterly mechanics (as-filed XBRL under the annual winning tag):

- **discrete quarter** = the filed ~3-month duration when present; else
  fiscal-YTD differencing (10-Q cash-flow statements are YTD-only); a
  fiscal Q4 (never filed discretely) = FY − 9-month YTD (or FY − ΣQ1..Q3);
- **LTM (flows)** = last FY + latest fiscal YTD − year-ago comparative YTD
  (= the FY itself when the latest period end is the FY end);
- quarters with any missing leg are skipped, never interpolated.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional, Tuple

from .edgar import QuarterlyFundamentals, parse_quarterly_facts
from .metrics import fy_label

_SPAN_TOL = 14    # days tolerance matching a filed span boundary
_YEAR_TOL = 21    # days tolerance matching the year-ago span
_SHOW_QUARTERS = 4


# ---------------------------------------------------------------- span math

def _find_span(entries, start: dt.date, end: dt.date,
               tol: int = _SPAN_TOL) -> Optional[float]:
    for s, e, v in entries:
        if abs((e - end).days) <= tol and abs((s - start).days) <= tol:
            return v
    return None


def _find_3m(entries, qe: dt.date) -> Optional[float]:
    for s, e, v in entries:
        if abs((e - qe).days) <= _SPAN_TOL and 80 <= (e - s).days <= 100:
            return v
    return None


def _match_instant(obs: Dict[dt.date, float], target: dt.date,
                   tol: int = 7) -> Optional[float]:
    if target in obs:
        return obs[target]
    for d, v in obs.items():
        if abs((d - target).days) <= tol:
            return v
    return None


def _fy_bounds(qe: dt.date, fy_ends: List[dt.date]
               ) -> Tuple[Optional[dt.date], Optional[dt.date]]:
    """(fiscal-year start, containing FY end) for the quarter ending qe."""
    prev = None
    containing = None
    for fe in fy_ends:  # ascending
        if fe < qe:
            prev = fe
        elif containing is None and (fe - qe).days < 400:
            containing = fe
    start = prev + dt.timedelta(days=1) if prev else None
    return start, containing


def _all_quarter_ends(qdata: QuarterlyFundamentals,
                      fy_ends: List[dt.date]) -> List[dt.date]:
    """Every fiscal-quarter end the filings support (ascending), FY
    boundaries included, near-duplicate ends folded — the uncapped body of
    `quarter_spine` (FIX-15a split so TTM series can use the full history)."""
    interim = set()
    for entries in qdata.duration.values():
        for s, e, _ in entries:
            if 60 <= (e - s).days <= 300:  # sub-annual spans only
                interim.add(e)
    if not interim:
        return []
    latest = max(max(interim), fy_ends[-1]) if fy_ends else max(interim)
    candidates = sorted(interim | set(fy_ends))
    ends: List[dt.date] = []
    for e in candidates:  # fold ends a few days apart into one quarter
        if e > latest:
            continue
        if ends and (e - ends[-1]).days <= 10:
            ends[-1] = max(ends[-1], e)
        else:
            ends.append(e)
    # quarters need a known fiscal-year start for labeling/derivation
    return [e for e in ends if _fy_bounds(e, fy_ends)[0] is not None]


def quarter_spine(qdata: QuarterlyFundamentals,
                  fy_ends: List[dt.date]) -> List[dt.date]:
    """Trailing fiscal-quarter ends (newest last), FY boundaries included.

    Returns up to _SHOW_QUARTERS ends; empty when the filer has no
    interim data at all.
    """
    return _all_quarter_ends(qdata, fy_ends)[-_SHOW_QUARTERS:]


def quarter_label(qe: dt.date, fy_ends: List[dt.date]) -> str:
    fy_start, containing = _fy_bounds(qe, fy_ends)
    idx = max(1, min(4, round((qe - fy_start).days / 91.3)))
    # year suffix from the dashboard's fiscal-year convention (fy_label),
    # so off-calendar filers label consistently across the app
    ref = containing if containing is not None \
        else fy_ends[-1] + dt.timedelta(days=365)
    return f"Q{idx}'{fy_label(ref)[-2:]}"


def _ytd(entries, fy_start: dt.date, end: dt.date) -> Optional[float]:
    return _find_span(entries, fy_start, end)


def _ytd9m(entries, fy_start: dt.date, target: dt.date) -> Optional[float]:
    """9-month YTD for Q4 derivation: filed span, else ΣQ1..Q3 discretes."""
    v = _ytd(entries, fy_start, target)
    if v is not None:
        return v
    total = 0.0
    for back in range(3):
        q = _find_3m(entries, target - dt.timedelta(days=round(back * 91.3)))
        if q is None:
            return None
        total += q
    return total


def _discrete(entries, qe: dt.date, fy_ends: List[dt.date],
              annual_map: Dict[dt.date, Optional[float]],
              allow_fy_diff: bool = True) -> Optional[float]:
    """One fiscal quarter's flow, by whatever the filings support."""
    v = _find_3m(entries, qe)
    if v is not None:
        return v
    fy_start, containing = _fy_bounds(qe, fy_ends)
    if fy_start is None:
        return None
    if (qe - fy_start).days <= 100:  # fiscal Q1: YTD is the quarter
        return _ytd(entries, fy_start, qe)
    prev_target = qe - dt.timedelta(days=91)
    if containing is not None and abs((containing - qe).days) <= 7:
        if not allow_fy_diff:  # fiscal Q4 = FY − 9M YTD
            return None
        fy_val = annual_map.get(containing)
        ytd9 = _ytd9m(entries, fy_start, prev_target)
        if fy_val is not None and ytd9 is not None:
            return fy_val - ytd9
        return None
    y2 = _ytd(entries, fy_start, qe)
    y1 = _ytd(entries, fy_start, prev_target)
    if y2 is not None and y1 is not None:
        return y2 - y1
    return None


def _ltm_flow(fy_val: Optional[float], entries, fy_ends: List[dt.date],
              q_ends: List[dt.date]) -> Tuple[Optional[float], str]:
    """LTM = last FY + latest filed fiscal YTD − year-ago comparative YTD.

    Returns (value, basis): basis "ltm" for a true trailing twelve months,
    "fy" when the value fell back to the completed fiscal year, "none"
    when nothing could be computed (FIX-11c provenance).
    """
    if fy_val is None:
        return None, "none"
    if not q_ends:
        return fy_val, "fy"  # trailing twelve months == the completed year
    last_fy_end = fy_ends[-1]
    fy_start = last_fy_end + dt.timedelta(days=1)
    prior_fy_start = (fy_ends[-2] + dt.timedelta(days=1)
                      if len(fy_ends) >= 2 else None)
    for qe in reversed(q_ends):  # latest period end with a usable YTD
        if abs((qe - last_fy_end).days) <= 7:
            return fy_val, "fy"  # the latest period IS the fiscal year
        if qe < last_fy_end:
            continue  # stale interim inside an already-reported year
        ytd = _ytd(entries, fy_start, qe)
        if ytd is None:
            continue
        if prior_fy_start is None:
            return None, "none"
        prior = _find_span(entries, prior_fy_start,
                           qe - dt.timedelta(days=365), tol=_YEAR_TOL)
        if prior is None:
            return None, "none"
        return fy_val + ytd - prior, "ltm"
    return None, "none"


# ------------------------------------------------- FIX-15a TTM additions

# four consecutive fiscal-quarter ENDS span ~273 days first→last; a hole in
# the spine (a skipped quarter) pushes the window past a year
_TTM_WINDOW_MAX_DAYS = 300


def quarterly_of(d) -> Optional[QuarterlyFundamentals]:
    """Quarterly parse off the dashboard's stored companyfacts payload,
    memoized on the DashboardData (the export re-parses independently;
    Explore re-renders per card, so the memo keeps redraws instant)."""
    cached = getattr(d, "_qdata_cache", None)
    if cached is not None:
        return cached
    annual = getattr(d, "fundamentals", None)
    raw = getattr(annual, "raw_facts", None) if annual is not None else None
    if annual is None or raw is None:
        return None
    qdata = parse_quarterly_facts(raw, annual)
    try:
        d._qdata_cache = qdata
    except Exception:
        pass  # exotic containers without attribute assignment: just re-parse
    return qdata


def ttm_series(d, concept: str) -> List[Tuple[dt.date, float]]:
    """(quarter_end, trailing-4Q sum) for a flow concept, using the same
    discrete-quarter derivation as the export (incl. Q4 = FY − 9M).
    Quarters with any missing leg are skipped, not interpolated — a TTM
    point exists only where four consecutive fiscal quarters all resolve.

    concept "fcf" derives per quarter as CFO − capex; a quarter enters
    only when both legs exist (the FIX-11c mixed-basis rule, per point).
    Per-share concepts (eps_diluted) sum the same way — the additive
    approximation already footnoted in the export.
    """
    annual = getattr(d, "fundamentals", None)
    qdata = quarterly_of(d)
    if annual is None or qdata is None or not annual.fy_ends:
        return []
    fy_ends = annual.fy_ends
    q_ends = _all_quarter_ends(qdata, fy_ends)
    if not q_ends:
        return []

    def per_quarter(name: str) -> Dict[dt.date, Optional[float]]:
        entries = qdata.duration.get(name, [])
        ann = list(annual.series.get(name) or [None] * len(fy_ends))
        annual_map = dict(zip(fy_ends, ann))
        return {qe: _discrete(entries, qe, fy_ends, annual_map)
                for qe in q_ends}

    if concept == "fcf":
        cfo, capex = per_quarter("cfo"), per_quarter("capex")
        vals = {qe: (cfo[qe] - capex[qe])
                if cfo[qe] is not None and capex[qe] is not None else None
                for qe in q_ends}
    else:
        vals = per_quarter(concept)

    out: List[Tuple[dt.date, float]] = []
    for i in range(3, len(q_ends)):
        window = q_ends[i - 3:i + 1]
        legs = [vals[qe] for qe in window]
        if any(v is None for v in legs):
            continue
        if (window[-1] - window[0]).days > _TTM_WINDOW_MAX_DAYS:
            continue  # a quarter is missing from the spine itself
        out.append((window[-1], sum(legs)))
    return out


def step_at(series: List[Tuple[dt.date, float]],
            when: dt.date) -> Optional[float]:
    """Step-function lookup: latest quarter_end ≤ when, None before the
    first point."""
    out = None
    for qe, v in series:
        if qe <= when:
            out = v
        else:
            break
    return out

"""Growth anchor ladder — disciplined g₀ seeding for the FCFF two-stage fade.

The old prefill mapped analyst *dispersion* to *scenarios* (Bear ← lowest
analyst, Bull ← highest) and fed a one-year forward estimate into a ten-year
linear fade. This module replaces that mapping with three anchors:

    consensus    Yahoo +1y revenue growth (the existing fetch) — once it
                 feeds a decade fade, the sell-side mean IS the optimistic
                 case, so it seeds Bull, not Base
    hist_cagr    trailing 5y revenue CAGR on the headline basis (FIX-11a)
    fundamental  median ROIC(3y) × median reinvestment rate(3y) — growth
                 and reinvestment are one economic decision (g = ROIC × RR)

Base = min(available anchors); Bear = ½ Base (floored at 0, never above
Base); a consensus-only ladder takes
a 25% haircut. Every seed carries provenance (source, window, formula) and
every prefill stays editable — the automation referees Yahoo, it does not
replace the analyst. Capex enters as base normalization and growth
discipline, never as a fourth projection input (parity with the v3 shell).
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# When a concept lives on DashboardData under a different name than the
# AnnualFundamentals series key, look it up there as the fallback.
_DASH_ALIAS = {"operating_income": "ebit_reported"}

_ASSUMED_TAX = 0.21  # metrics.py's labeled fallback when no usable rate filed

RR_CLAMP = (0.0, 1.5)      # per-year reinvestment-rate clamp
FUNDAMENTAL_CLAMP = (0.0, 0.40)   # g = ROIC × RR clamp
SINGLE_ANCHOR_HAIRCUT = 0.75      # Base = consensus × 0.75 when it stands alone
CAPEX_DEVIATION = 0.30     # |latest/median − 1| beyond this = peak/trough year


def _series(d, concept: str) -> List[Optional[float]]:
    """Full-history fiscal series, oldest → newest. Prefers the untrimmed
    AnnualFundamentals arrays (`d.fundamentals.series`) so the anchors do not
    change with the user's display window; falls back to the DashboardData
    attribute of the same (or aliased) name. All arrays end at the latest
    fiscal year, so trailing windows align across sources."""
    f = getattr(d, "fundamentals", None)
    if f is not None:
        arr = (getattr(f, "series", None) or {}).get(concept)
        if arr:
            return list(arr)
    attr = getattr(d, concept, None)
    if attr is None and concept in _DASH_ALIAS:
        attr = getattr(d, _DASH_ALIAS[concept], None)
    return list(attr) if attr else []


def _at(series: List[Optional[float]], i: int) -> Optional[float]:
    """series[i] with Python index semantics (negative = from the latest
    fiscal year); out of range → None."""
    n = len(series)
    j = n + i if i < 0 else i
    return series[j] if 0 <= j < n else None


def revenue_cagr(d, years: int = 5) -> Optional[float]:
    """Geometric CAGR between the first and last non-None revenue values
    inside the trailing `years+1` fiscal points; None if < 3 non-None points
    or a non-positive endpoint. Revenue is the headline basis (FIX-11a)."""
    window = _series(d, "revenue")[-(years + 1):]
    points = [(i, v) for i, v in enumerate(window) if v is not None]
    if len(points) < 3:
        return None
    (i0, first), (i1, last) = points[0], points[-1]
    span = i1 - i0
    if first <= 0 or last <= 0 or span <= 0:
        return None
    return (last / first) ** (1.0 / span) - 1.0


def operating_nwc(d, i: int, notes: Optional[List[str]] = None) -> Optional[float]:
    """Operating net working capital (AR + inventory − AP) at fiscal index
    `i` (Python semantics, -1 = latest). Missing components are treated as 0
    with a note appended to `notes`; None when all three are missing."""
    parts = {"AR": _at(_series(d, "accounts_receivable"), i),
             "inventory": _at(_series(d, "inventory"), i),
             "AP": _at(_series(d, "accounts_payable"), i)}
    if all(v is None for v in parts.values()):
        return None
    missing = [k for k, v in parts.items() if v is None]
    if missing and notes is not None:
        notes.append(f"NWC[{i}]: {', '.join(missing)} missing, treated as 0")
    return ((parts["AR"] or 0.0) + (parts["inventory"] or 0.0)
            - (parts["AP"] or 0.0))


def reinvestment_rate(d, notes: Optional[List[str]] = None) -> Optional[float]:
    """Median over the last 3 fiscal years of

        (capex + ΔNWC − D&A) / NOPAT,   NOPAT = EBIT × (1 − τ_eff)

    with the existing effective-tax logic (d.effective_tax_rate, labeled 21%
    assumption when absent). Years with NOPAT ≤ 0 are skipped; a missing
    ΔNWC or D&A leg is treated as 0 with a note; a year without capex or
    EBIT is unusable. Each year clamps to [0.0, 1.5]; None if < 2 usable
    years."""
    tau = getattr(d, "effective_tax_rate", None)
    if tau is None:
        tau = _ASSUMED_TAX
        if notes is not None:
            notes.append(f"τ_eff missing — ASSUMPTION {_ASSUMED_TAX:.0%}")
    capex_s, dna_s = _series(d, "capex"), _series(d, "dna")
    ebit_s = _series(d, "operating_income")
    rates = []
    for i in (-3, -2, -1):
        capex, ebit = _at(capex_s, i), _at(ebit_s, i)
        if capex is None or ebit is None:
            if notes is not None:
                notes.append(f"RR[{i}]: no {'capex' if capex is None else 'EBIT'} — year skipped")
            continue
        nopat = ebit * (1.0 - tau)
        if nopat <= 0:
            if notes is not None:
                notes.append(f"RR[{i}]: NOPAT ≤ 0 — year skipped")
            continue
        dna = _at(dna_s, i)
        if dna is None:
            dna = 0.0
            if notes is not None:
                notes.append(f"RR[{i}]: D&A missing, treated as 0")
        nwc_now, nwc_prev = operating_nwc(d, i, notes), operating_nwc(d, i - 1, notes)
        if nwc_now is None or nwc_prev is None:
            d_nwc = 0.0
            if notes is not None:
                notes.append(f"RR[{i}]: ΔNWC unavailable, treated as 0")
        else:
            d_nwc = nwc_now - nwc_prev
        rate = (capex + d_nwc - dna) / nopat
        rates.append(min(max(rate, RR_CLAMP[0]), RR_CLAMP[1]))
    if len(rates) < 2:
        return None
    return statistics.median(rates)


def median_roic(d) -> Optional[float]:
    """Median of the last 3 available (non-None) ROIC years."""
    have = [v for v in getattr(d, "roic", None) or [] if v is not None]
    return statistics.median(have[-3:]) if have else None


def fundamental_growth(d) -> Optional[float]:
    """g = median ROIC (last 3 available) × reinvestment_rate, clamped to
    [0.0, 0.40]. None when either leg is None."""
    roic, rr = median_roic(d), reinvestment_rate(d)
    if roic is None or rr is None:
        return None
    g = roic * rr
    return min(max(g, FUNDAMENTAL_CLAMP[0]), FUNDAMENTAL_CLAMP[1])


def capex_intensity(d, years: int = 5) -> Optional[Tuple[float, float]]:
    """(median capex/revenue over the trailing `years` fiscal points, latest
    capex/revenue). A usable pair needs both values with revenue > 0; None
    if < 3 usable pairs. 'Latest' is the most recent usable pair."""
    capex_s, rev_s = _series(d, "capex"), _series(d, "revenue")
    intensities = []
    for i in range(-years, 0):
        c, r = _at(capex_s, i), _at(rev_s, i)
        if c is not None and r is not None and r > 0:
            intensities.append(c / r)
    if len(intensities) < 3:
        return None
    return statistics.median(intensities), intensities[-1]


def capex_peak_flag(d, years: int = 5) -> bool:
    """The automated house-§2 capex-peak rule: latest capex intensity more
    than ±30% off its trailing median marks a peak/trough year whose
    as-reported base needs normalization."""
    ci = capex_intensity(d, years)
    if ci is None or ci[0] <= 0:
        return False
    median, latest = ci
    return abs(latest / median - 1.0) > CAPEX_DEVIATION


def normalized_base(d) -> Optional[Tuple[float, float]]:
    """(normalized FCFF base = latest CFO − median_intensity × latest
    revenue, median_intensity) — the shell's B42−B43 frame with
    through-cycle capex. None when capex_intensity, CFO or revenue is
    unavailable for the latest fiscal year."""
    ci = capex_intensity(d)
    cfo = _at(_series(d, "cfo"), -1)
    rev = _at(_series(d, "revenue"), -1)
    if ci is None or cfo is None or rev is None or rev <= 0:
        return None
    median, _latest_i = ci
    return cfo - median * rev, median


@dataclass
class GrowthAnchors:
    consensus: Optional[float] = None    # Yahoo +1y revenue growth
    consensus_range: Optional[Tuple[float, float]] = None  # (g_low, g_high), display-only
    n_analysts: Optional[int] = None
    hist_cagr: Optional[float] = None    # trailing 5y revenue CAGR
    fundamental: Optional[float] = None  # median ROIC(3y) × median RR(3y)
    details: Dict[str, str] = field(default_factory=dict)  # per-anchor provenance
    seeds: Dict[str, float] = field(default_factory=dict)  # {"Bear"/"Base"/"Bull": g0}
    binding: str = ""                    # which anchor bound Base


def build_growth_anchors(d) -> GrowthAnchors:
    """Assemble the anchor ladder and the Bear/Base/Bull g₀ seeds.

    Seeding: Bull = consensus (else hist_cagr, else no Bull seed) — the
    sell-side mean is the optimistic decade case once it feeds a ten-year
    fade. Base = min(available anchors); consensus standing alone takes a
    25% haircut. Bear = ½ Base floored at 0 but never above Base (a
    shrinking name seeds Bear = Base). Terminal-g seeding is untouched
    (house GDP-cap default lives with the callers). No anchors → seeds = {}
    (the old silent no-prefill behavior)."""
    est = getattr(d, "analyst_estimates", None) or {}
    consensus = est.get("g_avg")
    g_low, g_high = est.get("g_low"), est.get("g_high")
    rng = (g_low, g_high) if g_low is not None and g_high is not None else None
    n = est.get("n_analysts")

    details: Dict[str, str] = {}
    if consensus is not None:
        details["consensus"] = (
            f"{est.get('period', '+1y revenue vs 0y consensus')} "
            f"({est.get('source', 'analyst consensus')}"
            + (f", n={n}" if n else "") + ", Rung 4)")

    hist = revenue_cagr(d)
    if hist is not None:
        details["hist_cagr"] = ("geometric CAGR, first→last non-None revenue "
                                "in the trailing 6 fiscal points, headline "
                                "basis (FIX-11a)")

    rr_notes: List[str] = []
    rr = reinvestment_rate(d, rr_notes)
    roic = median_roic(d)
    fund = fundamental_growth(d)
    if fund is not None:
        details["fundamental"] = (
            f"median ROIC(3y) {roic:.1%} × median RR(3y) {rr:.0%} "
            f"(RR = (capex + ΔNWC − D&A) / NOPAT)")
    if rr_notes:
        details["reinvestment_notes"] = "; ".join(rr_notes)

    ladder = {"consensus": consensus, "5y CAGR": hist, "fundamental": fund}
    avail = {k: v for k, v in ladder.items() if v is not None}
    seeds: Dict[str, float] = {}
    binding = ""
    if avail:
        if set(avail) == {"consensus"}:
            base = consensus * SINGLE_ANCHOR_HAIRCUT
            binding = "consensus (single-anchor, 25% haircut)"
        else:
            binding, base = min(avail.items(), key=lambda kv: kv[1])
        bull = consensus if consensus is not None else hist
        # ½ × Base floored at 0 — but never ABOVE Base: for a negative-
        # consensus (shrinking) name the zero floor would otherwise seed a
        # Bear more optimistic than Base (owner-ratified amendment,
        # 2026-07-11 GSL observation)
        seeds["Bear"] = min(base, max(0.0, 0.5 * base))
        seeds["Base"] = base
        if bull is not None:
            seeds["Bull"] = bull
            details["seed:Bull"] = ("consensus mean — the optimistic decade case"
                                    if consensus is not None
                                    else "5y CAGR (no consensus)")
        details["seed:Base"] = f"min anchor = {binding}"
        details["seed:Bear"] = "½ × Base, floored at 0, never above Base"

    return GrowthAnchors(consensus=consensus, consensus_range=rng,
                         n_analysts=n, hist_cagr=hist, fundamental=fund,
                         details=details, seeds=seeds, binding=binding)


def anchor_readout(a: GrowthAnchors) -> str:
    """One-line provenance readout for the dialog / CLI, e.g.:

    anchors — consensus +22.4% (Yahoo, n=31, Rung 4) · 5y rev CAGR +19.8% ·
    ROIC×RR +11.2% → Base = fundamental (binding) · analyst range
    +15.1%…+29.8%
    """
    if not a.seeds:
        return ""
    parts = []
    if a.consensus is not None:
        src = "Yahoo" if "Yahoo" in (a.details.get("consensus") or "") else "consensus"
        meta = [src] + ([f"n={a.n_analysts}"] if a.n_analysts else []) + ["Rung 4"]
        parts.append(f"consensus {a.consensus:+.1%} ({', '.join(meta)})")
    if a.hist_cagr is not None:
        parts.append(f"5y rev CAGR {a.hist_cagr:+.1%}")
    if a.fundamental is not None:
        parts.append(f"ROIC×RR {a.fundamental:+.1%}")
    line = "anchors — " + " · ".join(parts)
    if a.binding:
        suffix = "" if "(" in a.binding else " (binding)"
        line += f" → Base = {a.binding}{suffix}"
    if a.consensus_range is not None:
        lo, hi = a.consensus_range
        line += f" · analyst range {lo:+.1%}…{hi:+.1%}"
    return line

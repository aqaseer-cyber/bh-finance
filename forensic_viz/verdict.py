"""Phase 5 — stress test, dual-track FV average, MoS, and the rating gate.

Core mechanics follow the workbook (Control / Phase5_Verdict tabs):
- FV_avg = average(FV_A, FV_B);  MoS = (FV_avg − P0) / P0     (master §5.2)
- Standard-track stress: −5% shock to FCFF₁ (Phase5_Verdict!B22 default)

Deliberate deviations from the shell (documented per the parity rule):
- The coherence gate is a SUPERSET of Control!B67: it adds "Strong Buy" to the
  Hold/Buy set, and adds a named-optionality exception that also requires the
  §4.D reverse-DCF implied g to exceed the GDP cap (the shell's B67 has no
  optionality carve-out).
- Stress is applied to BOTH tracks and averaged (stressed FV_A and FV_B), where
  the shell's Phase5!B23/B24 stresses Track B only.
- The reverse-DCF basis feeding the optionality exception is the Track-B ex-SBC
  base over market EV including the bridge legs, matching Control!B58 (FIX-2).

Dual-track mapping in this app (documented approximation of §4 Track A/B):
- DCF:   Track A = Bear-case growths on the as-reported FCFF base;
         Track B = Base-case growths on the ex-SBC base (house §2b).
- RI:    Track A = Bear ROE path (trough), Track B = Base (through-cycle).
- AFFO / manual: Track A = Bear case, Track B = Base case.

Track-specific shocks (master §5.1), applied to BOTH tracks:
- Standard/SOTP: FCFF −5% (workbook default; ≈ −200 bps margin on a 40%-
  gross business — override in the dialog if the house file says otherwise)
- Banks:     −100 bps NIM on avg assets (proxy), after tax, through ROE
- Insurance: +5 pts combined ratio on NEP, after tax, through ROE
- REITs:     +100 bps target AFFO yield
The rating itself stays with the analyst — the app only checks coherence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from . import config
from .metrics import DashboardData, fmt_pct
from .valuation import (
    CASE_NAMES, ValuationInputs, ValuationResult, dcf_fcff, effective_sbc,
    residual_income,
)

RATINGS = ("", "Strong Buy", "Buy", "Hold", "Sell")
COHERENCE_MOS = -0.15  # Control!B67 threshold
# House-overridable stress shocks (FIX-7); names kept for back-compat.
STANDARD_FCFF_SHOCK = config.STANDARD_FCFF_SHOCK  # Phase5_Verdict!B22
BANK_NIM_SHOCK = config.BANK_NIM_SHOCK            # master §5.1
INSURANCE_CR_SHOCK = config.INSURANCE_CR_SHOCK
REIT_YIELD_SHOCK = config.REIT_YIELD_SHOCK


@dataclass
class Phase5Verdict:
    fv_a: Optional[float]
    fv_b: Optional[float]
    fv_avg: Optional[float]
    mos: Optional[float]
    stressed_fv_a: Optional[float]
    stressed_fv_b: Optional[float]
    stressed_fv_avg: Optional[float]
    stressed_mos: Optional[float]
    shock_label: str
    track_a_label: str
    track_b_label: str
    rating: str = ""
    optionality: str = ""
    coherence: str = "ok"
    coherence_detail: str = ""
    notes: List[str] = field(default_factory=list)


def _latest(seq):
    for v in reversed(seq or []):
        if v is not None:
            return v
    return None


def _dcf_fv(base: float, rate: float, g0: float, g_term: float,
            bridge: float, shares: float) -> float:
    out = dcf_fcff(base, rate, g0, g_term)
    return (out["ev"] - bridge) / shares


def _ri_fv(bv0: float, rate: float, roe: float, g0: float, g_term: float,
           shares: float) -> float:
    return residual_income(bv0, rate, roe, g0, g_term)["value"] / shares


def build_verdict(d: DashboardData, inputs: ValuationInputs,
                  res: ValuationResult, rating: str = "",
                  optionality: str = "") -> Phase5Verdict:
    """Assemble Phase 5 from a completed valuation. Never raises on gaps —
    every missing leg becomes a note (the verdict page states what's missing)."""
    method = inputs.method
    bear, base = inputs.cases["Bear"], inputs.cases["Base"]
    rate = res.discount_rate
    # Full equity bridge from the valuation (FIX-2); net-debt-only fallback
    # covers results built before the bridge existed.
    bridge = res.bridge if res.bridge is not None else (res.net_debt or 0.0)
    shares = res.shares
    notes: List[str] = []
    tau = d.effective_tax_rate if d.effective_tax_rate is not None else 0.21

    fv_a = fv_b = s_a = s_b = None
    shock_label = ""
    track_a_label = "Track A — skeptic (Bear case)"
    track_b_label = "Track B — institutional (Base case)"

    if method == "dcf" and rate is not None and shares:
        base_a = res.base_value if not inputs.ex_sbc else None
        if base_a is None:
            base_a = _latest(d.fcff)
        # FIX-11d: same SBC read as valuation (override-aware) — the two
        # engines cannot diverge on the Track B basis
        sbc = effective_sbc(d) or 0.0
        base_b = (base_a - sbc) if base_a is not None else None
        track_a_label = "Track A — as-reported FCFF, Bear growths"
        track_b_label = "Track B — ex-SBC FCFF (house §2b), Base growths"
        shock_label = f"FCFF shock {fmt_pct(STANDARD_FCFF_SHOCK, signed=True)} (§5.1 Standard)"
        if base_a is not None and base_a > 0:
            fv_a = _dcf_fv(base_a, rate, bear.g0, bear.g_term, bridge, shares)
            s_a = _dcf_fv(base_a * (1 + STANDARD_FCFF_SHOCK), rate,
                          bear.g0, bear.g_term, bridge, shares)
        else:
            notes.append("Track A base unavailable — as-reported FCFF missing")
        if base_b is not None and base_b > 0:
            fv_b = _dcf_fv(base_b, rate, base.g0, base.g_term, bridge, shares)
            s_b = _dcf_fv(base_b * (1 + STANDARD_FCFF_SHOCK), rate,
                          base.g0, base.g_term, bridge, shares)
        else:
            notes.append("Track B ex-SBC base non-positive — SBC exceeds FCFF; "
                         "normalize manually (house §2b)")

    elif method == "ri" and rate is not None and shares:
        bv0 = res.base_value
        # ROE shock: banks −100 bps NIM on avg assets; insurance +5 pts CR on NEP.
        # Both hit net income after tax, expressed as a ROE haircut off BV0.
        droe = None
        if d.track == "insurance":
            nep = _latest(d.premiums_earned)
            if nep and bv0:
                droe = INSURANCE_CR_SHOCK * nep * (1 - tau) / bv0
            shock_label = "+5 pts combined ratio (§5.1 Insurance)"
        else:
            assets = None  # back out total assets from equity / (equity/assets)
            for ratio, eq in zip(reversed(d.equity_to_assets or []),
                                 reversed(d.book_equity or [])):
                if ratio and eq:
                    assets = eq / ratio
                    break
            if assets and bv0:
                droe = -BANK_NIM_SHOCK * assets * (1 - tau) / bv0
            shock_label = "−100 bps NIM on avg assets (§5.1 Banks)"
        if bv0 and bv0 > 0:
            fv_a = _ri_fv(bv0, rate, bear.roe, bear.g0, bear.g_term, shares)
            fv_b = _ri_fv(bv0, rate, base.roe, base.g0, base.g_term, shares)
            if droe is not None:
                shocked = abs(droe)
                s_a = _ri_fv(bv0, rate, bear.roe - shocked, bear.g0, bear.g_term, shares)
                s_b = _ri_fv(bv0, rate, base.roe - shocked, base.g0, base.g_term, shares)
            else:
                notes.append("ROE shock base unavailable (needs assets/NEP) — "
                             "stressed MoS not computed")

    elif method == "affo":
        shock_label = f"+100 bps target AFFO yield (§5.1 REITs)"
        if bear.affo_ps and bear.target_yield:
            fv_a = bear.affo_ps / bear.target_yield
            s_a = bear.affo_ps / (bear.target_yield + REIT_YIELD_SHOCK)
        if base.affo_ps and base.target_yield:
            fv_b = base.affo_ps / base.target_yield
            s_b = base.affo_ps / (base.target_yield + REIT_YIELD_SHOCK)

    else:  # manual / SOTP
        fv_a, fv_b = bear.fv_ps, base.fv_ps
        shock_label = "no model shock — SOTP values are analyst-supplied (§5.1)"
        notes.append("stress the segment models externally and re-enter")

    fv_avg = ((fv_a + fv_b) / 2 if fv_a is not None and fv_b is not None
              else fv_a if fv_a is not None else fv_b)
    stressed_avg = ((s_a + s_b) / 2 if s_a is not None and s_b is not None
                    else s_a if s_a is not None else s_b)
    price = res.price
    mos = (fv_avg - price) / price if fv_avg is not None else None
    s_mos = (stressed_avg - price) / price if stressed_avg is not None else None

    v = Phase5Verdict(
        fv_a=fv_a, fv_b=fv_b, fv_avg=fv_avg, mos=mos,
        stressed_fv_a=s_a, stressed_fv_b=s_b,
        stressed_fv_avg=stressed_avg, stressed_mos=s_mos,
        shock_label=shock_label, track_a_label=track_a_label,
        track_b_label=track_b_label, rating=rating.strip(),
        optionality=optionality.strip(), notes=notes,
    )

    # Coherence gate — Control!B67 mechanics + the §4.D optionality exception
    if not v.rating:
        v.coherence = "no rating"
        v.coherence_detail = ("rating is analyst judgment (§5.3) — enter it in "
                              "the dialog / --rating; the gate then checks it "
                              "against the MoS")
    elif mos is None:
        v.coherence = "no MoS"
        v.coherence_detail = "FV_avg unavailable — see notes"
    elif mos < COHERENCE_MOS and v.rating in ("Hold", "Buy", "Strong Buy"):
        named = bool(v.optionality)
        over_cap = res.implied_g is not None and res.implied_g > config.GDP_CAP
        if named and over_cap:
            v.coherence = "ok (optionality named)"
            v.coherence_detail = (f"MoS {fmt_pct(mos)} vs '{v.rating}' is carried by "
                                  f"named optionality: {v.optionality}")
        else:
            v.coherence = "CHECK: rating vs MoS"
            v.coherence_detail = (
                f"MoS {fmt_pct(mos)} < −15% with '{v.rating}' — a deeply negative "
                "MoS + Hold is a Sell unless the gap is §4.D optionality, which "
                "must be NAMED"
                + ("" if not named else
                   " and supported by an over-cap implied g (it isn't here)"))
    else:
        v.coherence = "ok"
        v.coherence_detail = f"rating '{v.rating}' is consistent with MoS {fmt_pct(mos)}"
    return v
"""The live DCF sandbox compute (FIX-15c; engine-side since v3 R3).

Moved verbatim out of the deleted `explore.py` — the web Valuation
screen drives it through /api/sandbox. A thin wrapper over the
PRODUCTION functions (`dcf_fcff`, the valuation's bridge,
`reverse_dcf_implied_g` on the Track-B ex-SBC basis per FIX-2).
Deliberately no new math: there is no parallel implementation to
parity-test, which is what retired the JS replica."""
from __future__ import annotations

from typing import Optional

from .valuation import (
    ValuationError, dcf_fcff, implied_return, reverse_dcf_implied_g,
)

WACC_EXCEEDS_G = "n/a — WACC must exceed g"


def sandbox_compute(base: float, wacc: float, g0: float, g_term: float,
                    bridge: float, shares: float, sbc: float, ex_sbc: bool,
                    price: Optional[float] = None) -> dict:
    """Returns {"fv_ps", "mos", "tv_share", "implied_g",
    "implied_return", "ev", "error"}; on a guard failure only "error"
    is set (wacc ≤ g renders as a message, never an exception)."""
    out = {"fv_ps": None, "mos": None, "tv_share": None,
           "implied_g": None, "implied_return": None, "ev": None,
           "error": None}
    if not shares or shares <= 0:
        out["error"] = "n/a — diluted share count unavailable"
        return out
    eff_base = max(base - sbc, 0.0) if ex_sbc else base
    if eff_base <= 0:
        out["error"] = "n/a — base must be positive (normalize per §4.0)"
        return out
    if wacc <= g_term:
        out["error"] = WACC_EXCEEDS_G
        return out
    try:
        dcf = dcf_fcff(eff_base, wacc, g0, g_term)
    except ValuationError as exc:
        out["error"] = f"n/a — {exc}"
        return out
    out["ev"] = dcf["ev"]
    out["tv_share"] = dcf["tv_share"]
    out["fv_ps"] = (dcf["ev"] - bridge) / shares
    if price and price > 0:
        out["mos"] = (out["fv_ps"] - price) / price
        # the entry is always the AS-REPORTED base (the checkbox derives),
        # so the Track-B reverse-DCF basis is base − SBC (Control!B58)
        base_b = base - sbc
        if base_b > 0:
            out["implied_g"] = reverse_dcf_implied_g(
                base_b, wacc, price * shares + bridge)
        # FIX-16c: the return buying at P₀ earns under the slider fade
        out["implied_return"] = implied_return(
            price, eff_base, g0, g_term, bridge, shares)
    return out

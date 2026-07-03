"""Phase-4 intrinsic value calculator — Bear / Base / Bull cases.

Methods (master prompt Phase 4):
- DCF   — §4.A FCFF 2-stage DCF, 10-year linear fade from stage-1 g0 to
          terminal g, TV Gordon growth, equity bridge, FV per share, plus the
          §4.D reverse-DCF sanity frame (implied single-stage g).
- RI    — §4.B residual income at r_e for banks/insurance:
          V0 = BV0 + Σ (ROE − r_e)·BV_{t-1}/(1+r_e)^t + TV/(1+r_e)^T.
- AFFO  — §4.C REIT cross-check: FV/sh = AFFO per share / target AFFO yield.
- MANUAL— SOTP or any externally-modelled value: the analyst supplies FV per
          share (segment economics are not in companyfacts XBRL), the app
          computes the margin of safety.

Guardrails ported from the master: terminal g capped at 3.5% (GDP cap, warn),
discount rate must exceed terminal g (hard error), TV share of EV reported
and flagged when high, price staleness > 5 trading days warned (house §8).

Simplifications (stated on the report): net debt = total debt − cash, with
no minority interest / preferred / non-operating-investment legs (those XBRL
concepts are not pulled yet); r_f is not fetched, so the g ≤ r_f constraint
is left to the analyst.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .metrics import DashboardData, fmt_money, fmt_pct

HORIZON = 10
GDP_CAP = 0.035
HIGH_TV_SHARE = 0.75
PRICE_STALENESS_DAYS = 7  # ~5 trading days, house §8

METHODS = {
    "dcf": "DCF — FCFF 2-stage, 10y fade (Standard track)",
    "ri": "Residual income at r_e (Banks / Insurance)",
    "affo": "AFFO yield (REIT cross-check)",
    "manual": "Manual / SOTP — analyst-supplied FV per share",
}
CASE_NAMES = ("Bear", "Base", "Bull")


class ValuationError(ValueError):
    """User-facing input problem (bad rate, missing base, WACC <= g, ...)."""


@dataclass
class CaseInputs:
    """Per-case assumptions; which fields matter depends on the method.

    dcf:    g0 (stage-1 growth), g_term (terminal growth)
    ri:     roe (sustainable ROE), g0 (book growth, year 1), g_term
    affo:   affo_ps ($ per share), target_yield
    manual: fv_ps ($ per share)
    """
    g0: Optional[float] = None
    g_term: Optional[float] = None
    roe: Optional[float] = None
    affo_ps: Optional[float] = None
    target_yield: Optional[float] = None
    fv_ps: Optional[float] = None


@dataclass
class ValuationInputs:
    method: str
    cases: Dict[str, CaseInputs]                 # keyed by CASE_NAMES
    discount_rate: Optional[float] = None        # WACC (dcf) or r_e (ri)
    base_value: Optional[float] = None           # base FCFF $ (dcf) / BV0 $ (ri)
    ex_sbc: bool = False                         # dcf base on ex-SBC FCF (house §2b)


@dataclass
class CaseResult:
    name: str
    assumptions: str
    fv_ps: Optional[float]
    mos: Optional[float]
    ev: Optional[float] = None
    equity: Optional[float] = None
    tv_share: Optional[float] = None
    warnings: List[str] = field(default_factory=list)


@dataclass
class ValuationResult:
    method: str
    method_label: str
    basis_label: str
    discount_rate: Optional[float]
    base_value: Optional[float]
    price: float
    price_date: Optional[dt.date]
    net_debt: Optional[float]
    shares: float
    cases: List[CaseResult]
    implied_g: Optional[float] = None            # §4.D reverse DCF
    warnings: List[str] = field(default_factory=list)


def suggest_method(sic_code: str) -> str:
    """Pre-select the Logic Track from the SIC code; the analyst can override
    (economic engine beats vendor code, SKILL_General §2)."""
    if not sic_code:
        return "dcf"
    if sic_code == "6798":
        return "affo"
    if sic_code.startswith("6"):
        return "ri"
    return "dcf"


# ------------------------------------------------------------------ math

def dcf_fcff(base_fcff: float, wacc: float, g0: float, g_term: float,
             years: int = HORIZON) -> dict:
    """Master §4.A: g_i fades linearly from g0 (year 1) to g_term (year N)."""
    if years < 2:
        raise ValuationError("DCF horizon must be at least 2 years.")
    if wacc <= g_term:
        raise ValuationError(
            f"WACC ({fmt_pct(wacc)}) must exceed terminal g ({fmt_pct(g_term)}) "
            "— the terminal value is undefined otherwise (master §4.A).")
    fcff, pv_explicit = base_fcff, 0.0
    for i in range(1, years + 1):
        g_i = g0 + (g_term - g0) * (i - 1) / (years - 1)
        fcff *= 1 + g_i
        pv_explicit += fcff / (1 + wacc) ** i
    tv = fcff * (1 + g_term) / (wacc - g_term)
    pv_tv = tv / (1 + wacc) ** years
    ev = pv_explicit + pv_tv
    return {"ev": ev, "pv_explicit": pv_explicit, "pv_tv": pv_tv,
            "tv_share": pv_tv / ev if ev else None, "fcff_final": fcff}


def residual_income(bv0: float, r_e: float, roe: float, g0: float,
                    g_term: float, years: int = HORIZON) -> dict:
    """Master §4.B: V0 = BV0 + Σ (ROE − r_e)·BV_{t-1}/(1+r_e)^t + TV."""
    if years < 2:
        raise ValuationError("RI horizon must be at least 2 years.")
    if r_e <= g_term:
        raise ValuationError(
            f"r_e ({fmt_pct(r_e)}) must exceed terminal g ({fmt_pct(g_term)}).")
    bv, pv_ri, ri = bv0, 0.0, 0.0
    for t in range(1, years + 1):
        g_t = g0 + (g_term - g0) * (t - 1) / (years - 1)
        ri = (roe - r_e) * bv
        pv_ri += ri / (1 + r_e) ** t
        bv *= 1 + g_t
    tv = ri * (1 + g_term) / (r_e - g_term)
    pv_tv = tv / (1 + r_e) ** years
    value = bv0 + pv_ri + pv_tv
    return {"value": value, "pv_ri": pv_ri, "pv_tv": pv_tv,
            "tv_share": pv_tv / value if value else None}


def reverse_dcf_implied_g(base_fcff: float, wacc: float,
                          market_ev: float) -> Optional[float]:
    """Master §4.D single-stage frame: g_implied = WACC − FCFF0/EV."""
    if market_ev <= 0 or base_fcff <= 0:
        return None
    return wacc - base_fcff / market_ev


# ------------------------------------------------------------- orchestration

def _latest(seq) -> Optional[float]:
    for v in reversed(seq or []):
        if v is not None:
            return v
    return None


def _require(value: Optional[float], what: str) -> float:
    if value is None:
        raise ValuationError(f"{what} is required for this method.")
    return value


def _case_warnings(g_term: Optional[float]) -> List[str]:
    if g_term is not None and g_term > GDP_CAP:
        return [f"terminal g {fmt_pct(g_term)} exceeds the 3.5% GDP cap (master §4.A)"]
    return []


def build_valuation(d: DashboardData, inputs: ValuationInputs) -> ValuationResult:
    if inputs.method not in METHODS:
        raise ValuationError(f"Unknown method '{inputs.method}'.")
    if d.last_close is None or d.last_close <= 0:
        raise ValuationError(
            "No usable current price (price sources failed or returned a "
            "non-positive value) — the margin of safety needs P0 (house §8).")
    price = d.last_close
    price_date = d.price_dates[-1] if d.price_dates else None
    shares = _latest(d.diluted_shares)
    if inputs.method in ("dcf", "ri") and (shares is None or shares <= 0):
        raise ValuationError("Diluted share count missing or non-positive in XBRL.")

    debt, cash = _latest(d.total_debt), _latest(d.cash)
    net_debt = None
    if debt is not None or cash is not None:
        net_debt = (debt or 0.0) - (cash or 0.0)

    warnings: List[str] = []
    if price_date is not None and (d.generated - price_date).days > PRICE_STALENESS_DAYS:
        warnings.append(
            f"P0 is {(d.generated - price_date).days} days old — exceeds the "
            "5-trading-day staleness cap for any MoS (house §8)")
    if (debt is None) ^ (cash is None):  # exactly one leg present
        warnings.append(
            f"net debt is one-sided ({'cash' if debt is None else 'debt'} tag "
            "missing) — the missing leg is treated as 0, which biases the "
            "equity bridge; verify against the filing")
    # Fundamentals staleness: _latest() can reach back past a missing latest FY.
    if d.diluted_shares and d.diluted_shares[-1] is None and shares is not None:
        warnings.append("latest-FY diluted share count missing — using the most "
                        "recent reported year, which lags the current price")

    result = ValuationResult(
        method=inputs.method, method_label=METHODS[inputs.method],
        basis_label="", discount_rate=inputs.discount_rate,
        base_value=inputs.base_value, price=price, price_date=price_date,
        net_debt=net_debt, shares=shares or 0.0, cases=[], warnings=warnings,
    )

    if inputs.method == "dcf":
        rate = _require(inputs.discount_rate, "WACC")
        base = inputs.base_value
        levered_proxy = False
        if base is None:
            base = _latest(d.fcff)  # FCF + after-tax interest (master §4.0)
            if base is not None and inputs.ex_sbc:
                sbc = _latest(d.sbc)
                if sbc is not None:
                    base -= sbc
            # if no interest tag was found, fcff fell back to levered FCF
            levered_proxy = (d.interest_expense and d.interest_expense[-1] is None
                             and _latest(d.interest_expense) is None)
        if base is None or base <= 0:
            raise ValuationError(
                "Base FCFF must be positive — normalize a trough/negative base "
                "yourself and enter it (master §4.0: never annualize a quarter, "
                "normalize capex through-cycle).")
        result.base_value = base
        tax_note = (f", after-tax interest at τ={fmt_pct(d.effective_tax_rate)}"
                    if d.effective_tax_rate is not None and not levered_proxy else "")
        result.basis_label = (
            f"FCFF = FCF + after-tax interest{'' if not inputs.ex_sbc else ', ex-SBC'} "
            f"(master §4.0{tax_note}; {'Track B' if inputs.ex_sbc else 'Track A'})")
        if levered_proxy:
            warnings.append("no interest-expense tag in XBRL — base is levered FCF, "
                            "not true FCFF; FV is conservative for a leveraged firm")
        if net_debt is None:
            warnings.append("net debt unavailable — equity bridge assumes 0 (check XBRL tags)")
        market_ev = price * shares + (net_debt or 0.0)
        result.implied_g = reverse_dcf_implied_g(base, rate, market_ev)
        if result.implied_g is not None and result.implied_g > GDP_CAP:
            warnings.append(
                f"reverse-DCF implied g {fmt_pct(result.implied_g)} exceeds the "
                "3.5% cap — the market is paying for optionality; name it "
                "before acting on a sub-price FV (master §4.D)")
        for name in CASE_NAMES:
            c = inputs.cases[name]
            g0, g_term = _require(c.g0, f"{name} g0"), _require(c.g_term, f"{name} terminal g")
            out = dcf_fcff(base, rate, g0, g_term)
            equity = out["ev"] - (net_debt or 0.0)
            fv = equity / shares
            cw = _case_warnings(g_term)
            if out["tv_share"] and out["tv_share"] > HIGH_TV_SHARE:
                cw.append(f"TV is {fmt_pct(out['tv_share'])} of EV — terminal-value "
                          "dominated; check the base before trusting FV (master §4.A)")
            result.cases.append(CaseResult(
                name=name,
                assumptions=f"g₀ {fmt_pct(g0)} → g {fmt_pct(g_term)}",
                fv_ps=fv, mos=(fv - price) / price, ev=out["ev"], equity=equity,
                tv_share=out["tv_share"], warnings=cw))

    elif inputs.method == "ri":
        rate = _require(inputs.discount_rate, "r_e")
        bv0 = inputs.base_value if inputs.base_value is not None else _latest(d.book_equity)
        if bv0 is None or bv0 <= 0:
            raise ValuationError(
                "BV0 (latest reported equity) missing or non-positive — enter it "
                "directly (master §4.B: BV0 = latest reported equity).")
        result.base_value = bv0
        result.basis_label = "BV0 = latest reported stockholders' equity"
        for name in CASE_NAMES:
            c = inputs.cases[name]
            roe = _require(c.roe, f"{name} ROE")
            g0, g_term = _require(c.g0, f"{name} book growth g0"), _require(c.g_term, f"{name} terminal g")
            out = residual_income(bv0, rate, roe, g0, g_term)
            fv = out["value"] / shares
            cw = _case_warnings(g_term)
            if roe > rate + 0.15:
                cw.append("thin-book high-ROE grower — RI structurally under-prices "
                          "it; add a forward P/E or P/S cross-check (master §4.B)")
            result.cases.append(CaseResult(
                name=name,
                assumptions=f"ROE {fmt_pct(roe)}, g₀ {fmt_pct(g0)} → g {fmt_pct(g_term)}",
                fv_ps=fv, mos=(fv - price) / price, equity=out["value"],
                tv_share=out["tv_share"], warnings=cw))

    elif inputs.method == "affo":
        result.basis_label = "FV/sh = AFFO per share ÷ target AFFO yield (master §4.C)"
        for name in CASE_NAMES:
            c = inputs.cases[name]
            affo = _require(c.affo_ps, f"{name} AFFO per share")
            y = _require(c.target_yield, f"{name} target AFFO yield")
            if affo <= 0:
                raise ValuationError(f"{name}: AFFO per share must be positive.")
            if y <= 0:
                raise ValuationError(f"{name}: target AFFO yield must be positive.")
            fv = affo / y
            result.cases.append(CaseResult(
                name=name,
                assumptions=f"AFFO/sh ${affo:,.2f} @ {fmt_pct(y)} yield",
                fv_ps=fv, mos=(fv - price) / price))
        result.warnings.append(
            "AFFO is analyst-supplied — the FFO→AFFO bridge and maintenance "
            "capex are not in companyfacts XBRL (master §3.2 REIT track)")

    else:  # manual / SOTP
        result.basis_label = "analyst-supplied FV per share (SOTP / external model)"
        for name in CASE_NAMES:
            fv = _require(inputs.cases[name].fv_ps, f"{name} FV per share")
            result.cases.append(CaseResult(
                name=name, assumptions=f"FV/sh ${fv:,.2f} (input)",
                fv_ps=fv, mos=(fv - price) / price))
        result.warnings.append(
            "SOTP segment economics are not in companyfacts XBRL — values are "
            "carried from the analyst's model, only the MoS is computed here")

    order = {n: i for i, n in enumerate(CASE_NAMES)}
    result.cases.sort(key=lambda c: order[c.name])
    bear, bull = result.cases[0].fv_ps, result.cases[-1].fv_ps
    if bear is not None and bull is not None and bear > bull:
        result.warnings.append("Bear FV exceeds Bull FV — check the case inputs")
    return result

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

from . import config
from .anchors import CAPEX_DEVIATION, capex_intensity
from .metrics import DashboardData, fmt_money, fmt_pct

HORIZON = 10
GDP_CAP = config.GDP_CAP  # house-overridable (FIX-7); tests import this name
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
    implied_g_basis: str = ""
    # FIX-16c entry-price discipline (Base case, production dcf_fcff only)
    implied_return_now: Optional[float] = None   # buying at P₀
    irr_ladder: List = field(default_factory=list)  # [(price, return|None)]
    hurdle_price: Optional[float] = None         # price that buys HURDLE_RATE
    hurdle_rate: Optional[float] = None
    market_ev: Optional[float] = None
    bridge: Optional[float] = None               # net debt + MI + pref − non-op
    rate_build: str = ""                         # §4.0 build audit string
    warnings: List[str] = field(default_factory=list)
    _inputs: Optional[ValuationInputs] = field(default=None, repr=False)


def suggest_method(track: str) -> str:
    """Valuation method for a resolved Logic Track (master Phase 1 table)."""
    return {"bank": "ri", "insurance": "ri", "reit": "affo",
            "sotp": "manual"}.get(track, "dcf")


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


# FIX-16c: entry-price discipline (owner-ratified benchmark insight) —
# what annual return does buying at a given price earn under the Base-case
# fade, and what price buys the hurdle. Deliberately NO new math: both
# directions run through the production `dcf_fcff`.
HURDLE_RATE = 0.15        # ASSUMPTION: house entry hurdle, labeled on-page
LADDER_STEPS = 9
LADDER_SPREAD = 0.40      # ladder spans ±40% around P₀ (DVH-style strip)
_IRR_MAX = 0.60           # implied returns beyond 60% render as n/a


def implied_return(price_ps: Optional[float], base: Optional[float],
                   g0: float, g_term: float, bridge: float,
                   shares: Optional[float]) -> Optional[float]:
    """The discount rate r solving (dcf_fcff EV − bridge)/shares = price —
    the Base-case implied annual return of buying at `price_ps`. FV is
    strictly decreasing in r, so a bisection over [g_term+ε, 60%] is
    exact; None outside that bracket or on unusable inputs."""
    if not price_ps or price_ps <= 0 or not base or base <= 0 \
            or not shares or shares <= 0:
        return None
    lo, hi = g_term + 1e-4, _IRR_MAX

    def fv(r: float) -> float:
        return (dcf_fcff(base, r, g0, g_term)["ev"] - bridge) / shares

    try:
        if fv(hi) >= price_ps or fv(lo) <= price_ps:
            return None  # cheaper than the 60% cap / dearer than ~g_term
        for _ in range(80):
            mid = (lo + hi) / 2
            if fv(mid) > price_ps:
                lo = mid
            else:
                hi = mid
    except ValuationError:
        return None
    return (lo + hi) / 2


def price_for_return(hurdle: float, base: Optional[float], g0: float,
                     g_term: float, bridge: float,
                     shares: Optional[float]) -> Optional[float]:
    """The entry price that earns `hurdle`: FV per share discounted at the
    hurdle itself (closed-form — no search needed)."""
    if not base or base <= 0 or not shares or shares <= 0 \
            or hurdle is None or hurdle <= g_term:
        return None
    try:
        fv = (dcf_fcff(base, hurdle, g0, g_term)["ev"] - bridge) / shares
    except ValuationError:
        return None
    return fv if fv > 0 else None


def price_irr_ladder(price: Optional[float], base: Optional[float],
                     g0: float, g_term: float, bridge: float,
                     shares: Optional[float], steps: int = LADDER_STEPS,
                     spread: float = LADDER_SPREAD):
    """[(price point, implied annual return)] at ±spread around `price`."""
    if not price or price <= 0 or steps < 2:
        return []
    return [(p, implied_return(p, base, g0, g_term, bridge, shares))
            for k in range(steps)
            for p in (price * (1 - spread + 2 * spread * k / (steps - 1)),)]


# ------------------------------------------------------------- orchestration

def _latest(seq) -> Optional[float]:
    for v in reversed(seq or []):
        if v is not None:
            return v
    return None


def effective_sbc(d) -> Optional[float]:
    """Analyst override wins; else latest tagged SBC; None when neither.

    The single SBC read for the ex-SBC base and the FIX-2 reverse-DCF
    basis (Track B), so valuation and verdict cannot diverge (FIX-11d).
    """
    return d.sbc_override if d.sbc_override is not None else _latest(d.sbc)


def sbc_series_warning(d) -> Optional[str]:
    """Warn when the tagged SBC series dies before the latest fiscal year
    and no analyst override is set — Track B then rides a stale (or
    missing) SBC figure without saying so."""
    if getattr(d, "sbc_override", None) is not None or not d.sbc \
            or d.sbc[-1] is not None:
        return None
    idx = [i for i, v in enumerate(d.sbc) if v is not None]
    if not idx:
        return None  # never tagged at all: ex-SBC == as-reported by design
    last = (d.fy_labels[idx[-1]] if d.fy_labels
            and idx[-1] < len(d.fy_labels) else "an earlier year")
    return (f"SBC series ends {last} under all candidate tags — Track B "
            "currently rides that stale figure; if compensation is "
            "cash-settled (LTRP-style) label the decision, otherwise set "
            "the SBC override from the comp note")


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

    # Auto discount rate from the §4.0 build when the analyst didn't override.
    discount = inputs.discount_rate
    rate_build = ""
    build = getattr(d, "wacc_build", None)
    if discount is None and build is not None and inputs.method in ("dcf", "ri"):
        discount = build.wacc if inputs.method == "dcf" else build.r_e
        if discount is not None:
            rate_build = build.summary()

    result = ValuationResult(
        method=inputs.method, method_label=METHODS[inputs.method],
        basis_label="", discount_rate=discount,
        base_value=inputs.base_value, price=price, price_date=price_date,
        net_debt=net_debt, shares=shares or 0.0, cases=[], warnings=warnings,
        rate_build=rate_build,
    )

    if inputs.method == "dcf":
        rate = result.discount_rate
        if rate is None:
            raise ValuationError(
                "WACC unavailable — the automated build needs a live 10-Y UST "
                "and market cap; enter the rate manually (master §4.0).")
        base = inputs.base_value
        levered_proxy = False
        if base is None:
            base = _latest(d.fcff)  # FCF + after-tax interest (master §4.0)
            if base is not None and inputs.ex_sbc:
                sbc = effective_sbc(d)
                if sbc is not None:
                    base -= sbc
            # the base's leveredness is a property of the LATEST year only:
            # metrics adds after-tax interest per-year, so a stale early-year
            # interest tag does not un-lever fcff[-1]
            levered_proxy = (not d.interest_expense
                             or d.interest_expense[-1] is None)
            # FIX-14b house-§2 capex-peak rule, AUTO base only — an explicit
            # base is already the analyst's normalization decision
            ci = capex_intensity(d)
            if ci is not None and ci[0] > 0 \
                    and abs(ci[1] / ci[0] - 1.0) > CAPEX_DEVIATION:
                warnings.append(
                    f"latest capex/revenue {ci[1]:.1%} vs 5y median "
                    f"{ci[0]:.1%} — capex peak/trough year; base "
                    "normalization required per house §2 (prefill available)")
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
        # Full equity bridge, mirroring FCFF_DCF!B31 / Control!B57:
        # EV − net debt − minority interest − preferred + non-op investments
        mi = _latest(d.minority_interest) or 0.0
        pref = _latest(d.preferred_equity) or 0.0
        nonop = d.non_op_investments or 0.0
        bridge = (net_debt or 0.0) + mi + pref - nonop
        result.bridge = bridge
        if mi or pref:
            warnings.append(f"equity bridge includes MI {fmt_money(mi)} / "
                            f"preferred {fmt_money(pref)} (Phase1_Anchor B17/B18)")
        if d.non_op_investments is None:
            warnings.append("non-operating investments not entered — bridge "
                            "assumes 0 (Phase1_Anchor!B19, analyst input)")
        market_ev = price * shares + bridge
        result.market_ev = market_ev
        # Reverse-DCF basis is Track B ex-SBC, mirroring Control!B58 (which
        # divides FCFF_DCF!C5 — the ex-SBC base — by the full market EV)
        sbc_warn = sbc_series_warning(d)
        if sbc_warn:
            warnings.append(sbc_warn)
        sbc_latest = effective_sbc(d) or 0.0
        base_b = base if inputs.ex_sbc else base - sbc_latest
        if base_b > 0:
            result.implied_g = reverse_dcf_implied_g(base_b, rate, market_ev)
            result.implied_g_basis = ("Track B ex-SBC base / market EV incl. "
                                      "MI+pref−non-op (Control!B58)")
        else:
            result.implied_g = None
            warnings.append("ex-SBC base non-positive — reverse-DCF frame "
                            "(Control!B58 basis) unavailable; normalize per "
                            "house §2b")
        if result.implied_g is not None and result.implied_g > GDP_CAP:
            warnings.append(
                f"reverse-DCF implied g {fmt_pct(result.implied_g)} exceeds the "
                "3.5% cap — the market is paying for optionality; name it "
                "before acting on a sub-price FV (master §4.D)")
        # FIX-16c entry-price discipline: Base-case implied annual return
        # at P₀, the ±40% price ladder, and the price that buys the
        # HURDLE_RATE — every leg through the production dcf_fcff
        bc = inputs.cases.get("Base")
        if price and bc is not None and bc.g0 is not None \
                and bc.g_term is not None:
            result.implied_return_now = implied_return(
                price, base, bc.g0, bc.g_term, bridge, shares)
            result.irr_ladder = price_irr_ladder(
                price, base, bc.g0, bc.g_term, bridge, shares)
            result.hurdle_price = price_for_return(
                HURDLE_RATE, base, bc.g0, bc.g_term, bridge, shares)
            result.hurdle_rate = HURDLE_RATE
        for name in CASE_NAMES:
            c = inputs.cases[name]
            g0, g_term = _require(c.g0, f"{name} g0"), _require(c.g_term, f"{name} terminal g")
            out = dcf_fcff(base, rate, g0, g_term)
            equity = out["ev"] - bridge
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
        rate = result.discount_rate
        if rate is None:
            raise ValuationError(
                "r_e unavailable — the automated build needs a live 10-Y UST; "
                "enter the rate manually (master §4.0).")
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
    result._inputs = inputs  # carried for Phase 5 and the workbook exporter
    return result

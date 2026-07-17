"""Market-joined per-fiscal-year ratio series (FIX-16a).

The benchmark insight (owner-ratified): fundamentals joined to the market
series *per year* — market cap, EV, P/E, EV/EBIT, adj-FCF yield as
columns — is the value investor's one-glance table. Every input was
already fetched (FY-end closes drive Altman MVE); this module only joins
them. The honest-gap rule applies throughout: a ratio with a missing or
non-positive denominator is None, never a fabricated number.

Definitions (labeled, house-consistent):

- market cap     = FY-end close × diluted shares (the same MVE read as
                   Altman Z);
- EV             = market cap + total debt − cash + minority interest +
                   preferred (the equity-bridge legs, Phase1_Anchor);
- adj FCF        = FCF ex-SBC (house §2b: SBC is a real cost);
- owner's yield  = (dividends paid + gross buybacks) / current market
                   cap — issuance is NOT netted (the dilution panel shows
                   it), and every rendering of the number says so;
- tangible book  = equity − goodwill − intangibles (a missing goodwill or
                   intangibles leg counts as 0; missing equity → None).
"""
from __future__ import annotations

from typing import List, Optional

from .anchors import _at, _series
from .metrics import DashboardData, attach_fy_prices


def _pos(v: Optional[float]) -> Optional[float]:
    return v if v is not None and v > 0 else None


def compute_market_ratios(d: DashboardData) -> None:
    """Fill the per-FY market-joined series on `d` (displayed window;
    years outside the price history stay None)."""
    n = len(d.fy_ends)
    if not d.fy_prices:
        attach_fy_prices(d)
    goodwill = _series(d, "goodwill")
    intang = _series(d, "intangibles")

    d.market_cap_fy = [None] * n
    d.ev_fy = [None] * n
    d.pe_fy = [None] * n
    d.ev_ebit_fy = [None] * n
    d.net_debt_fy = [None] * n
    d.net_debt_ebit_fy = [None] * n
    d.adj_fcf_yield_fy = [None] * n
    d.tangible_book = [None] * n

    for i in range(n):
        px = d.fy_prices[i] if i < len(d.fy_prices) else None
        shares = d.diluted_shares[i] if i < len(d.diluted_shares) else None
        mcap = px * shares if px and shares else None
        d.market_cap_fy[i] = mcap

        debt = d.total_debt[i] if i < len(d.total_debt) else None
        cash = d.cash[i] if i < len(d.cash) else None
        nd = debt - cash if debt is not None and cash is not None else None
        d.net_debt_fy[i] = nd
        mi = (d.minority_interest[i] or 0.0) if i < len(d.minority_interest) else 0.0
        pref = (d.preferred_equity[i] or 0.0) if i < len(d.preferred_equity) else 0.0
        ev = (mcap + nd + mi + pref
              if mcap is not None and nd is not None else None)
        d.ev_fy[i] = ev

        eps = d.eps_diluted[i] if i < len(d.eps_diluted) else None
        d.pe_fy[i] = px / eps if px and _pos(eps) else None

        ebit = d.ebit_reported[i] if i < len(d.ebit_reported) else None
        d.ev_ebit_fy[i] = ev / ebit if ev is not None and _pos(ebit) else None
        d.net_debt_ebit_fy[i] = (nd / ebit
                                 if nd is not None and _pos(ebit) else None)

        afcf = d.fcf_ex_sbc[i] if i < len(d.fcf_ex_sbc) else None
        d.adj_fcf_yield_fy[i] = (afcf / mcap
                                 if afcf is not None and _pos(mcap) else None)

        # negative-index into the untrimmed source arrays so the display
        # trim can never misalign the tangible-book legs
        eq = d.book_equity[i] if i < len(d.book_equity) else None
        gw = _at(goodwill, i - n)
        ia = _at(intang, i - n)
        d.tangible_book[i] = (eq - (gw or 0.0) - (ia or 0.0)
                              if eq is not None else None)

    # current-market scalars (KPIs) — need a live close and share count
    shares_now = next((v for v in reversed(d.diluted_shares) if v), None)
    mcap_now = (d.last_close * shares_now
                if d.last_close and shares_now else None)
    afcf_now = next((v for v in reversed(d.fcf_ex_sbc) if v is not None),
                    None)
    d.adj_fcf_yield_now = (afcf_now / mcap_now
                           if afcf_now is not None and _pos(mcap_now)
                           else None)
    divs = next((v for v in reversed(d.dividends_paid) if v is not None),
                None)
    bb = next((v for v in reversed(_series(d, "buybacks") or [])
               if v is not None), None)
    if mcap_now and (divs is not None or bb is not None):
        d.owners_yield = ((divs or 0.0) + (bb or 0.0)) / mcap_now
    else:
        d.owners_yield = None


def summary_stat(values: List[Optional[float]],
                 kind: str) -> Optional[float]:
    """The per-row summary the export's CAGR/avg column prints (FIX-16b):
    kind "cagr" = geometric CAGR first→last positive value (needs ≥ 3
    points and positive endpoints, matching the anchor-ladder rule);
    kind "avg" = arithmetic mean of the non-None values (≥ 3)."""
    have = [(i, v) for i, v in enumerate(values) if v is not None]
    if len(have) < 3:
        return None
    if kind == "avg":
        return sum(v for _, v in have) / len(have)
    (i0, first), (i1, last) = have[0], have[-1]
    span = i1 - i0
    if first <= 0 or last <= 0 or span <= 0:
        return None
    return (last / first) ** (1.0 / span) - 1.0

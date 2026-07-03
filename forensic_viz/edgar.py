"""SEC EDGAR XBRL client: ticker -> CIK -> annual fundamentals.

Tag selection is coverage- and recency-scored rather than first-match: for each
concept the candidate us-gaap tag that covers the most recent fiscal years wins.
Companies migrate tags over time (e.g. ``Revenues`` ->
``RevenueFromContractWithCustomerExcludingAssessedTax`` after ASC 606), and a
first-match rule silently returns a series that stops years ago.

Only US-GAAP filers (10-K, and 20-F filers reporting under us-gaap) are
supported; pure IFRS taxonomies are rejected with a clear error.
"""
from __future__ import annotations

import datetime as dt
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import requests

from . import config
from .cache import Cache

TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"

ANNUAL_FORMS = ("10-K", "20-F", "40-F")

# Duration (flow) concepts: candidate tags in preference order.
DURATION_TAGS: Dict[str, List[str]] = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueGoodsNet",
        "SalesRevenueServicesNet",
        "RegulatedAndUnregulatedOperatingRevenue",
    ],
    "cost_of_revenue": [
        "CostOfRevenue",
        "CostOfGoodsAndServicesSold",
        "CostOfGoodsSold",
        "CostOfServices",
    ],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": [
        "NetIncomeLoss",
        "ProfitLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
    ],
    "cfo": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
        "PaymentsForCapitalImprovements",
    ],
    "diluted_shares": [
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "WeightedAverageNumberOfSharesOutstandingBasic",
    ],
    # Phase-3 health-check inputs
    "cfi": [
        "NetCashProvidedByUsedInInvestingActivities",
        "NetCashProvidedByUsedInInvestingActivitiesContinuingOperations",
    ],
    "sbc": [
        "ShareBasedCompensation",
        "AllocatedShareBasedCompensationExpense",
    ],
    "rnd": [
        "ResearchAndDevelopmentExpense",
        "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
    ],
    # Phase-4 FCFF bridge inputs (master §4.0: FCFF = FCF + after-tax interest)
    "interest_expense": [
        "InterestExpense",
        "InterestExpenseDebt",
        "InterestAndDebtExpense",
        "InterestExpenseNonoperating",
    ],
    "tax_expense": ["IncomeTaxExpenseBenefit"],
    "pretax_income": [
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ],
}

# Instant (balance-sheet) concepts.
INSTANT_TAGS: Dict[str, List[str]] = {
    "total_assets": ["Assets"],
    "cash": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ],
    "lt_debt_noncurrent": [
        "LongTermDebtNoncurrent",
        "LongTermDebtAndCapitalLeaseObligations",
    ],
    "lt_debt_current": [
        "LongTermDebtCurrent",
        "LongTermDebtAndCapitalLeaseObligationsCurrent",
    ],
    "st_borrowings": ["ShortTermBorrowings", "CommercialPaper"],
    "lt_debt_total": ["LongTermDebt"],
    # Phase-3 health-check inputs
    "assets_current": ["AssetsCurrent"],
    "liabilities_current": ["LiabilitiesCurrent"],
    "liabilities_total": ["Liabilities"],
    "retained_earnings": ["RetainedEarningsAccumulatedDeficit"],
    # Phase-4 valuation inputs
    "equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
}

_UNITS_BY_CONCEPT = {"diluted_shares": ("shares",)}
_DEFAULT_UNITS = ("USD",)


class EdgarError(RuntimeError):
    """User-facing EDGAR failure (unknown ticker, unsupported filer, ...)."""


@dataclass
class AnnualFundamentals:
    """As-filed annual series, keyed by fiscal-year end date (ascending)."""

    cik: int
    entity_name: str
    fy_ends: List[dt.date]
    series: Dict[str, List[Optional[float]]]
    tags_used: Dict[str, str] = field(default_factory=dict)
    sic_description: str = ""
    sic_code: str = ""
    exchange_ticker: str = ""

    def value(self, concept: str, i: int) -> Optional[float]:
        s = self.series.get(concept)
        return s[i] if s is not None and 0 <= i < len(s) else None


class _SecSession:
    """requests.Session with the mandatory User-Agent, pacing and retries."""

    def __init__(self, cache: Cache):
        self.cache = cache
        self.session = requests.Session()
        self.session.headers["User-Agent"] = config.SEC_USER_AGENT
        self.session.headers["Accept-Encoding"] = "gzip, deflate"
        self._lock = threading.Lock()
        self._last_call = 0.0

    def get_json(self, url: str, ttl: float) -> dict:
        cached = self.cache.get(url, ttl)
        if cached is not None:
            return cached
        last_err: Optional[Exception] = None
        for attempt in range(config.HTTP_RETRIES):
            with self._lock:
                wait = config.SEC_MIN_INTERVAL - (time.time() - self._last_call)
                if wait > 0:
                    time.sleep(wait)
                self._last_call = time.time()
            try:
                resp = self.session.get(url, timeout=config.HTTP_TIMEOUT)
                if resp.status_code == 404:
                    raise EdgarError(f"SEC returned 404 for {url}")
                if resp.status_code in (403, 429) or resp.status_code >= 500:
                    raise requests.HTTPError(f"HTTP {resp.status_code}", response=resp)
                resp.raise_for_status()
                data = resp.json()
                self.cache.put(url, data)
                return data
            except EdgarError:
                raise
            except (requests.RequestException, ValueError) as exc:
                last_err = exc
                time.sleep(2**attempt)
        raise EdgarError(f"SEC request failed after retries: {url} ({last_err})")


def _norm_ticker(ticker: str) -> str:
    return re.sub(r"[^A-Z0-9.\-]", "", ticker.strip().upper())


def lookup_cik(ticker: str, sec: _SecSession) -> Tuple[int, str]:
    """Resolve a ticker to (CIK, registered company title)."""
    t = _norm_ticker(ticker)
    if not t:
        raise EdgarError("Empty ticker.")
    data = sec.get_json(TICKER_MAP_URL, config.TTL_TICKER_MAP)
    # File maps index -> {cik_str, ticker, title}. Dots/dashes vary (BRK-B vs BRK.B).
    variants = {t, t.replace(".", "-"), t.replace("-", ".")}
    for row in data.values():
        if str(row.get("ticker", "")).upper() in variants:
            return int(row["cik_str"]), str(row.get("title", ""))
    raise EdgarError(
        f"Ticker '{t}' not found in the SEC company list. "
        "Only US SEC filers are supported."
    )


def _parse_date(s: str) -> Optional[dt.date]:
    try:
        return dt.date.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def _annual_duration_obs(tag_units: dict, units: Tuple[str, ...]) -> Dict[dt.date, float]:
    """FY-end -> value for one tag, annual (10-K family) durations only."""
    out: Dict[dt.date, Tuple[str, float]] = {}  # end -> (filed, val)
    for unit in units:
        for item in tag_units.get(unit, []):
            form = str(item.get("form", ""))
            if not form.startswith(ANNUAL_FORMS):
                continue
            start = _parse_date(item.get("start", ""))
            end = _parse_date(item.get("end", ""))
            val = item.get("val")
            if start is None or end is None or not isinstance(val, (int, float)):
                continue
            if not 330 <= (end - start).days <= 400:  # full-year durations only
                continue
            filed = str(item.get("filed", ""))
            prev = out.get(end)
            if prev is None or filed >= prev[0]:
                out[end] = (filed, float(val))
    return {end: v for end, (_, v) in out.items()}


def _annual_instant_obs(tag_units: dict, units: Tuple[str, ...]) -> Dict[dt.date, float]:
    """Instant values reported in annual filings, keyed by balance-sheet date."""
    out: Dict[dt.date, Tuple[str, float]] = {}
    for unit in units:
        for item in tag_units.get(unit, []):
            form = str(item.get("form", ""))
            if not form.startswith(ANNUAL_FORMS):
                continue
            end = _parse_date(item.get("end", ""))
            val = item.get("val")
            if end is None or not isinstance(val, (int, float)):
                continue
            filed = str(item.get("filed", ""))
            prev = out.get(end)
            if prev is None or filed >= prev[0]:
                out[end] = (filed, float(val))
    return {end: v for end, (_, v) in out.items()}


def _score_tag(obs: Dict[dt.date, float], window_ends: List[dt.date]) -> float:
    """Coverage of the target fiscal years, weighted toward recent years."""
    if not obs:
        return 0.0
    if not window_ends:  # no spine yet: prefer the most recent, best-covered tag
        return max(obs).toordinal() + len(obs) / 100.0
    score = 0.0
    n = len(window_ends)
    for rank, end in enumerate(sorted(window_ends)):  # oldest first
        if end in obs:
            score += 1.0 + rank / max(n, 1)  # recent years weigh more
    return score


def _union_window(
    gaap: dict, candidates: List[str], units: Tuple[str, ...], years: int
) -> List[dt.date]:
    """Last `years` fiscal-year ends across all candidate tags combined."""
    ends: set = set()
    for tag in candidates:
        tag_units = gaap.get(tag, {}).get("units")
        if tag_units:
            ends.update(_annual_duration_obs(tag_units, units).keys())
    return sorted(ends)[-years:]


def _select_series(
    gaap: dict,
    candidates: List[str],
    window_ends: List[dt.date],
    units: Tuple[str, ...],
    extractor,
    prefer_larger_on_tie: bool = False,
) -> Tuple[Optional[str], Dict[dt.date, float]]:
    """Best candidate tag by fiscal-year coverage.

    Coverage ties break by list priority — except for revenue
    (prefer_larger_on_tie), where the larger series wins: filers with material
    non-ASC-606 revenue (lessors, banks, autos) tag both the income-statement
    total (``Revenues``) and the 606-scope subtotal with identical coverage,
    and picking the subtotal would silently understate the whole series.
    """
    best_key, best_tag, best_obs = None, None, {}
    for priority, tag in enumerate(candidates):
        tag_units = gaap.get(tag, {}).get("units")
        if not tag_units:
            continue
        obs = extractor(tag_units, units)
        if not obs:
            continue
        score = _score_tag(obs, window_ends)
        if prefer_larger_on_tie:
            covered = [abs(obs[e]) for e in window_ends if e in obs]
            tie = sum(covered) / len(covered) if covered else 0.0
        else:
            tie = float(-priority)
        key = (score, tie)
        if best_key is None or key > best_key:
            best_key, best_tag, best_obs = key, tag, obs
    return best_tag, best_obs


def _match_instant(obs: Dict[dt.date, float], fy_end: dt.date) -> Optional[float]:
    """Balance-sheet date == FY end, with a few days' tolerance."""
    if fy_end in obs:
        return obs[fy_end]
    for d, v in obs.items():
        if abs((d - fy_end).days) <= 7:
            return v
    return None


def parse_companyfacts(
    facts: dict,
    ticker: str,
    cik: int = 0,
    fallback_title: str = "",
    years: int = config.FETCH_YEARS,
) -> AnnualFundamentals:
    """Reduce a companyfacts payload to the last `years` fiscal years (pure)."""
    gaap = facts.get("facts", {}).get("us-gaap")
    if not gaap:
        available = ", ".join(sorted(facts.get("facts", {}).keys())) or "none"
        raise EdgarError(
            f"{ticker.upper()}: no us-gaap facts (taxonomies: {available}). "
            "IFRS-only filers are not supported in this version."
        )
    entity = str(facts.get("entityName") or fallback_title or ticker.upper())

    # Establish the fiscal-year spine as the union of recent year-ends across
    # all revenue candidates (falling back to net income — some financials
    # report no revenue-family tag). Using the union, not one tag's own years,
    # means the first year after a tag migration is never silently dropped.
    window = _union_window(gaap, DURATION_TAGS["revenue"], _DEFAULT_UNITS, years)
    if not window:
        window = _union_window(gaap, DURATION_TAGS["net_income"], _DEFAULT_UNITS, years)
    if not window:
        raise EdgarError(
            f"{ticker.upper()}: no annual revenue or net-income series found in XBRL."
        )
    fy_ends = window

    series: Dict[str, List[Optional[float]]] = {}
    tags_used: Dict[str, str] = {}

    def _fill_gaps(values, candidates, primary_tag, units, extractor, matcher):
        """Fill years the primary tag misses from lower-ranked candidates.

        A 10-year window usually spans a tag migration (e.g. ASC 606), so the
        best tag rarely covers every year. Filled years are recorded in the
        tags_used audit string — mixed-tag series are visible, never silent.
        """
        fills: Dict[str, List[int]] = {}
        for tag in candidates:
            if tag == primary_tag or all(v is not None for v in values):
                continue
            tag_units = gaap.get(tag, {}).get("units")
            if not tag_units:
                continue
            obs = extractor(tag_units, units)
            for i, end in enumerate(fy_ends):
                if values[i] is None:
                    v = matcher(obs, end)
                    if v is not None:
                        values[i] = v
                        fills.setdefault(tag, []).append(end.year)
        if not fills:
            return primary_tag
        notes = "; ".join(
            f"FY{min(yrs)}–FY{max(yrs)} from {t}" if len(yrs) > 1 else f"FY{yrs[0]} from {t}"
            for t, yrs in fills.items()
        )
        return f"{primary_tag} ({notes})"

    for concept, candidates in DURATION_TAGS.items():
        units = _UNITS_BY_CONCEPT.get(concept, _DEFAULT_UNITS)
        tag, obs = _select_series(
            gaap, candidates, fy_ends, units, _annual_duration_obs,
            prefer_larger_on_tie=(concept == "revenue"),
        )
        values = [obs.get(end) for end in fy_ends]
        if tag:
            tags_used[concept] = _fill_gaps(
                values, candidates, tag, units, _annual_duration_obs,
                lambda o, end: o.get(end))
        series[concept] = values

    for concept, candidates in INSTANT_TAGS.items():
        units = _UNITS_BY_CONCEPT.get(concept, _DEFAULT_UNITS)
        tag, obs = _select_series(gaap, candidates, fy_ends, units, _annual_instant_obs)
        values = [_match_instant(obs, end) for end in fy_ends]
        if tag:
            tags_used[concept] = _fill_gaps(
                values, candidates, tag, units, _annual_instant_obs, _match_instant)
        series[concept] = values

    return AnnualFundamentals(
        cik=cik, entity_name=entity, fy_ends=fy_ends, series=series, tags_used=tags_used
    )


def fetch_fundamentals(
    ticker: str, cache: Optional[Cache] = None, years: int = config.FETCH_YEARS
) -> AnnualFundamentals:
    """Pull companyfacts from EDGAR and reduce to the last `years` fiscal years."""
    cache = cache or Cache()
    sec = _SecSession(cache)
    cik, title = lookup_cik(ticker, sec)

    facts = sec.get_json(COMPANYFACTS_URL.format(cik=cik), config.TTL_COMPANYFACTS)
    result = parse_companyfacts(facts, ticker, cik=cik, fallback_title=title, years=years)

    try:  # header metadata is nice-to-have; never fail the run for it
        subs = sec.get_json(SUBMISSIONS_URL.format(cik=cik), config.TTL_SUBMISSIONS)
        result.sic_description = str(subs.get("sicDescription") or "")
        result.sic_code = str(subs.get("sic") or "")
        tickers = subs.get("tickers") or []
        exchanges = subs.get("exchanges") or []
        if tickers:
            exch = f" ({exchanges[0]})" if exchanges and exchanges[0] else ""
            result.exchange_ticker = f"{tickers[0]}{exch}"
    except Exception:
        pass
    return result

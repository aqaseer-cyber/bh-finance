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
import xml.etree.ElementTree as ET
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
    # capitalized-cost SBC elements (…CapitalizedAmount) are excluded by
    # design — capitalized ≠ expensed (MELI: the only covered ShareBased
    # concept is a capitalized amount; using it would misstate the expense)
    "sbc": [
        "ShareBasedCompensation",
        "AllocatedShareBasedCompensationExpense",
    ],
    "rnd": [
        "ResearchAndDevelopmentExpense",
        "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
        # software filers (e.g. ADBE) use the software-specific variant;
        # some (e.g. PYPL) present the line as "Technology and development"
        "ResearchAndDevelopmentExpenseSoftwareExcludingAcquiredInProcessCost",
        "TechnologyAndDevelopmentExpense",
    ],
    # Phase-4 FCFF bridge inputs (master §4.0: FCFF = FCF + after-tax
    # interest). FinanceLeaseInterestExpense is a component — excluded to
    # avoid double-count when filers tag both it and a total.
    "interest_expense": [
        "InterestExpense",
        "InterestExpenseDebt",
        "InterestAndDebtExpense",
        "InterestExpenseNonoperating",
        "InterestExpenseAndOtherFinancialCharges",  # MELI FY2019+ rotation
    ],
    "tax_expense": ["IncomeTaxExpenseBenefit"],
    "pretax_income": [
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ],
    # Banks capitalization audit (master §3.2): reserve-release detection
    "credit_provision": [
        "ProvisionForLoanLeaseAndOtherLosses",
        "ProvisionForLoanAndLeaseLosses",
        "ProvisionForCreditLossExpenseReversal",
        "ProvisionForDoubtfulAccounts",
    ],
    # Phase-2 unit economics (track-specific marginal unit, master §2.2)
    "net_interest_income": ["InterestIncomeExpenseNet"],
    "policy_benefits": ["PolicyholderBenefitsAndClaimsIncurredNet"],
    "premiums_earned": ["PremiumsEarnedNet"],
    "underwriting_expense": ["OtherUnderwritingExpense"],
    # Workbook ties & bridge legs (Control/Phase1 tabs)
    "eps_diluted": ["EarningsPerShareDiluted"],
    "dna": [
        "DepreciationDepletionAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
        "DepreciationAndAmortization",
    ],
    "basic_shares": ["WeightedAverageNumberOfSharesOutstandingBasic"],
    "dividends_paid": [
        "PaymentsOfDividendsCommonStock",
        "PaymentsOfDividends",
        "PaymentsOfDividendsCommonStockAndPreferredStock",
    ],
    # Financial-model export (three-statement sheet) extras.
    # Opex is three separate concepts because filers tag either the combined
    # SG&A line or the split lines — never both consistently; a combined
    # bucket mislabels bare G&A as "SG&A" (seen on PYPL/ADBE).
    "sga": ["SellingGeneralAndAdministrativeExpense"],
    "marketing": [
        "SellingAndMarketingExpense",
        "MarketingExpense",
        "AdvertisingExpense",
    ],
    "ga": ["GeneralAndAdministrativeExpense"],
    "opex_total": ["OperatingExpenses", "CostsAndExpenses"],
    "cff": [
        "NetCashProvidedByUsedInFinancingActivities",
        "NetCashProvidedByUsedInFinancingActivitiesContinuingOperations",
    ],
    "buybacks": ["PaymentsForRepurchaseOfCommonStock"],
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
    # Banks/insurance solvency (master §3.3): regulatory capital ratios
    "cet1_ratio": ["CommonEquityTierOneCapitalToRiskWeightedAssets"],
    "tier1_ratio": ["TierOneRiskBasedCapitalToRiskWeightedAssets"],
    "leverage_ratio": ["TierOneLeverageCapitalToAverageAssets"],
    "credit_allowance": [
        "FinancingReceivableAllowanceForCreditLosses",
        "FinancingReceivableAllowanceForCreditLossExcludingAccruedInterest",
        "AllowanceForLoanAndLeaseLosses",
    ],
    # Phase-2 working-capital cycle (master §2.2 Standard track)
    "inventory": ["InventoryNet", "InventoryFinishedGoodsNetOfReserves"],
    "accounts_receivable": [
        "AccountsReceivableNetCurrent",
        "ReceivablesNetCurrent",
    ],
    "accounts_payable": ["AccountsPayableCurrent", "AccountsPayableTradeCurrent"],
    # Equity-bridge legs (master §4.A / workbook Phase1_Anchor)
    "minority_interest": ["MinorityInterest", "RedeemableNoncontrollingInterestEquityCarryingAmount"],
    "preferred_equity": ["PreferredStockValue", "PreferredStockValueOutstanding"],
    # Financial-model export (three-statement sheet) extras
    "ppe_net": ["PropertyPlantAndEquipmentNet"],
    "goodwill": ["Goodwill"],
}

_UNITS_BY_CONCEPT = {
    "diluted_shares": ("shares",),
    "basic_shares": ("shares",),
    "eps_diluted": ("USD/shares",),
    "cet1_ratio": ("pure",),
    "tier1_ratio": ("pure",),
    "leverage_ratio": ("pure",),
}
_DEFAULT_UNITS = ("USD",)


class EdgarError(RuntimeError):
    """User-facing EDGAR failure (unknown ticker, unsupported filer, ...)."""


@dataclass
class AnnualFiling:
    """One 10-K-family filing row from the submissions index."""

    form: str            # "10-K" or "10-K/A"
    filed: dt.date
    report_date: dt.date  # fiscal period the filing covers
    accession: str
    document: str        # primaryDocument


def _collect_annual_filings(recent: dict) -> List[AnnualFiling]:
    """Every 10-K / 10-K/A row in the submissions 'recent' arrays (pure).

    Rows with unparseable dates are dropped — a filing we cannot place on
    the fiscal timeline cannot participate in per-year selection.
    """
    out: List[AnnualFiling] = []
    for form, filed, report, accn, doc in zip(
            recent.get("form", []), recent.get("filingDate", []),
            recent.get("reportDate", []), recent.get("accessionNumber", []),
            recent.get("primaryDocument", [])):
        if form not in ("10-K", "10-K/A"):
            continue
        filed_d, report_d = _parse_date(str(filed)), _parse_date(str(report))
        if filed_d is None or report_d is None:
            continue
        out.append(AnnualFiling(form=str(form), filed=filed_d,
                                report_date=report_d, accession=str(accn),
                                document=str(doc)))
    return out


def select_annual_filings(filings: List[AnnualFiling],
                          years: int) -> List[AnnualFiling]:
    """One filing per fiscal year, newest `years` years, oldest first.

    Group by report_date (±14 days folds duplicate periods); within a
    group prefer the 10-K/A with the latest filed date, else the 10-K
    with the latest filed date (house rule: latest amendment wins).
    """
    groups: List[List[AnnualFiling]] = []
    for f in sorted(filings, key=lambda f: f.report_date):
        if groups and abs((f.report_date
                           - groups[-1][0].report_date).days) <= 14:
            groups[-1].append(f)
        else:
            groups.append([f])
    chosen: List[AnnualFiling] = []
    for group in groups:
        amendments = [f for f in group if f.form == "10-K/A"]
        pool = amendments or group
        chosen.append(max(pool, key=lambda f: f.filed))
    return chosen[-years:]


def sibling_annual_filing(filings: List[AnnualFiling],
                          preferred: AnnualFiling) -> Optional[AnnualFiling]:
    """The same fiscal year's plain 10-K, for a 10-K/A that ships without
    XBRL (amendments sometimes carry none)."""
    pool = [f for f in filings if f.form == "10-K"
            and f.accession != preferred.accession
            and abs((f.report_date - preferred.report_date).days) <= 14]
    return max(pool, key=lambda f: f.filed) if pool else None


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
    latest_10k_date: str = ""
    latest_10q_date: str = ""
    # accession + primary document of the latest 10-K/10-Q, so the segment
    # reader can locate each filing's extracted XBRL instance (…_htm.xml)
    latest_10k_accession: str = ""
    latest_10k_document: str = ""
    latest_10q_accession: str = ""
    latest_10q_document: str = ""
    # FIX-11a: per-year tag provenance (concept -> fy_end -> tag that
    # supplied that year) and human-readable selection decisions
    year_sources: Dict[str, Dict[dt.date, str]] = field(default_factory=dict)
    selection_notes: List[str] = field(default_factory=list)
    # every 10-K / 10-K/A row from the submissions index (FIX-10a) — the
    # segment-history fetch selects one per fiscal year from these
    annual_filings: List["AnnualFiling"] = field(default_factory=list)
    # full companyfacts payload, kept so the financial-model export can pull
    # interim (10-Q) observations without a second fetch
    raw_facts: Optional[dict] = field(default=None, repr=False)

    def value(self, concept: str, i: int) -> Optional[float]:
        s = self.series.get(concept)
        return s[i] if s is not None and 0 <= i < len(s) else None


@dataclass
class QuarterlyFundamentals:
    """As-filed interim observations for the financial-model export.

    ``duration[concept]`` holds every filed duration up to ~400 days under
    the concept's winning tag as ``(start, end, value)`` — 10-Qs file both
    discrete ~3-month spans and fiscal-YTD spans (plus prior-year
    comparatives), and cash-flow statements are YTD-only; the
    discrete-quarter and LTM arithmetic lives in ``model_export``.
    ``instant[concept]`` maps every balance-sheet date to its latest-filed
    value across all forms.
    """

    duration: Dict[str, List[Tuple[dt.date, dt.date, float]]] = field(
        default_factory=dict)
    instant: Dict[str, Dict[dt.date, float]] = field(default_factory=dict)
    # FIX-11c: per-span gap-fill provenance — which non-primary tags
    # supplied interim spans (audit trail for the export footnotes)
    source_notes: List[str] = field(default_factory=list)


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
        saw_403 = False
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
                if resp.status_code == 403:
                    saw_403 = True  # SEC blocks anonymous/placeholder UAs
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
        raise EdgarError(
            f"SEC request failed after retries: {url} ({last_err})"
            + (" — SEC returned 403: set SEC_EDGAR_USER_AGENT to "
               "'name email' and retry" if saw_403 else ""))

    def get_text(self, url: str, ttl: float) -> str:
        """Cached raw-text GET (XBRL instance documents), same pacing."""
        cached = self.cache.get(url, ttl)
        if cached is not None:
            return cached
        last_err: Optional[Exception] = None
        saw_403 = False
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
                if resp.status_code == 403:
                    saw_403 = True  # SEC blocks anonymous/placeholder UAs
                if resp.status_code in (403, 429) or resp.status_code >= 500:
                    raise requests.HTTPError(f"HTTP {resp.status_code}", response=resp)
                resp.raise_for_status()
                self.cache.put(url, resp.text)
                return resp.text
            except EdgarError:
                raise
            except requests.RequestException as exc:
                last_err = exc
                time.sleep(2**attempt)
        raise EdgarError(
            f"SEC request failed after retries: {url} ({last_err})"
            + (" — SEC returned 403: set SEC_EDGAR_USER_AGENT to "
               "'name email' and retry" if saw_403 else ""))


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


def _duration_obs_all(
    tag_units: dict, units: Tuple[str, ...]
) -> Dict[Tuple[dt.date, dt.date], float]:
    """(start, end) -> value for every filed duration up to ~400 days.

    No form filter: 10-Qs carry the interim spans (discrete quarters, fiscal
    YTD, prior-year comparatives) and 10-Ks the full years; the consolidator
    picks spans by their dates. Latest filed wins per exact span.
    """
    out: Dict[Tuple[dt.date, dt.date], Tuple[str, float]] = {}
    for unit in units:
        for item in tag_units.get(unit, []):
            start = _parse_date(item.get("start", ""))
            end = _parse_date(item.get("end", ""))
            val = item.get("val")
            if start is None or end is None or not isinstance(val, (int, float)):
                continue
            if not 20 <= (end - start).days <= 400:
                continue
            filed = str(item.get("filed", ""))
            prev = out.get((start, end))
            if prev is None or filed >= prev[0]:
                out[(start, end)] = (filed, float(val))
    return {k: v for k, (_, v) in out.items()}


def _instant_obs_all(tag_units: dict, units: Tuple[str, ...]) -> Dict[dt.date, float]:
    """Instant values across all forms (10-Q quarter ends included)."""
    out: Dict[dt.date, Tuple[str, float]] = {}
    for unit in units:
        for item in tag_units.get(unit, []):
            end = _parse_date(item.get("end", ""))
            val = item.get("val")
            if end is None or not isinstance(val, (int, float)):
                continue
            filed = str(item.get("filed", ""))
            prev = out.get(end)
            if prev is None or filed >= prev[0]:
                out[end] = (filed, float(val))
    return {end: v for end, (_, v) in out.items()}


def parse_quarterly_facts(
    facts: dict, annual: AnnualFundamentals
) -> QuarterlyFundamentals:
    """Collect interim observations under each concept's winning annual tag.

    The annual parse already chose the tag that carries the recent fiscal
    years; recent quarters live under the same tag, so quarterly extraction
    reuses that choice (falling through the candidate list only when the
    winner has no interim data at all). Pure — no network.
    """
    gaap = (facts or {}).get("facts", {}).get("us-gaap") or {}
    q = QuarterlyFundamentals()

    def ordered(concept: str, candidates: List[str]) -> List[str]:
        primary = (annual.tags_used.get(concept) or "").split(" (")[0]
        pri = [primary] if primary else []
        if concept == "revenue":
            # FIX-11c: follow the FIX-11a basis decision — tags that
            # supplied annual years via coherence rank first (most-recent
            # year first), so quarter cells sit on the basis the annual
            # row shows
            ys = getattr(annual, "year_sources", {}).get("revenue", {})
            recent_first: List[str] = []
            for fe in sorted(ys, reverse=True):
                if ys[fe] not in recent_first:
                    recent_first.append(ys[fe])
            pri = recent_first + [t for t in pri if t not in recent_first]
        return pri + [t for t in candidates if t not in pri]

    # FIX-11c: per-span union with priority — the old first-tag-with-data
    # rule let a winner's stale interim history block fall-through, leaving
    # whole quarter columns blank while a sibling tag carried them (MELI
    # capex: annual under …PropertyPlantAndEquipment, 10-Q under
    # …ProductiveAssets). Lowest priority wins per span.
    for concept, candidates in DURATION_TAGS.items():
        units = _UNITS_BY_CONCEPT.get(concept, _DEFAULT_UNITS)
        merged: Dict[Tuple[dt.date, dt.date], Tuple[int, str, float]] = {}
        for prio, tag in enumerate(ordered(concept, candidates)):
            tag_units = gaap.get(tag, {}).get("units")
            if not tag_units:
                continue
            for span, val in _duration_obs_all(tag_units, units).items():
                cur = merged.get(span)
                if cur is None or prio < cur[0]:
                    merged[span] = (prio, tag, val)
        if merged:
            q.duration[concept] = [(s, e, v) for (s, e), (_p, _t, v)
                                   in sorted(merged.items())]
            fill_tags = sorted({t for p, t, _ in merged.values() if p > 0})
            if fill_tags:
                q.source_notes.append(
                    f"{concept}: interim spans also from {fill_tags}")
    for concept, candidates in INSTANT_TAGS.items():
        units = _UNITS_BY_CONCEPT.get(concept, _DEFAULT_UNITS)
        merged_i: Dict[dt.date, Tuple[int, str, float]] = {}
        for prio, tag in enumerate(ordered(concept, candidates)):
            tag_units = gaap.get(tag, {}).get("units")
            if not tag_units:
                continue
            for end, val in _instant_obs_all(tag_units, units).items():
                cur = merged_i.get(end)
                if cur is None or prio < cur[0]:
                    merged_i[end] = (prio, tag, val)
        if merged_i:
            q.instant[concept] = {end: v for end, (_p, _t, v)
                                  in sorted(merged_i.items())}
            fill_tags = sorted({t for p, t, _ in merged_i.values() if p > 0})
            if fill_tags:
                q.source_notes.append(
                    f"{concept}: period-end balances also from {fill_tags}")
    return q


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

    result = AnnualFundamentals(
        cik=cik, entity_name=entity, fy_ends=fy_ends, series=series,
        tags_used=tags_used, raw_facts=facts,
    )
    _apply_revenue_coherence(result, gaap)
    return result


def _year_span(fy_ends: List[dt.date]) -> str:
    years = sorted(fe.year for fe in fy_ends)
    return (f"FY{years[0]}–FY{years[-1]}" if len(years) > 1
            else f"FY{years[0]}")


def _apply_revenue_coherence(annual: AnnualFundamentals, gaap: dict) -> None:
    """Per fiscal year, prefer the revenue tag satisfying
    revenue ≈ gross_profit + cost_of_revenue (IS_TIE_TOL).

    The income statement supplies its own referee: filers like MELI tag
    BOTH a headline total (``Revenues``) and a contract-only subtotal
    undimensioned, and coverage+recency scoring can pick the subtotal
    while COGS and GrossProfit sit on the headline basis — every
    revenue-denominated ratio then computes on the wrong basis.

    Runs only for years where BOTH the gross-profit and cost-of-revenue
    winners have values. Substitutions are recorded in tags_used
    (gap-fill note format), year_sources["revenue"], and
    selection_notes. Years where no candidate is coherent keep the
    winner and add a warning note — never fabricate.
    """
    n = len(annual.fy_ends)
    gp = annual.series.get("gross_profit") or [None] * n
    cogs = annual.series.get("cost_of_revenue") or [None] * n
    rev = annual.series.get("revenue")
    if rev is None:
        return
    tol = config.IS_TIE_TOL
    obs_by_tag: Dict[str, Dict[dt.date, float]] = {}
    for tag in DURATION_TAGS["revenue"]:
        tag_units = gaap.get(tag, {}).get("units")
        if tag_units:
            obs = _annual_duration_obs(tag_units, _DEFAULT_UNITS)
            if obs:
                obs_by_tag[tag] = obs

    def ok(v: Optional[float], target: float) -> bool:
        return v is not None and v > 0 and abs(v - target) <= tol * target

    subs: Dict[str, List[dt.date]] = {}
    unresolved: List[dt.date] = []
    pass_chosen: List[str] = []  # series stability: reuse this pass's tags
    for i, fe in enumerate(annual.fy_ends):
        if gp[i] is None or cogs[i] is None:
            continue  # identity not checkable this year
        target = gp[i] + cogs[i]
        if target <= 0:
            continue
        if ok(rev[i], target):
            continue  # the winner already satisfies the identity
        order = ([t for t in pass_chosen if t in obs_by_tag]
                 + [t for t in DURATION_TAGS["revenue"]
                    if t not in pass_chosen])
        new_tag = next((t for t in order
                        if ok(obs_by_tag.get(t, {}).get(fe), target)), None)
        if new_tag is None:
            unresolved.append(fe)
            continue
        rev[i] = obs_by_tag[new_tag][fe]
        annual.year_sources.setdefault("revenue", {})[fe] = new_tag
        subs.setdefault(new_tag, []).append(fe)
        if new_tag not in pass_chosen:
            pass_chosen.append(new_tag)

    if subs:
        suffix = "; ".join(f"{_year_span(fes)} from {t} — basis coherence"
                           for t, fes in subs.items())
        cur = annual.tags_used.get("revenue", "")
        if cur.endswith(")"):
            annual.tags_used["revenue"] = cur[:-1] + f"; {suffix})"
        else:
            annual.tags_used["revenue"] = f"{cur} ({suffix})" if cur else suffix
        for t, fes in subs.items():
            annual.selection_notes.append(
                f"Revenue basis: winner failed Rev ≈ GP + COGS in "
                f"{_year_span(fes)}; substituted {t}")
    for fe in unresolved:
        annual.selection_notes.append(
            f"Revenue basis UNRESOLVED in FY{fe.year}: no candidate within "
            f"±{tol:.0%} of GP + COGS — margins for that year are suspect")


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
        recent = subs.get("filings", {}).get("recent", {})
        # one full walk: latest 10-K/10-Q markers AND the whole 10-K-family
        # history (FIX-10a) — the arrays are already in memory, cost is nil
        for form, filed, accn, doc in zip(
                recent.get("form", []), recent.get("filingDate", []),
                recent.get("accessionNumber", []),
                recent.get("primaryDocument", [])):
            if form == "10-K" and not result.latest_10k_date:
                result.latest_10k_date = str(filed)
                result.latest_10k_accession = str(accn)
                result.latest_10k_document = str(doc)
            elif form == "10-Q" and not result.latest_10q_date:
                result.latest_10q_date = str(filed)
                result.latest_10q_accession = str(accn)
                result.latest_10q_document = str(doc)
        result.annual_filings = _collect_annual_filings(recent)
    except Exception:
        pass
    return result


def _require_declared_ua() -> None:
    """www.sec.gov/Archives returns 403 for the placeholder UA (verified);
    data.sec.gov currently tolerates it — so fundamentals stay usable and
    only Archives-dependent features are gated, with an actionable error."""
    if config.UA_IS_PLACEHOLDER:
        raise EdgarError(
            "SEC Archives blocks the placeholder User-Agent (HTTP 403). "
            "Set SEC_EDGAR_USER_AGENT to 'name email' and retry.")


def instance_url(cik: int, accession: str, primary_document: str) -> str:
    """URL of a filing's extracted XBRL instance (…_htm.xml on EDGAR)."""
    accn = accession.replace("-", "")
    stem = primary_document.rsplit(".", 1)[0]
    return (f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn}/"
            f"{stem}_htm.xml")


def _discover_instance_url(sec: _SecSession, cik: int,
                           accession: str) -> Optional[str]:
    """Locate the extracted instance via the filing's index.json when the
    conventional …_htm.xml name misses (older packagers vary)."""
    accn = accession.replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn}"
    try:
        idx = sec.get_json(f"{base}/index.json", config.TTL_COMPANYFACTS)
    except Exception:
        return None
    names = [str(item.get("name", ""))
             for item in idx.get("directory", {}).get("item", [])]
    cands = [n for n in names if n.endswith("_htm.xml")]
    if not cands:  # classic (non-inline) filings ship a plain .xml instance
        skip = ("filingsummary", "metalinks", "_cal", "_def", "_lab",
                "_pre", ".xsd")
        cands = [n for n in names if n.lower().endswith(".xml")
                 and not n.lower().startswith("r")
                 and not any(s in n.lower() for s in skip)]
    return f"{base}/{cands[0]}" if cands else None


def fetch_segment_instances(annual: AnnualFundamentals,
                            cache: Optional[Cache] = None) -> List[str]:
    """XBRL instance XML of the latest 10-K and 10-Q (best-effort each)."""
    _require_declared_ua()  # FIX-13a: Archives 403s the placeholder UA
    cache = cache or Cache()
    sec = _SecSession(cache)
    out: List[str] = []
    for accn, doc in ((annual.latest_10k_accession, annual.latest_10k_document),
                      (annual.latest_10q_accession, annual.latest_10q_document)):
        if not accn or not doc or not annual.cik:
            continue
        try:
            out.append(sec.get_text(instance_url(annual.cik, accn, doc),
                                    config.TTL_COMPANYFACTS))
            continue
        except Exception:
            pass  # fall through to index.json discovery
        try:
            url = _discover_instance_url(sec, annual.cik, accn)
            if url:
                out.append(sec.get_text(url, config.TTL_COMPANYFACTS))
        except Exception:
            continue  # segment data is an enrichment, never a hard failure
    return out


# --------------------------------- as-filed statement structure (FIX-13d)

_XLINK = "{http://www.w3.org/1999/xlink}"
_STD_LABEL_ROLE = "http://www.xbrl.org/2003/role/label"
# The three primary statements in a FilingSummary's report list; the $
# anchors exclude 'Parenthetical' and comprehensive-income variants.
_STATEMENT_SHORTNAME_RX = re.compile(
    r"CONSOLIDATED (BALANCE SHEETS?$"
    r"|STATEMENTS? OF (INCOME|OPERATIONS)$"
    r"|STATEMENTS? OF CASH FLOWS?$)", re.IGNORECASE)


@dataclass
class PresRow:
    """One line of a statement's presentation tree, in as-filed order."""

    concept: str          # local name
    label: str            # as-filed label (lab linkbase), fallback humanized
    depth: int            # presentation tree depth (indent)
    is_total: bool        # preferredLabel endswith 'totalLabel'
    is_abstract: bool     # concept local name endswith 'Abstract'


def _local(tag: str) -> str:
    """Local name of an ElementTree '{ns}tag'."""
    return tag.rsplit("}", 1)[-1]


def _href_local(href: str) -> str:
    """'…schema.xsd#us-gaap_Revenues' -> 'Revenues' (namespace dropped)."""
    frag = (href or "").rsplit("#", 1)[-1]
    return frag.split("_", 1)[-1] if "_" in frag else frag


def _humanize_concept(local: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])",
                  " ", local).strip() or local


def parse_filing_summary(xml_text: str) -> Dict[str, Tuple[str, str]]:
    """{'income'/'balance'/'cashflow': (Role URI, ShortName)} for the three
    consolidated primary statements; 'Parenthetical' reports excluded."""
    root = ET.fromstring(xml_text)
    out: Dict[str, Tuple[str, str]] = {}
    for report in root.iter("Report"):
        short = (report.findtext("ShortName") or "").strip()
        role = (report.findtext("Role") or "").strip()
        if not short or not role or "parenthetical" in short.lower():
            continue
        if not _STATEMENT_SHORTNAME_RX.search(short):
            continue
        upper = short.upper()
        if "BALANCE" in upper:
            key = "balance"
        elif "CASH FLOW" in upper:
            key = "cashflow"
        else:
            key = "income"
        out.setdefault(key, (role, short))  # first matching report wins
    return out


def parse_presentation(xml_text: str, role: str
                       ) -> List[Tuple[str, int, str]]:
    """[(concept local name, depth, preferredLabel role)] for one
    presentationLink role, children ordered by the arc 'order' attribute.
    Axis/table scaffolding (Table/Axis/Domain/Member/LineItems) is skipped
    with its children promoted, matching how EDGAR renders R-files."""
    root = ET.fromstring(xml_text)
    out: List[Tuple[str, int, str]] = []
    skip_suffix = ("Table", "Axis", "Domain", "Member", "LineItems")
    for link in root.iter():
        if _local(link.tag) != "presentationLink" \
                or link.get(_XLINK + "role", "") != role:
            continue
        concept_of: Dict[str, str] = {}
        loc_order: List[str] = []
        children: Dict[str, List[Tuple[float, str, str]]] = {}
        tos = set()
        for el in link:
            ln = _local(el.tag)
            if ln == "loc":
                lb = el.get(_XLINK + "label", "")
                concept_of[lb] = _href_local(el.get(_XLINK + "href", ""))
                loc_order.append(lb)
            elif ln == "presentationArc":
                frm = el.get(_XLINK + "from", "")
                to = el.get(_XLINK + "to", "")
                try:
                    order = float(el.get("order", "1") or "1")
                except ValueError:
                    order = 1.0
                children.setdefault(frm, []).append(
                    (order, to, el.get("preferredLabel", "") or ""))
                tos.add(to)

        def walk(lb: str, depth: int, pref: str) -> None:
            concept = concept_of.get(lb, "")
            skipped = concept.endswith(skip_suffix)
            if concept and not skipped:
                out.append((concept, depth, pref))
            next_depth = depth if skipped else depth + 1
            for _, to, p in sorted(children.get(lb, []),
                                   key=lambda t: t[0]):
                walk(to, next_depth, p)

        for lb in loc_order:  # roots in document order
            if lb not in tos:
                walk(lb, 0, "")
    return out


def parse_labels(xml_text: str) -> Dict[Tuple[str, str], str]:
    """(concept local name, label role) -> text, from a label linkbase."""
    if not xml_text:
        return {}
    root = ET.fromstring(xml_text)
    out: Dict[Tuple[str, str], str] = {}
    for link in root.iter():
        if _local(link.tag) != "labelLink":
            continue
        concept_of: Dict[str, str] = {}
        texts: Dict[str, List[Tuple[str, str]]] = {}
        arcs: List[Tuple[str, str]] = []
        for el in link:
            ln = _local(el.tag)
            if ln == "loc":
                concept_of[el.get(_XLINK + "label", "")] = \
                    _href_local(el.get(_XLINK + "href", ""))
            elif ln == "labelArc":
                arcs.append((el.get(_XLINK + "from", ""),
                             el.get(_XLINK + "to", "")))
            elif ln == "label":
                texts.setdefault(el.get(_XLINK + "label", ""), []).append(
                    (el.get(_XLINK + "role", ""), (el.text or "").strip()))
        for frm, to in arcs:
            concept = concept_of.get(frm, "")
            for lrole, text in texts.get(to, []):
                if concept and text:
                    out[(concept, lrole)] = text
    return out


def build_statement_rows(pre_xml: str, lab_xml: str,
                         roles: Dict[str, Tuple[str, str]]
                         ) -> Dict[str, List[PresRow]]:
    """Pure assembly: presentation order + as-filed labels -> PresRow lists
    keyed 'income'/'balance'/'cashflow' (only roles that yielded rows)."""
    labels = parse_labels(lab_xml)
    out: Dict[str, List[PresRow]] = {}
    for key, (role, _short) in roles.items():
        rows = []
        for concept, depth, pref in parse_presentation(pre_xml, role):
            label = (labels.get((concept, pref)) if pref else None) \
                or labels.get((concept, _STD_LABEL_ROLE)) \
                or _humanize_concept(concept)
            rows.append(PresRow(
                concept=concept, label=label, depth=depth,
                is_total=pref.endswith("totalLabel"),
                is_abstract=concept.endswith("Abstract")))
        if rows:
            out[key] = rows
    return out


def annual_values_for_concept(raw_facts: dict, concept: str,
                              fy_ends: List[dt.date]
                              ) -> Tuple[List[Optional[float]], str]:
    """Annual values for one presentation concept across ``fy_ends``, from
    the companyfacts payload (latest amendment wins) — the statement sheets'
    value source. Scans every namespace for the local name (extension
    concepts included); unit preference USD > USD/shares > shares > pure.
    Duration tags use full-year observations, instant tags match the
    balance-sheet dates. Returns (values, unit key or '')."""
    blank: List[Optional[float]] = [None] * len(fy_ends)
    facts = (raw_facts or {}).get("facts") or {}
    tag = None
    for ns in sorted(facts, key=lambda n: (n != "us-gaap", n)):
        if concept in facts[ns]:
            tag = facts[ns][concept]
            break
    if tag is None:
        return blank, ""
    units = tag.get("units") or {}
    unit = next((u for u in ("USD", "USD/shares", "shares", "pure")
                 if u in units), next(iter(units), ""))
    if not unit:
        return blank, ""
    obs = _annual_duration_obs(units, (unit,))
    if obs:
        return [obs.get(e) for e in fy_ends], unit
    iobs = _annual_instant_obs(units, (unit,))
    if iobs:
        return [_match_instant(iobs, e) for e in fy_ends], unit
    return blank, unit


def _fetch_linkbase(sec: "_SecSession", base: str, stem: str,
                    suffix: str, ttl: float) -> Optional[str]:
    """{base}/{stem}{suffix}, falling back to an index.json suffix scan
    (mirrors _discover_instance_url's discovery)."""
    if stem:
        try:
            return sec.get_text(f"{base}/{stem}{suffix}", ttl)
        except Exception:
            pass
    try:
        idx = sec.get_json(f"{base}/index.json", ttl)
        names = [str(item.get("name", ""))
                 for item in idx.get("directory", {}).get("item", [])]
        cands = [n for n in names if n.lower().endswith(suffix)]
        if cands:
            return sec.get_text(f"{base}/{cands[0]}", ttl)
    except Exception:
        pass
    return None


def fetch_statement_presentation(annual: AnnualFundamentals,
                                 cache: Optional[Cache] = None
                                 ) -> Tuple[Dict[str, list], List[str]]:
    """{'income'/'balance'/'cashflow': [PresRow, ...], '_short_names': {...}},
    notes — the latest 10-K's as-filed statement structure.

    Steps (all behind the FIX-13a UA gate, all cached at
    TTL_FILING_INSTANCE — filed artifacts are immutable — under the latest
    10-K's Archives folder): FilingSummary.xml locates the three statement
    Role URIs; {stem}_pre.xml gives line order/depth/preferredLabel;
    {stem}_lab.xml gives the as-filed labels. Failures after the UA gate
    return ({}, [reason]) — the caller degrades gracefully."""
    _require_declared_ua()
    if not (annual.cik and annual.latest_10k_accession):
        return {}, ["no 10-K accession on file — statement sheets need a "
                    "full Analyze first"]
    cache = cache or Cache()
    sec = _SecSession(cache)
    accn = annual.latest_10k_accession.replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/{annual.cik}/{accn}"
    ttl = config.TTL_FILING_INSTANCE
    try:
        summary = sec.get_text(f"{base}/FilingSummary.xml", ttl)
        roles = parse_filing_summary(summary)
    except Exception as exc:
        return {}, [f"FilingSummary.xml unusable: {exc}"]
    if not roles:
        return {}, ["no consolidated-statement reports found in "
                    "FilingSummary.xml"]
    stem = (annual.latest_10k_document or "").rsplit(".", 1)[0]
    pre = _fetch_linkbase(sec, base, stem, "_pre.xml", ttl)
    if pre is None:
        return {}, ["presentation linkbase (_pre.xml) not found in the "
                    "filing folder"]
    lab = _fetch_linkbase(sec, base, stem, "_lab.xml", ttl) or ""
    try:
        rows = build_statement_rows(pre, lab, roles)
    except ET.ParseError as exc:
        return {}, [f"linkbase unparseable: {exc}"]
    if not rows:
        return {}, ["the presentation roles matched no rows"]
    rows["_short_names"] = {k: sn for k, (_r, sn) in roles.items()
                            if k in rows}
    return rows, []

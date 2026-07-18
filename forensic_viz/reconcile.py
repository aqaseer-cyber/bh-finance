"""FIX-17c: the provider recheck — reconciliation + gap-rescue audit.

Doctrine (owner-ratified, docs/FIX17_SPEC.md): SEC EDGAR stays the single
displayed source of truth. This module never changes a displayed number;
it compares the EDGAR-derived series against two independent reads and
reports three outcomes per (item, fiscal year):

  match       within tolerance — counted, silent
  divergent   the sources disagree — flagged with both values
  restated    v3 R3a (a4): the sources disagree BUT EDGAR's own filings
              carry more than one distinct value for that span — the
              filer recast the number and the provider is serving the
              original. Listed separately from true divergences (the
              MELI FY2023 false alarm).
  rescuable   EDGAR left the cell empty but a provider has a value —
              surfaced with its source tag (series fill + recompute
              cascade is FIX-17c.2, deliberately not v1)

Legs: FMP statements (free-plan depth, the recent five FYs — where the
empty cells live) and Finnhub financials-as-reported (an independent
parse of the same filings, all years; values are as FIRST filed, so a
later restatement shows up as a flagged divergence — that is signal,
not noise). A provider value of exactly 0 is treated as absent: FMP
serves 0 for missing line items, and a fabricated "0 vs None" rescue
would be dishonest.

The audit NEVER blocks the pipeline: any provider failure lands in
AuditReport.error and the report renders what it has.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import config
from .edgar import (ANNUAL_FORMS, DURATION_TAGS, INSTANT_TAGS, _parse_date)

# tolerance: |a-b| <= max(REL * max(|a|,|b|), floor). The floor absorbs
# aggregator rounding (statements are frequently re-published in $mm).
REL_TOL = 0.02
_MONEY_FLOOR = 2e6

# (concept, statement, FMP field, compare-absolute, floor, label, unit)
# compare-absolute: FMP signs cash outflows negative (capex, dividends,
# buybacks) and occasionally flips convention between filers — for those
# items magnitude is the honest comparison.
FMP_ITEMS: List[Tuple[str, str, str, bool, float, str, str]] = [
    ("revenue", "income", "revenue", False, _MONEY_FLOOR,
     "Revenue", "money"),
    ("operating_income", "income", "operatingIncome", False, _MONEY_FLOOR,
     "Operating income", "money"),
    ("net_income", "income", "netIncome", False, _MONEY_FLOOR,
     "Net income", "money"),
    ("gross_profit", "income", "grossProfit", False, _MONEY_FLOOR,
     "Gross profit", "money"),
    ("diluted_shares", "income", "weightedAverageShsOutDil", False, 0.0,
     "Diluted shares", "shares"),
    ("cfo", "cashflow", "operatingCashFlow", False, _MONEY_FLOOR,
     "Operating cash flow", "money"),
    ("capex", "cashflow", "capitalExpenditure", True, _MONEY_FLOOR,
     "Capex", "money"),
    ("sbc", "cashflow", "stockBasedCompensation", True, _MONEY_FLOOR,
     "SBC", "money"),
    ("dividends_paid", "cashflow", "dividendsPaid", True, _MONEY_FLOOR,
     "Dividends paid", "money"),
    ("buybacks", "cashflow", "commonStockRepurchased", True, _MONEY_FLOOR,
     "Buybacks", "money"),
    ("equity", "balance", "totalStockholdersEquity", False, _MONEY_FLOOR,
     "Book equity", "money"),
    ("goodwill", "balance", "goodwill", True, _MONEY_FLOOR,
     "Goodwill", "money"),
]

# Finnhub as-reported: deep-history cross-check on the headline flows,
# matched by our own us-gaap tag priority lists (extension-tagged lines
# stay invisible here — same known limitation as companyfacts).
FNH_ITEMS: List[Tuple[str, str, str, str]] = [
    ("revenue", "ic", "Revenue", "money"),
    ("operating_income", "ic", "Operating income", "money"),
    ("net_income", "ic", "Net income", "money"),
    ("cfo", "cf", "Operating cash flow", "money"),
]

_MATCH_WINDOW_DAYS = 45   # provider period-end vs our fiscal-year end


@dataclass
class AuditEntry:
    item: str
    fy: str                       # e.g. "FY2024"
    ours: Optional[float]
    theirs: float
    source: str                   # "FMP" | "FNH"
    kind: str                     # "divergent" | "restated" | "rescuable"
    unit: str = "money"


@dataclass
class AuditReport:
    checked: int = 0
    matched: int = 0
    entries: List[AuditEntry] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)
    error: str = ""
    fetched_at: str = ""   # v3 R0: provenance timestamp (UTC ISO)

    @property
    def divergent(self) -> List[AuditEntry]:
        return [e for e in self.entries if e.kind == "divergent"]

    @property
    def restated(self) -> List[AuditEntry]:
        return [e for e in self.entries if e.kind == "restated"]

    @property
    def rescuable(self) -> List[AuditEntry]:
        return [e for e in self.entries if e.kind == "rescuable"]

    def summary(self) -> str:
        if self.error and not self.checked:
            return f"Data audit unavailable ({self.error})"
        src = " + ".join(self.sources) or "no providers"
        s = (f"Data audit: {self.checked} item-years vs {src} — "
             f"{self.matched} match, {len(self.divergent)} divergent, "
             f"{len(self.restated)} restated, "
             f"{len(self.rescuable)} rescuable (EDGAR empty)")
        if self.error:
            s += f" · partial: {self.error}"
        return s


def fmt_val(v: Optional[float], unit: str) -> str:
    if v is None:
        return "–"
    if unit == "shares":
        return f"{v / 1e6:,.1f}M sh"
    return f"${v / 1e6:,.0f}M"


def _tolerant_match(a: float, b: float, floor: float) -> bool:
    return abs(a - b) <= max(REL_TOL * max(abs(a), abs(b)), floor)


def _num(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f != 0.0 else None   # NaN and 0 -> absent


def _year_index(fy_ends: List[dt.date]):
    """Map a provider period-end date onto our fiscal-year index."""
    def find(end: Optional[dt.date]) -> Optional[int]:
        if end is None:
            return None
        for i, fe in enumerate(fy_ends):
            if abs((fe - end).days) <= _MATCH_WINDOW_DAYS:
                return i
        return None
    return find


def _date(raw) -> Optional[dt.date]:
    try:
        return dt.date.fromisoformat(str(raw)[:10])
    except (TypeError, ValueError):
        return None


def _concept_tags(f, concept: str) -> List[str]:
    """Candidate tags for the restatement scan, most specific first: the
    per-year substitution record, then the winning tag (first token of the
    tags_used audit string), then the concept's full priority list."""
    tags: List[str] = []
    for by_year in (getattr(f, "year_sources", None) or {}).get(
            concept, {}).values():
        if by_year and by_year not in tags:
            tags.append(by_year)
    used = (getattr(f, "tags_used", None) or {}).get(concept, "")
    first = str(used).split(";")[0].split("(")[0].strip()
    if first and first not in tags:
        tags.append(first)
    for t in DURATION_TAGS.get(concept) or INSTANT_TAGS.get(concept) or []:
        if t not in tags:
            tags.append(t)
    return tags


def _edgar_restated(f, concept: str, fy_end: dt.date,
                    floor: float) -> bool:
    """v3 R3a (a4): True when EDGAR's OWN filings carry more than one
    distinct value (beyond the audit tolerance) for this concept's annual
    span — the filer recast the number in a later filing, so a provider
    serving the original is 'restated', not 'divergent'.

    Scans the raw companyfacts payload for the concept's tag(s): annual
    forms only; duration concepts match full-year spans ending at the FY
    end, instant concepts match the balance-sheet date (±7 days). The
    first tag with ≥1 span observation decides — mixing tags would turn
    every tag migration into a fake restatement."""
    raw = getattr(f, "raw_facts", None) or {}
    facts = raw.get("facts") or {}
    is_duration = concept in DURATION_TAGS
    for tag in _concept_tags(f, concept):
        entry = None
        for ns in sorted(facts, key=lambda n: (n != "us-gaap", n)):
            if tag in facts[ns]:
                entry = facts[ns][tag]
                break
        if entry is None:
            continue
        vals: List[float] = []
        for unit_items in (entry.get("units") or {}).values():
            for item in unit_items or []:
                if not str(item.get("form", "")).startswith(ANNUAL_FORMS):
                    continue
                end = _parse_date(str(item.get("end", "")))
                val = item.get("val")
                if end is None or not isinstance(val, (int, float)):
                    continue
                if abs((end - fy_end).days) > 7:
                    continue
                if is_duration:
                    start = _parse_date(str(item.get("start", "")))
                    if start is None or not 330 <= (end - start).days <= 400:
                        continue
                vals.append(float(val))
        if vals:
            lo, hi = min(vals), max(vals)
            return not _tolerant_match(lo, hi, floor)
    return False


def _compare(report: AuditReport, item: str, fy: str,
             ours: Optional[float], theirs: Optional[float], source: str,
             absolute: bool, floor: float, unit: str,
             restated_check=None) -> None:
    if theirs is None:
        return
    if ours is None:
        report.entries.append(AuditEntry(item, fy, None, theirs, source,
                                         "rescuable", unit))
        return
    a, b = (abs(ours), abs(theirs)) if absolute else (ours, theirs)
    report.checked += 1
    if _tolerant_match(a, b, floor):
        report.matched += 1
    else:
        # a4: only a genuine mismatch pays for the restatement scan
        kind = ("restated" if restated_check is not None
                and restated_check() else "divergent")
        report.entries.append(AuditEntry(item, fy, ours, theirs, source,
                                         kind, unit))


# ------------------------------------------------------------------ FMP

def reconcile_fmp(d, statements: Dict[str, list],
                  report: AuditReport) -> None:
    """statements: {"income"|"cashflow"|"balance": [FMP rows]}."""
    f = getattr(d, "fundamentals", None)
    if f is None or not f.fy_ends:
        return
    find = _year_index(f.fy_ends)
    by_stmt_year: Dict[str, Dict[int, dict]] = {}
    for stmt, rows in statements.items():
        idx: Dict[int, dict] = {}
        for row in rows or []:
            i = find(_date(row.get("date")))
            if i is not None:
                idx[i] = row
        by_stmt_year[stmt] = idx
    for concept, stmt, fmp_field, absolute, floor, label, unit in FMP_ITEMS:
        series = f.series.get(concept)
        for i, row in by_stmt_year.get(stmt, {}).items():
            ours = series[i] if series and i < len(series) else None
            theirs = _num(row.get(fmp_field))
            fy = f"FY{f.fy_ends[i].year}"
            _compare(report, label, fy, ours, theirs, "FMP",
                     absolute, floor, unit,
                     restated_check=lambda c=concept, e=f.fy_ends[i],
                     fl=floor: _edgar_restated(f, c, e, fl))


# -------------------------------------------------------------- Finnhub

def _fnh_lookup(section: list, tags: List[str]) -> Optional[float]:
    """First matching us-gaap concept by OUR tag priority order."""
    by_local = {}
    for entry in section or []:
        concept = str(entry.get("concept") or "")
        if concept.startswith("us-gaap_"):
            local = concept[len("us-gaap_"):]
        elif concept.startswith("us-gaap:"):
            local = concept[len("us-gaap:"):]
        else:
            continue
        if local not in by_local:
            by_local[local] = entry.get("value")
    for tag in tags:
        if tag in by_local:
            v = _num(by_local[tag])
            if v is not None:
                return v
    return None


def reconcile_finnhub(d, payload: dict, report: AuditReport) -> None:
    f = getattr(d, "fundamentals", None)
    if f is None or not f.fy_ends:
        return
    find = _year_index(f.fy_ends)
    for filing in (payload or {}).get("data", []) or []:
        i = find(_date(filing.get("endDate")))
        if i is None:
            continue
        rep = filing.get("report") or {}
        fy = f"FY{f.fy_ends[i].year}"
        for concept, section, label, unit in FNH_ITEMS:
            series = f.series.get(concept)
            ours = series[i] if series and i < len(series) else None
            theirs = _fnh_lookup(rep.get(section), DURATION_TAGS[concept])
            _compare(report, label, fy, ours, theirs, "FNH",
                     False, _MONEY_FLOOR, unit,
                     restated_check=lambda c=concept, e=f.fy_ends[i]:
                     _edgar_restated(f, c, e, _MONEY_FLOOR))


# ------------------------------------------------------------- fetching

def _cached(cache, key: str, ttl: float, fetch):
    if cache is not None:
        hit = cache.get(key, ttl)
        if hit is not None:
            return hit
    value = fetch()
    if cache is not None and value:
        cache.put(key, value)
    return value


def run_reconciliation(d, cache=None) -> AuditReport:
    """Fetch both legs (cached, TTL as companyfacts) and reconcile.
    Provider failures degrade to a partial report, never an exception."""
    from .providers.fmp import FREE_STATEMENT_LIMIT, FMPClient
    from .providers.finnhub import FinnhubClient

    report = AuditReport()
    symbol = d.ticker.strip().upper().replace(".", "-")
    errors: List[str] = []

    if config.FMP_API_KEY:
        try:
            c = FMPClient()
            statements = {}
            for stmt, method in (("income", c.income_statement),
                                 ("cashflow", c.cash_flow_statement),
                                 ("balance", c.balance_sheet_statement)):
                statements[stmt] = _cached(
                    cache, f"fmp17c://{stmt}/{symbol}",
                    config.TTL_COMPANYFACTS,
                    lambda m=method: m(symbol,
                                       limit=FREE_STATEMENT_LIMIT))
            reconcile_fmp(d, statements, report)
            report.sources.append("FMP")
        except Exception as exc:
            errors.append(f"FMP: {str(exc)[:60]}")

    if config.FINNHUB_API_KEY:
        try:
            payload = _cached(
                cache, f"fnh17c://financials-reported/{symbol}",
                config.TTL_COMPANYFACTS,
                lambda: FinnhubClient().financials_reported(symbol))
            reconcile_finnhub(d, payload, report)
            report.sources.append("Finnhub as-reported")
        except Exception as exc:
            errors.append(f"Finnhub: {str(exc)[:60]}")

    report.error = "; ".join(errors)
    report.fetched_at = dt.datetime.now(dt.timezone.utc).isoformat(
        timespec="seconds")
    return report

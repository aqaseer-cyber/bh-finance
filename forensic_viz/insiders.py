"""FIX-17e: insider transactions — EDGAR Form 4, parsed natively.

The DVH sheet scrapes openinsider.com, which itself scrapes EDGAR Form 4
filings; this module goes straight to the primary source. Only OPEN-
MARKET codes are shown — P (purchase) and S (sale): awards, exercises,
gifts and tax withholding are compensation mechanics, not conviction.

Costs and gates: each Form 4 is one small Archives fetch (immutable —
cached a year by accession); the panel reads the most recent
`config.INSIDER_MAX_FILINGS` filings inside the 12-month window and
says so when more exist. www.sec.gov/Archives rejects the placeholder
User-Agent, so the panel is gated exactly like the segment fetch.
Provenance grade: audited-filing.
"""
from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import List, Optional

from . import config
from .cache import Cache
from .edgar import (
    SUBMISSIONS_URL, EdgarError, _require_declared_ua, _SecSession,
    prefetch_texts,
)

TX_CODES = {"P": "P — Purchase", "S": "S — Sale"}


@dataclass
class InsiderTx:
    date: dt.date
    name: str
    title: str
    code: str                      # rendered TX_CODES value
    shares: float                  # signed: sales negative
    price: Optional[float]
    value: Optional[float]         # signed shares × price
    owned_after: Optional[float]


@dataclass
class InsiderPanel:
    rows: List[InsiderTx] = field(default_factory=list)
    filings_read: int = 0
    filings_in_window: int = 0
    window_months: int = 12
    note: str = ""

    def summary(self) -> str:
        buys = [t for t in self.rows if t.shares > 0]
        sells = [t for t in self.rows if t.shares < 0]
        bv = sum(t.value or 0.0 for t in buys)
        sv = sum(t.value or 0.0 for t in sells)
        net = bv + sv
        return (f"{self.window_months}m open-market: {len(buys)} buys "
                f"${bv / 1e6:,.1f}M · {len(sells)} sells "
                f"${abs(sv) / 1e6:,.1f}M · net ${net / 1e6:+,.1f}M")


def raw_form4_document(primary_document: str) -> str:
    """The raw XML behind the styled viewer path the submissions index
    lists (e.g. 'xslF345X05/wk-form4_1.xml' -> 'wk-form4_1.xml')."""
    return primary_document.rsplit("/", 1)[-1]


def select_form4(recent: dict, today: dt.date, months: int = 12,
                 cap: Optional[int] = None):
    """(accession, raw document, filing date) for Form 4/4/A filings in
    the window, newest first; `cap` limits Archives fetches."""
    cap = cap if cap is not None else config.INSIDER_MAX_FILINGS
    cutoff = today - dt.timedelta(days=round(months * 30.44))
    out = []
    forms = recent.get("form", [])
    for i, form in enumerate(forms):
        if form not in ("4", "4/A"):
            continue
        try:
            fdate = dt.date.fromisoformat(recent["filingDate"][i])
        except (KeyError, IndexError, ValueError):
            continue
        if fdate < cutoff:
            continue
        try:
            accn = recent["accessionNumber"][i]
            doc = raw_form4_document(recent["primaryDocument"][i])
        except (KeyError, IndexError):
            continue
        if accn and doc:
            out.append((accn, doc, fdate))
    out.sort(key=lambda t: t[2], reverse=True)
    return out[:cap], len(out)


def _text(node, path: str) -> str:
    el = node.find(path)
    return (el.text or "").strip() if el is not None else ""


def _val(node, path: str) -> Optional[float]:
    raw = _text(node, path + "/value") or _text(node, path)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _owner_title(owner) -> str:
    rel = owner.find("reportingOwnerRelationship")
    if rel is None:
        return ""
    title = _text(rel, "officerTitle")
    if title:
        return title
    if _text(rel, "isDirector") in ("1", "true"):
        return "Director"
    if _text(rel, "isTenPercentOwner") in ("1", "true"):
        return "10% owner"
    return ""


def parse_form4(xml_text: str) -> List[InsiderTx]:
    """Open-market (P/S) non-derivative transactions of one Form 4.
    Derivative tables and non-P/S codes are excluded by design."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    owner = root.find("reportingOwner")
    name = _text(owner, "reportingOwnerId/rptOwnerName") if owner is not None else ""
    title = _owner_title(owner) if owner is not None else ""
    fallback_date = _text(root, "periodOfReport")
    out: List[InsiderTx] = []
    table = root.find("nonDerivativeTable")
    if table is None:
        return out
    for tx in table.findall("nonDerivativeTransaction"):
        code = _text(tx, "transactionCoding/transactionCode")
        if code not in TX_CODES:
            continue
        raw_date = _text(tx, "transactionDate/value") or fallback_date
        try:
            date = dt.date.fromisoformat(raw_date[:10])
        except (TypeError, ValueError):
            continue
        shares = _val(tx, "transactionAmounts/transactionShares")
        price = _val(tx, "transactionAmounts/transactionPricePerShare")
        if shares is None:
            continue
        disposed = _text(
            tx, "transactionAmounts/transactionAcquiredDisposedCode/value")
        signed = -abs(shares) if disposed == "D" else abs(shares)
        out.append(InsiderTx(
            date=date, name=name, title=title, code=TX_CODES[code],
            shares=signed, price=price,
            value=(signed * price if price is not None else None),
            owned_after=_val(
                tx, "postTransactionAmounts/"
                    "sharesOwnedFollowingTransaction"),
        ))
    return out


def fetch_insider_panel(fundamentals, cache: Optional[Cache] = None,
                        today: Optional[dt.date] = None,
                        months: int = 12) -> InsiderPanel:
    """Enumerate Form 4s from the (cached) submissions index and parse
    each raw XML from Archives. Raises EdgarError on the placeholder UA
    (same gate as segments); individual bad filings are skipped."""
    _require_declared_ua()
    cache = cache or Cache()
    today = today or dt.date.today()
    sec = _SecSession(cache)
    subs = sec.get_json(SUBMISSIONS_URL.format(cik=fundamentals.cik),
                        config.TTL_SUBMISSIONS)
    recent = (subs.get("filings") or {}).get("recent") or {}
    selected, in_window = select_form4(recent, today, months=months)
    panel = InsiderPanel(filings_read=len(selected),
                         filings_in_window=in_window,
                         window_months=months)

    def form4_url(accn: str, doc: str) -> str:
        return (f"https://www.sec.gov/Archives/edgar/data/"
                f"{fundamentals.cik}/{accn.replace('-', '')}/{doc}")

    # FIX-17h: warm all Form 4s concurrently (immutable, cached a year)
    prefetch_texts(sec, [form4_url(a, doc) for a, doc, _ in selected],
                   config.TTL_FILING_INSTANCE)
    for accn, doc, _fdate in selected:
        try:
            panel.rows.extend(parse_form4(sec.get_text(
                form4_url(accn, doc), config.TTL_FILING_INSTANCE)))
        except EdgarError:
            continue   # one unfetchable filing never kills the panel
    panel.rows.sort(key=lambda t: t.date, reverse=True)
    if in_window > len(selected):
        panel.note = (f"showing the {len(selected)} most recent of "
                      f"{in_window} Form 4s filed in the window")
    return panel

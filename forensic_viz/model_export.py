"""One-sheet three-statement financial model export (annual + quarterly + LTM).

Layout follows the analyst's Financial_Model_Template.xlsx: line items down
column A, one column per fiscal year, then the **last four fiscal quarters**
(spanning the fiscal-year boundary, ``Q3'25 Q4'25 Q1'26 Q2'26`` style), then
**LTM** — with the income statement, balance sheet and cash-flow statement
consolidated on ONE sheet, styled in the house colour scheme.

The sheet adapts to each company's own presentation (as tagged in its SEC
filings): line items the filer never reports are dropped rather than left
blank, opex appears as the split lines (Sales & Marketing / G&A) or the
combined SG&A line — whichever the company files — and row labels follow
the winning XBRL tag (e.g. "Technology & Development").

Quarterly mechanics (as-filed XBRL under the annual winning tag):

- **discrete quarter** = the filed ~3-month duration when present; else
  fiscal-YTD differencing (10-Q cash-flow statements are YTD-only); a
  fiscal Q4 (never filed discretely) = FY − 9-month YTD (or FY − ΣQ1..Q3);
- **LTM (flows)** = last FY + latest fiscal YTD − year-ago comparative YTD
  (= the FY itself when the latest period end is the FY end);
- **balance-sheet rows** show period-end balances, latest in the LTM column;
- **per-share rows** use the same additive arithmetic (approximation).

**% change rows** sit under the relevant line items: fiscal-year cells are
YoY, quarter cells are QoQ, and the LTM cell holds the latest quarter's YoY
(vs the year-ago quarter). Computed from the same consolidated values.

Everything is computed from data already fetched for the dashboard — the
export itself never touches the network.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import palette as P
from .edgar import (
    INSTANT_TAGS, AnnualFundamentals, QuarterlyFundamentals,
    parse_quarterly_facts,
)
from .metrics import DashboardData

_MM = 1e6
_SPAN_TOL = 14    # days tolerance matching a filed span boundary
_YEAR_TOL = 21    # days tolerance matching the year-ago span
_SHOW_QUARTERS = 4
_SPINE_EXTRA = 1  # one earlier quarter, so the first shown QoQ computes

# (label, concept, style, pct_row); concept None = section header;
# "=name" = derived row; style: item | total | eps | shares
LAYOUT: List[Tuple[str, Optional[str], str, bool]] = [
    ("INCOME STATEMENT", None, "section", False),
    ("Total Revenue", "revenue", "item", True),
    ("Cost of Revenue", "cost_of_revenue", "item", True),
    ("Gross Profit", "=gross_profit", "total", True),
    ("Research & Development", "rnd", "item", True),
    ("Sales & Marketing", "marketing", "item", True),
    ("General & Administrative", "ga", "item", True),
    ("Selling, General & Administrative", "sga", "item", True),
    ("Total Operating Expenses", "opex_total", "item", True),
    ("Operating Income (EBIT)", "operating_income", "total", True),
    ("Interest Expense", "interest_expense", "item", False),
    ("Income Before Taxes", "=pretax", "item", False),
    ("Income Tax Provision", "tax_expense", "item", False),
    ("Net Income", "net_income", "total", True),
    ("Diluted EPS ($)", "eps_diluted", "eps", True),
    ("Diluted Shares (mm)", "diluted_shares", "shares", False),
    ("BALANCE SHEET (period end)", None, "section", False),
    ("Cash & Equivalents", "cash", "item", False),
    ("Accounts Receivable", "accounts_receivable", "item", False),
    ("Inventory", "inventory", "item", False),
    ("Total Current Assets", "assets_current", "total", False),
    ("Property & Equipment, Net", "ppe_net", "item", False),
    ("Goodwill", "goodwill", "item", False),
    ("Total Assets", "total_assets", "total", False),
    ("Accounts Payable", "accounts_payable", "item", False),
    ("Short-Term Borrowings", "st_borrowings", "item", False),
    ("Current Portion of Long-Term Debt", "lt_debt_current", "item", False),
    ("Total Current Liabilities", "liabilities_current", "total", False),
    ("Long-Term Debt", "lt_debt_noncurrent", "item", False),
    ("Total Liabilities", "liabilities_total", "total", False),
    ("Retained Earnings", "retained_earnings", "item", False),
    ("Minority Interest", "minority_interest", "item", False),
    ("Preferred Equity", "preferred_equity", "item", False),
    ("Total Stockholders' Equity", "equity", "total", False),
    ("CASH FLOW STATEMENT", None, "section", False),
    ("Net Income", "net_income", "item", False),
    ("Depreciation & Amortization", "dna", "item", False),
    ("Stock-Based Compensation", "sbc", "item", False),
    ("Cash from Operations", "cfo", "total", True),
    ("Capital Expenditure", "capex", "item", True),
    ("Cash from Investing", "cfi", "total", False),
    ("Dividends Paid", "dividends_paid", "item", False),
    ("Share Repurchases", "buybacks", "item", False),
    ("Cash from Financing", "cff", "total", False),
    ("Free Cash Flow (CFO − capex)", "=fcf", "total", True),
]

# Row labels follow the company's presentation when the winning tag says so
_TAG_LABELS = {
    "TechnologyAndDevelopmentExpense": "Technology & Development",
    "AdvertisingExpense": "Advertising",
    "CostsAndExpenses": "Total Costs & Expenses",
    "CostOfGoodsAndServicesSold": "Cost of Goods & Services Sold",
}

# Weighted-average share counts can't be derived by FY − YTD subtraction
_NO_FY_DIFF = {"diluted_shares", "basic_shares"}


@dataclass
class ModelRow:
    """One consolidated line: annual, displayed quarters, LTM (+ internals)."""

    ann: List[Optional[float]]
    q: List[Optional[float]]                 # aligned to the displayed spine
    ltm: Optional[float]
    qfull: List[Optional[float]] = field(default_factory=list)  # +1 earlier
    yoy_q: Optional[float] = None            # latest quarter vs year-ago Q


# ---------------------------------------------------------------- span math

def _find_span(entries, start: dt.date, end: dt.date,
               tol: int = _SPAN_TOL) -> Optional[float]:
    for s, e, v in entries:
        if abs((e - end).days) <= tol and abs((s - start).days) <= tol:
            return v
    return None


def _find_3m(entries, qe: dt.date) -> Optional[float]:
    for s, e, v in entries:
        if abs((e - qe).days) <= _SPAN_TOL and 80 <= (e - s).days <= 100:
            return v
    return None


def _match_instant(obs: Dict[dt.date, float], target: dt.date,
                   tol: int = 7) -> Optional[float]:
    if target in obs:
        return obs[target]
    for d, v in obs.items():
        if abs((d - target).days) <= tol:
            return v
    return None


def _fy_bounds(qe: dt.date, fy_ends: List[dt.date]
               ) -> Tuple[Optional[dt.date], Optional[dt.date]]:
    """(fiscal-year start, containing FY end) for the quarter ending qe."""
    prev = None
    containing = None
    for fe in fy_ends:  # ascending
        if fe < qe:
            prev = fe
        elif containing is None and (fe - qe).days < 400:
            containing = fe
    start = prev + dt.timedelta(days=1) if prev else None
    return start, containing


def quarter_spine(qdata: QuarterlyFundamentals,
                  fy_ends: List[dt.date]) -> List[dt.date]:
    """Trailing fiscal-quarter ends (newest last), FY boundaries included.

    Returns up to _SHOW_QUARTERS + _SPINE_EXTRA ends; the display uses the
    last _SHOW_QUARTERS. Empty when the filer has no interim data at all.
    """
    interim = set()
    for entries in qdata.duration.values():
        for s, e, _ in entries:
            if 60 <= (e - s).days <= 300:  # sub-annual spans only
                interim.add(e)
    if not interim:
        return []
    latest = max(max(interim), fy_ends[-1]) if fy_ends else max(interim)
    candidates = sorted(interim | set(fy_ends))
    ends: List[dt.date] = []
    for e in candidates:  # fold ends a few days apart into one quarter
        if e > latest:
            continue
        if ends and (e - ends[-1]).days <= 10:
            ends[-1] = max(ends[-1], e)
        else:
            ends.append(e)
    # quarters need a known fiscal-year start for labeling/derivation
    ends = [e for e in ends if _fy_bounds(e, fy_ends)[0] is not None]
    return ends[-(_SHOW_QUARTERS + _SPINE_EXTRA):]


def quarter_label(qe: dt.date, fy_ends: List[dt.date]) -> str:
    fy_start, containing = _fy_bounds(qe, fy_ends)
    idx = max(1, min(4, round((qe - fy_start).days / 91.3)))
    fy_year = containing.year if containing else fy_ends[-1].year + 1
    return f"Q{idx}'{fy_year % 100:02d}"


def _ytd(entries, fy_start: dt.date, end: dt.date) -> Optional[float]:
    return _find_span(entries, fy_start, end)


def _ytd9m(entries, fy_start: dt.date, target: dt.date) -> Optional[float]:
    """9-month YTD for Q4 derivation: filed span, else ΣQ1..Q3 discretes."""
    v = _ytd(entries, fy_start, target)
    if v is not None:
        return v
    total = 0.0
    for back in range(3):
        q = _find_3m(entries, target - dt.timedelta(days=round(back * 91.3)))
        if q is None:
            return None
        total += q
    return total


def _discrete(entries, qe: dt.date, fy_ends: List[dt.date],
              annual_map: Dict[dt.date, Optional[float]],
              allow_fy_diff: bool = True) -> Optional[float]:
    """One fiscal quarter's flow, by whatever the filings support."""
    v = _find_3m(entries, qe)
    if v is not None:
        return v
    fy_start, containing = _fy_bounds(qe, fy_ends)
    if fy_start is None:
        return None
    if (qe - fy_start).days <= 100:  # fiscal Q1: YTD is the quarter
        return _ytd(entries, fy_start, qe)
    prev_target = qe - dt.timedelta(days=91)
    if containing is not None and abs((containing - qe).days) <= 7:
        if not allow_fy_diff:  # fiscal Q4 = FY − 9M YTD
            return None
        fy_val = annual_map.get(containing)
        ytd9 = _ytd9m(entries, fy_start, prev_target)
        if fy_val is not None and ytd9 is not None:
            return fy_val - ytd9
        return None
    y2 = _ytd(entries, fy_start, qe)
    y1 = _ytd(entries, fy_start, prev_target)
    if y2 is not None and y1 is not None:
        return y2 - y1
    return None


def _ltm_flow(fy_val: Optional[float], entries, fy_ends: List[dt.date],
              q_ends: List[dt.date]) -> Optional[float]:
    """LTM = last FY + latest filed fiscal YTD − year-ago comparative YTD."""
    if fy_val is None:
        return None
    if not q_ends:
        return fy_val  # trailing twelve months == the completed year
    last_fy_end = fy_ends[-1]
    fy_start = last_fy_end + dt.timedelta(days=1)
    prior_fy_start = (fy_ends[-2] + dt.timedelta(days=1)
                      if len(fy_ends) >= 2 else None)
    for qe in reversed(q_ends):  # latest period end with a usable YTD
        if abs((qe - last_fy_end).days) <= 7:
            return fy_val  # the latest period IS the fiscal year
        if qe < last_fy_end:
            continue  # stale interim inside an already-reported year
        ytd = _ytd(entries, fy_start, qe)
        if ytd is None:
            continue
        if prior_fy_start is None:
            return None
        prior = _find_span(entries, prior_fy_start,
                           qe - dt.timedelta(days=365), tol=_YEAR_TOL)
        if prior is None:
            return None
        return fy_val + ytd - prior
    return None


def _latest(vals: List[Optional[float]]) -> Optional[float]:
    for v in reversed(vals):
        if v is not None:
            return v
    return None


def _pct(cur: Optional[float], prev: Optional[float]) -> Optional[float]:
    if cur is None or prev is None or prev <= 0:
        return None
    return cur / prev - 1.0


# ----------------------------------------------------------- consolidation

def build_model_rows(annual: AnnualFundamentals,
                     qdata: QuarterlyFundamentals) -> Tuple[
                         Dict[str, ModelRow], List[dt.date], List[dt.date]]:
    """concept -> ModelRow, plus the annual and displayed-quarter spines."""
    fy_ends = annual.fy_ends
    spine = quarter_spine(qdata, fy_ends)
    q_ends = spine[-_SHOW_QUARTERS:]

    rows: Dict[str, ModelRow] = {}
    concepts = {c for _, c, _, _ in LAYOUT if c and not c.startswith("=")}
    concepts.update(("gross_profit", "pretax_income"))  # feed derived rows
    for concept in concepts:
        ann = list(annual.series.get(concept) or [None] * len(fy_ends))
        if concept in INSTANT_TAGS:
            obs = qdata.instant.get(concept, {})
            qfull = [_match_instant(obs, qe) for qe in spine]
            qs = qfull[-len(q_ends):] if q_ends else []
            ltm = _latest(qs)
            if ltm is None:
                ltm = _latest(ann)  # latest period-end balance
            rows[concept] = ModelRow(ann, qs, ltm, qfull)
            continue
        entries = qdata.duration.get(concept, [])
        annual_map = dict(zip(fy_ends, ann))
        qfull = [_discrete(entries, qe, fy_ends, annual_map,
                           allow_fy_diff=concept not in _NO_FY_DIFF)
                 for qe in spine]
        qs = qfull[-len(q_ends):] if q_ends else []
        if concept in _NO_FY_DIFF:
            ltm = _latest(qs)  # latest weighted count
            if ltm is None:
                ltm = _latest(ann)
        else:
            ltm = _ltm_flow(ann[-1] if ann else None, entries, fy_ends, q_ends)
        yoy_q = None
        if q_ends:
            year_ago = _discrete(entries, q_ends[-1] - dt.timedelta(days=365),
                                 fy_ends, annual_map,
                                 allow_fy_diff=concept not in _NO_FY_DIFF)
            yoy_q = _pct(qs[-1] if qs else None, year_ago)
        rows[concept] = ModelRow(ann, qs, ltm, qfull, yoy_q)

    def _combine(a: ModelRow, b: ModelRow, op) -> ModelRow:
        def cell(x, y):
            return op(x, y) if x is not None and y is not None else None
        return ModelRow([cell(x, y) for x, y in zip(a.ann, b.ann)],
                        [cell(x, y) for x, y in zip(a.q, b.q)],
                        cell(a.ltm, b.ltm),
                        [cell(x, y) for x, y in zip(a.qfull, b.qfull)])

    def _prefer(tagged: ModelRow, derived: ModelRow) -> ModelRow:
        def cell(t, d):
            return t if t is not None else d
        return ModelRow([cell(t, d) for t, d in zip(tagged.ann, derived.ann)],
                        [cell(t, d) for t, d in zip(tagged.q, derived.q)],
                        cell(tagged.ltm, derived.ltm),
                        [cell(t, d) for t, d in
                         zip(tagged.qfull, derived.qfull)])

    sub = lambda x, y: x - y  # noqa: E731
    add = lambda x, y: x + y  # noqa: E731
    # Gross profit: as tagged, falling back to revenue − cost of revenue
    rows["=gross_profit"] = _prefer(
        rows["gross_profit"], _combine(rows["revenue"],
                                       rows["cost_of_revenue"], sub))
    # Pre-tax income: as tagged, falling back to net income + tax provision
    rows["=pretax"] = _prefer(
        rows["pretax_income"], _combine(rows["net_income"],
                                        rows["tax_expense"], add))
    rows["=fcf"] = _combine(rows["cfo"], rows["capex"], sub)  # capex = +outflow
    for name in ("=gross_profit", "=pretax", "=fcf"):
        r = rows[name]
        # year-ago quarter for derived rows: 4 quarters back in the full
        # spine, valid when the spine is a contiguous trailing year
        if r.q and len(spine) >= 5 \
                and abs((spine[-1] - spine[-5]).days - 365) <= _YEAR_TOL:
            r.yoy_q = _pct(r.q[-1], r.qfull[-5])
    return rows, fy_ends, q_ends


# ------------------------------------------------------------------ writer

def _label_for(default: str, concept: Optional[str],
               annual: AnnualFundamentals) -> str:
    if not concept or concept.startswith("="):
        return default
    primary = (annual.tags_used.get(concept) or "").split(" (")[0]
    return _TAG_LABELS.get(primary, default)


def export_financial_model(d: DashboardData, path: str) -> str:
    """Write the consolidated three-statement model workbook; returns path."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    f = getattr(d, "fundamentals", None)
    if f is None or f.raw_facts is None:
        raise ValueError(
            "financial-model export needs the fetched filing data — "
            "run Analyze on a ticker first")
    qdata = parse_quarterly_facts(f.raw_facts, f)
    rows, fy_ends, q_ends = build_model_rows(f, qdata)

    headers = ([f"FY{e.year}" for e in fy_ends]
               + [quarter_label(qe, fy_ends) for qe in q_ends]
               + ["LTM"])
    ltm_col = 1 + len(headers)  # 1-based; column A is the line items

    ink = P.INK_PRIMARY.lstrip("#").upper()
    forest = P.GUI_SIDEBAR_BG.lstrip("#").upper()
    cream = P.SURFACE.lstrip("#").upper()
    muted = P.INK_MUTED.lstrip("#").upper()
    section_fill = PatternFill("solid", fgColor="DFE9E1")   # pale sage
    ltm_fill = PatternFill("solid", fgColor="FBF0D4")       # pale amber
    header_fill = PatternFill("solid", fgColor=forest)
    total_border = Border(top=Side(style="thin", color="9AA79B"))

    wb = Workbook()
    ws = wb.active
    ws.title = "Financial Model"
    ws.freeze_panes = "B2"
    ws.sheet_view.showGridLines = False

    ws.cell(row=1, column=1, value="Line Items")
    for j, h in enumerate(headers, start=2):
        ws.cell(row=1, column=j, value=h)
    for j in range(1, ltm_col + 1):
        c = ws.cell(row=1, column=j)
        c.fill = header_fill
        c.font = Font(bold=True, color=cream, size=10)
        c.alignment = Alignment(horizontal="left" if j == 1 else "right")

    fmt_mm = "#,##0.0;(#,##0.0)"
    fmt_eps = "0.00;(0.00)"
    fmt_pct = "0.0%;(0.0%)"
    r = 2
    for label, concept, style, pct_row in LAYOUT:
        if style == "section":
            ws.cell(row=r, column=1, value=label)
            for j in range(1, ltm_col + 1):
                c = ws.cell(row=r, column=j)
                c.fill = section_fill
                c.font = Font(bold=True, color=forest, size=10)
            r += 1
            continue
        row = rows[concept]
        cells = list(row.ann) + list(row.q) + [row.ltm]
        if all(v is None for v in cells):
            continue  # the filer never reports this line — drop the row
        ws.cell(row=r, column=1, value=_label_for(label, concept, f))
        scale = 1.0 if style == "eps" else _MM
        numfmt = fmt_eps if style == "eps" else fmt_mm
        bold = style == "total"
        ws.cell(row=r, column=1).font = Font(bold=bold, color=ink, size=10)
        for j, v in enumerate(cells, start=2):
            c = ws.cell(row=r, column=j)
            if v is not None:
                c.value = v / scale
                c.number_format = numfmt
            c.font = Font(bold=bold, color=ink, size=10)
            c.alignment = Alignment(horizontal="right")
            if j == ltm_col:
                c.fill = ltm_fill
            if bold:
                c.border = total_border
        if bold:
            ws.cell(row=r, column=1).border = total_border
        r += 1
        if not pct_row:
            continue
        # % change row: FY cells YoY · quarter cells QoQ · LTM cell =
        # latest quarter YoY (vs the year-ago quarter)
        fy_pcts = [None] + [_pct(row.ann[i], row.ann[i - 1])
                            for i in range(1, len(row.ann))]
        off = len(row.qfull) - len(row.q)
        q_pcts = [_pct(row.q[i], row.qfull[off + i - 1] if off + i - 1 >= 0
                       else None) for i in range(len(row.q))]
        pcts = fy_pcts + q_pcts + [row.yoy_q]
        if all(v is None for v in pcts):
            continue
        ws.cell(row=r, column=1, value="   % change")
        ws.cell(row=r, column=1).font = Font(italic=True, color=muted, size=8.5)
        for j, v in enumerate(pcts, start=2):
            c = ws.cell(row=r, column=j)
            if v is not None:
                c.value = v
                c.number_format = fmt_pct
            c.font = Font(italic=True, color=muted, size=8.5)
            c.alignment = Alignment(horizontal="right")
        r += 1

    # ---------------------------------------------------------- footnotes
    notes = [
        f"{d.company} ({d.ticker}) — consolidated financial model · "
        f"generated {d.generated.isoformat()} · USD in millions "
        "(EPS in $, shares in mm) · values as filed (SEC EDGAR XBRL; "
        "latest amendment wins).",
        "Quarter columns are the last four fiscal quarters: discrete "
        "3-month values as filed, else fiscal-YTD differencing (10-Q "
        "cash-flow statements are YTD-only); a fiscal Q4 is derived as "
        "FY − 9-month YTD (or FY − ΣQ1..Q3).",
        "LTM (flows) = last FY + latest fiscal YTD − year-ago comparative "
        "YTD (= the FY itself when the latest period end is the FY end, or "
        "when a concept has no current-year interim data). Balance-sheet "
        "rows show the latest period-end balance in the LTM column; "
        "per-share rows use the same additive arithmetic (approximation).",
        "% change rows: fiscal-year cells are YoY, quarter cells are QoQ, "
        "and the LTM cell holds the LATEST QUARTER's YoY vs the year-ago "
        "quarter. Blank where the prior-period base is missing or "
        "non-positive.",
        "Line items the filer never tags are omitted, so the sheet mirrors "
        "the company's own SEC presentation. Derived rows: Gross Profit "
        "falls back to Revenue − Cost of Revenue; Income Before Taxes to "
        "Net Income + Tax Provision; Free Cash Flow = CFO − capex. Capex "
        "and other 'Payments…' concepts are positive outflows as filed.",
        "Not investment advice.",
    ]
    tag_bits = "; ".join(f"{k} = {v}" for k, v in sorted(f.tags_used.items()))
    if tag_bits:
        notes.append(f"XBRL tags: {tag_bits}")
    r += 1
    for note in notes:
        c = ws.cell(row=r, column=1, value=note)
        c.font = Font(color=muted, size=8)
        r += 1

    ws.column_dimensions["A"].width = 36
    for j in range(2, ltm_col + 1):
        ws.column_dimensions[get_column_letter(j)].width = 11.5
    wb.save(path)
    return path

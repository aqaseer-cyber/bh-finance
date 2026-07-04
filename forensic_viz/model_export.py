"""One-sheet three-statement financial model export (annual + quarterly + LTM).

Layout follows the analyst's Financial_Model_Template.xlsx: line items down
column A, one column per fiscal year, then the current fiscal year's
quarters (``Q1'26`` …), then **LTM** — with the income statement, balance
sheet and cash-flow statement consolidated on ONE sheet, styled in the house
colour scheme.

Quarterly mechanics (as-filed 10-Q XBRL under the annual winning tag):

- **discrete quarter** = the filed ~3-month duration when present, else the
  difference of successive fiscal-YTD durations (cash-flow statements are
  YTD-only in 10-Qs, so Q2 CFO = H1 YTD − Q1);
- **LTM (flows)** = last FY + latest fiscal YTD − year-ago YTD (the
  comparative YTD is filed in the same 10-Q);
- **balance-sheet rows** show the latest period-end balance in the LTM
  column; weighted-share rows show the latest quarter's count;
- **per-share rows** use the same additive LTM arithmetic (a standard
  approximation, noted in the footer).

Everything is computed from data already fetched for the dashboard — the
export itself never touches the network.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional, Tuple

from . import palette as P
from .edgar import (
    INSTANT_TAGS, AnnualFundamentals, QuarterlyFundamentals,
    parse_quarterly_facts,
)
from .metrics import DashboardData

_MM = 1e6
_SPAN_TOL = 14   # days tolerance when matching a filed span boundary
_YEAR_TOL = 21   # days tolerance when matching the year-ago span
_MAX_QUARTERS = 4

# (label, concept, style); concept None = section header row;
# "=name" = derived row; style: item | total | eps | shares
LAYOUT: List[Tuple[str, Optional[str], str]] = [
    ("INCOME STATEMENT", None, "section"),
    ("Total Revenue", "revenue", "item"),
    ("Cost of Revenue", "cost_of_revenue", "item"),
    ("Gross Profit", "=gross_profit", "total"),
    ("Research & Development", "rnd", "item"),
    ("Selling, General & Administrative", "sga", "item"),
    ("Operating Income (EBIT)", "operating_income", "total"),
    ("Interest Expense", "interest_expense", "item"),
    ("Income Before Taxes", "pretax_income", "item"),
    ("Income Tax Provision", "tax_expense", "item"),
    ("Net Income", "net_income", "total"),
    ("Diluted EPS ($)", "eps_diluted", "eps"),
    ("Diluted Shares (mm)", "diluted_shares", "shares"),
    ("BALANCE SHEET (period end)", None, "section"),
    ("Cash & Equivalents", "cash", "item"),
    ("Accounts Receivable", "accounts_receivable", "item"),
    ("Inventory", "inventory", "item"),
    ("Total Current Assets", "assets_current", "total"),
    ("Property & Equipment, Net", "ppe_net", "item"),
    ("Goodwill", "goodwill", "item"),
    ("Total Assets", "total_assets", "total"),
    ("Accounts Payable", "accounts_payable", "item"),
    ("Short-Term Borrowings", "st_borrowings", "item"),
    ("Current Portion of Long-Term Debt", "lt_debt_current", "item"),
    ("Total Current Liabilities", "liabilities_current", "total"),
    ("Long-Term Debt", "lt_debt_noncurrent", "item"),
    ("Total Liabilities", "liabilities_total", "total"),
    ("Retained Earnings", "retained_earnings", "item"),
    ("Minority Interest", "minority_interest", "item"),
    ("Preferred Equity", "preferred_equity", "item"),
    ("Total Stockholders' Equity", "equity", "total"),
    ("CASH FLOW STATEMENT", None, "section"),
    ("Net Income", "net_income", "item"),
    ("Depreciation & Amortization", "dna", "item"),
    ("Stock-Based Compensation", "sbc", "item"),
    ("Cash from Operations", "cfo", "total"),
    ("Capital Expenditure", "capex", "item"),
    ("Cash from Investing", "cfi", "total"),
    ("Dividends Paid", "dividends_paid", "item"),
    ("Share Repurchases", "buybacks", "item"),
    ("Cash from Financing", "cff", "total"),
    ("Free Cash Flow (CFO − capex)", "=fcf", "total"),
]

Row = Tuple[List[Optional[float]], List[Optional[float]], Optional[float]]


# ---------------------------------------------------------------- span math

def _find_span(entries, start: dt.date, end: dt.date,
               tol: int = _SPAN_TOL) -> Optional[float]:
    for s, e, v in entries:
        if abs((e - end).days) <= tol and abs((s - start).days) <= tol:
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


def quarter_ends(q: QuarterlyFundamentals, last_fy_end: dt.date) -> List[dt.date]:
    """Period ends after the last fiscal year, clustered and capped at 4."""
    raw = set()
    for entries in q.duration.values():
        for s, e, _ in entries:
            if e > last_fy_end and (e - s).days >= 60:
                raw.add(e)
    for obs in q.instant.values():
        raw.update(e for e in obs if e > last_fy_end)
    ends: List[dt.date] = []
    for e in sorted(raw):  # fold ends a few days apart into one quarter
        if ends and (e - ends[-1]).days <= 10:
            ends[-1] = max(ends[-1], e)
        else:
            ends.append(e)
    return ends[:_MAX_QUARTERS]


def _discrete_quarters(entries, fy_start: dt.date,
                       q_ends: List[dt.date]) -> List[Optional[float]]:
    """Per-quarter flows: filed 3M spans first, else YTD differencing."""
    vals: List[Optional[float]] = []
    ytd_prev: Optional[float] = 0.0  # None once the YTD chain breaks
    prev_end: Optional[dt.date] = None
    for i, qe in enumerate(q_ends):
        s_direct = fy_start if i == 0 else prev_end + dt.timedelta(days=1)
        direct = _find_span(entries, s_direct, qe)
        ytd = _find_span(entries, fy_start, qe)
        if direct is not None:
            vals.append(direct)
        elif ytd is not None and ytd_prev is not None:
            vals.append(ytd - ytd_prev)
        else:
            vals.append(None)
        if ytd is not None:
            ytd_prev = ytd
        elif ytd_prev is not None and direct is not None:
            ytd_prev += direct
        else:
            ytd_prev = None
        prev_end = qe
    return vals


def _ltm_flow(fy_val: Optional[float], entries, fy_start: dt.date,
              prior_fy_start: Optional[dt.date],
              q_ends: List[dt.date]) -> Optional[float]:
    """LTM = last FY + latest filed fiscal YTD − year-ago comparative YTD."""
    if fy_val is None:
        return None
    if not q_ends:
        return fy_val  # trailing twelve months == the completed year
    if prior_fy_start is None:
        return None
    for qe in reversed(q_ends):  # latest quarter end with a filed YTD span
        ytd = _find_span(entries, fy_start, qe)
        if ytd is None:
            continue
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


# ----------------------------------------------------------- consolidation

def build_model_rows(annual: AnnualFundamentals,
                     qdata: QuarterlyFundamentals) -> Tuple[
                         Dict[str, Row], List[dt.date], List[dt.date]]:
    """concept -> (annual values, quarter values, LTM), plus the two spines."""
    fy_ends = annual.fy_ends
    last_fy_end = fy_ends[-1]
    fy_start = last_fy_end + dt.timedelta(days=1)
    prior_fy_start = (fy_ends[-2] + dt.timedelta(days=1)
                      if len(fy_ends) >= 2 else None)
    q_ends = quarter_ends(qdata, last_fy_end)

    rows: Dict[str, Row] = {}
    concepts = {c for _, c, _ in LAYOUT if c and not c.startswith("=")}
    concepts.add("gross_profit")  # tagged GP feeds the =gross_profit fallback
    for concept in concepts:
        ann = list(annual.series.get(concept) or [None] * len(fy_ends))
        if concept in INSTANT_TAGS:
            obs = qdata.instant.get(concept, {})
            qs = [_match_instant(obs, qe) for qe in q_ends]
            ltm = _latest(qs)
            if ltm is None:
                ltm = _latest(ann)  # latest period-end balance
        else:
            entries = qdata.duration.get(concept, [])
            qs = _discrete_quarters(entries, fy_start, q_ends)
            if concept in ("diluted_shares", "basic_shares"):
                ltm = _latest(qs)  # latest weighted count
                if ltm is None:
                    ltm = _latest(ann)
            else:
                ltm = _ltm_flow(ann[-1] if ann else None, entries,
                                fy_start, prior_fy_start, q_ends)
        rows[concept] = (ann, qs, ltm)

    def _minus(a: Row, b: Row) -> Row:
        def sub(x, y):
            return x - y if x is not None and y is not None else None
        return ([sub(x, y) for x, y in zip(a[0], b[0])],
                [sub(x, y) for x, y in zip(a[1], b[1])],
                sub(a[2], b[2]))

    # Gross profit: as tagged, falling back to revenue − cost of revenue
    tagged = rows["gross_profit"]
    derived = _minus(rows["revenue"], rows["cost_of_revenue"])
    rows["=gross_profit"] = (
        [t if t is not None else d for t, d in zip(tagged[0], derived[0])],
        [t if t is not None else d for t, d in zip(tagged[1], derived[1])],
        tagged[2] if tagged[2] is not None else derived[2])
    rows["=fcf"] = _minus(rows["cfo"], rows["capex"])  # capex filed as +outflow
    return rows, fy_ends, q_ends


# ------------------------------------------------------------------ writer

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

    next_fy_yy = (fy_ends[-1].year + 1) % 100
    headers = ([f"FY{e.year}" for e in fy_ends]
               + [f"Q{i + 1}'{next_fy_yy:02d}" for i in range(len(q_ends))]
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
    r = 2
    for label, concept, style in LAYOUT:
        ws.cell(row=r, column=1, value=label)
        if style == "section":
            for j in range(1, ltm_col + 1):
                c = ws.cell(row=r, column=j)
                c.fill = section_fill
                c.font = Font(bold=True, color=forest, size=10)
            r += 1
            continue
        ann, qs, ltm = rows[concept]
        scale = 1.0 if style == "eps" else _MM
        numfmt = fmt_eps if style == "eps" else fmt_mm
        bold = style == "total"
        ws.cell(row=r, column=1).font = Font(bold=bold, color=ink, size=10)
        for j, v in enumerate(list(ann) + list(qs) + [ltm], start=2):
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

    # ---------------------------------------------------------- footnotes
    notes = [
        f"{d.company} ({d.ticker}) — consolidated financial model · "
        f"generated {d.generated.isoformat()} · USD in millions "
        "(EPS in $, shares in mm) · values as filed (SEC EDGAR XBRL; "
        "latest amendment wins).",
        "Quarters are the fiscal periods after the last completed fiscal "
        "year: discrete 3-month values as filed, else derived by "
        "differencing successive fiscal-YTD spans (10-Q cash-flow "
        "statements are YTD-only).",
        "LTM (flows) = last FY + latest fiscal YTD − year-ago comparative "
        "YTD. Balance-sheet rows show the latest period-end balance in the "
        "LTM column; per-share rows use the same additive arithmetic "
        "(approximation).",
        "Derived rows: Gross Profit falls back to Revenue − Cost of Revenue "
        "when untagged; Free Cash Flow = CFO − capex. Capex and other "
        "'Payments…' concepts are positive outflows as filed.",
        "Blank cells = concept not tagged in that period's XBRL. "
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

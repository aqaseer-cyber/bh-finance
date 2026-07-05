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
YoY vs the prior fiscal year, and quarter cells are YoY vs the same fiscal
quarter a year earlier (seasonal businesses make quarter-on-quarter noise,
so QoQ is deliberately not shown). Computed from the same consolidated
values; year-ago quarters derive from the filing history exactly like the
displayed ones.

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
from .metrics import DashboardData, fy_label

_MM = 1e6
_SPAN_TOL = 14    # days tolerance matching a filed span boundary
_YEAR_TOL = 21    # days tolerance matching the year-ago span
_SHOW_QUARTERS = 4

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
    # same-quarter-a-year-earlier values, aligned to q (drives the YoY cells)
    q_prior: List[Optional[float]] = field(default_factory=list)


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

    Returns up to _SHOW_QUARTERS ends; empty when the filer has no
    interim data at all.
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
    return ends[-_SHOW_QUARTERS:]


def quarter_label(qe: dt.date, fy_ends: List[dt.date]) -> str:
    fy_start, containing = _fy_bounds(qe, fy_ends)
    idx = max(1, min(4, round((qe - fy_start).days / 91.3)))
    # year suffix from the dashboard's fiscal-year convention (fy_label),
    # so off-calendar filers label consistently across the app
    ref = containing if containing is not None \
        else fy_ends[-1] + dt.timedelta(days=365)
    return f"Q{idx}'{fy_label(ref)[-2:]}"


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


def _annual_from_entries(entries, fy_ends: List[dt.date]
                         ) -> List[Optional[float]]:
    """Full-year values aligned to the fiscal spine (segment lines)."""
    return [next((v for s, e, v in entries
                  if abs((e - fe).days) <= 7 and 330 <= (e - s).days <= 400),
                 None)
            for fe in fy_ends]


def _annual_spans(entries, fy_ends: List[dt.date]):
    """The matched full-year span per fiscal year (for synth-flagging)."""
    return [next(((s, e) for s, e, v in entries
                  if abs((e - fe).days) <= 7 and 330 <= (e - s).days <= 400),
                 None)
            for fe in fy_ends]


def _flow_row(entries, ann: List[Optional[float]], fy_ends: List[dt.date],
              q_ends: List[dt.date], allow_fy_diff: bool = True,
              shares_like: bool = False) -> ModelRow:
    """Consolidate one flow line: quarters, year-ago quarters, LTM."""
    annual_map = dict(zip(fy_ends, ann))
    qs = [_discrete(entries, qe, fy_ends, annual_map,
                    allow_fy_diff=allow_fy_diff) for qe in q_ends]
    # same fiscal quarter a year earlier — the filing history (prior-year
    # 10-Qs and comparatives) supports the same derivation chain
    q_prior = [_discrete(entries, qe - dt.timedelta(days=365), fy_ends,
                         annual_map, allow_fy_diff=allow_fy_diff)
               for qe in q_ends]
    if shares_like:
        ltm = _latest(qs)  # latest weighted count
        if ltm is None:
            ltm = _latest(ann)
    else:
        ltm = _ltm_flow(ann[-1] if ann else None, entries, fy_ends, q_ends)
    return ModelRow(ann, qs, ltm, q_prior)


# ----------------------------------------------------------- consolidation

def build_model_rows(annual: AnnualFundamentals,
                     qdata: QuarterlyFundamentals) -> Tuple[
                         Dict[str, ModelRow], List[dt.date], List[dt.date]]:
    """concept -> ModelRow, plus the annual and displayed-quarter spines."""
    fy_ends = annual.fy_ends
    q_ends = quarter_spine(qdata, fy_ends)

    rows: Dict[str, ModelRow] = {}
    concepts = {c for _, c, _, _ in LAYOUT if c and not c.startswith("=")}
    concepts.update(("gross_profit", "pretax_income"))  # feed derived rows
    for concept in concepts:
        ann = list(annual.series.get(concept) or [None] * len(fy_ends))
        if concept in INSTANT_TAGS:
            obs = qdata.instant.get(concept, {})
            qs = [_match_instant(obs, qe) for qe in q_ends]
            ltm = _latest(qs)
            if ltm is None:
                ltm = _latest(ann)  # latest period-end balance
            rows[concept] = ModelRow(ann, qs, ltm, [None] * len(q_ends))
            continue
        rows[concept] = _flow_row(
            qdata.duration.get(concept, []), ann, fy_ends, q_ends,
            allow_fy_diff=concept not in _NO_FY_DIFF,
            shares_like=concept in _NO_FY_DIFF)

    def _combine(a: ModelRow, b: ModelRow, op) -> ModelRow:
        def cell(x, y):
            return op(x, y) if x is not None and y is not None else None
        # prior-of-a-difference == difference-of-priors, so q_prior combines
        # element-wise exactly like the displayed quarters
        return ModelRow([cell(x, y) for x, y in zip(a.ann, b.ann)],
                        [cell(x, y) for x, y in zip(a.q, b.q)],
                        cell(a.ltm, b.ltm),
                        [cell(x, y) for x, y in zip(a.q_prior, b.q_prior)])

    def _prefer(tagged: ModelRow, derived: ModelRow) -> ModelRow:
        def cell(t, d):
            return t if t is not None else d
        return ModelRow([cell(t, d) for t, d in zip(tagged.ann, derived.ann)],
                        [cell(t, d) for t, d in zip(tagged.q, derived.q)],
                        cell(tagged.ltm, derived.ltm),
                        [cell(t, d) for t, d in
                         zip(tagged.q_prior, derived.q_prior)])

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

    headers = ([fy_label(e) for e in fy_ends]
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

    def pct_cells(row: ModelRow) -> List[Optional[float]]:
        """FY cells: YoY vs prior FY · quarter cells: YoY vs the same
        fiscal quarter a year earlier · LTM cell: blank."""
        fy = [None] + [_pct(row.ann[i], row.ann[i - 1])
                       for i in range(1, len(row.ann))]
        qs = [_pct(v, p) for v, p in zip(row.q, row.q_prior)]
        return fy + qs + [None]

    def write_pct_row(r: int, row: ModelRow) -> int:
        pcts = pct_cells(row)
        if all(v is None for v in pcts):
            return r
        ws.cell(row=r, column=1, value="   % change")
        ws.cell(row=r, column=1).font = Font(italic=True, color=muted,
                                             size=8.5)
        for j, v in enumerate(pcts, start=2):
            c = ws.cell(row=r, column=j)
            if v is not None:
                c.value = v
                c.number_format = fmt_pct
            c.font = Font(italic=True, color=muted, size=8.5)
            c.alignment = Alignment(horizontal="right")
        return r + 1

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
        if pct_row:
            r = write_pct_row(r, row)

    # ------------------------------------------------- SEGMENTS (as filed)
    seg = getattr(d, "segments", None)
    seg_lines = list(getattr(seg, "lines", None) or [])
    any_synth_cell = False
    if seg_lines:
        ws.cell(row=r, column=1, value="SEGMENTS (as filed)")
        for j in range(1, ltm_col + 1):
            c = ws.cell(row=r, column=j)
            c.fill = section_fill
            c.font = Font(bold=True, color=forest, size=10)
        r += 1

        def write_check_row(r, label, values, pct_fmt=False):
            """Muted checksum row (Σ members / gap-vs-consolidated)."""
            ws.cell(row=r, column=1, value=label)
            ws.cell(row=r, column=1).font = Font(italic=True, color=muted,
                                                 size=8.5)
            bad = P.DELTA_BAD.lstrip("#").upper()
            for j, v in enumerate(values, start=2):
                c = ws.cell(row=r, column=j)
                color = muted
                if v is not None:
                    c.value = v if pct_fmt else v / _MM
                    c.number_format = fmt_pct if pct_fmt else fmt_mm
                    if pct_fmt and abs(v) > 0.02:
                        color = bad  # the tie is off — make it read as a flag
                c.font = Font(italic=True, color=color, size=8.5)
                c.alignment = Alignment(horizontal="right")
            return r + 1

        blocks: List[Tuple[Tuple[str, str], List]] = []
        for ln in seg_lines:  # group into (measure, axis) blocks, in order
            key = (ln.group, ln.axis)
            if not blocks or blocks[-1][0] != key:
                blocks.append((key, []))
            blocks[-1][1].append(ln)
        for (group, axis), lns in blocks:
            rendered = []
            for ln in lns:
                ann = _annual_from_entries(ln.entries, fy_ends)
                rowv = _flow_row(ln.entries, ann, fy_ends, q_ends)
                if any(v is not None for v in
                       list(rowv.ann) + list(rowv.q) + [rowv.ltm]):
                    rendered.append((ln, rowv))
            if not rendered:
                continue
            c = ws.cell(row=r, column=1, value=f"{group} by {axis}")
            c.font = Font(bold=True, italic=True, color=forest, size=9)
            r += 1
            for ln, rowv in rendered:
                spans = _annual_spans(ln.entries, fy_ends)
                flags = ([sp is not None and sp in ln.synth for sp in spans]
                         + [any(abs((e - qe).days) <= _SPAN_TOL
                                for _, e in ln.synth) for qe in q_ends]
                         + [bool(ln.synth)
                            and any(e >= fy_ends[-1] for _, e in ln.synth)])
                cells = list(rowv.ann) + list(rowv.q) + [rowv.ltm]
                ws.cell(row=r, column=1, value=f"  {ln.member}")
                ws.cell(row=r, column=1).font = Font(color=ink, size=10)
                for j, (v, fl) in enumerate(zip(cells, flags), start=2):
                    c = ws.cell(row=r, column=j)
                    if v is not None:
                        c.value = v / _MM
                        c.number_format = fmt_mm
                        if fl:
                            any_synth_cell = True
                    c.font = Font(color=ink, size=10, italic=fl)
                    c.alignment = Alignment(horizontal="right")
                    if j == ltm_col:
                        c.fill = ltm_fill
                r += 1
                r = write_pct_row(r, rowv)
            if group != "Revenue":
                continue
            # visible tie-out (house scale-tie doctrine): Σ of the members
            # vs the consolidated statement, per column — a positive gap
            # means hierarchical members double-count on this axis
            cons = rows["revenue"]
            cons_cells = list(cons.ann) + list(cons.q) + [cons.ltm]
            sums: List[Optional[float]] = []
            for i in range(len(cons_cells)):
                vals = [(list(rv.ann) + list(rv.q) + [rv.ltm])[i]
                        for _, rv in rendered]
                vals = [v for v in vals if v is not None]
                sums.append(sum(vals) if vals else None)
            r = write_check_row(r, "   Σ members", sums)
            r = write_check_row(r, "   vs consolidated (gap %)",
                                [_pct(sv, cv) for sv, cv
                                 in zip(sums, cons_cells)], pct_fmt=True)

    # ---------------------------------------------------------- footnotes
    notes = [
        f"{d.company} ({d.ticker}) — consolidated financial model · "
        f"generated {d.generated.isoformat()} · USD in millions "
        "(EPS in $, shares in mm) · values as filed (SEC EDGAR XBRL; "
        "latest amendment wins).",
        "Quarter columns are the last four fiscal quarters: discrete "
        "3-month values as filed, else fiscal-YTD differencing (10-Q "
        "cash-flow statements are YTD-only); a fiscal Q4 is derived as "
        "FY − 9-month YTD (or FY − ΣQ1..Q3) — note a restated FY places "
        "the full restatement delta in that derived Q4.",
        "LTM (flows) = last FY + latest fiscal YTD − year-ago comparative "
        "YTD (= the FY itself when the latest period end is the FY end, or "
        "when a concept has no current-year interim data). Balance-sheet "
        "rows show the latest period-end balance in the LTM column; "
        "per-share rows use the same additive arithmetic (approximation).",
        "% change rows: fiscal-year cells are YoY vs the prior fiscal "
        "year; quarter cells are YoY vs the SAME fiscal quarter a year "
        "earlier (QoQ is not shown — seasonality makes it noise). Blank "
        "where the prior-period base is missing or non-positive.",
        "Line items the filer never tags are omitted, so the sheet mirrors "
        "the company's own SEC presentation. Derived rows: Gross Profit "
        "falls back to Revenue − Cost of Revenue; Income Before Taxes to "
        "Net Income + Tax Provision; Free Cash Flow = CFO − capex. Capex "
        "and other 'Payments…' concepts are positive outflows as filed.",
        "Not investment advice.",
    ]
    if seg_lines:
        src = getattr(seg, "source", "") or "latest filings"
        extra = getattr(seg, "status", "")
        notes.insert(-1, (
            f"Segments: dimensional XBRL parsed from {src}; history depth "
            "= as reported there (a 10-K carries 2–3 comparative years, "
            "the 10-Q the current quarters + year-ago comparatives). "
            "Members ordered by latest annual revenue. The 'Σ members' / "
            "'vs consolidated (gap %)' rows tie each revenue block to the "
            "consolidated statement — a positive gap beyond +2% signals "
            "hierarchical (parent + child) members double-counting on that "
            "axis; a negative gap means members the filer left untagged."
            + (f" Note: {extra}." if extra else "")))
        if any_synth_cell:
            notes.insert(-1, (
                "Italic segment cells were synthesized by summing the "
                "two-axis disaggregation table (not directly filed); the "
                "gap row shows how completely that table covers the "
                "consolidated total."))
    else:
        why = getattr(seg, "status", "") if seg is not None else \
            "not fetched in this run"
        notes.insert(-1, (
            "Segments: no dimensional segment data in this workbook — "
            + (why or "it lives in the 10-K/10-Q XBRL instance (fetched "
                      "live, not in the companyfacts API)") + "."))
    tagged_pt, merged_pt = rows["pretax_income"], rows["=pretax"]
    if any(t is None and m is not None for t, m in zip(
            list(tagged_pt.ann) + list(tagged_pt.q) + [tagged_pt.ltm],
            list(merged_pt.ann) + list(merged_pt.q) + [merged_pt.ltm])):
        notes.insert(-1, (
            "Income Before Taxes cells without a filed pretax tag are "
            "derived as Net Income + Tax Provision; parent-attributable "
            "net income understates pretax income when minority interest "
            "is material."))
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

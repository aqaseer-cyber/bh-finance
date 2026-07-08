"""Fill the forensic_valuation_model_v3.xlsx shell from app data.

Writes every blue input cell the app can source (XBRL, prices, the §4.0 rate
build, the valuation dialog, analyst inputs already entered in-app) into a
copy of the template, and returns the list of cells left for the analyst with
a suggested source for each — the workbook's own formulas (360 of them) then
do the rest. Monetary cells are in $mm, shares in millions, per the shell's
unit convention (Control!B11).

Nothing here overwrites a formula: only known blue-input coordinates are
touched, so the 133-blue-cell / 360-formula contract stays intact for the
user's preflight lint.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from . import config
from .metrics import DashboardData

def asset_path(name: str) -> Path:
    """Bundled-asset resolution: source tree or PyInstaller _MEIPASS.

    The single path scheme for everything under assets/ (workbook shell,
    app icons) — do not invent a second one.
    """
    import sys
    if getattr(sys, "frozen", False):  # PyInstaller bundle (--add-data assets)
        return Path(getattr(sys, "_MEIPASS", ".")) / "assets" / name
    return Path(__file__).resolve().parent.parent / "assets" / name


TEMPLATE = asset_path("forensic_valuation_model_v3.xlsx")

TRACK_NAMES = {"standard": "Standard", "bank": "Banks", "insurance": "Insurance",
               "reit": "REIT", "sotp": "SOTP"}

# Analyst-only blue cells: (sheet, cell, label, suggested source). The tool
# ladder (master §1): Fiscal.ai MCP / IBKR -> EDGAR full text / IR -> web.
ANALYST_CELLS = [
    ("Phase1_Anchor", "B19", "Non-operating investments",
     "10-K balance sheet + investments footnote (equity stakes at fair value)"),
    ("Phase1_Anchor", "B24", "Latest earnings transcript date",
     "company IR page / earnings-call provider"),
    ("Phase2_UnitEcon", "B5:B7", "Segment revenue split",
     "10-K segment footnote (ASC 280) — dimensional XBRL, not in companyfacts"),
    ("Phase2_UnitEcon", "B12:B15", "Organic/inorganic, price/volume split",
     "MD&A + earnings release; deal 8-Ks for acquired revenue"),
    ("Phase2_UnitEcon", "B23:B24", "LTV / CAC",
     "company KPI disclosures / investor day; not a GAAP concept"),
    ("Phase2_UnitEcon", "B28", "Average earning assets (banks)",
     "10-K average balance sheet table (the app's NIM proxy uses avg TOTAL assets)"),
    ("Phase2_UnitEcon", "B36:B39", "REIT NOI / same-store / FFO / AFFO",
     "REIT supplemental package (non-GAAP, not in XBRL)"),
    ("Phase2_UnitEcon", "B47:B50", "Concentrations (customer/geo/supplier)",
     "10-K Item 1/1A + concentration-risk footnote (≥10% house flag)"),
    ("Phase3_Forensic", "B11:C13", "Top-3 add-backs + recurring verdicts",
     "earnings-release non-GAAP reconciliation table"),
    ("FCFF_DCF", "B42:C43", "NORMALIZED OCF / capex",
     "analyst normalization (§4.0: through-cycle capex, never a single quarter) — "
     "the app pre-fills as-reported values as the starting point"),
    ("Val_Fin_RI", "B12:F16", "Through-cycle ROE paths (Track A/B)",
     "analyst judgment off the credit cycle; app pre-fills the dialog ROEs"),
    ("Val_REIT_NAV", "B5:B10", "Forward NOI, cap rates, other assets/liabilities",
     "supplemental + broker cap-rate surveys (Track B: +50–100 bps, §4.C)"),
    ("Phase5_Verdict", "A35", "One-sentence rating rationale",
     "analyst: rating tied to the §2.3 terminal risk + thesis restatement"),
]


@dataclass
class FillReport:
    filled: int
    out_path: str
    analyst_cells: List[tuple]  # (sheet, cells, label, source)
    notes: List[str] = None  # tie-out / data-quality notes (may be None)


def _mm(v: Optional[float]) -> Optional[float]:
    return None if v is None else round(v / 1e6, 3)


def _latest(seq):
    for v in reversed(seq or []):
        if v is not None:
            return v
    return None


def _consolidated_at(d, span_end):
    """Consolidated revenue at the fiscal year matching a segment span.

    Returns (total, aligned): aligned=False means no fiscal year matched
    within 7 days and the latest FY was used as a fallback.
    """
    for fe, v in zip(d.fy_ends or [], d.revenue or []):
        if v is not None and abs((fe - span_end).days) <= 7:
            return v, True
    return _latest(d.revenue), False


def fill_workbook(d: DashboardData, out_path: str, res=None, verdict=None,
                  template: Optional[str] = None) -> FillReport:
    import openpyxl

    path = Path(template) if template else TEMPLATE
    wb = openpyxl.load_workbook(path)
    writes = {}
    comments = {}  # cell notes (e.g. segment names); values stay untouched

    def put(sheet: str, cell: str, value) -> None:
        if value is not None and value != "":
            writes[(sheet, cell)] = value

    # ---- Control ----------------------------------------------------------
    put("Control", "B7", d.ticker)
    put("Control", "B8", d.company)
    put("Control", "B9", TRACK_NAMES.get(d.track, "Standard"))
    put("Control", "B10", d.generated.isoformat())
    put("Control", "B50", _latest(d.eps_diluted))
    shares = _latest(d.diluted_shares)
    if d.last_close and shares:  # computed cap; verify vs 2 third-party sources
        put("Control", "B53", _mm(d.last_close * shares))
    put("Control", "B60", _mm(_latest(d.dna)))
    if verdict is not None and verdict.rating:
        put("Control", "B20", verdict.rating)

    # ---- Phase1_Anchor ----------------------------------------------------
    put("Phase1_Anchor", "B5", d.last_close)
    basic = _latest(d.basic_shares)
    put("Phase1_Anchor", "B6", None if basic is None else round(basic / 1e6, 3))
    put("Phase1_Anchor", "B7", None if shares is None else round(shares / 1e6, 3))
    if d.price_closes:
        window = d.price_closes[-252:]
        put("Phase1_Anchor", "B9", round(max(window), 2))
        put("Phase1_Anchor", "B10", round(min(window), 2))
    put("Phase1_Anchor", "B14", _mm(_latest(d.total_debt)))
    put("Phase1_Anchor", "B15", _mm(_latest(d.cash)))
    put("Phase1_Anchor", "B17", _mm(_latest(d.minority_interest)) or 0)
    put("Phase1_Anchor", "B18", _mm(_latest(d.preferred_equity)) or 0)
    if d.non_op_investments is not None:
        put("Phase1_Anchor", "B19", _mm(d.non_op_investments))
    if d.latest_10k_date:
        put("Phase1_Anchor", "B22", f"10-K — filed {d.latest_10k_date}")
    if d.latest_10q_date:
        put("Phase1_Anchor", "B23", f"10-Q — filed {d.latest_10q_date}")
    if d.thesis:
        put("Phase1_Anchor", "A27", d.thesis)

    # ---- Phase2_UnitEcon --------------------------------------------------
    # Revenue architecture (§2.1) from as-filed segment disclosures: top-2
    # segments into B5/B6, remainder into B7 (B8 sums back to total). The
    # blue cells get the values; the segment names ride as cell comments.
    # TIE-OUT GATE (FIX-10d: on the last COMMON fiscal-year span): XBRL
    # axes routinely carry hierarchical members (parent "Commerce" plus its
    # child "Commerce Services") — top-2 by size would double-count while
    # B8 still ties; and with N years of history, retired members would
    # otherwise mix fiscal years into sigma as the common case.
    fill_notes: List[str] = []
    seg = getattr(d, "segments", None)
    if seg is not None and getattr(seg, "n_segments", 0) >= 2:
        ax = seg.axes()[0]
        rev_lines = [ln for ln in seg.lines
                     if ln.axis == ax and ln.group == "Revenue"]
        span_count: dict = {}
        for ln in rev_lines:
            for s, e, _ in ln.entries:
                if 330 <= (e - s).days <= 400:
                    span_count[(s, e)] = span_count.get((s, e), 0) + 1
        gate_span = max((sp for sp, n in span_count.items() if n >= 2),
                        key=lambda sp: sp[1], default=None)
        if gate_span is None:
            fill_notes.append(
                f"Phase-2 segment fill skipped: no fiscal-year span shared "
                f"by two or more {ax} members — fill "
                "Phase2_UnitEcon!B5:B7 manually from the segment note.")
        else:
            def at_span(ln):
                return next((v for s, e, v in ln.entries
                             if (s, e) == gate_span), None)
            revs = [(ln.member, at_span(ln), gate_span in ln.synth)
                    for ln in rev_lines if at_span(ln) is not None]
            revs.sort(key=lambda t: -t[1])
            total, aligned = _consolidated_at(d, gate_span[1])
            sigma = sum(v for _, v, _ in revs)
            tol = config.SEGMENT_TIE_TOL
            fy_tag = f"FY{gate_span[1].year}"
            if len(revs) >= 2 and total and sigma > total * (1 + tol):
                fill_notes.append(
                    f"Phase-2 segment fill SKIPPED: Σ {ax} members at "
                    f"{fy_tag} (${sigma / 1e6:,.0f}mm) exceeds consolidated "
                    f"revenue (${total / 1e6:,.0f}mm) by "
                    f"{sigma / total - 1:+.1%} — hierarchical (parent + "
                    "child) members share the axis; fill "
                    "Phase2_UnitEcon!B5:B7 manually from the segment note.")
            elif len(revs) >= 2:
                for cell, (name, val, synth) in zip(("B5", "B6"), revs[:2]):
                    put("Phase2_UnitEcon", cell, _mm(val))
                    note = f"{name} (as filed {fy_tag}, by {ax})"
                    if synth:
                        note += " (synthesized from the two-axis table)"
                    comments[("Phase2_UnitEcon", cell)] = note
                rest = (max(total - revs[0][1] - revs[1][1], 0.0)
                        if total is not None
                        else (sum(v for _, v, _ in revs[2:])
                              if len(revs) > 2 else None))
                if rest is not None:
                    put("Phase2_UnitEcon", "B7", _mm(rest))
                    others = (", ".join(m for m, _, _ in revs[2:])
                              or "remainder")
                    note = (f"{others} — total minus top-2 "
                            f"(as filed {fy_tag}, by {ax})")
                    if total and sigma < total * (1 - tol):
                        note += (f"; members Σ cover only "
                                 f"{sigma / total:.0%} of consolidated "
                                 "revenue — the remainder absorbs the "
                                 "untagged gap")
                    if not aligned:
                        note += ("; consolidated total from the latest FY "
                                 "(no fiscal-year match — verify)")
                    comments[("Phase2_UnitEcon", "B7")] = note
    put("Phase2_UnitEcon", "B11", _latest(d.revenue_yoy))
    if len(d.inventory) >= 2 and d.inventory[-1] is not None:
        prev = d.inventory[-2]
        avg_inv = (d.inventory[-1] + prev) / 2 if prev is not None else d.inventory[-1]
        put("Phase2_UnitEcon", "B19", _mm(avg_inv))
    put("Phase2_UnitEcon", "B20", _mm(_latest(d.cogs)))
    put("Phase2_UnitEcon", "B27", _mm(_latest(d.nii)))
    put("Phase2_UnitEcon", "B31", _mm(_latest(d.policy_benefits)))
    put("Phase2_UnitEcon", "B32", _mm(_latest(d.uw_expense)))
    put("Phase2_UnitEcon", "B33", _mm(_latest(d.premiums_earned)))
    if d.terminal_risk:
        put("Phase2_UnitEcon", "A42", d.terminal_risk)

    # ---- Phase3_Forensic ---------------------------------------------------
    ni = _latest(d.net_income)
    put("Phase3_Forensic", "B27", _mm(ni))
    put("Phase3_Forensic", "B28", _mm(_latest(d.cfo)))
    if d.adjusted_ni is not None and ni is not None:
        put("Phase3_Forensic", "B4", "NI")
        put("Phase3_Forensic", "B5", _mm(ni))
        put("Phase3_Forensic", "B6", _mm(d.adjusted_ni))
    put("Phase3_Forensic", "B16", config.RND_LIFE_YEARS)
    rnd = [v for v in d.rnd if v is not None]
    for offset, cell in enumerate(("B17", "B18", "B19", "B20", "B21")):
        idx = len(d.rnd) - 1 - offset
        if 0 <= idx < len(d.rnd) and d.rnd[idx] is not None:
            put("Phase3_Forensic", cell, _mm(d.rnd[idx]))
    p_latest = _latest(d.piotroski_score)
    put("Phase3_Forensic", "B37", p_latest)
    put("Phase3_Forensic", "B38", None if _latest(d.altman_z) is None
        else round(_latest(d.altman_z), 2))
    put("Phase3_Forensic", "B39", _latest(d.cet1_ratio))

    # ---- WACC_Build --------------------------------------------------------
    build = getattr(d, "wacc_build", None)
    if build is not None:
        put("WACC_Build", "B4", build.r_f)
        put("WACC_Build", "B5", build.erp)
        put("WACC_Build", "B6", None if build.beta is None else round(build.beta, 3))
        put("WACC_Build", "B10", None if build.r_d is None else round(build.r_d, 4))
        put("WACC_Build", "B11", build.tax)
        if (build.beta is not None and build.tax is not None
                and build.e_weight and build.d_weight is not None and build.e_weight > 0):
            de = build.d_weight / build.e_weight
            put("WACC_Build", "B25", round(build.beta / (1 + (1 - build.tax) * de), 3))

    # ---- FCFF_DCF ----------------------------------------------------------
    fcff_a = _latest(d.fcff)
    sbc = _latest(d.sbc) or 0.0
    put("FCFF_DCF", "B5", _mm(fcff_a))
    if fcff_a is not None:
        put("FCFF_DCF", "C5", _mm(fcff_a - sbc))
    put("FCFF_DCF", "B42", _mm(_latest(d.cfo)))
    put("FCFF_DCF", "C42", _mm(None if _latest(d.cfo) is None else _latest(d.cfo) - sbc))
    capex = None
    if _latest(d.cfo) is not None and _latest(d.fcf) is not None:
        capex = _latest(d.cfo) - _latest(d.fcf)
    put("FCFF_DCF", "B43", _mm(capex))
    put("FCFF_DCF", "C43", _mm(capex))
    if res is not None and res.method == "dcf":
        # growths as entered come through ValuationInputs on `res._inputs`
        inputs = getattr(res, "_inputs", None)
        if inputs is not None:
            put("FCFF_DCF", "B9", inputs.cases["Bear"].g0)
            put("FCFF_DCF", "B6", inputs.cases["Bear"].g_term)
            put("FCFF_DCF", "C9", inputs.cases["Base"].g0)
            put("FCFF_DCF", "C6", inputs.cases["Base"].g_term)
            g0 = inputs.cases["Base"].g0
            for k, cell in enumerate(("B42", "C42", "D42", "E42", "F42")):
                put("Phase5_Verdict", cell, round(g0 - 0.04 + 0.02 * k, 4))

    # ---- Val_Fin_RI --------------------------------------------------------
    bv = _latest(d.book_equity)
    if bv is not None and shares:
        put("Val_Fin_RI", "B8", round(bv / shares, 2))
    divs, ni_l = _latest(d.dividends_paid), ni
    if divs is not None and ni_l and ni_l > 0:
        put("Val_Fin_RI", "B7", round(min(divs / ni_l, 1.0), 3))
    if divs is not None and shares:
        put("Val_Fin_RI", "B28", round(divs / shares, 2))
    if res is not None and res.method == "ri":
        inputs = getattr(res, "_inputs", None)
        if inputs is not None:
            put("Val_Fin_RI", "B6", inputs.cases["Base"].g_term)
            for col in "BCDEF":
                put("Val_Fin_RI", f"{col}12", inputs.cases["Bear"].roe)
                put("Val_Fin_RI", f"{col}16", inputs.cases["Base"].roe)

    # ---- Val_REIT_NAV ------------------------------------------------------
    put("Val_REIT_NAV", "B9", _mm(_latest(d.total_debt)))
    if shares:
        put("Val_REIT_NAV", "B12", round(shares / 1e6, 3))
    if res is not None and res.method == "affo":
        inputs = getattr(res, "_inputs", None)
        if inputs is not None:
            put("Val_REIT_NAV", "B16", inputs.cases["Base"].affo_ps)
            put("Val_REIT_NAV", "B17", inputs.cases["Bear"].target_yield)
            put("Val_REIT_NAV", "C17", inputs.cases["Base"].target_yield)

    # ---- Phase5_Verdict ----------------------------------------------------
    channel = {"standard": "Standard: revenue/FCFF shock",
               "sotp": "Standard: revenue/FCFF shock",
               "bank": "Banks: −100 bps NIM / NCO spike",
               "insurance": "Insurance: +5 pts combined ratio",
               "reit": "REIT: +100 bps cap rate"}[d.track if d.track in
               ("standard", "sotp", "bank", "insurance", "reit") else "standard"]
    put("Phase5_Verdict", "B21", channel)
    if d.track in ("standard", "sotp"):
        put("Phase5_Verdict", "B22", -0.05)
    if verdict is not None and verdict.rating:
        put("Phase5_Verdict", "B33", verdict.rating)
        sentence = f"{verdict.rating} — MoS {verdict.mos:+.1%}" if verdict.mos is not None else verdict.rating
        if d.terminal_risk:
            sentence += f"; terminal risk: {d.terminal_risk}"
        if verdict.optionality:
            sentence += f"; named optionality: {verdict.optionality}"
        put("Phase5_Verdict", "A35", sentence)

    for (sheet, cell), value in writes.items():
        wb[sheet][cell] = value
    from openpyxl.comments import Comment
    for (sheet, cell), text in comments.items():
        if (sheet, cell) in writes:
            wb[sheet][cell].comment = Comment(text, "ForensicStockViz")
    wb.save(out_path)
    # drop analyst rows the app has now filled
    filled_ranges = set()
    if ("Phase1_Anchor", "B19") in writes:
        filled_ranges.add(("Phase1_Anchor", "B19"))
    if ("Phase2_UnitEcon", "B5") in writes:
        filled_ranges.add(("Phase2_UnitEcon", "B5:B7"))
    remaining = [row for row in ANALYST_CELLS
                 if (row[0], row[1]) not in filled_ranges]
    return FillReport(filled=len(writes), out_path=out_path,
                      analyst_cells=remaining, notes=fill_notes)

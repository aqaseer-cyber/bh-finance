# bh-finance v3 — R3 EXPORT DESIGN (analyst edition; expands the charter's R3)

This replaces the charter's export bullet with the full specification. It
is written from the review of the 2026-07-18 PYPL/MELI artifact sets and
encodes what those exports got wrong. Prerequisite: charter R0–R2 merged;
this ships as R3 in four slices (R3a–R3d), each gated.

## Binding principles

1. **Decision-first.** The verdict opens the report; evidence follows.
2. **One run, three artifacts, zero divergence.** Every run mints a
   `run_id` and an input hash (ticker, inputs, rates, bases, provider
   set). All three artifacts carry it; before emitting, the exporter
   asserts FV/MoS/rating equality across PDF, workbook Cover, and the
   forensic shell — mismatch aborts the export with the diff.
3. **A report challenges its own base before presenting a verdict on it**
   (the base-quality gate, R3a).
4. **No silent absence.** A statement sheet, segment section, or metric
   that cannot be produced is *declared* missing with the reason.
5. **No truncation, ever.** Footnote content that exceeds its slot moves
   to the Appendix in full; ellipses in a deliverable are a defect.
6. **DRAFT until the analyst speaks.** Empty thesis/terminal-risk renders
   a DRAFT watermark on every page and a red line on the Decision
   Dashboard; final styling requires the inputs.
7. Track-appropriate metrics or labeled: Altman Standard-Mfg is
   suppressed (with a note) for financial-signature filers; every
   borrowed-model score names its model and its fit.

---

## R3a — Engine-adjacent computations (small, tested, before any layout)

**a1. Base-quality gate** (`metrics.py` or `anchors.py`, pure):

```python
@dataclass
class BaseQuality:
    accruals_median_3y: Optional[float]   # (NI − CFO)/avg assets, house sign
    cfo_ni_ratio: Optional[float]         # latest CFO / latest NI (NI > 0)
    financial_signature: bool             # loans/receivable-book tags present
    challenged: bool
    text: str
```

`challenged` when any of: median |accruals| > 15%; CFO/NI > 3.0;
`financial_signature` (any of `LoansAndLeasesReceivable*`,
`NotesReceivable*` material vs assets, or SIC in the finance ranges).
`text` states the mechanism and the consequence:
`"CFO runs {x}× net income (3y median accruals {a:+.0%}) — the Standard-
track FCFF base carries financing float; SOTP / de-consolidated credit is
the house-preferred frame. Verdict below is conditional on the base."`
Verdict rendering consumes it (R3b); nothing else changes — goldens
byte-identical (the gate is text + a flag, never a number).

**a2. Regime-trimmed exit multiple** (`quarters.py`/`anchors.py`): the 5y
exit cross-check uses BOTH the raw 10y median EV/EBIT and a trimmed
median (drop the top and bottom quintile of yearly observations). Report
shows `trimmed (raw)`; when the cross-check FV diverges from the DCF
FV_avg by > 20% either way, a one-line divergence note is mandatory.

**a3. Stale-series KPI guard**: any KPI whose underlying series ends
before the latest fiscal year renders as `n/a (series ends FY20xx)` —
never the relic value. Fixes "FCF ex-SBC $110.2M". Applies to every
strip KPI generically (last-index check), not just SBC.

**a4. Restatement-aware reconciliation**: before flagging an
EDGAR-vs-provider divergence, check whether EDGAR's value changed across
filings for that span (the FIX-10 recast_log / override provenance). If
yes → classify as `restated (EDGAR carries the recast; provider carries
the original)`, listed separately from true divergences. Fixes the MELI
FY2023 false alarm.

**a5. House-config regression test**: a unit test asserting that when a
house file is present, `ERP_ASSUMPTION` reflects it *after* the settings
loader runs (the FIX-16/17 settings rework broke precedence in the
field); plus a workbook-fill assertion that `WACC_Build!B5` equals
`config.ERP_ASSUMPTION` at fill time.

**a6. Statement-name matching hardened**: FilingSummary ShortName regex
extended (`STATEMENTS? OF (INCOME|OPERATIONS)( \(LOSS\))?`, comprehensive
variants), with a fallback: if a role isn't matched, scan role
definitions in the pre-linkbase; if still absent, the workbook Cover and
the PDF Appendix both print `"Income Statement: not identified in this
filing's presentation — sheets omitted"`.

**Gate:** unit tests for a1–a6; goldens identical; MELI fixture trips a1,
PYPL does not.

---

## R3b — The Report (one PDF, print-CSS per charter; six sections)

**P1 — Decision Dashboard** (everything an IC needs on one page):
rating + coherence gate; FV average with the Bear→Bull band drawn
against P₀; MoS base and stressed; the entry-price ladder; **the
base-quality box when challenged (red-keyed, above the rating)**; thesis
and terminal risk (or the DRAFT banner); open triggers from the ledger;
**delta vs prior run** (`FV_avg {now} vs {prior} on {date} · Δ{x}%` from
the verdict-history table — a report that doesn't know its predecessor
invites anchoring); run_id, input hash, provider set.

**P2 — Expectations & Valuation**: the **expectations bridge** — one
horizontal growth scale plotting market-implied g (reverse-DCF), the
three anchors (consensus/CAGR/ROIC×RR), and the case g₀ seeds; this
single chart is the report's argument. Then the case table, sensitivity
grid, stress bars, exit cross-check `trimmed (raw)` with the a2
divergence note, and ONE assumptions-and-bridge table (the Valuation/
Verdict duplication dies).

**P3 — Business & Segments** (multi-segment filers get this page;
single-segment filers get the unit-economics page alone): segment
revenue stack + mix-shift over the window, per-segment growth and
(where filed) direct-contribution margin, the tie row, recast breaks
footnoted; then the marginal unit, ROIC-vs-WACC spread band, working
capital. **No revenue chart appears anywhere else in the report.**

**P4 — Quality & Forensics**: Piotroski (asterisk semantics kept), Sloan,
Altman per principle 7, SBC (% revenue and % FCF, with the a3 guard),
accruals, R&D audit, FCF vs ex-SBC — each chart exactly once.

**P5 — Capital & Balance Sheet**: buybacks vs SBC (net shareholder
return on comp), dilution path, debt/cash/maturity posture, capex
intensity vs the 5y median (the FIX-14b flag drawn, not just noted).

**P6 — Appendix**: the full data-audit table (matches / restated /
divergent / rescued, per a4), the complete tag map, gap-rescue log,
segment status verbatim, warnings register — formatted tables,
untruncated by construction.

Formatting: A4 portrait throughout, tokens.css, tabular numerals, the
`fmt` conventions shared with the UI; footers carry run_id + sources +
"Not investment advice."

**Gate:** MELI and PYPL PDFs regenerated; owner review against this
section list; the MELI Decision Dashboard must show the base-quality
challenge above the Buy; zero ellipses (`grep -c '…' == 0` on extracted
text, excluding the Appendix's deliberate quotations).

---

## R3c — The Workbook

Sheets, in order, one format regime (FIX-12h): **Cover** (decision
summary mirroring P1 numbers, run metadata, input hash, artifact
checklist incl. explicit statement-completeness lines per a6) ·
**Financial Model** · **Income Statement** · **Balance Sheet** ·
**Cash Flow** · **Segments** · **Audit** (new — the P6 tables as real
tables: data audit, tag map, rescues, provenance per field). The
footnote walls on the Financial Model sheet shrink to one-line pointers
into Audit.

**Gate:** MELI workbook shows 7 sheets; PYPL shows the declared-missing
line if a6's fallback still can't find its income statement; formats
spot-checked; Cover FV equals PDF P1 equals shell (principle 2 assertion
exercised).

---

## R3d — The Shell, naming, and the consistency contract

- Forensic shell fill unchanged except: a Control-sheet comment stamping
  `run_id · input hash · generated · app version`, and the fill aborts if
  its computed FV/MoS disagree with the run's verdict object.
- Naming, all artifacts:
  `{TICKER}_{YYYY-MM-DD}_{run_id}_{report|model|shell}.{pdf|xlsx}`.
  The scattered per-feature filename patterns are deleted.
- A `run manifest` JSON written beside the artifacts (paths, hashes,
  provider set, warnings count) — the machine-readable receipt.

**Gate:** one command produces exactly four files (report, model, shell,
manifest) with matching run_ids; the cross-artifact assertion is
covered by a test that corrupts one artifact's FV and expects the abort.

---

## Standing owner items this design cannot absorb

1. The MELI SBC decision (override or labeled Track B = Track A) — the
   warning has fired since FIX-11; it now sits inside a printed Buy.
2. The house-ERP regression check and, if confirmed, re-running anything
   valued on the hot WACC.
3. Thesis and terminal risk per name — the DRAFT watermark will make the
   absence impossible to ignore, which is the point.

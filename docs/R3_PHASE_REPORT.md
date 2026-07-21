# v3 R3 phase report — consolidation (2026-07-18)

## Deletions (the charter's point)

- **`forensic_viz/gui.py` deleted** (1,598 lines) — the Tk shell is
  gone; `run_windows.bat` with no arguments now opens the web shell
  (`--gui` survives as an alias). The five A4 report pages exist only
  inside the PDF exporter.
- **`forensic_viz/explore.py` deleted** (691 lines) — the last card
  builders and hover helpers died with the Tk surfaces;
  `sandbox_compute` moved verbatim to `forensic_viz/sandbox.py`
  (engine-side; still powers `/api/sandbox`, parity tests intact).
- **Audit CSVs retired** (`--csv`, three exporter functions, the API
  `csv` kind): provenance lives in the workbook's tag notes and the
  goldens. `--png` retired with the pages' screen role.
- Tests: Tk-only tests deleted/pruned; the suite is now **fully
  headless — 304 passed, 0 skipped** (the tkinter skips are gone with
  their subject).

## The three artifacts (single run)

1. **ONE workbook** — Cover · Financial Model (annual + quarterly +
   LTM) · Income Statement · Balance Sheet · Cash Flow · Segments,
   single format regime (FIX-12h). The CLI writes it on every ticker
   run; the shell's Workbook button exports it to Documents.
2. **ONE PDF** — the A4 five-page report (fixture fill: 100% on all
   five pages against the 85% gate).
3. **Forensic-shell fill** — on request (`--xlsx` / the Fill-shell
   button; `/api/export/fill` attaches the last computed valuation).

## PDF engine decision (recorded, not fudged)

The charter asked for a print-CSS attempt via the shell's
print-to-PDF first. **Decision: the matplotlib A4 pipeline stays as
the PDF engine.** Grounds: pywebview exposes no stable cross-version
print-to-PDF API, WebView2 printing cannot be validated from the
Linux build environment at all, and the matplotlib pipeline passes
the fill gate at 100% today. Revisit only if pywebview ships a real
print API and the owner wants the screen look in print.

## Gate status

- Offline: suite 304/0, smoke 10/10 (model + fill + pdf exports),
  goldens byte-identical, frozen engine untouched, fill gate 100%.
- Owner-run (open): the rewritten `docs/UI_VALIDATION.md` (v3 shell)
  fully ticked + the fresh MELI run reviewed externally against the
  filing instances.

---

# R3a — engine-adjacent computations (docs/V3_R3_EXPORT_DESIGN.md)

Shipped as the first gated slice of the export design. Six items, all
tested offline (`tests/test_r3a.py`), goldens byte-identical.

- **a1 base-quality gate** — `anchors.assess_base_quality` /
  `BaseQuality`: challenged when 3y median |accruals| > 15%, CFO/NI >
  3.0, or a financial signature (SIC 6000–6999, or a
  `LoansAndLeasesReceivable*`/`NotesReceivable*` book ≥ 10% of assets).
  Text + flag only — no number changes. Rendering lands in R3b P1.
- **a2 regime-trimmed exit multiple** — `exit_multiple_check` now also
  returns `multiple_trimmed` / `fv_today_trimmed` / `return_5y_trimmed`
  (raw keys untouched). **Spec deviation, recorded:** the design says
  "trimmed median", but a median is invariant under symmetric trimming
  (dropping the top and bottom quintile of a sorted list never moves
  its middle), so that statistic would equal the raw median on every
  input and `trimmed (raw)` would print one number twice. Implemented
  as the interquintile MEAN (`anchors.trimmed_mean`): protected from
  single-year outliers, still responds to a genuine multi-year regime.
- **a3 stale-series KPI guard** — new `forensic_viz/kpi.py`
  (`stale_note`, tail-aligned last-index check) mirrored by
  `staleNote` in `overview.js`; every Overview strip KPI is guarded,
  incl. `fcf_ex_sbc` behind the Adj-FCF-yield tile (the "FCF ex-SBC
  $110.2M" relic).
- **a4 restatement-aware reconciliation** — before flagging divergent,
  `reconcile._edgar_restated` scans the raw companyfacts payload for
  >1 distinct EDGAR value at that concept's span (annual forms, own
  tag only); if found the entry is classed `restated (EDGAR carries
  the recast; provider carries the original)` — separate list,
  separate summary count, own DATA-AUDIT status line (the MELI FY2023
  false alarm).
- **a5 house-config precedence** — two real bugs fixed:
  `apply_user_settings` never re-ran the house loader (constants kept
  import-time values; now `_apply_house(_load_house(saved=…))` rebinds
  all twelve house constants), and `WaccBuild.erp` was a plain
  dataclass default frozen at import (now `default_factory`).
  Regression tests pin settings-apply, build-time ERP, and
  `WACC_Build!B5 == config.ERP_ASSUMPTION` at fill time.
- **a6 statement-name hardening** — ShortName regex admits
  `CONDENSED` and `(LOSS)` variants; a comprehensive-only second pass
  covers combined-statement filers; a pre-linkbase role-URI fallback
  (`roles_from_pre_linkbase`) catches ShortNames that defeat both;
  anything still unmatched is DECLARED missing ("… not identified in
  this filing's presentation — sheet omitted") on the UI card, the
  workbook Cover ("Statement sheets" row), and the warnings register
  (report).

Gate: suite 326/0 (22 new), goldens byte-identical, frozen-engine
edits confined to the seams a1–a6 name.

---

# R3b — the report (six A4-portrait sections)

`render_report` (dashboard.py) is now the single assembly every caller
uses — CLI and `/api/export/pdf` both. A4 portrait THROUGHOUT.

- **P1 Decision Dashboard** — base-quality box (red-keyed, ABOVE the
  rating; unchallenged is still declared), rating/FV/MoS/stressed tiles,
  coherence gate, Bear→Bull field vs P₀, the entry-price ladder drawn as
  a curve, thesis/terminal risk (or the red-lined DRAFT box), open
  triggers, **delta vs prior run** off the verdict-history table, and
  the run identity footer (`Run id · inputs hash · providers`, new
  `forensic_viz/runid.py` — provider NAMES only, never key material).
- **P2 Expectations & Valuation** — the **expectations bridge** (market-
  implied g vs the three anchors vs the case g₀ seeds, GDP cap drawn),
  case table, sensitivity grid, stress bars, exit cross-check
  `trimmed (raw)` with the mandatory >20% divergence note, and ONE
  assumptions-and-bridge table (its per-case rows are dead — the
  Valuation/Verdict duplication is killed).
- **P3 Business & Segments** — multi-segment filers get the segment
  band (stacked revenue + mix shift + per-segment growth/margin + tie &
  provenance); single-segment filers get revenue + YoY; then the
  track's unit-economics panels. The report's ONLY revenue charts.
- **P4 Quality & Forensics** — Piotroski, Sloan, accruals, Altman
  (suppressed with a note for financial-signature filers — principle
  7 via the a1 gate), SBC now % revenue AND % FCF with the a3 stale
  guard, R&D audit, FCF vs ex-SBC, earnings quality.
- **P5 Capital & Balance Sheet** — dilution path, buybacks vs SBC
  (coverage multiple labeled), debt vs cash + maturity-posture line,
  capex intensity vs 5y median with the FIX-14b flag DRAWN.
- **P6 Appendix** — data audit (incl. RESTATED), full tag map, rescue
  log, segment status, warnings register; content flows onto as many
  pages as it needs (untruncated by construction), monospace tables.

Killed: the price/drawdown page (the shell owns interactive prices),
the margins panel, the warnings-callout 6-entry cap and every
`[:N] + ellipsis` truncation (zero-ellipsis gate is a test), the
landscape pages, the five old page renderers.

Wiring: `/api/valuation` now records the verdict to the ledger (the
web flow finally feeds verdict history — the CLI always had) and
captures the predecessor row for P1's delta line. DRAFT watermark on
every page while thesis/terminal-risk are missing (principle 6).

Gate status: offline — suite 338/0 (12 new in tests/test_r3b.py),
smoke 10/10, fill tool (now portrait-per-page) 100%, goldens
byte-identical, engine modules untouched. Owner-run — regenerate the
MELI and PYPL reports and review against the section list; the MELI
Decision Dashboard must show the base-quality challenge above the Buy;
zero ellipses on extracted text.

---

# R3c — the workbook

Sheets, in order, one format regime: **Cover · Financial Model ·
Income Statement · Balance Sheet · Cash Flow · Segments · Audit**
(statement sheets omitted-and-declared per a6 when unidentified;
Segments omitted when no dimensional data; Audit always present).

- **Cover** now opens with the DECISION, mirroring the report's P1
  exactly (principle 2): rating, coherence gate, FV average / MoS /
  stressed MoS / P₀ written as real numbers, the base-quality line
  (red-keyed when the a1 gate challenges), then run identity (run_id ·
  input hash · app version), provider set, and the three-artifact
  checklist. No valuation attached → the Decision row says so.
- **Financial Model** sheet slims down: the inline SEGMENTS block and
  the DATA AUDIT block are gone (the Segments sheet and the new Audit
  sheet are their homes), the XBRL-tags wall and the interim gap-fill
  notes moved to Audit, and the footnote wall shrinks to the notes
  that explain THIS sheet's cells (quarters/LTM/%-change semantics,
  market block, LTM-basis provenance) plus one pointer line.
- **Audit** (new): the report's P6 tables as real tables — provider
  data audit (match/restated/divergent/rescuable, full), the complete
  XBRL tag map, the gap-rescue & selection log (selection notes,
  interim gap fills, statements note, price errors), segment
  provenance (coverage, breaks, the FULL recast log — the old
  "first-3 + ellipsis" truncation is dead), and the warnings register
  (health notes + valuation/case warnings + verdict notes).
- Principle 2 exercised: a test pins Cover `FV average` ==
  `verdict.fv_avg` == the figure P1 prints; R3d turns this into the
  hard cross-artifact abort.
- Principle 5 now enforced in the workbook too: a test sweeps every
  cell of every sheet for ellipses (it caught and killed a residual
  one in the capex footnote).

Gate status: offline — suite 344/0 (6 new in tests/test_r3c.py),
smoke 10/10, goldens byte-identical, engine modules untouched
(model_export/callers only). Owner-run — the MELI workbook shows all
7 sheets; PYPL shows the declared-missing statement line if a6's
fallback still can't identify its income statement; formats
spot-checked; Cover FV vs the PDF P1 vs the shell.

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

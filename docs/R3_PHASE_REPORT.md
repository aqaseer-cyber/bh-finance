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

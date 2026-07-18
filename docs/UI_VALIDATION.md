# UI validation checklist (FIX-12 / FIX-15 / FIX-16 / FIX-17) — owner-run, Windows

CI has no display and the development container has no Windows, so the
presentation layer's final acceptance is this owner-run pass. Run it on a
**Windows machine at 150% display scaling** (Settings → System → Display →
Scale). Tick every box; anything that fails goes back as a bug report with
a screenshot.

Setup: `run_windows.bat` (or the packaged `ForensicStockViz.exe`), then
Analyze a real ticker (AAPL) and a segment filer (MELI).

## DPI & rendering (FIX-12a/b/c)

- [ ] At 150% scaling the sidebar text, dialogs and menus are **crisp** —
      no bitmap-stretched blur anywhere in the shell.
- [ ] The window and taskbar show the **forest "FV" app icon** (not the
      default Tk feather).
- [ ] Report pages are sharp at first render (no fuzzy text on a 4K/150%
      monitor).
- [ ] Maximize the window, wait ~a second: pages **re-render sharp** at the
      larger size and stay **horizontally centered** in the viewport.
- [ ] Shrink the window well below the page width: a horizontal scrollbar
      appears, nothing overlaps.
- [ ] Save PDF (A4)… → open the file: page 1 portrait, pages 2–5 landscape,
      no half-empty sheets. Then run
      `python tools\check_pdf_fill.py THE_FILE.pdf` — every page ≥ 85% fill
      and the right sheet orientation (expect 100%).

## Verdict & valuation pages (FIX-12d)

- [ ] Verdict page shows all four panels: stress bars, **sensitivity grid**
      (center cell highlighted amber and equal to the FV-average tile),
      **assumptions & bridge**, **triggers & rating gate**.
- [ ] With no open triggers the box reads "No open triggers — add via
      --ledger or the watchlist." After adding a trigger
      (`--ledger-import` or a seeded ledger), it lists as `• text`.
- [ ] Valuation page ends in the bordered **"Warnings & assumptions"**
      callout (⚠ lines), not a raw text dump; more than 6 warnings shows
      "+N more — see the CSV audit trail".
- [ ] Every page carries exactly one footer line ending
      "Not investment advice."

## Menu, Settings & persistence (FIX-12e)

- [ ] Menu bar: File (Save PDF / Financial model / Fill workbook / Exit),
      Tools (Compare… / Refresh prices / Settings…), Help (About / Open cache folder /
      Open settings folder). Data items are greyed out until an Analyze
      completes and while busy.
- [ ] Fresh profile (delete `%LOCALAPPDATA%\ForensicStockViz\settings.json`):
      startup shows the SEC warning and a **one-time** yes/no offer to open
      Settings; it never asks again on later launches.
- [ ] Tools → Settings…: enter a `name email` User-Agent, Save → the SEC
      warning in the status area clears. **Restart the app** — the warning
      stays cleared (the UA persisted).
- [ ] With `SEC_EDGAR_USER_AGENT` set in the environment, the Settings
      dialog notes that the env var wins.
- [ ] Set a house-assumptions file via Browse… → note says "takes effect
      next launch"; after restart the report labels flip ASSUMPTION → house.
- [ ] Default years = 5 in Settings → restart → the Years combobox starts
      at 5.

## Watchlist (FIX-12f)

- [ ] Numeric columns (FV avg, MoS, Stressed, P₀, Age) are right-aligned;
      the Gate column shows full coherence text (230px).
- [ ] Click MoS heading → sorts ascending on the numbers (not the strings);
      click again → descending; blanks always at the bottom.
- [ ] Negative-MoS rows read red, positive green; a stale row is red
      regardless of MoS sign.
- [ ] Select a row → **History…** opens the read-only verdict history,
      newest first.

## Dialogs & flow (FIX-12g)

- [ ] Escape closes: Intrinsic value…, Analyst inputs…, Settings…,
      Compare…, About.
- [ ] Compare… is a branded dialog (entry + hint + Compare/Cancel); Return
      submits.
- [ ] During Analyze: an animated progress bar and a **Cancel** button
      appear under the status text; Cancel stops the run at the next stage
      with status "Cancelled — … not built." and no error dialog.
- [ ] At 150% scaling the valuation-dialog help text wraps to the dialog
      width (no clipped lines).

## Model export (FIX-12h)

- [ ] MELI and AAPL **Financial model…** exports: money rows like
      `20,335.0` / `(1,204.5)`, EPS `6.13`, shares `15,744.2`, % rows
      `+12.4%` / `-3.1%`; zeros render as `–`.
- [ ] Section headers read `INCOME STATEMENT ($mm; EPS in $, shares in mm)`,
      `BALANCE SHEET (period end, $mm)`, `CASH FLOW STATEMENT ($mm)`.

## Explore (FIX-15)

- [x] Every card's mode dropdown redraws **that card only**, instantly,
      and the redrawn chart is correct (spot-check P/S (TTM) against a
      hand ratio: price × diluted shares / TTM revenue at one date).
- [x] Sandbox sliders track smoothly at 150% scaling (no lag while
      dragging; live % labels follow) and, reset to the Base case, the
      outputs match the valuation page.
- [x] The ratio chart **masks** a known negative-EPS stretch as a gap for
      a name that has one (no line through the loss period, no
      interpolation).
- [x] Drawdown and Both (stacked) modes render sharp after maximize (the
      resize debounce re-renders cards at the new DPI).

## Overview & market joins (FIX-16)

- [ ] Overview tab renders all five cards after Analyze; KPI tiles show
      dashes (–) only where an input is honestly missing, and the owner's
      yield footnote ("issuance not netted") is present. The mouse wheel
      scrolls the Overview (and Explore) tab to the cards below the fold.
- [ ] After a DCF valuation the Overview valuation card gains the
      entry-price ladder line — with the hurdle price labeled
      (ASSUMPTION) — and the 5y exit cross-check line; the Valuation
      page shows the same ladder under the reverse-DCF frame.
- [ ] MELI and AAPL **Financial model…** exports carry the MARKET &
      RATIOS block (values per FY, today's values in the LTM column) and
      the CAGR/avg summary column; spot-check one market cap against
      FY-end close × diluted shares.
- [ ] Tools → **Refresh prices** updates the last close and re-renders,
      without refetching EDGAR data; the window stays responsive (spinner
      + Cancel) while the fetch runs.
- [ ] Years = 15 renders: report pages stay legible and the export grows
      the extra fiscal-year columns. Settings → default years = 15
      persists across a relaunch.

## Providers & probe (FIX-17a)

- [ ] `setx` the three provider keys (README "Provider keys"), open a
      NEW terminal, run `run_windows.bat --probe PYPL`: the matrix
      prints with per-endpoint OK/DENIED/KEY? statuses, keys appear
      only as `...tail4`, and the verdict lines state whether analyst
      estimates are served. Paste the full output back to the session.

## Data audit (FIX-17c)

- [ ] Analyze a keyed ticker (e.g. PYPL): the status line ends with
      "Audit: N/M match, X divergent, Y rescuable", the Health checks
      page carries the audit footnote (+ largest divergence when any),
      and the financial-model export contains the DATA AUDIT block with
      per-row EDGAR vs provider values and the tolerance footnote.
- [ ] Remove the keys (temporarily unset the env vars), relaunch,
      Analyze: no audit line appears anywhere and the pipeline is
      unaffected — the audit never blocks or replaces EDGAR numbers.

## Company profile (FIX-17d)

- [ ] Overview tab opens with the profile header: company name,
      description (max 3 lines, ellipsized), country / employees /
      website / SIC / IPO facts row, and the "context only, feeds no
      calculation" provenance footnote naming FMP as display-only.
- [ ] Without the FMP key the header degrades to the one-line pointer
      (README 'Provider keys') and everything below renders unchanged.
- [ ] FIX-17d.1 re-verify: no text overlaps anywhere on the card at any
      window width, the clipped description shows the "click the card
      for the full description" hint, clicking expands to the full text
      (cursor becomes a hand), clicking again collapses.

## Insiders & estimates (FIX-17e/f)

- [ ] Overview shows the Form 4 insider panel: dated open-market rows
      (purchases in green), the 12m net-buying summary, and the
      "audited-filing … awards/exercises excluded" footnote. With a
      placeholder SEC UA it degrades to the gate note instead.
- [ ] The estimates panel shows forward revenue vs the latest EDGAR
      actual, the "Street accuracy" line, the ratings strip, and the
      "consensus (FMP), unaudited … never enters FV" labels.
- [ ] Intrinsic value dialog: the anchors line now reads
      "consensus … (FMP, n=…, Rung 4)" instead of Yahoo, and the Bull
      seed matches the panel's next-FY growth. All cases still editable.

## Chart interactivity (FIX-17g)

- [ ] Hovering an Explore or Overview chart card shows the dotted
      crosshair and a readout with date + per-series values; it reads
      "–" over masked (gap) stretches and clears when the cursor
      leaves the card.
- [ ] Each Explore card's head row has Home / Pan / Zoom buttons that
      work (box-zoom then Home restores) — and NO save button.
- [ ] Wheel scrolling of the tab still works when the cursor is over a
      chart (the crosshair must not swallow the wheel).

## Speed (FIX-17h)

- [ ] Cold Analyze of a fresh multi-segment ticker (e.g. UNH,
      --no-cache) completes noticeably faster than before the update;
      the segment/insider stages no longer crawl one request at a time.
- [ ] Re-Analyze of the same ticker (warm) completes in seconds; the
      cache folder now contains facts.db and deleting it only makes the
      next run slower, never wrong.

## Sign-off

| Check block | Pass/Fail | Notes |
|---|---|---|
| DPI & rendering | | |
| Verdict & valuation | | |
| Menu & Settings | | |
| Watchlist | | |
| Dialogs & flow | | |
| Model export | | |
| Explore | Pass | owner-run 2026-07-11, Windows @150% |
| Overview & market joins | Pass | owner-run 2026-07-18 |
| Providers probe | Pass | owner-run 2026-07-18 (matrix pasted back twice) |
| Data audit | Pass | owner-run 2026-07-18 |
| Company profile | Pass* | owner-run 2026-07-18 — *text overlap + no expand; fixed in FIX-17d.1, re-verify below |
| Insiders & estimates | Pass | owner-run 2026-07-18 |
| Chart interactivity | | |
| Speed | | |

Date / machine / scaling: ______________________

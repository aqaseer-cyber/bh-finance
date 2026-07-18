# UI validation checklist (v3 shell) — owner-run, Windows

Rewritten for the v3 web shell per the charter R3 gate. The Tk-era
checklist (all blocks Pass) is archived at
`docs/UI_VALIDATION_TK_ARCHIVE.md`; git history carries every earlier
sign-off.

## Shell & frame

- [ ] `run_windows.bat` (double-click, no args) opens the native
      WebView2 window — the web shell IS the app now. `run_web.bat`
      does the same.
- [ ] Crisp at 150% scaling; ONE off-white surface, white cards one
      step up, dark forest nav, amber accents — no cream anywhere.
- [ ] The five screens and only the five: Overview · Financials ·
      Quality · Valuation · Watchlist.

## Run loop

- [ ] Enter ticker → Run: SSE progress streams in the top bar; on
      completion Overview fills. Errors (bad ticker, placeholder SEC
      UA) surface as readable status text, never a dead window.
- [ ] Watchlist renders from the ledger without any run.

## Screens (spot checks — full element list per charter §2)

- [ ] Overview: profile strip, price chart (range + drawdown toggles
      inside the card, hover crosshair), verdict strip, KPI row,
      badged estimates + insider cards.
- [ ] Financials: model table Annual ↔ Quarterly+LTM toggle matching
      the workbook's quarter columns; as-filed IS/BS/CF fully valued
      (extension concepts included — MELI interest expense); segments
      with synth flags; audit line.
- [ ] Quality: every chart once; revenue modes switch; charts fill
      their cards at every window size.
- [ ] Valuation: anchors prefill → Compute → cases/FV_avg match the
      workbook fill for the same inputs; sensitivity center = FV_avg;
      verdict + triggers; sandbox sliders live.
- [ ] Watchlist: sort, MoS colors, stale red, history drawer, re-run.

## Artifacts (v3 R3: a run yields exactly three)

- [ ] Top-bar exports: Workbook → ONE workbook (Cover · Model · IS ·
      BS · CF · Segments); PDF → the A4 report; Fill shell → the
      forensic_valuation_model fill. Paths land in Documents and are
      printed in the status line.
- [ ] CLI parity: `run_windows.bat MELI` writes the PDF + the
      workbook (no PNGs, no CSVs — retired).
- [ ] `python tools/check_pdf_fill.py` (or the CI fixture gate) ≥ 85%.

## Packaging

- [ ] `build_exe_windows.bat` → `dist\ForensicStockViz.exe` opens the
      web shell; `dist\forensic-viz-cli.exe MELI` writes both
      artifacts.

## R3 gate — fresh MELI review

- [ ] Run MELI end-to-end in the shell; export all three artifacts;
      send the workbook + PDF back for the external review against
      the filing instances.

## Sign-off

| Block | Pass/Fail | Notes |
|---|---|---|
| Shell & frame | | |
| Run loop | | |
| Screens | | |
| Artifacts | | |
| Packaging | | |
| MELI review | | |

Date / machine / scaling: ______________________

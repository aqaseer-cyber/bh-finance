# v3 R2 phase report (push 1 — 2026-07-18)

## Delivered

- **Quality screen**: merged Health + Unit-economics content as cards
  on one scrolling grid — revenue (ONE card, three modes: level /
  YoY growth / margins overlay), Piotroski, Sloan/accruals, Altman Z,
  SBC discipline (FCF vs ex-SBC), R&D audit, CCC (once), returns on
  capital, margins-vs-incremental, health notes. Each chart appears
  exactly once in the app.
- **Valuation screen**: anchors readout (`/api/anchors` — engine
  `build_growth_anchors` + `suggest_method` + auto-WACC prefill), the
  Bear/Base/Bull case grid with anchor-seeded prefills (all editable),
  case table + FV average, football field vs P₀, the verdict page's
  own sensitivity grid (center cell reproduces FV_avg — pinned by
  contract test), reverse-DCF/implied-return/hurdle/ladder/exit-check
  lines, verdict block with coherence gate + notes + open triggers,
  and the live DCF sandbox (sliders over `/api/sandbox`).
- **Watchlist screen**: sortable ledger table, MoS-colored, stale
  rows red, click-through history drawer, re-run action.

## Kill list — executed this push (deletions in the diff)

- Tk `_OverviewTab` (the Overview-built-from-Explore-cards assembly)
- Tk `_ExploreTab` + `_SandboxCard` (the Explore tab; its dropdown
  pattern is now the DEFAULT card behavior on the web screens)
- Tk `_CardToolbar` + `_attach_hover` (FIX-17g Tk interactivity —
  superseded by native web tooltips/toggles)
- Standalone revenue-growth/architecture panels exist nowhere as web
  screens (modes of the one revenue card); duplicate CCC gone (one
  CCC card in the app); no provider-reconciliation tab exists (audit
  is per-field badges + the Financials audit line).

**Line count (charter metric)** — `gui.py + dashboard.py + explore.py`:
4609 → **4157** (−452 net, with three new screens added elsewhere).

## Push 2 (same day) — Financials completion

- **Quarterly toggle**: the model table switches Annual ↔ Quarterly+LTM;
  columns and values come from `/api/financials`, which calls the SAME
  `build_model_rows` the XLSX export uses (discrete quarters, YTD
  differencing, derived Q4, LTM) — no parallel math, pinned by a
  parity contract test.
- **Full as-filed value join**: every non-abstract presentation line
  now gets its values from `annual_values_for_concept` — the export
  statement sheets' own value source, extension namespaces included —
  with unit-aware formatting and per-line provenance on hover. The
  R1 tag-map join survives only as a fallback.
- R2.1 chart-scale fix (owner feedback): hidden-screen chart init +
  legend overlap resolved.

## Remaining inside R2 (owner parity gate)

1. Owner runs the "v3 R2 — feature parity" checklist, including the
   four-name validation protocol against the new Financials/Segments
   screens.
2. The five A4 report pages as Tk *screens* — removed once the parity
   checklist confirms the web screens cover them (the pages survive
   inside the PDF exporter regardless, per the kill list).
3. `explore.py`'s now-unused Tk card builders are deleted with the
   module in R3 (`sandbox_compute` moves to the engine side then —
   it still powers `/api/sandbox`).

Goldens byte-identical; frozen engine untouched; suite green.

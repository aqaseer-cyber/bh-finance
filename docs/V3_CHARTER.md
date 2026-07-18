# bh-finance v3 — REDESIGN CHARTER & PHASE PLAN (for Claude Code)

Ratified by the owner: web UI in a native shell (Koyfin-class), full pass
including data-provider cleanup, all three provider keys retained. This
document is the top-down design artifact the project never had. It breaks
from the FIX-nn patch numbering deliberately: phases are **R0–R3**, and a
phase that only *adds* fails the charter — **subtraction is a deliverable**.

## Non-negotiables

1. **The engine is frozen.** `edgar.py`, `segments.py`, `metrics.py`,
   `valuation.py`, `verdict.py`, `anchors.py`, `quarters.py`, `ledger.py`,
   `rates.py`, `workbook.py` change only where a phase explicitly says so.
   All existing tests keep passing; `docs/golden_*.json` byte-identical
   through every phase.
2. **Rung discipline is law:** anything that feeds a valuation, verdict,
   or workbook blue cell comes from filing-grade sources (SEC XBRL) or the
   analyst. Paid providers feed *context* (estimates, profile, quotes,
   news-adjacent panels) and are always provenance-badged. If a paid
   value ever becomes a verdict input, that is a defect, not a feature.
3. Never modify `assets/forensic_valuation_model_v3.xlsx`.
4. One design system, defined below, enforced by review: no component may
   introduce a color, size, or type value not in the tokens file.
5. Packaging must survive PyInstaller on Windows at every phase gate.

---

## 1. Design system (normative)

**File: `webui/static/tokens.css`** — the only place visual constants live.

- **Color:** Palette 07 mapped to CSS variables. ONE page background
  (`--surface`, the current figure off-white); the cream `PAGE` tone is
  retired; forest is ink/accent only; pure `#ffffff` is banned outside
  `--surface-raised` (cards), which sits one step from `--surface`, not
  four. Semantic tokens: `--pos`, `--neg`, `--flag`, `--muted`,
  `--gridline` — taken from the existing palette values.
- **Type:** system stack (Segoe UI first); a 5-step scale
  (12/13/15/18/24) as variables; tabular numerals (`font-variant-numeric:
  tabular-nums`) on every numeric cell.
- **Space:** 8-pt grid; card padding 16; card gap 16; section gap 32.
- **Card anatomy (the only container):** title row (15px semibold +
  optional control on the right) · body · footnote row (12px muted).
  Every panel in the app is this card. No exceptions.
- **Chart language:** ECharts everywhere, one theme file generated from
  the tokens; `lightweight-charts` permitted for the price chart only.
  Rules: no chart borders, gridlines `--gridline` only, one series color
  ramp, axis labels 12px, values formatted by the shared `fmt.js`
  (mirrors the Python formatting: $mm with thin separators, signed
  percents, dash for null). Tooltips on hover are the default everywhere —
  this is where "non-interactive" dies.
- **Tables:** dense HTML tables, sticky first column and header, 13px,
  right-aligned numerics, row hover; no grid library.

## 2. Information architecture — five screens, hard cap

Left nav (icon + label), ticker switcher and run-status in the top bar.

1. **Overview** — profile strip (one line: name, SIC, price, day/52w
   context) · price chart (range + drawdown toggle inside the chart, not
   a separate chart) · verdict strip (rating, FV avg, MoS, gate — links
   to Valuation) · KPI row (revenue TTM, margins, ROIC, FCF) · analyst
   estimates card (FMP, badged) · insider card (EDGAR Form 4).
2. **Financials** — table-first. As-filed IS / BS / CF (the FIX-13d
   presentation-linkbase data, now rendered as tables with per-column
   fiscal years, quarterly toggle) · Segments block (axes as sub-tables,
   tie rows inline, synthesized cells flagged) · every number carries a
   provenance badge on hover (concept, accession, amendment note).
3. **Quality** — the merged Health + Unit-economics content: Piotroski,
   Sloan, Altman, SBC, R&D audit, CCC (once), ROIC/ROE, margins-vs-
   incremental — as cards on one scrolling grid, each chart appearing
   exactly once in the app.
4. **Valuation** — anchors readout · case table · football field ·
   sensitivity grid · the DCF sandbox (sliders, live) · reverse-DCF and
   coherence gates · verdict block with triggers. One screen owns the
   entire §4–§5 story.
5. **Watchlist** — the ledger table (sortable, MoS-colored, history
   drawer), re-run actions.

**Kill list (binding — R2 deletes these):** the separate Drawdown chart
(becomes a toggle); "Revenue growth" and "Revenue architecture" as
standalone panels (modes of one revenue card); the duplicate CCC panel;
the Overview-built-from-Explore-cards assembly; the Explore tab itself
(its dropdown pattern becomes the *default* card behavior everywhere);
the provider-reconciliation tab (becomes per-field provenance badges +
one "Data audit" drawer on Financials); the five A4 raster report pages
as *screens* (they survive only inside the PDF exporter until R3).

## 3. Data layer — cleanup with all three keys kept

"Cleanup" here means **roles and precedence, not deletion** (owner kept
the keys). R0 produces `docs/PROVIDER_MATRIX.md` from the current code,
then enforces:

| Concern | Primary | Fallback | May feed verdicts? |
|---|---|---|---|
| Fundamentals, segments, statements | SEC XBRL | — | YES (sole source) |
| Insider activity | EDGAR Form 4 | — | context only |
| Analyst estimates / anchors A₁ | FMP | Yahoo | seeds only, labeled Rung 4 |
| Daily prices | Tiingo | Stooq → Yahoo | price/MoS yes (quote, not judgment) |
| Live quote / profile | Finnhub | FMP | context only |

Rules: one concern → one primary + ordered fallbacks; every fetched field
records `(provider, timestamp)`; disagreement between providers beyond
tolerance surfaces in the Data-audit drawer, never silently averaged;
keys live in env/settings.json (existing FIX-12e mechanism), never in
the repo; each provider client gets a timeout, a cache TTL, and a
circuit-breaker (skip after N consecutive failures, badge the gap).

## 4. Architecture

- **Service:** `webui/server.py` — FastAPI on `127.0.0.1:<random free
  port>`, started by the shell process. Endpoints (JSON, snake_case):
  `/api/run/{ticker}` (kicks the existing pipeline, streams progress via
  SSE), `/api/data/{ticker}` (DashboardData serialized),
  `/api/valuation` (POST inputs → build_valuation/build_verdict),
  `/api/sandbox` (POST → the FIX-15c compute fn), `/api/ledger…`,
  `/api/export/{kind}`. The service is a thin adapter — **no analytics
  in the web layer**, ever.
- **Shell:** `pywebview` over WebView2; single window, app icon, native
  title bar; localhost only, token-guarded (random bearer in the page
  bootstrap) so no other local process can drive the API.
- **Frontend:** buildless — vendored ES modules (`echarts.min.js`,
  `lightweight-charts`, `petite-vue`), no Node toolchain in the build
  path, everything served from `webui/static/`. Rationale: PyInstaller
  stays one-step, Claude Code iterates without a bundler, fully offline.
  If the UI outgrows this, React+Vite is the documented escape hatch —
  a decision for the owner, not a drive-by.
- **Old GUI:** `gui.py` remains launchable (`--legacy`) until the R2
  parity gate passes; deleted in R3.

## 5. Phases and gates

**R0 — Service extraction + provider matrix (no visible change).**
Build the FastAPI adapter over the frozen engine; serializers for
DashboardData/ValuationResult/Verdict/SegmentData with a versioned
schema; SSE progress; provider matrix documented and enforced (clients
refactored to the table above; circuit-breakers; provenance fields).
*Gate:* all existing tests green; new contract tests for every endpoint
(offline, fixture-driven); goldens identical; a smoke script drives
`/api/run` on the TESTCO fixture end-to-end.

**R1 — Shell + Overview + Financials.**
tokens.css, the card component, nav frame; Overview and Financials
screens complete per §2, provenance badges live; price chart with the
range/drawdown toggle; PDF and workbook exports still produced by the
legacy pipeline. *Gate:* owner side-by-side review on Windows at 150%
(crispness is native in WebView2 — the DPI problem class disappears);
screen-recording of hover/tooltip behavior; packaging proof (PyInstaller
exe runs both shells).

**R2 — Quality + Valuation + Watchlist + the kill list.**
Remaining screens; sandbox and sensitivity live; ledger wired; **execute
the kill list** — the diff must show deletions (Explore tab, duplicate
panels, reconciliation tab, Overview-assembly). *Gate:* feature-parity
checklist (owner-run, every §2 element ticked); the four-name validation
protocol re-run against the new Financials/Segments screens; goldens
identical; net line-count of `gui.py`+`dashboard.py`+`explore.py` down,
recorded in the phase report.

**R3 — Consolidation.**
Exports: ONE workbook (Cover · Model · IS · BS · CF · Segments, single
format regime per FIX-12h) and ONE PDF — first attempt print-CSS via the
shell's print-to-PDF; if WebView2 print proves unreliable, the matplotlib
A4 pipeline stays as the PDF engine and that decision is recorded, not
fudged. Delete `--legacy` Tk, `explore.py`, the raster report pages'
screen role, and the redundant output files; single run → exactly three
artifacts (workbook, PDF, forensic-shell fill when requested).
*Gate:* fresh MELI run reviewed by the external reviewer (me) against
the instances; `check_pdf_fill` or its print-CSS successor ≥ 85%;
UI_VALIDATION rewritten for the new shell and fully ticked.

## 6. What this charter refuses to do

No timeline promises inside the spec (phases gate on evidence, not
dates). No analytics in JavaScript. No CDN dependencies. No new chart
types that duplicate an existing card's data. No provider promotion into
verdict inputs regardless of convenience. And no phase merges on green
tests alone — every gate has an owner-run element, because the failure
mode this charter exists to end was "green suite, unusable product."

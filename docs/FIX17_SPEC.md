# FIX-17 — Recheck, rescue, and context (ratified 2026-07-18)

Owner decisions this spec encodes:

1. Provider keys: FMP + Tiingo + Finnhub, all free registrations.
   Keys live in environment variables (`FMP_API_KEY`, `TIINGO_API_KEY`,
   `FINNHUB_API_KEY`), settings.json as fallback — **never in any file
   inside the repository**, never displayed beyond a `...tail4`.
2. **EDGAR stays the single displayed source of truth.** Providers
   recheck it: confirm, flag divergence, or fill cells EDGAR left empty
   — always visibly tagged, never silently merged.
3. Analyst growth estimates wanted; no good free API is guaranteed to
   exist — the FIX-17a probe records which configured key serves them
   and the FIX-17f design locks on that recorded fact.
4. International (non-SEC) tickers: out of scope.

Provenance grades (every provider declares one, every rescued or
divergent value renders its tag):

| grade | meaning |
|---|---|
| `audited-filing` | parsed directly from an SEC filing (EDGAR) |
| `aggregator` | commercial normalization (FMP, Tiingo, Finnhub) |
| `scrape` | HTML page read — reserved, none shipped |

## Stages

- **FIX-17a — provider layer + capability probe** (this commit).
  `forensic_viz/providers/` (FMP/Tiingo/Finnhub clients, header-only
  auth), config key plumbing, `--probe` CLI. **STOP: owner runs
  `run_windows.bat --probe PYPL` and reports the output** — the matrix
  decides 17f and confirms 17b/17c inputs.
- **FIX-17b — price stack.** Tiingo primary → Stooq fallback → Yahoo
  scrape retired. Same cache/trim; offline fixtures.
- **FIX-17c — reconciliation + gap rescue (self-correcting core).**
  After the EDGAR pipeline: FMP statements (recent FYs) + Finnhub
  financials-as-reported (independent parse of the same filings)
  reconciled per line item × FY. Outcomes: match (counted), divergent
  (Data Audit panel: item, FY, both values, source filing), rescued
  (EDGAR-empty cell filled, tagged `[FMP]`/`[FNH]`, distinct color —
  in GUI and model export). Data Audit panel lives at the bottom of the
  Health checks page. Goldens stay byte-identical (additive fields
  only).
- **FIX-17d — company profile card.** Overview header: name, 2-line
  description, country, website, employees, exchange, SIC — SEC
  submissions + FMP profile, per-field provenance tags.
- **FIX-17e — insider transactions, EDGAR-native.** Form 4 parse
  (last 12 months): date, insider, title, buy/sell, price, qty, value +
  net-insider-buying summary. Primary source; no scraping.
- **FIX-17f — analyst estimates panel.** Design locked by the 17a
  probe. If served: consensus forward revenue/EPS + implied growth
  rendered NEXT TO the Base-case g0, labeled `consensus (source),
  unaudited`; plus the Finnhub recommendation-trends strip. If not
  served: owner decides FMP Starter vs trends-only.
- **FIX-17g — native chart interactivity.** Hover crosshair + value
  readout on price/ratio/Explore cards; zoom/pan toolbar on
  Explore/Overview. No HTML (FIX-15 stands).
- **FIX-17h — speed.** Parallel filing-instance fetches (within SEC
  rate courtesy), SQLite fact store keyed by accession in app data,
  incremental updates. Warm re-analysis in seconds.

## Standing gates (unchanged)

Suite green offline after every stage (providers behind recorded
fixtures/fake transports; no test touches the network), goldens
byte-identical, provenance notes on everything non-EDGAR, UI checklist
boxes per stage, owner live-gate reports before sign-off.

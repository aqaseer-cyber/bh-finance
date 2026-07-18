# Provider matrix (v3 R0 — generated from the shipped code, 2026-07-18)

Charter §3 rule: one concern → one primary + ordered fallbacks; paid
providers feed **context**, never verdict inputs. Rung discipline: only
filing-grade sources (SEC XBRL) or the analyst reach a valuation,
verdict, or workbook blue cell.

| Concern | Primary | Fallback | May feed verdicts? | Code seam |
|---|---|---|---|---|
| Fundamentals, segments, statements | SEC EDGAR XBRL | — | **YES (sole source)** | `edgar.py`, `segments.py` |
| Insider activity | SEC EDGAR Form 4 | — | context only | `insiders.py` |
| Analyst estimates / anchor A₁ | FMP (grounded on EDGAR actual) | Yahoo earningsTrend (keyless only) | Bull **seed only**, labeled Rung 4, always editable | `estimates.py` |
| Daily prices | Tiingo (split-only adjusted) | Stooq | price/MoS yes (a quote, not a judgment) | `prices.py` |
| Company profile | FMP profile | — (EDGAR identity always present) | context only | `profile.py` |
| Live quote | *(unused today — last close = latest daily close)* | — | — | — |
| Recheck / data audit | FMP statements + Finnhub as-reported | — | **never** (annotates only) | `reconcile.py` |
| Recommendation trends | Finnhub | — | context only | `estimates.py` |

## Enforcement (shipped)

- **Circuit breaker** (`providers/base.py`): after
  `BREAKER_THRESHOLD = 3` consecutive transport-class failures a
  provider opens for the session and every later call short-circuits
  with "circuit open" — surfaced through the same honest-gap paths as
  any other provider failure. Plan/auth 4xx answers never trip it (the
  provider is *working*). Any success closes it.
- **Timeouts**: every provider call runs under `config.HTTP_TIMEOUT`;
  probe calls use a tighter 20 s.
- **Cache TTLs**: statements/estimates/trends 1 day
  (`TTL_COMPANYFACTS`/`TTL_ESTIMATES`), profile 7 days
  (`TTL_SUBMISSIONS`), prices 6 h (`TTL_PRICES`), filing instances and
  Form 4s 365 days (immutable).
- **Provenance timestamps**: `CompanyProfile.fetched_at`,
  `AuditReport.fetched_at`, `estimates_panel["provider"/"fetched_at"]`
  — serialized to the API for R1's per-field badges.
- **Keys**: env-first, settings.json fallback (FIX-12e mechanism),
  never in the repo, displayed `...tail4` only.
- Disagreements beyond tolerance surface in the **Data audit**
  (`reconcile.py`), never silently averaged.

## Deltas vs the charter table (RATIFIED by owner, 2026-07-18)

1. **Daily-price fallback**: charter lists `Stooq → Yahoo`; shipped
   chain is `Tiingo → Stooq` — the Yahoo chart scrape was retired in
   FIX-17b (owner-ratified) as the stack's least reliable leg.
   Recommendation: keep it retired; revisit only if Tiingo+Stooq both
   prove insufficient.
2. **Live quote / profile**: charter lists Finnhub primary with FMP
   fallback. Shipped profile is FMP-primary because the free Finnhub
   `profile2` lacks description and employee count — the fields the
   profile card exists for. There is no live-quote consumer yet; when
   R1 adds one, Finnhub `quote` becomes its primary per the charter.

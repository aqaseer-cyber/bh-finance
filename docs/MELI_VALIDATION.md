# MELI live validation — FIX-11f, FIX-13f and FIX-14 acceptance gates

**Status: FIX-11f 8/9 PASS (interest-expense deviation open) ·
FIX-13f 10/11 PASS (placeholder-UA run pending) — verified 2026-07-11
against the owner's live export** `MELI_financial_model_20260711.xlsx`
(fix-15 build). The implementation environment
has no route to sec.gov, so these gates must be executed by the owner on a
connected machine with `SEC_EDGAR_USER_AGENT` set (`name email`). **Do not
tick a row without running it live.** Expected values are
**instance-verified evidence**, not guesses: the FIX-11 table was read from
the FY2025 10-K instance (accession `0001099590-26-000006`), the FIX-13
table from the FY2024 instance (`0001099590-25-000007`). An unexplained
deviation is an app defect; a deviation explained by a filing fact is
recorded as such.

```bat
set SEC_EDGAR_USER_AGENT=Your Name you@example.com
run_windows.bat MELI --model --no-cache
```

Then open `MELI_financial_model_<date>.xlsx` and work the two sections in
gate order (FIX-11 first — it is the merge gate for FIX-13).

## FIX-11f — income-statement basis ($mm)

| Line | FY2025 expected | FY2024 expected | Recorded | Verdict |
|---|---|---|---|---|
| Total Revenue (headline basis) | 28,893 | 20,777 | 28,893 / 20,777 | PASS |
| Cost of Goods & Services Sold | 16,035 | 11,200 | 16,035 / 11,200 | PASS |
| Gross Profit | 12,858 | 9,577 | 12,858 / 9,577 | PASS |
| Rev − COGS vs GP gap | ≤ 0.1% | ≤ 0.1% | 0.0% every column | PASS |
| Operating Income | 3,201 | 2,631 | 3,201 / 2,631 | PASS |
| Net Income | 1,997 | 1,911 | 1,997 / 1,911 | PASS |
| CFO | 12,116 | 7,918 | 12,116 / 7,918 | PASS |
| Capex (all four quarter cells populated + gap-fill footnote) | 1,343 | 860 | 1,343 / 860 · quarters 287/357/427/271 · gap-fill note present | PASS |
| Interest Expense (new candidate) | 160 | 165 | empty FY2018+ (winner `InterestExpenseDebt`, FY2015–17 only) | **FAIL — open** |

**Interest-expense diagnosis (2026-07-11, updated):** the owner's
companyfacts probe shows plain `us-gaap:InterestExpense` EXISTS (the
interim gap-filler already consumes its 10-Q spans) and **no** `meli:`
extension with "interest" in its name — the first extension hypothesis is
refuted. Remaining candidates: (a) `InterestExpense` carries interim
spans only and the 10-K's annual "Interest expense and other financial
charges" line rides an extension element named without "interest"
(`Financial…`); or (b) annual 10-K observations exist under
`InterestExpense` and the annual filter (10-K form + ~365-day span) drops
them — an app bug, reproducible offline. A second probe (extension
elements filtered to finance/expense/charge names + recent
`InterestExpense` observations with forms/spans) decides it; the fix
ships once pinned. Consequence today: FCFF falls back to the levered-FCF
proxy with the standing warning — conservative and labeled, not silent.

### Additional FIX-11 pass criteria

- [x] `=fcf` LTM present with basis `"ltm"` once capex quarters fill —
      no mixed-basis suppression note for Free Cash Flow (LTM 11,818 =
      CFO 13,160 − capex 1,342; verified 2026-07-11).
- [x] the SBC row carries the dead-series warning **or** the analyst
      override — never a silent blank column: owner confirmed the Track-B
      dead-series warning on the valuation page (2026-07-11); the export's
      blank SBC column is the expected symptom of MELI's dead
      `ShareBasedCompensation` series.
- [x] FY2015–FY2020 revenue unchanged (pre-split years were already on
      the headline basis) — FY2020 = 3,974, matches the as-filed
      headline figure (verified 2026-07-11).
- [x] % change rows re-verified after the basis switch (FY2021 YoY is
      headline-on-headline): +77.9% = 7,069 / 3,974 − 1 exactly
      (verified 2026-07-11).

## FIX-13f — segments, streams, and as-filed statement sheets

FY2024-instance expected values; record the FY2025-instance analogues
alongside (the same run fetches both filings).

| # | Check | Expected | Pass? |
|---|---|---|---|
| 1 | Segments sheet: revenue-stream axis | Commerce 12,159 · Fintech 8,618 (FY2024, $mm) | PASS — exact |
| 2 | Revenue-stream tie row FY2024 | 0.0% (12,159 + 8,618 = 20,777) | PASS — Σ 20,777, gap 0.0% |
| 3 | Country axis after dedupe | Brazil 11,406 · Mexico 4,664 · Argentina 3,818 · Other Countries 889 (one line, not two) | PASS — exact, one line |
| 4 | Country tie row FY2024 | 0.0% (was +4.3% pre-13c) | PASS — 0.0% |
| 5 | Country×Stream cross spot-check | Brazil = 7,038 Commerce + 4,368 Fintech | PASS by sum (7,038+4,368 = 11,406 = filed Brazil; cross components aggregate internally, not rendered) |
| 6 | Status line | "member aliases merged: Other Countries (2 qnames)"; "100 facts at 3+ segment axes ignored" | PASS — aliases line verbatim; ignored-facts count is 340 (live run spans 11 instances, FY2016–FY2025 + 10-Q, vs the two-instance spec-era count) |
| 7 | Income Statement sheet | top-line Revenues FY2024 = 20,777; NI = 1,911; line order matches the filing's R5 rendering (spot-check first 10 rows) | PASS — "Net revenues and financial income" 20,777; NI 1,911; as-filed order |
| 8 | Balance Sheet sheet | Assets = Liabilities + Equity, every year | PASS — FY2024 25,196 = 20,845 + 4,351; FY2025 42,667 = 35,919 + 6,748 |
| 9 | Cash Flow sheet | CFO FY2024 = 7,918 | PASS — 7,918 (FY2025 12,116) |
| 10 | KPI footnote | present on the Income Statement sheet | PASS — verbatim |
| 11 | Placeholder-UA run (env var unset) | segments status carries the SEC_EDGAR_USER_AGENT instruction verbatim | INCONCLUSIVE (2026-07-11): env var unset but the Settings-saved UA filled the gap (FIX-12e working as designed) — segments fetched normally. A true test needs the Settings UA field cleared too; offline CI (`test_ua_gate.py`) covers the gate mechanism. |

Row 11 is a second run with the env var **unset**: the segments footnote on
the Model sheet (and `statements_note`) must read
"SEC Archives blocks the placeholder User-Agent (HTTP 403). Set
SEC_EDGAR_USER_AGENT to 'name email' and retry." — not "unreachable".

## FIX-14 anchors — growth discipline (live run)

**Status: COMPLETE 2026-07-11 — all criteria recorded (MELI + PYPL + GSL edge case)** (UA already set from the
gates above). One growth name with a live consensus (MELI) and one
low-capex-intensity control (PYPL):

```bat
run_windows.bat MELI --value dcf --rating Hold --no-cache
run_windows.bat PYPL --value dcf --rating Hold --no-cache
```

Record the anchor readout line (printed by the CLI before the case seeds;
identical to the dialog's readout) **verbatim**:

| Name | Anchor readout (verbatim) |
|---|---|
| MELI | anchors — consensus +26.6% (Yahoo, n=24, Rung 4) · 5y rev CAGR +48.7% · ROIC×RR +6.4% → Base = fundamental (binding) · analyst range +17.4%…+41.0% (dialog screenshot, 2026-07-11) |
| PYPL | anchors — consensus +4.3% (Yahoo, n=42, Rung 4) · 5y rev CAGR +9.1% · ROIC×RR +0.0% → Base = fundamental (binding) · analyst range +1.1%…+10.6% (dialog screenshot, 2026-07-11; seeds Bear 0.0 / Base 0.0 / Bull 4.3) |

Pass criteria:

- [x] MELI **Base seed ≤ consensus** — and strictly below the old `g_avg`
      prefill: seeds Bear 3.2 / Base 6.4 / Bull 26.6; old prefill would
      have put Base at the 26.6% consensus (2026-07-11).
- [x] The **binding anchor is named** in the readout: `Base = fundamental
      (binding)`.
- [x] MELI **capex deviation flag state recorded either way**:
      `base — as-reported $10.8B · capex-normalized $10.9B (5y median
      intensity 4.2%)` — **no** peak/trough flag (intensities inside the
      ±30% band).
- [x] Verdict shows the **growth–reinvestment note only if the threshold
      genuinely trips**: owner reports SILENT (2026-07-11) — and silent is
      the mathematically required outcome here: MELI's Base seeded from the
      fundamental anchor, so implied RR = g₀/median ROIC = median RR
      exactly (×1.0 < 1.25). The note firing would have been the bug.
- [x] MELI geography axis (US-only partial disclosure): the Segments tie
      renders `partial disclosure axis — tie suppressed (1 member(s), 0%
      of consolidated)` on both the Model and Segments sheets — **no
      −99.8% red row** (US-only 35 / 51 $mm; export 2026-07-11).
- [x] PYPL control: low capex intensity ⇒ capex-normalized base ≈
      as-reported base and no peak/trough flag unless genuinely deviant:
      `base — as-reported $5.9B · capex-normalized $5.6B (5y median
      intensity 2.6%)`, no flag (2026-07-11). Note: PYPL's fundamental
      anchor is 0.0% — the per-year reinvestment rate (capex + ΔNWC − D&A)
      clamps at the zero floor for a buyback-heavy low-capex name, so the
      ladder's Base seed is the conservative floor; the readout says so
      and every value stays editable (the analyst overrides, the
      automation referees).

Standing analytical caveat (also in the README): standard-track FCFF on an
embedded-finance name carries the credit book in CFO; anchors discipline
the seed, they do not fix a track choice — SOTP with credit de-consolidated
remains the analyst's call.

### Observed FIX-14 edge case (GSL, 2026-07-11 — design note, not a bug)

With a **negative consensus** (GSL: −6.0%, n=3), the ladder seeds
Base = consensus (binding) = −6.0% while Bear = max(0, ½ × Base) floors
at **0.0% — above Base**, and Bull = consensus = −6.0% ties Base. The
per-spec rules were designed for growth names; for shrinking names the
seed ordering inverts and `build_valuation`'s existing "Bear FV exceeds
Bull FV" warning fires if computed as-is. Every seed stays editable — the
analyst sets the real cases. If the owner wants the floor changed
(e.g. Bear = min(Base, max(0, ½ × Base))), that is a one-line spec
amendment for a future FIX.

## Record

Fill after each live run (append rows; keep failures with their diagnosis):

| Date | Runner | App commit | Gate | Result |
|---|---|---|---|---|
| 2026-07-11 | owner (export verified by Claude) | fix-15 @ ddf6ddd | FIX-11f | 8/9 PASS + criteria 3/4; interest-expense row FAIL (suspected meli: extension tag — open) |
| 2026-07-11 | owner (export verified by Claude) | fix-15 @ ddf6ddd | FIX-13f | 10/11 PASS (row 6 count 340 vs 100, explained by 11-instance history); row 11 placeholder-UA run pending |
| 2026-07-11 | owner (dialog + export) | fix-15 @ ddf6ddd | FIX-14 | anchors readout + capex line + FIX-14d suppression recorded; PYPL control PASS; verdict-note state pending |

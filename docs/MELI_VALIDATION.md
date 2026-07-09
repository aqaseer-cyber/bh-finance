# MELI live validation — FIX-11f and FIX-13f acceptance gates

**Status: PENDING — live runs required.** The implementation environment
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
| Total Revenue (headline basis) | 28,893 | 20,777 | _pending_ | |
| Cost of Goods & Services Sold | 16,035 | 11,200 | _pending_ | |
| Gross Profit | 12,858 | 9,577 | _pending_ | |
| Rev − COGS vs GP gap | ≤ 0.1% | ≤ 0.1% | _pending_ | |
| Operating Income | 3,201 | 2,631 | _pending_ | |
| Net Income | 1,997 | 1,911 | _pending_ | |
| CFO | 12,116 | 7,918 | _pending_ | |
| Capex (all four quarter cells populated + gap-fill footnote) | 1,343 | 860 | _pending_ | |
| Interest Expense (new candidate) | 160 | 165 | _pending_ | |

### Additional FIX-11 pass criteria

- [ ] `=fcf` LTM present with basis `"ltm"` once capex quarters fill —
      no mixed-basis suppression note for Free Cash Flow;
- [ ] the SBC row carries the dead-series warning **or** the analyst
      override — never a silent blank column;
- [ ] FY2015–FY2020 revenue unchanged (pre-split years were already on
      the headline basis);
- [ ] % change rows re-verified after the basis switch (FY2021 YoY is
      headline-on-headline).

## FIX-13f — segments, streams, and as-filed statement sheets

FY2024-instance expected values; record the FY2025-instance analogues
alongside (the same run fetches both filings).

| # | Check | Expected | Pass? |
|---|---|---|---|
| 1 | Segments sheet: revenue-stream axis | Commerce 12,159 · Fintech 8,618 (FY2024, $mm) | |
| 2 | Revenue-stream tie row FY2024 | 0.0% (12,159 + 8,618 = 20,777) | |
| 3 | Country axis after dedupe | Brazil 11,406 · Mexico 4,664 · Argentina 3,818 · Other Countries 889 (one line, not two) | |
| 4 | Country tie row FY2024 | 0.0% (was +4.3% pre-13c) | |
| 5 | Country×Stream cross spot-check | Brazil = 7,038 Commerce + 4,368 Fintech | |
| 6 | Status line | "member aliases merged: Other Countries (2 qnames)"; "100 facts at 3+ segment axes ignored" | |
| 7 | Income Statement sheet | top-line Revenues FY2024 = 20,777; NI = 1,911; line order matches the filing's R5 rendering (spot-check first 10 rows) | |
| 8 | Balance Sheet sheet | Assets = Liabilities + Equity, every year | |
| 9 | Cash Flow sheet | CFO FY2024 = 7,918 | |
| 10 | KPI footnote | present on the Income Statement sheet | |
| 11 | Placeholder-UA run (env var unset) | segments status carries the SEC_EDGAR_USER_AGENT instruction verbatim | |

Row 11 is a second run with the env var **unset**: the segments footnote on
the Model sheet (and `statements_note`) must read
"SEC Archives blocks the placeholder User-Agent (HTTP 403). Set
SEC_EDGAR_USER_AGENT to 'name email' and retry." — not "unreachable".

## Record

Fill after each live run (append rows; keep failures with their diagnosis):

| Date | Runner | App commit | Gate | Result |
|---|---|---|---|---|
| | | | FIX-11f | |
| | | | FIX-13f | |

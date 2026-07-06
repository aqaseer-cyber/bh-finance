# FIX-11f — MELI live re-validation

**Status: PENDING — live run required.** The implementation environment
has no route to sec.gov. Run on a network-connected machine with
`SEC_EDGAR_USER_AGENT` set (`name email`), then fill the Recorded column:

```bat
set SEC_EDGAR_USER_AGENT=Your Name you@example.com
run_windows.bat MELI --model --no-cache
```

Expected values are **instance-verified evidence** (FY2025 10-K, accession
`0001099590-26-000006`), not guesses. An unexplained deviation is a
defect; a deviation explained by a filing fact is recorded as such.

## Income-statement table ($mm)

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

## Additional pass criteria

- [ ] `=fcf` LTM present with basis `"ltm"` once capex quarters fill —
      no mixed-basis suppression note for Free Cash Flow;
- [ ] the SBC row carries the dead-series warning **or** the analyst
      override — never a silent blank column;
- [ ] FY2015–FY2020 revenue unchanged (pre-split years were already on
      the headline basis);
- [ ] % change rows re-verified after the basis switch (FY2021 YoY is
      headline-on-headline);
- [ ] if FIX-10 has merged: the segment section renders with tie-row gaps
      inside ±2% and any breaks footnoted — extend
      `docs/SEGMENT_VALIDATION.md`'s MELI row from the same run.

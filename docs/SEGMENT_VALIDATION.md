# FIX-10g — Live segment-history validation

**Status: PENDING — live run required.** The FIX-10 implementation
environment has no route to sec.gov, and synthetic fixtures cannot
represent the real axis zoo. This protocol must be executed on a
network-connected machine before the `fix-10-segment-history` branch
merges to `main`. A row that can't be explained is a defect, not a caveat.

## Protocol

For each of **MELI** (two-axis + hierarchy + known reorg history),
**PYPL**, **AXON**, **GSL** (small-cap coverage check):

```bat
run_windows.bat <TICKER> --model
:: or: python -m forensic_viz <TICKER> --model
```

Then open the exported model and record below:

1. **FY columns populated per axis** (count) and the coverage footnote
   line verbatim (`Segment coverage: dimensional facts found in n/m …`);
2. **tie-row gap per FY** — post-recast years must sit within ±2%
   (`segment_tie_tol`); any year outside gets an explanation (break
   footnote present? incomplete cross table?);
3. **every `breaks` footnote entry**, with a one-line judgment (real
   reorg vs tagging noise) — MELI is expected to produce at least one;
4. **first-pull wall time and cache growth** (target: < 60 s, < 150 MB
   per name — the instance cache TTL is one year, so this cost is paid
   once);
5. **any skipped/unmatched instances**, verbatim from the status
   footnote.

## Records

### MELI — PENDING

| Item | Result |
|---|---|
| FY columns per axis / coverage line | _pending live run_ |
| Tie-row gaps per FY (±2%?) | _pending_ |
| Breaks + judgment | _pending (≥1 expected)_ |
| Wall time / cache growth | _pending_ |
| Skipped / unmatched | _pending_ |

### PYPL — PENDING

| Item | Result |
|---|---|
| FY columns per axis / coverage line | _pending live run_ |
| Tie-row gaps per FY (±2%?) | _pending_ |
| Breaks + judgment | _pending_ |
| Wall time / cache growth | _pending_ |
| Skipped / unmatched | _pending_ |

### AXON — PENDING

| Item | Result |
|---|---|
| FY columns per axis / coverage line | _pending live run_ |
| Tie-row gaps per FY (±2%?) | _pending_ |
| Breaks + judgment | _pending_ |
| Wall time / cache growth | _pending_ |
| Skipped / unmatched | _pending_ |

### GSL — PENDING

| Item | Result |
|---|---|
| FY columns per axis / coverage line | _pending live run_ |
| Tie-row gaps per FY (±2%?) | _pending_ |
| Breaks + judgment | _pending_ |
| Wall time / cache growth | _pending_ |
| Skipped / unmatched | _pending_ |

# FIX-10g — Live segment-history validation

**Status: MELI / PYPL / AXON verified 2026-07-11 from the owner's live
exports (fix-15 build) — every out-of-band tie gap explained; GSL and the
wall-time/cache items remain owner-run.** The FIX-10 implementation
environment has no route to sec.gov, and synthetic fixtures cannot
represent the real axis zoo. A row that can't be explained is a defect,
not a caveat.

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

### MELI — verified 2026-07-11 (export `MELI_financial_model_20260711.xlsx`)

| Item | Result |
|---|---|
| FY columns per axis / coverage line | 10y history; "Segment coverage: dimensional facts found in 11/11 instances (10-K 0001562762-17-000024 (FY2016) … 10-Q 0001099590-26-000017)" |
| Tie-row gaps per FY (±2%?) | business segments 0.0% (FY2024); revenue stream 0.0%; product/service +100% — EXPLAINED: generational overlap (Service/Services, Product/Product Sales across the FY2020→FY2022 recasts, all footnoted); geography — tie suppressed per FIX-14d (US-only partial disclosure, 1 member, 0% of consolidated) |
| Breaks + judgment | Venezuela discontinuous-series flag (real: deconsolidation-era reporting); product/service recasts at FY2019/FY2020/FY2021 boundaries (real reorgs: Marketplace/Nonmarketplace → Commerce/Fintech → Credit/Product/Services); ≥1 expected — satisfied |
| Wall time / cache growth | cache total 254 MB across MELI+PYPL+AXON+GSL, ≤4–5 MB per instance file — comfortably under the 150 MB/name target (owner, 2026-07-11) |
| Skipped / unmatched | none skipped; "340 facts at 3+ segment axes ignored (beyond the 2-axis model)" |

### PYPL — verified 2026-07-11 (export `PYPL_financial_model_20260711.xlsx`)

| Item | Result |
|---|---|
| FY columns per axis / coverage line | business segments 6 FY columns (recent two-segment disclosure, FY2022+), product/service 11–13, geography 10; "dimensional facts in 11/11 instances" |
| Tie-row gaps per FY (±2%?) | business segments 0.0% all years; product/service 0.0% except FY2016 +9.2% / FY2017 +9.9% / FY2018 −3.5% / FY2019 −9.4% — EXPLAINED: pre-ASC-606-era member generations at the footnoted recast boundaries; geography 0.0% except FY2021 +46.0% / FY2022 +42.6% — EXPLAINED: two overlapping partitions filed on one axis (US/Non-US AND US/UK/Other; Non-US 11,659 = UK 2,340 + Other 9,319 exactly — parent + children share the axis, the positive gap is the designed double-count flag) |
| Breaks + judgment | "8 membership break(s)" — product/service recasts (×6, tag-generation churn: tagging noise) and geography recasts at FY2021/FY2022 (real disclosure change: UK split out) |
| Wall time / cache growth | cache total 254 MB across MELI+PYPL+AXON+GSL, ≤4–5 MB per instance file — comfortably under the 150 MB/name target (owner, 2026-07-11) |
| Skipped / unmatched | none skipped (11/11) |

### AXON — verified 2026-07-11 (export `AXON_financial_model_20260711.xlsx`)

| Item | Result |
|---|---|
| FY columns per axis / coverage line | business segments 13, product/service 12, geography 13 columns; "dimensional facts in 11/11 instances" |
| Tie-row gaps per FY (±2%?) | geography 0.0% every year; business segments −93.6%…+116.8% — EXPLAINED: segment-name generations coexist per span (FY2023 carries Connected Devices 964.0 + Software And Sensors 596.7 + Software And Services 596.7 + TASER 613.5 + Taser 612.6; Connected Devices + Software And Services = 1,560.7 ≈ consolidated — the rest are prior-generation names and case variants; renames are never auto-spliced per FIX-10c doctrine); product/service +100%…+250% — EXPLAINED: the full disaggregation tree shares one axis (Product/Service parents + TASER Devices/Axon Evidence/Cartridges/… children + label variants) |
| Breaks + judgment | many recasts footnoted across business/product/geography — TASER→Connected Devices era renames (real reorg) + label/case churn (tagging noise). **Analyst action available:** `[segment_aliases.AXON]` merging the case/label variants (`Taser`→`TASER`, `Software And Sensors`→`Software And Services`, `Axon Body And Camera Accessories`→`Axon Body Cameras And Accessories`, `Taser Devices Professional`→`TASER Devices Professional`) collapses the noise; splicing TASER→Connected Devices across the rename stays a judgment call |
| Wall time / cache growth | cache total 254 MB across MELI+PYPL+AXON+GSL, ≤4–5 MB per instance file — comfortably under the 150 MB/name target (owner, 2026-07-11) |
| Skipped / unmatched | none skipped (11/11); status line already auto-merged Evidence Com And Video / Software And Sensors / Softwareand Sensors / Taser Weapons qname pairs (2 qnames each) |

### GSL — verified 2026-07-11 (export `GSL_financial_model_20260711.xlsx`)

**Coverage-check outcome: the honesty clause, working.** GSL is a foreign
private issuer filing **20-F / 6-K**, not 10-K/10-Q: the 10-K-family
instance enumerator finds nothing, so the export carries NO segments
section and no as-filed statement sheets, with the honest footnote
"Segments: no dimensional segment data in this workbook — filing XBRL
instances unreachable (offline, or an unexpected EDGAR layout for this
filer)." — blanks stated, never faked. Annual fundamentals populate fully
(FY2015–FY2025 from the US-GAAP 20-F facts); the interim spine is
semi-annual (6-K half-years, rendered as Q2/Q4 columns).
**20-F/40-F support shipped 2026-07-11 (owner-ratified):** the annual
enumerator now collects the 20-F family, so segment instances and the
as-filed statement sheets light up for FPIs — a GSL re-run is available
to verify live (GSL may still genuinely report one segment).

| Item | Result |
|---|---|
| FY columns per axis / coverage line | _pending live run_ |
| Tie-row gaps per FY (±2%?) | _pending_ |
| Breaks + judgment | _pending_ |
| Wall time / cache growth | _pending_ |
| Skipped / unmatched | _pending_ |

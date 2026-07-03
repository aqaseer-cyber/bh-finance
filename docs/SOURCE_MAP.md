# Workbook source map — `forensic_valuation_model_v3.xlsx`

Every blue input cell in the shell, with its data source. **AUTO** cells are
written by the app's `Fill workbook…` button / `--xlsx` flag; **ANALYST**
cells are judgment or non-XBRL disclosures — the suggested source follows the
master prompt's tool ladder (§1: Fiscal.ai/IBKR → EDGAR full-text / company
IR → web; analyst memory never a valuation input).

## Control

| Cell | Input | Source |
|---|---|---|
| B7/B8 | Ticker / company | AUTO — EDGAR entity |
| B9 | Sector / Logic Track | AUTO — app track selector (override in the GUI; economic engine beats vendor code) |
| B10 | Analysis date | AUTO |
| B20 | Institutional rating | ANALYST — §5.3 judgment, entered in the valuation dialog; app checks coherence only |
| B47 | Terminal-g cap | Template constant (3.5%) |
| B50 | Reported diluted EPS | AUTO — `EarningsPerShareDiluted` XBRL (the §1.2a EPS tie) |
| B53 | Third-party market cap | AUTO (computed P0 × diluted) — **verify against two third-party sources** (IBKR snapshot, exchange site) per §1.2b before trusting the tie |
| B60 | D&A | AUTO — `DepreciationDepletionAndAmortization` |

## Phase1_Anchor

| Cell | Input | Source |
|---|---|---|
| B5–B10 | P0, basic/diluted shares, 52-wk range | AUTO — prices (Stooq/Yahoo) + XBRL share counts. House §8: P0 max 5 trading days stale |
| B14/B15 | Total debt / cash | AUTO — XBRL (§2c simplification: converts & finance leases not split out — check the debt footnote) |
| B17/B18 | Minority interest / preferred | AUTO — `MinorityInterest` / `PreferredStockValue` (0 when untagged; confirm in the equity statement) |
| B19 | Non-operating investments | ANALYST — 10-K investments footnote (equity stakes, at fair value) |
| B22/B23 | 10-K / 10-Q filing dates | AUTO — EDGAR submissions API |
| B24 | Earnings transcript date | ANALYST — company IR page |
| A27 | Bull thesis | ANALYST — §2.4, entered in Analyst inputs… |

## Phase2_UnitEcon

| Cell | Input | Source |
|---|---|---|
| B5–B7 | Segment revenue | ANALYST — 10-K segment footnote (ASC 280). Dimensional XBRL; companyfacts returns consolidated only. (The frames API or Fiscal.ai can automate this later) |
| B11 | Total revenue growth | AUTO |
| B12–B15 | Organic/inorganic, price/volume | ANALYST — MD&A + earnings release; deal 8-Ks for acquired revenue (the CELH/ADBE lesson) |
| B19/B20 | Avg inventory / COGS | AUTO |
| B23/B24 | LTV / CAC | ANALYST — company KPI disclosures / investor day; not a GAAP concept |
| B27 | Net interest income | AUTO — `InterestIncomeExpenseNet` |
| B28 | Average earning assets | ANALYST — 10-K average-balance-sheet table (app's NIM proxy uses avg **total** assets; the workbook wants the real base) |
| B31–B33 | Losses+LAE / UW expense / NEP | AUTO where tagged (`PolicyholderBenefitsAndClaimsIncurredNet`, `OtherUnderwritingExpense`, `PremiumsEarnedNet`) |
| B36–B39 | NOI / same-store / FFO / AFFO | ANALYST — REIT supplemental package (non-GAAP, never in XBRL) |
| A42 | Terminal risk | ANALYST — §2.3, cite Item 1A; entered in Analyst inputs… |
| B47–B50 | Concentrations | ANALYST — 10-K Item 1/1A + concentration-risk footnote (≥10% house flag) |

## Phase3_Forensic

| Cell | Input | Source |
|---|---|---|
| B4–B6 | Adjusted vs GAAP | AUTO once you enter adjusted NI (fluff filter §3.1) — the adjusted figure itself comes from the **earnings-release non-GAAP reconciliation** |
| B11–C13 | Top-3 add-backs + verdicts | ANALYST — same reconciliation table; recurring/one-off is a judgment call |
| B16–B21 | R&D life n + R&D t..t−4 | AUTO (n = house ASSUMPTION 5y until the house file is attached) |
| B27–B31 | NI, CFO, CFI, assets begin/end | AUTO |
| B37–B39 | Piotroski / Altman / CET1 | AUTO — computed & regulatory tags |

## WACC_Build

| Cell | Input | Source |
|---|---|---|
| B4 | r_f | AUTO — FRED DGS10 live (refresh every session, master §2) |
| B5 | ERP | AUTO — house ASSUMPTION 4.6%; **Damodaran's monthly implied ERP** is the named source to refresh it |
| B6 | β | AUTO — Blume-adjusted regression vs S&P 500. Master prefers bottom-up relevered: get sector unlevered β from **Damodaran's industry tables**, relever, and overwrite |
| B10/B11 | r_d / τ | AUTO — interest/avg debt, effective tax |
| B25 | Unlevered β | AUTO — computed from the regression β and D/E |

## FCFF_DCF / Val_Fin_RI / Val_REIT_NAV

| Cell | Input | Source |
|---|---|---|
| FCFF B5/C5 | Base FCFF Track A/B | AUTO — as-reported FCFF / ex-SBC (house §2b) |
| FCFF B6–C9 | g0 / terminal g per track | AUTO from the valuation dialog (A=Bear, B=Base) — **your growth assumptions** |
| FCFF B42–C43 | *Normalized* OCF/capex | ANALYST — §4.0 normalization (through-cycle capex, never one quarter); app pre-fills as-reported as the starting point |
| RI B7/B8/B28 | Payout, BV/sh, D1 | AUTO — dividends/NI, equity/shares, dividends/share |
| RI B12–F16 | Track A/B ROE paths | ANALYST — through-cycle judgment off the credit cycle; app pre-fills the dialog ROEs |
| REIT B5–B10, B16–C17 | NOI, cap rates, AFFO, yields | ANALYST — supplemental + broker cap-rate surveys (Track B +50–100 bps, §4.C); app fills debt/shares |

## Phase5_Verdict

| Cell | Input | Source |
|---|---|---|
| B21/B22 | Risk channel + shock | AUTO — track-mapped (§5.1); Standard −5% FCFF₁ |
| B33 | Institutional rating | ANALYST — coherence-gated by the app (Control!B67: MoS < −15% + Hold/Buy → CHECK unless §4.D optionality named) |
| A35 | Rating sentence | AUTO-composed from rating + terminal risk + optionality — **edit to your voice** |
| B42–F42 | g0 scenario grid | AUTO — centered on your Base g0 |

## Not yet in the app (from the master prompt)

- **Sizing (§5.6)** — needs the house R2 bucket table (attach `SKILL_Sizing` + house file)
- **Verdict ledger (§5.7)** — the SQLite Layer-C port; seed from `verdict_ledger_seed.json`
- **IBKR live P0/beta** — the app uses free sources; wire IBKR Client Portal for the §1 rung-2 ladder

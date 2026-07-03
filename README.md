# Forensic Stock Viz

A Windows desktop tool for forensic financial analysts: type a US-listed
ticker and get a single dashboard showing the company's performance over the
past five years — price, growth, profitability, **earnings quality**, and the
classic forensic red flags — built entirely from primary sources (as-filed SEC
XBRL) with a CSV audit trail.

![Demo dashboard](docs/demo_dashboard.png)

## Quick start (Windows)

1. Install Python 3.10+ from <https://www.python.org/downloads/>
   (tick **"Add python.exe to PATH"** during setup).
2. Double-click **`run_windows.bat`**. The first run creates a local
   virtual environment and installs the two dependencies (`requests`,
   `matplotlib`); later runs start instantly.
3. Type a ticker (e.g. `AAPL`) and press **Analyze**. Use **Save PNG…** /
   **Export CSV…** for the deliverables, or **Offline demo** to verify the
   install without touching the network.

Command line (same launcher):

```bat
run_windows.bat AAPL --csv       :: writes AAPL_5y_dashboard_<date>.png + CSVs
run_windows.bat --demo -o demo.png
run_windows.bat MSFT --no-cache  :: bypass the local cache
```

To produce a standalone `ForensicStockViz.exe` (no Python on the target PC),
run **`build_exe_windows.bat`** once; the binary lands in `dist\`.

## What the dashboard shows

| Panel | Forensic reading |
|---|---|
| **KPI row** | Last close + 5y return, latest revenue + CAGR, net margin + 5y change, FCF + CAGR, diluted shares (red = dilution) |
| **Price / drawdown** | 5y split-adjusted daily close; % below rolling peak with the max-drawdown point marked |
| **Revenue** | Annual as-filed revenue, labelled per year, 5y CAGR |
| **Margins** | Gross / operating / net margin trend — divergence between gross and net is where to start reading footnotes |
| **Earnings quality** | Net income vs operating cash flow vs FCF. NI persistently ahead of CFO = accrual build-up |
| **Accruals ratio (Sloan proxy)** | (NI − CFO) / average total assets, diverging bars; the dashed **+10% line** is the aggressive-accruals threshold |
| **Diluted shares** | Dilution vs buyback over the window |
| **Balance sheet** | Total borrowings vs cash & equivalents |

The **CSV export** is the table-view twin of the chart: every plotted value,
plus fiscal year-end dates, plus the exact XBRL tag used for each concept —
the audit trail for tying numbers back to the filings.

## Data sources & methodology

- **Fundamentals** — SEC EDGAR XBRL `companyfacts` API. Annual (10-K family)
  values only; a later-filed amendment (10-K/A) supersedes the original.
  Tag selection is **coverage- and recency-scored**: when a company migrates
  tags (e.g. `Revenues` → `RevenueFromContractWithCustomerExcludingAssessedTax`
  after ASC 606), the tag covering the recent fiscal years wins, so the series
  can't silently end years ago. The chosen tags are printed on the dashboard
  footer and in the CSV.
- **Prices** — Stooq daily CSV (keyless), falling back to the Yahoo Finance
  chart API. Split-adjusted closes. If both fail, the dashboard still renders
  from fundamentals alone.
- **Derived** — FCF = CFO − capex. Gross profit falls back to
  revenue − cost of revenue when `GrossProfit` isn't tagged. Total debt =
  long-term debt (current + noncurrent) + short-term borrowings, falling back
  to `LongTermDebt`. Accruals ratio uses average total assets.

The SEC requires an identifying User-Agent; the default is set in
`forensic_viz/config.py` and can be overridden with the
`SEC_EDGAR_USER_AGENT` environment variable.

Cached responses live in `%LOCALAPPDATA%\ForensicStockViz\cache`
(fundamentals 24 h, prices 6 h) so re-runs are instant and polite to the APIs.

## Limitations (v1)

- **US-GAAP filers only.** IFRS-only foreign private issuers are rejected
  with a clear error rather than mis-parsed.
- Banks/insurers/REITs render, but revenue-family tags vary by sector; check
  the footer tags before trusting a sector outlier (wrong-track selection is
  the known failure mode — see `ARCHITECTURE.md` Layer B in the project docs).
- Prices come from free unofficial endpoints; they are for context, not
  execution.
- This tool automates the deterministic layer only. It deliberately does
  **not** attempt judgment calls (adjustment burden, one-time items, organic
  vs. acquired growth) — those stay with the analyst.

## Development

```bash
pip install -r requirements.txt pytest
python -m pytest tests/          # 25 tests: parsing, metrics, prices, rendering
python -m forensic_viz --demo    # offline render
```

Layout: `forensic_viz/edgar.py` (XBRL pull + tag selection),
`prices.py` (Stooq/Yahoo), `metrics.py` (derivations), `dashboard.py`
(renderer), `gui.py` (Tkinter app), `pipeline.py` (orchestration),
`export.py` (CSV), `demo_data.py` (synthetic red-flag company).

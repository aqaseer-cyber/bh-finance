"""Financial-model export: quarterly consolidation + the one-sheet workbook.

Extends the TESTCO fixture with FY2026 interim filings:
- revenue: discrete 3-month values for Q1'26 and Q2'26, plus fiscal-YTD
  spans and the year-ago comparative YTD (for LTM);
- cfo: YTD-ONLY spans (like a real 10-Q cash-flow statement), so Q2 must
  be derived by differencing;
- instants (cash, total assets): balances at both quarter ends.
"""
import datetime as dt

import pytest
from openpyxl import load_workbook

from conftest import CASH, CFO, REVENUE, build_testco_companyfacts
from forensic_viz.edgar import parse_companyfacts, parse_quarterly_facts
from forensic_viz.metrics import DashboardData, apply_track, build_fundamental_metrics
from forensic_viz.model_export import build_model_rows, export_financial_model

# FY2026 interim values (fixture FYs end 2025-12-31)
Q1_REV, Q2_REV = 520e6, 540e6
Q1_CFO, H1_CFO = 150e6, 310e6
# year-ago comparatives as filed in the FY2026 10-Qs
H1_REV_PRIOR = 470e6
H1_CFO_PRIOR = 280e6
Q1_CASH, Q2_CASH = 500e6, 520e6


def _dur(start, end, val, filed):
    return {"start": start, "end": end, "val": val, "form": "10-Q",
            "fp": "Q", "filed": filed}


def _inst(end, val, filed):
    return {"end": end, "val": val, "form": "10-Q", "fp": "Q", "filed": filed}


def _facts_with_quarters() -> dict:
    facts = build_testco_companyfacts()
    gaap = facts["facts"]["us-gaap"]
    rev = gaap["RevenueFromContractWithCustomerExcludingAssessedTax"]["units"]["USD"]
    rev += [
        _dur("2026-01-01", "2026-03-31", Q1_REV, "2026-05-05"),   # Q1 (3M == YTD)
        _dur("2026-04-01", "2026-06-30", Q2_REV, "2026-08-05"),   # Q2 discrete
        _dur("2026-01-01", "2026-06-30", Q1_REV + Q2_REV, "2026-08-05"),  # H1 YTD
        _dur("2025-01-01", "2025-06-30", H1_REV_PRIOR, "2026-08-05"),     # comparative
    ]
    cfo = gaap["NetCashProvidedByUsedInOperatingActivities"]["units"]["USD"]
    cfo += [  # YTD-only, like a real 10-Q cash-flow statement
        _dur("2026-01-01", "2026-03-31", Q1_CFO, "2026-05-05"),
        _dur("2026-01-01", "2026-06-30", H1_CFO, "2026-08-05"),
        _dur("2025-01-01", "2025-06-30", H1_CFO_PRIOR, "2026-08-05"),
    ]
    gaap["CashAndCashEquivalentsAtCarryingValue"]["units"]["USD"] += [
        _inst("2026-03-31", Q1_CASH, "2026-05-05"),
        _inst("2026-06-30", Q2_CASH, "2026-08-05"),
    ]
    gaap["Assets"]["units"]["USD"] += [
        _inst("2026-03-31", 4.0e9, "2026-05-05"),
        _inst("2026-06-30", 4.1e9, "2026-08-05"),
    ]
    return facts


def _data(facts) -> DashboardData:
    d = DashboardData(ticker="TESTCO", company="TESTCO Inc", subtitle="",
                      generated=dt.date(2026, 8, 10))
    d.sic_code = "3571"
    apply_track(d, "auto")
    build_fundamental_metrics(parse_companyfacts(facts, "TESTCO"), d)
    return d


def test_quarterly_consolidation_discrete_ytd_and_ltm():
    facts = _facts_with_quarters()
    annual = parse_companyfacts(facts, "TESTCO")
    qdata = parse_quarterly_facts(facts, annual)
    rows, fy_ends, q_ends = build_model_rows(annual, qdata)

    assert fy_ends[-1] == dt.date(2025, 12, 31)
    assert q_ends == [dt.date(2026, 3, 31), dt.date(2026, 6, 30)]

    ann, qs, ltm = rows["revenue"]
    assert qs == [pytest.approx(Q1_REV), pytest.approx(Q2_REV)]
    assert ltm == pytest.approx(REVENUE[2025] + (Q1_REV + Q2_REV) - H1_REV_PRIOR)

    # cfo has no discrete Q2 span: derived by YTD differencing
    _, qs_cfo, ltm_cfo = rows["cfo"]
    assert qs_cfo == [pytest.approx(Q1_CFO), pytest.approx(H1_CFO - Q1_CFO)]
    assert ltm_cfo == pytest.approx(CFO[2025] + H1_CFO - H1_CFO_PRIOR)

    # balance sheet: instants at quarter ends; LTM = latest balance
    _, qs_cash, ltm_cash = rows["cash"]
    assert qs_cash == [pytest.approx(Q1_CASH), pytest.approx(Q2_CASH)]
    assert ltm_cash == pytest.approx(Q2_CASH)

    # derived FCF row exists and follows CFO − capex (no 2026 capex filed)
    _, qs_fcf, _ = rows["=fcf"]
    assert qs_fcf == [None, None]


def test_no_quarters_ltm_equals_last_fy():
    facts = build_testco_companyfacts()  # 2025 10-Q noise sits inside FY2025
    annual = parse_companyfacts(facts, "TESTCO")
    rows, _, q_ends = build_model_rows(annual, parse_quarterly_facts(facts, annual))
    assert q_ends == []
    assert rows["revenue"][2] == pytest.approx(REVENUE[2025])


def test_export_writes_template_layout(tmp_path):
    facts = _facts_with_quarters()
    d = _data(facts)
    out = tmp_path / "model.xlsx"
    export_financial_model(d, str(out))

    ws = load_workbook(str(out))[
        "Financial Model"]
    header = [c.value for c in ws[1]]
    assert header[0] == "Line Items"
    assert header[-1] == "LTM"
    assert header[-3:-1] == ["Q1'26", "Q2'26"]
    assert "FY2025" in header and ws.freeze_panes == "B2"

    labels = [ws.cell(row=r, column=1).value for r in range(1, ws.max_row + 1)]
    for section in ("INCOME STATEMENT", "BALANCE SHEET (period end)",
                    "CASH FLOW STATEMENT"):
        assert section in labels

    rev_row = labels.index("Total Revenue") + 1
    ltm_col = header.index("LTM") + 1
    # values are written in $mm
    assert ws.cell(row=rev_row, column=ltm_col).value == pytest.approx(
        (REVENUE[2025] + Q1_REV + Q2_REV - H1_REV_PRIOR) / 1e6)
    assert ws.cell(row=rev_row, column=header.index("Q1'26") + 1).value == \
        pytest.approx(Q1_REV / 1e6)

    # footer carries the derivation notes and the tag audit
    tail = "".join(str(v) for v in labels if v)
    assert "LTM (flows) = last FY + latest fiscal YTD" in tail
    assert "XBRL tags:" in tail


def test_export_without_fundamentals_raises(tmp_path):
    d = DashboardData(ticker="X", company="X", subtitle="",
                      generated=dt.date(2026, 8, 10))
    with pytest.raises(ValueError):
        export_financial_model(d, str(tmp_path / "x.xlsx"))

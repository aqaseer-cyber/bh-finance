"""Shared fixtures: a schema-exact synthetic SEC companyfacts payload.

TESTCO exercises the tricky parsing paths:
- revenue tag migration (`Revenues` dies in FY2021; ASC-606 tag carries on),
- a 10-K/A amendment for FY2023 whose later-filed value must win,
- quarterly (10-Q) rows that must be excluded from annual series,
- no GrossProfit tag (gross margin must be derived from cost of revenue),
- instant balance-sheet concepts keyed to fiscal year ends.
"""
import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

FY_YEARS = [2019, 2020, 2021, 2022, 2023, 2024, 2025]

# FY -> value tables (USD unless noted)
REVENUE = {2019: 800e6, 2020: 900e6, 2021: 1000e6, 2022: 1150e6,
           2023: 1300e6, 2024: 1500e6, 2025: 1700e6}
REVENUE_FY2023_ORIGINAL = 1250e6  # superseded by the 10-K/A below
COST = {y: REVENUE[y] * 0.6 for y in FY_YEARS}
OPINC = {y: REVENUE[y] * 0.18 for y in FY_YEARS}
NI = {y: REVENUE[y] * 0.12 for y in FY_YEARS}
CFO = {y: NI[y] * 1.3 for y in FY_YEARS}
CAPEX = {y: REVENUE[y] * 0.07 for y in FY_YEARS}
SHARES = {y: 100e6 + (y - 2019) * 2e6 for y in FY_YEARS}
ASSETS = {y: REVENUE[y] * 2.0 for y in FY_YEARS}
CASH = {y: REVENUE[y] * 0.25 for y in FY_YEARS}
LTD_NC = {y: 300e6 for y in FY_YEARS}
LTD_C = {y: 50e6 for y in FY_YEARS}


def _annual(fy: int, val: float, form: str = "10-K", filed: str | None = None) -> dict:
    return {
        "start": f"{fy}-01-01", "end": f"{fy}-12-31", "val": val,
        "fy": fy + 1, "fp": "FY", "form": form,
        "filed": filed or f"{fy + 1}-02-15", "frame": f"CY{fy}",
    }


def _quarterly(fy: int, q: int, val: float) -> dict:
    starts = {1: "01-01", 2: "04-01", 3: "07-01", 4: "10-01"}
    ends = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}
    return {
        "start": f"{fy}-{starts[q]}", "end": f"{fy}-{ends[q]}", "val": val,
        "fy": fy, "fp": f"Q{q}", "form": "10-Q", "filed": f"{fy}-11-05",
    }


def _instant(fy: int, val: float, form: str = "10-K") -> dict:
    return {
        "end": f"{fy}-12-31", "val": val, "fy": fy + 1, "fp": "FY",
        "form": form, "filed": f"{fy + 1}-02-15", "frame": f"CY{fy}Q4I",
    }


def _usd(items):
    return {"units": {"USD": items}}


def _shares(items):
    return {"units": {"shares": items}}


def build_testco_companyfacts() -> dict:
    # Old revenue tag: stops after FY2021 (the migration trap)
    revenues_old = [_annual(y, REVENUE[y]) for y in (2019, 2020, 2021)]
    # New tag: FY2020 onward, plus quarterly noise, plus the FY2023 amendment
    revenues_new = [_annual(y, REVENUE[y]) for y in (2020, 2021, 2022, 2024, 2025)]
    revenues_new.append(_annual(2023, REVENUE_FY2023_ORIGINAL))  # original 10-K
    revenues_new.append(_annual(2023, REVENUE[2023], form="10-K/A",
                                filed="2024-06-30"))             # amendment wins
    revenues_new += [_quarterly(2025, q, REVENUE[2025] / 4) for q in (1, 2, 3)]

    gaap = {
        "Revenues": _usd(revenues_old),
        "RevenueFromContractWithCustomerExcludingAssessedTax": _usd(revenues_new),
        "CostOfRevenue": _usd([_annual(y, COST[y]) for y in FY_YEARS]),
        "OperatingIncomeLoss": _usd([_annual(y, OPINC[y]) for y in FY_YEARS]),
        "NetIncomeLoss": _usd([_annual(y, NI[y]) for y in FY_YEARS]),
        "NetCashProvidedByUsedInOperatingActivities": _usd(
            [_annual(y, CFO[y]) for y in FY_YEARS]),
        "PaymentsToAcquirePropertyPlantAndEquipment": _usd(
            [_annual(y, CAPEX[y]) for y in FY_YEARS]),
        "WeightedAverageNumberOfDilutedSharesOutstanding": _shares(
            [_annual(y, SHARES[y]) for y in FY_YEARS]),
        "Assets": _usd([_instant(y, ASSETS[y]) for y in FY_YEARS]),
        "CashAndCashEquivalentsAtCarryingValue": _usd(
            [_instant(y, CASH[y]) for y in FY_YEARS]),
        "LongTermDebtNoncurrent": _usd([_instant(y, LTD_NC[y]) for y in FY_YEARS]),
        "LongTermDebtCurrent": _usd([_instant(y, LTD_C[y]) for y in FY_YEARS]),
    }
    return {"cik": 1234567, "entityName": "TESTCO INC", "facts": {"us-gaap": gaap}}


@pytest.fixture
def testco_facts() -> dict:
    return build_testco_companyfacts()


@pytest.fixture
def aapl_prices() -> dict:
    return json.loads((FIXTURES / "aapl_weekly_5y.json").read_text())

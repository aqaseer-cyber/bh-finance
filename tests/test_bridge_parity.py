"""FIX-2 — equity bridge (MI+pref−non-op) and reverse-DCF on Track-B ex-SBC
base, parity with the shell's Control!B57/B58 and FCFF_DCF!B31."""
import datetime as dt

import pytest

from forensic_viz.edgar import parse_companyfacts
from forensic_viz.metrics import DashboardData, apply_track, build_fundamental_metrics
from forensic_viz.valuation import (
    CaseInputs, ValuationInputs, build_valuation,
)
from forensic_viz.verdict import build_verdict


def _facts():
    """Minimal us-gaap facts: revenue/NI/CFO/capex/shares + bridge legs."""
    years = list(range(2020, 2026))

    def dur(vals):
        return {"units": {"USD": [
            {"start": f"{y}-01-01", "end": f"{y}-12-31", "val": v, "fy": y + 1,
             "fp": "FY", "form": "10-K", "filed": f"{y + 1}-02-15"}
            for y, v in zip(years, vals)]}}

    def inst(vals):
        return {"units": {"USD": [
            {"end": f"{y}-12-31", "val": v, "fy": y + 1, "fp": "FY",
             "form": "10-K", "filed": f"{y + 1}-02-15"}
            for y, v in zip(years, vals)]}}

    def shr(vals):
        return {"units": {"shares": [
            {"start": f"{y}-01-01", "end": f"{y}-12-31", "val": v, "fy": y + 1,
             "fp": "FY", "form": "10-K", "filed": f"{y + 1}-02-15"}
            for y, v in zip(years, vals)]}}

    rev = [8e9, 9e9, 10e9, 11e9, 12e9, 13e9]
    return {"cik": 1, "entityName": "BRIDGECO", "facts": {"us-gaap": {
        "Revenues": dur(rev),
        "CostOfRevenue": dur([r * 0.6 for r in rev]),
        "OperatingIncomeLoss": dur([r * 0.2 for r in rev]),
        "NetIncomeLoss": dur([r * 0.12 for r in rev]),
        "NetCashProvidedByUsedInOperatingActivities": dur([r * 0.18 for r in rev]),
        "PaymentsToAcquirePropertyPlantAndEquipment": dur([r * 0.05 for r in rev]),
        "ShareBasedCompensation": dur([r * 0.03 for r in rev]),
        "InterestExpense": dur([r * 0.01 for r in rev]),
        "IncomeTaxExpenseBenefit": dur([r * 0.03 for r in rev]),
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest":
            dur([r * 0.15 for r in rev]),
        "WeightedAverageNumberOfDilutedSharesOutstanding": shr([1e9] * 6),
        "Assets": inst([r * 2 for r in rev]),
        "StockholdersEquity": inst([r * 0.8 for r in rev]),
        "LongTermDebtNoncurrent": inst([3e9] * 6),
        "CashAndCashEquivalentsAtCarryingValue": inst([1e9] * 6),
        "MinorityInterest": inst([5e8] * 6),
        "PreferredStockValue": inst([2e8] * 6),
    }}}


def _data(nonop=2e9):
    d = DashboardData(ticker="BRIDGECO", company="BridgeCo", subtitle="",
                      generated=dt.date(2026, 7, 3))
    d.sic_code = "3571"
    apply_track(d, "auto")
    build_fundamental_metrics(parse_companyfacts(_facts(), "BRIDGECO"), d)
    d.last_close = 20.0
    d.price_dates = [dt.date(2026, 7, 1)]
    d.price_closes = [20.0]
    d.non_op_investments = nonop
    return d


def _cases():
    return {"Bear": CaseInputs(g0=0.02, g_term=0.02),
            "Base": CaseInputs(g0=0.05, g_term=0.025),
            "Bull": CaseInputs(g0=0.08, g_term=0.03)}


def test_bridge_equals_net_debt_plus_mi_pref_minus_nonop():
    d = _data(nonop=2e9)
    res = build_valuation(d, ValuationInputs("dcf", _cases(), discount_rate=0.09))
    net_debt = 3e9 - 1e9          # LT debt − cash
    expected = net_debt + 5e8 + 2e8 - 2e9
    assert res.net_debt == pytest.approx(net_debt)
    assert res.bridge == pytest.approx(expected)


def test_case_equity_and_market_ev_use_bridge():
    d = _data()
    res = build_valuation(d, ValuationInputs("dcf", _cases(), discount_rate=0.09))
    shares = 1e9
    assert res.market_ev == pytest.approx(20.0 * shares + res.bridge)
    for c in res.cases:
        assert c.equity == pytest.approx(c.ev - res.bridge)
        assert c.fv_ps == pytest.approx(c.equity / shares)


def test_reverse_dcf_on_track_b_ex_sbc_base():
    d = _data()
    res = build_valuation(d, ValuationInputs("dcf", _cases(), discount_rate=0.09))
    fcff = res.base_value            # FCFF = FCF + after-tax interest
    sbc = 13e9 * 0.03                # latest-FY SBC
    expected = 0.09 - (fcff - sbc) / res.market_ev  # Control!B58 arithmetic
    assert res.implied_g == pytest.approx(expected, rel=1e-9)
    assert "Control!B58" in res.implied_g_basis


def test_ex_sbc_base_nonpositive_disables_reverse_dcf():
    d = _data()
    # force SBC above the base: enormous SBC in the latest year
    d.sbc[-1] = d.fcff[-1] * 2
    res = build_valuation(d, ValuationInputs("dcf", _cases(), discount_rate=0.09))
    assert res.implied_g is None
    assert any("ex-SBC base non-positive" in w for w in res.warnings)


def test_verdict_fv_moves_with_bridge():
    d = _data(nonop=2e9)
    inputs = ValuationInputs("dcf", _cases(), discount_rate=0.09)
    res = build_valuation(d, inputs)
    v = build_verdict(d, inputs, res, rating="Hold")
    # hand-recompute Track A FV: Bear growths on FCFF base, minus the bridge
    from forensic_viz.valuation import dcf_fcff
    ev = dcf_fcff(res.base_value, 0.09, 0.02, 0.02)["ev"]
    assert v.fv_a == pytest.approx((ev - res.bridge) / 1e9, rel=1e-9)


def test_bridge_notes_present():
    d = _data(nonop=None)  # non-op not entered
    res = build_valuation(d, ValuationInputs("dcf", _cases(), discount_rate=0.09))
    assert any("MI" in w and "preferred" in w for w in res.warnings)
    assert any("non-operating investments not entered" in w for w in res.warnings)

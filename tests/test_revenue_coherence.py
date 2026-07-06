"""FIX-11a: coherence-based revenue selection — Rev ≈ GP + COGS referees
the tag per fiscal year (the MELI headline vs contract-only case)."""
import datetime as dt

import pytest

from conftest import (
    FY_YEARS, REVENUE, build_testco_companyfacts, _annual, _usd,
)
from forensic_viz.edgar import parse_companyfacts

CONTRACT = "RevenueFromContractWithCustomerExcludingAssessedTax"
FIN_INCOME = 300e6  # the headline-vs-contract wedge (≫ 2% of revenue)


def _meli_like_facts(gp_offset: float = 0.0, with_gp: bool = True) -> dict:
    """Contract tag full coverage; headline `Revenues` only FY2021–FY2025
    (so coverage scoring picks the contract tag); COGS and GrossProfit are
    tagged on the HEADLINE basis for the split years."""
    headline_years = [y for y in FY_YEARS if y >= 2021]
    contract = [_annual(y, REVENUE[y] - (FIN_INCOME if y in headline_years
                                         else 0.0)) for y in FY_YEARS]
    headline = [_annual(y, REVENUE[y]) for y in headline_years]
    cogs = [_annual(y, REVENUE[y] * 0.6) for y in FY_YEARS]
    gp = [_annual(y, REVENUE[y] * 0.4 + gp_offset) for y in FY_YEARS]
    gaap = {
        CONTRACT: _usd(contract),
        "Revenues": _usd(headline),
        "CostOfGoodsAndServicesSold": _usd(cogs),
        "NetIncomeLoss": _usd([_annual(y, REVENUE[y] * 0.1)
                               for y in FY_YEARS]),
    }
    if with_gp:
        gaap["GrossProfit"] = _usd(gp)
    return {"cik": 1, "entityName": "MELI-LIKE",
            "facts": {"us-gaap": gaap}}


def test_per_year_substitution_to_the_coherent_headline_tag():
    f = parse_companyfacts(_meli_like_facts(), "MLIKE")
    # coverage picked the contract tag; coherence swapped FY2021–FY2025
    by_year = dict(zip((e.year for e in f.fy_ends), f.series["revenue"]))
    for y in (2021, 2022, 2023, 2024, 2025):
        assert by_year[y] == pytest.approx(REVENUE[y])          # headline
    for y in (2016, 2017, 2020):
        assert by_year[y] == pytest.approx(REVENUE[y])  # no wedge pre-split
    ys = f.year_sources["revenue"]
    assert {fe.year for fe in ys} == {2021, 2022, 2023, 2024, 2025}
    assert set(ys.values()) == {"Revenues"}
    assert "basis coherence" in f.tags_used["revenue"]
    assert any("substituted Revenues" in n for n in f.selection_notes)


def test_missing_gross_profit_leaves_winner_untouched():
    f = parse_companyfacts(_meli_like_facts(with_gp=False), "MLIKE")
    by_year = dict(zip((e.year for e in f.fy_ends), f.series["revenue"]))
    assert by_year[2025] == pytest.approx(REVENUE[2025] - FIN_INCOME)
    assert f.selection_notes == [] and "revenue" not in f.year_sources


def test_no_coherent_candidate_keeps_winner_with_unresolved_note():
    # GP shifted so that NO candidate satisfies Rev ≈ GP + COGS
    f = parse_companyfacts(_meli_like_facts(gp_offset=500e6), "MLIKE")
    by_year = dict(zip((e.year for e in f.fy_ends), f.series["revenue"]))
    assert by_year[2025] == pytest.approx(REVENUE[2025] - FIN_INCOME)
    assert any("UNRESOLVED in FY2025" in n for n in f.selection_notes)
    assert any("margins for that year are suspect" in n
               for n in f.selection_notes)


def test_testco_regression_no_notes_no_changes(testco_facts):
    """TESTCO has no GrossProfit tag — the identity is never checkable,
    the pass is a no-op, and the golden snapshots stay byte-identical."""
    f = parse_companyfacts(testco_facts, "TESTCO")
    assert f.selection_notes == []
    assert f.year_sources == {}
    assert f.series["revenue"][-1] == pytest.approx(REVENUE[2025])

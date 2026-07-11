"""Annual interest rescue from filing instances.

MELI's income-statement line "Interest expense and other financial
charges" is extension-tagged (meli: namespace); the companyfacts API
serves standard taxonomies only, so the annual series dies there while
the value verifiably sits in every 10-K instance. The rescue reads the
consolidated (dimension-free) facts from the already-cached instances by
element LOCAL NAME — the FIX-11a candidate list finally reaches the tag
it was written for.
"""
import datetime as dt

import pytest

from conftest import build_testco_companyfacts
from forensic_viz import segments
from forensic_viz.edgar import parse_companyfacts
from forensic_viz.metrics import (
    DashboardData, apply_track, build_fundamental_metrics,
    refresh_interest_metrics,
)
from forensic_viz.segments import rescue_annual_series, undimensioned_annual_facts

_NS = ('xmlns="http://www.xbrl.org/2003/instance" '
       'xmlns:xbrldi="http://xbrl.org/2006/xbrldi" '
       'xmlns:us-gaap="http://fasb.org/us-gaap/2025" '
       'xmlns:srt="http://fasb.org/srt/2025" '
       'xmlns:meli="http://mercadolibre.com/20251231" '
       'xmlns:iso4217="http://www.xbrl.org/2003/iso4217"')

_TAG = "meli:InterestExpenseAndOtherFinancialCharges"


def _instance(fy_facts, extra=""):
    """{year: val} -> instance XML with dimension-free FY contexts, plus a
    dimensioned + a quarterly + a non-USD fact that must all be ignored."""
    parts = [f"<xbrl {_NS}>",
             '<unit id="usd"><measure>iso4217:USD</measure></unit>',
             '<unit id="brl"><measure>iso4217:BRL</measure></unit>']
    for y, v in fy_facts.items():
        parts.append(
            f'<context id="fy{y}"><entity><identifier scheme="s">1</identifier>'
            f"</entity><period><startDate>{y}-01-01</startDate>"
            f"<endDate>{y}-12-31</endDate></period></context>")
        parts.append(f'<{_TAG} contextRef="fy{y}" unitRef="usd">{v}</{_TAG}>')
    # rejects: a segment-dimensioned annual fact, a quarter, a non-USD fact
    parts.append(
        '<context id="dim"><entity><identifier scheme="s">1</identifier>'
        '<segment><xbrldi:explicitMember dimension="srt:StatementGeographicalAxis">'
        "country:BR</xbrldi:explicitMember></segment></entity>"
        "<period><startDate>2025-01-01</startDate>"
        "<endDate>2025-12-31</endDate></period></context>")
    parts.append(f'<{_TAG} contextRef="dim" unitRef="usd">999000000</{_TAG}>')
    parts.append(
        '<context id="q1"><entity><identifier scheme="s">1</identifier></entity>'
        "<period><startDate>2025-01-01</startDate>"
        "<endDate>2025-03-31</endDate></period></context>")
    parts.append(f'<{_TAG} contextRef="q1" unitRef="usd">888000000</{_TAG}>')
    parts.append(
        '<context id="brl25"><entity><identifier scheme="s">1</identifier></entity>'
        "<period><startDate>2025-01-01</startDate>"
        "<endDate>2025-12-31</endDate></period></context>")
    parts.append(f'<{_TAG} contextRef="brl25" unitRef="brl">777000000</{_TAG}>')
    parts.append(extra)
    parts.append("</xbrl>")
    return "".join(parts)


def test_undimensioned_annual_facts_filters_correctly():
    xml = _instance({2024: 165e6, 2025: 160e6})
    out = undimensioned_annual_facts(
        xml, ["InterestExpenseAndOtherFinancialCharges"])
    assert out == {
        (dt.date(2024, 1, 1), dt.date(2024, 12, 31)): pytest.approx(165e6),
        (dt.date(2025, 1, 1), dt.date(2025, 12, 31)): pytest.approx(160e6),
    }  # the dimensioned 999, quarterly 888 and BRL 777 never appear
    assert undimensioned_annual_facts(xml, ["SomethingElse"]) == {}


def _annual(monkeypatch, instances):
    annual = parse_companyfacts(build_testco_companyfacts(), "TESTCO")
    # kill the recent interest years, keep an early one (companyfacts value)
    n = len(annual.fy_ends)
    series = [None] * n
    series[0] = 17.3e6
    annual.series["interest_expense"] = series
    monkeypatch.setattr(segments, "fetch_segment_instances",
                        lambda a, cache=None: (instances, []))
    return annual


def test_rescue_fills_only_missing_years_later_filing_wins(monkeypatch):
    older = _instance({2024: 164e6})           # superseded FY2024 value
    newer = _instance({2024: 165e6, 2025: 160e6})
    annual = _annual(monkeypatch, [("10-K a24", older), ("10-K a25", newer)])
    filled = rescue_annual_series(annual, "interest_expense")
    assert filled == [2024, 2025]
    got = dict(zip((e.year for e in annual.fy_ends),
                   annual.series["interest_expense"]))
    assert got[2024] == pytest.approx(165e6)   # later filing won
    assert got[2025] == pytest.approx(160e6)
    assert got[annual.fy_ends[0].year] == pytest.approx(17.3e6)  # untouched
    assert "rescued from filing instances" in annual.tags_used["interest_expense"]
    assert any("companyfacts API serves standard taxonomies only" in n
               for n in annual.selection_notes)
    # second call: nothing left to fill for those years -> no double note
    notes_before = len(annual.selection_notes)
    rescue_annual_series(annual, "interest_expense")
    assert len(annual.selection_notes) == notes_before


def test_rescue_noop_when_series_complete_or_unreachable(monkeypatch):
    annual = parse_companyfacts(build_testco_companyfacts(), "TESTCO")
    full = [1.0] * len(annual.fy_ends)
    annual.series["interest_expense"] = full
    assert rescue_annual_series(annual, "interest_expense") == []
    annual.series["interest_expense"] = [None] * len(annual.fy_ends)
    monkeypatch.setattr(segments, "fetch_segment_instances",
                        lambda a, cache=None: (_ for _ in ()).throw(
                            RuntimeError("offline")))
    assert rescue_annual_series(annual, "interest_expense") == []


def test_refresh_interest_metrics_unlevers_fcff(monkeypatch):
    d = DashboardData(ticker="TESTCO", company="TESTCO Inc", subtitle="",
                      generated=dt.date(2026, 7, 11))
    d.sic_code = "3571"
    apply_track(d, "auto")
    annual = parse_companyfacts(build_testco_companyfacts(), "TESTCO")
    annual.series["interest_expense"] = [None] * len(annual.fy_ends)
    build_fundamental_metrics(annual, d)
    assert d.interest_expense[-1] is None
    fcf_before = d.fcf[-1]
    assert d.fcff[-1] == pytest.approx(fcf_before)  # levered proxy

    year = annual.fy_ends[-1].year
    inst = _instance({year: 160e6, year - 1: 165e6})
    monkeypatch.setattr(segments, "fetch_segment_instances",
                        lambda a, cache=None: ([("10-K", inst)], []))
    assert rescue_annual_series(annual, "interest_expense") != []
    refresh_interest_metrics(annual, d)
    tau = d.effective_tax_rate
    assert d.interest_expense[-1] == pytest.approx(160e6)
    assert d.fcff[-1] == pytest.approx(fcf_before + 160e6 * (1 - tau))
    assert d.fcf[-1] == pytest.approx(fcf_before)  # levered FCF untouched

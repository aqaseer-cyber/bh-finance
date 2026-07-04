"""Segment extraction from XBRL instances + SEGMENTS section + Phase-2 fill.

The synthetic instance mirrors MELI's structure: revenue disaggregated on
the geography axis (Brazil / Mexico / Other Countries) and the
product/service axis (Commerce / Fintech Services), with operating income
on the product axis. Includes rejection cases: an instant context, a
two-axis context, a non-USD unit, and a neutral OperatingSegments marker
that must NOT disqualify a context.
"""
import datetime as dt

import pytest
from openpyxl import load_workbook

from conftest import REVENUE, build_testco_companyfacts
from forensic_viz.edgar import instance_url, parse_companyfacts
from forensic_viz.metrics import DashboardData, apply_track, build_fundamental_metrics
from forensic_viz.model_export import export_financial_model
from forensic_viz.segments import (
    SegmentData, build_segment_data, member_label, parse_instance,
)
from forensic_viz.workbook import fill_workbook

_NS = ('xmlns="http://www.xbrl.org/2003/instance" '
       'xmlns:xbrldi="http://xbrl.org/2006/xbrldi" '
       'xmlns:us-gaap="http://fasb.org/us-gaap/2025" '
       'xmlns:srt="http://fasb.org/srt/2025" '
       'xmlns:meli="http://mercadolibre.com/20251231" '
       'xmlns:iso4217="http://www.xbrl.org/2003/iso4217"')

REV = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"


def _ctx(cid, axis, member, start, end, extra=""):
    return f"""
 <context id="{cid}"><entity><identifier scheme="http://www.sec.gov/CIK">0001099590</identifier>
  <segment><xbrldi:explicitMember dimension="{axis}">{member}</xbrldi:explicitMember>{extra}</segment></entity>
  <period><startDate>{start}</startDate><endDate>{end}</endDate></period></context>"""


def _fact(concept, ctx, val, unit="usd"):
    return f'\n <{concept} contextRef="{ctx}" unitRef="{unit}" decimals="-5">{val}</{concept}>'


def _tenk_instance() -> str:
    """FY2024+FY2025 segment revenue (geo + product), op income (product)."""
    parts = [f"<xbrl {_NS}>",
             '<unit id="usd"><measure>iso4217:USD</measure></unit>',
             '<unit id="brl"><measure>iso4217:BRL</measure></unit>']
    geo = {"meli:BrazilMember": (900e6, 1000e6),
           "country:MX": (500e6, 560e6),
           "meli:OtherCountriesMember": (300e6, 340e6)}
    for i, (m, (v24, v25)) in enumerate(geo.items()):
        parts.append(_ctx(f"g24{i}", "srt:StatementGeographicalAxis", m,
                          "2024-01-01", "2024-12-31"))
        parts.append(_ctx(f"g25{i}", "srt:StatementGeographicalAxis", m,
                          "2025-01-01", "2025-12-31"))
        parts.append(_fact(REV, f"g24{i}", v24))
        parts.append(_fact(REV, f"g25{i}", v25))
    prod = {"meli:CommerceMember": (1000e6, 1080e6),
            "meli:FintechServicesMember": (700e6, 820e6)}
    for i, (m, (v24, v25)) in enumerate(prod.items()):
        # neutral OperatingSegments marker must not disqualify the context
        extra = ('<xbrldi:explicitMember dimension="us-gaap:ConsolidationItemsAxis">'
                 'us-gaap:OperatingSegmentsMember</xbrldi:explicitMember>')
        parts.append(_ctx(f"p24{i}", "srt:ProductOrServiceAxis", m,
                          "2024-01-01", "2024-12-31", extra))
        parts.append(_ctx(f"p25{i}", "srt:ProductOrServiceAxis", m,
                          "2025-01-01", "2025-12-31", extra))
        parts.append(_fact(REV, f"p24{i}", v24))
        parts.append(_fact(REV, f"p25{i}", v25))
        parts.append(_fact("us-gaap:OperatingIncomeLoss", f"p25{i}", v25 * 0.2))
    # rejects: two-axis context, non-USD fact, sub-20-day span
    parts.append(_ctx("bad2ax", "srt:StatementGeographicalAxis",
                      "meli:BrazilMember", "2025-01-01", "2025-12-31",
                      '<xbrldi:explicitMember dimension="srt:ProductOrServiceAxis">'
                      'meli:CommerceMember</xbrldi:explicitMember>'))
    parts.append(_fact(REV, "bad2ax", 999e9))
    parts.append(_ctx("badbrl", "srt:StatementGeographicalAxis",
                      "meli:BrazilMember", "2025-01-01", "2025-12-31"))
    parts.append(_fact(REV, "badbrl", 888e9, unit="brl"))
    parts.append("</xbrl>")
    return "".join(parts)


def _tenq_instance() -> str:
    """Q1'26 discrete + prior-year Q1'25 comparative for the geo axis."""
    parts = [f"<xbrl {_NS}>",
             '<unit id="usd"><measure>iso4217:USD</measure></unit>']
    q = {"meli:BrazilMember": (230e6, 270e6),
         "country:MX": (130e6, 150e6),
         "meli:OtherCountriesMember": (80e6, 90e6)}
    for i, (m, (v25, v26)) in enumerate(q.items()):
        parts.append(_ctx(f"q25{i}", "srt:StatementGeographicalAxis", m,
                          "2025-01-01", "2025-03-31"))
        parts.append(_ctx(f"q26{i}", "srt:StatementGeographicalAxis", m,
                          "2026-01-01", "2026-03-31"))
        parts.append(_fact(REV, f"q25{i}", v25))
        parts.append(_fact(REV, f"q26{i}", v26))
    parts.append("</xbrl>")
    return "".join(parts)


def test_member_label_and_instance_url():
    assert member_label("meli:FintechServicesMember") == "Fintech Services"
    assert member_label("country:MX") == "Mexico"  # ISO code -> country name
    assert member_label("country:BR") == "Brazil"
    assert instance_url(1099590, "0001099590-26-000012", "meli-20251231.htm") \
        == ("https://www.sec.gov/Archives/edgar/data/1099590/"
            "000109959026000012/meli-20251231_htm.xml")


def test_parse_instance_accepts_segment_axes_and_rejects_noise():
    parsed = parse_instance(_tenk_instance())
    rev_local = REV.split(":")[1]
    br = parsed.singles[("geography", "Brazil", rev_local)]
    assert br[(dt.date(2025, 1, 1), dt.date(2025, 12, 31))] == 1000e6
    assert all(v < 1e11 for v in br.values())  # BRL-unit fact rejected
    # the two-axis (geo × product) fact lands in crosses, not in singles
    assert any(k[-1] == rev_local and v.get(
        (dt.date(2025, 1, 1), dt.date(2025, 12, 31))) == 999e9
        for k, v in parsed.crosses.items())
    # neutral OperatingSegments marker kept the product contexts alive
    assert ("product / service", "Fintech Services", rev_local) \
        in parsed.singles
    assert ("product / service", "Commerce", "OperatingIncomeLoss") \
        in parsed.singles


def test_build_orders_members_by_revenue_and_merges_instances():
    seg = build_segment_data([_tenk_instance(), _tenq_instance()], "test")
    assert seg.axes() == ["product / service", "geography"]
    assert seg.members("geography") == ["Brazil", "Mexico", "Other Countries"]
    assert seg.n_segments == 2  # primary axis = product / service
    rev_br = next(ln for ln in seg.lines
                  if ln.member == "Brazil" and ln.group == "Revenue")
    spans = {(s, e): v for s, e, v in rev_br.entries}
    assert spans[(dt.date(2026, 1, 1), dt.date(2026, 3, 31))] == 270e6
    # the noisy two-axis 999e9 fact never overrode the filed Brazil total
    assert spans[(dt.date(2025, 1, 1), dt.date(2025, 12, 31))] == 1000e6


def test_two_axis_only_disaggregation_is_aggregated():
    """MELI-style: the disaggregation table is tagged geography × business
    with NO single-axis totals — totals must be synthesized per axis."""
    parts = [f"<xbrl {_NS}>",
             '<unit id="usd"><measure>iso4217:USD</measure></unit>']
    cells = {("country:BR", "meli:CommerceMember"): 600e6,
             ("country:BR", "meli:FintechMember"): 400e6,
             ("country:MX", "meli:CommerceMember"): 250e6,
             ("country:MX", "meli:FintechMember"): 150e6}
    for i, ((geo, biz), v) in enumerate(cells.items()):
        extra = ('<xbrldi:explicitMember dimension="srt:ProductOrServiceAxis">'
                 f"{biz}</xbrldi:explicitMember>")
        parts.append(_ctx(f"x{i}", "srt:StatementGeographicalAxis", geo,
                          "2025-01-01", "2025-12-31", extra))
        parts.append(_fact(REV, f"x{i}", v))
    parts.append("</xbrl>")
    seg = build_segment_data(["".join(parts)], "x")
    by = {(ln.axis, ln.member): ln for ln in seg.lines
          if ln.group == "Revenue"}
    span = (dt.date(2025, 1, 1), dt.date(2025, 12, 31))
    assert {(s, e): v for s, e, v in
            by[("geography", "Brazil")].entries}[span] == 1000e6
    assert {(s, e): v for s, e, v in
            by[("product / service", "Fintech")].entries}[span] == 550e6
    assert "aggregated" in seg.status


def _data_with_segments():
    facts = build_testco_companyfacts()
    d = DashboardData(ticker="TESTCO", company="TESTCO Inc", subtitle="",
                      generated=dt.date(2026, 5, 1))
    d.sic_code = "3571"
    apply_track(d, "auto")
    build_fundamental_metrics(parse_companyfacts(facts, "TESTCO"), d)
    d.segments = build_segment_data([_tenk_instance(), _tenq_instance()], "t")
    return d


def test_segments_section_in_model_export(tmp_path):
    d = _data_with_segments()
    out = tmp_path / "model.xlsx"
    export_financial_model(d, str(out))
    ws = load_workbook(str(out))["Financial Model"]
    header = [c.value for c in ws[1]]
    labels = [ws.cell(row=r, column=1).value for r in range(1, ws.max_row + 1)]
    assert "SEGMENTS (as filed)" in labels
    assert "Revenue by geography" in labels
    assert "Revenue by product / service" in labels
    assert "Operating income by product / service" in labels
    br_row = labels.index("  Brazil") + 1
    fy25 = header.index("FY2025") + 1
    assert ws.cell(row=br_row, column=fy25).value == pytest.approx(1000.0)
    # % change row under the Brazil segment line: FY2025 YoY
    assert labels[br_row] == "   % change"
    assert ws.cell(row=br_row + 1, column=fy25).value == pytest.approx(
        1000e6 / 900e6 - 1)


def test_workbook_phase2_segment_fill(tmp_path):
    d = _data_with_segments()
    out = tmp_path / "wb.xlsx"
    report = fill_workbook(d, str(out))
    wb = load_workbook(str(out))
    ws = wb["Phase2_UnitEcon"]
    # top-2 product/service segments in $mm; remainder = total − top-2
    assert ws["B5"].value == pytest.approx(1080.0)
    assert ws["B6"].value == pytest.approx(820.0)
    assert ws["B7"].value == pytest.approx(REVENUE[2025] / 1e6 - 1080 - 820)
    assert "Commerce" in ws["B5"].comment.text
    assert "Fintech Services" in ws["B6"].comment.text
    # the segment row left the analyst to-do list
    assert not any(r[0] == "Phase2_UnitEcon" and r[1] == "B5:B7"
                   for r in report.analyst_cells)


def test_no_segments_keeps_workbook_and_export_working(tmp_path):
    facts = build_testco_companyfacts()
    d = DashboardData(ticker="TESTCO", company="TESTCO Inc", subtitle="",
                      generated=dt.date(2026, 5, 1))
    d.sic_code = "3571"
    apply_track(d, "auto")
    build_fundamental_metrics(parse_companyfacts(facts, "TESTCO"), d)
    assert d.segments is None
    report = fill_workbook(d, str(tmp_path / "wb.xlsx"))
    assert any(r[0] == "Phase2_UnitEcon" and r[1] == "B5:B7"
               for r in report.analyst_cells)
    export_financial_model(d, str(tmp_path / "m.xlsx"))
    ws = load_workbook(str(tmp_path / "m.xlsx"))["Financial Model"]
    labels = [ws.cell(row=r, column=1).value for r in range(1, ws.max_row + 1)]
    assert "SEGMENTS (as filed)" not in labels
    assert any("no dimensional segment data" in str(v) for v in labels)

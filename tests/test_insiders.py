"""FIX-17e: Form 4 parsing (open-market only), submissions selection,
panel summary math, and the card render. All offline."""
import datetime as dt

import matplotlib
matplotlib.use("Agg")

import pytest

from forensic_viz import config
from forensic_viz.insiders import (
    InsiderPanel, InsiderTx, parse_form4, raw_form4_document, select_form4,
)
from forensic_viz.metrics import DashboardData

FORM4 = """<?xml version="1.0"?>
<ownershipDocument>
  <periodOfReport>2026-06-15</periodOfReport>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>Miller Jamie S</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship>
      <isOfficer>1</isOfficer>
      <officerTitle>Chief Fin, Op Officer</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-06-15</value></transactionDate>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>6129</value></transactionShares>
        <transactionPricePerShare><value>41.53</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction><value>76904</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-06-03</value></transactionDate>
      <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>552</value></transactionShares>
        <transactionPricePerShare><value>42.65</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-06-01</value></transactionDate>
      <transactionCoding><transactionCode>A</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>9999</value></transactionShares>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""


def test_parse_form4_open_market_only():
    txs = parse_form4(FORM4)
    assert len(txs) == 2                      # the A-code award is excluded
    buy, sale = txs
    assert buy.name == "Miller Jamie S"
    assert buy.title == "Chief Fin, Op Officer"
    assert buy.code == "P — Purchase"
    assert buy.shares == pytest.approx(6129)
    assert buy.value == pytest.approx(6129 * 41.53)
    assert buy.owned_after == pytest.approx(76904)
    assert sale.shares == pytest.approx(-552)  # disposed -> negative
    assert sale.value == pytest.approx(-552 * 42.65)


def test_parse_form4_director_fallback_and_garbage():
    xml = FORM4.replace(
        "<isOfficer>1</isOfficer>\n      "
        "<officerTitle>Chief Fin, Op Officer</officerTitle>",
        "<isDirector>1</isDirector>")
    assert parse_form4(xml)[0].title == "Director"
    assert parse_form4("<not xml") == []
    assert parse_form4("<ownershipDocument/>") == []


def test_raw_document_strips_styled_viewer_prefix():
    assert raw_form4_document("xslF345X05/wk-form4_1.xml") == \
        "wk-form4_1.xml"
    assert raw_form4_document("form4.xml") == "form4.xml"


def test_select_form4_window_and_cap(monkeypatch):
    monkeypatch.setattr(config, "INSIDER_MAX_FILINGS", 2)
    today = dt.date(2026, 7, 18)
    recent = {
        "form": ["4", "10-K", "4", "4/A", "4"],
        "filingDate": ["2026-06-15", "2026-02-01", "2026-05-01",
                       "2026-04-01", "2024-01-01"],       # last: stale
        "accessionNumber": ["a1", "x", "a2", "a3", "a4"],
        "primaryDocument": ["xslF345X05/f1.xml", "k.htm", "f2.xml",
                            "f3.xml", "f4.xml"],
    }
    sel, in_window = select_form4(recent, today)
    assert in_window == 3                     # the 2024 filing is outside
    assert [s[0] for s in sel] == ["a1", "a2"]  # newest first, capped at 2
    assert sel[0][1] == "f1.xml"


def test_panel_summary_math():
    p = InsiderPanel(window_months=12)
    p.rows = [
        InsiderTx(dt.date(2026, 6, 15), "A", "CFO", "P — Purchase",
                  1000, 40.0, 40000.0, None),
        InsiderTx(dt.date(2026, 6, 3), "B", "Pres", "S — Sale",
                  -500, 42.0, -21000.0, None),
    ]
    s = p.summary()
    assert "1 buys $0.0M" in s and "1 sells $0.0M" in s
    assert "net $+0.0M" in s


def test_insider_card_render_paths():
    from forensic_viz.explore import insider_card
    d = DashboardData(ticker="T", company="T", subtitle="",
                      generated=dt.date(2026, 7, 18))
    # panel missing (placeholder UA) -> gate note
    fig = insider_card(d, dpi=80, width_in=8.0)
    texts = [t.get_text() for ax in fig.axes for t in ax.texts]
    assert any("declared SEC User-Agent" in t for t in texts)
    # empty panel -> honest empty note
    d.insiders = InsiderPanel(window_months=12)
    fig2 = insider_card(d, dpi=80, width_in=8.0)
    texts2 = [t.get_text() for ax in fig2.axes for t in ax.texts]
    assert any("no open-market Form 4" in t for t in texts2)
    # rows render with the provenance footnote and capped note
    d.insiders.rows = [InsiderTx(dt.date(2026, 6, 15), "Miller Jamie S",
                                 "CFO", "P — Purchase", 6129, 41.53,
                                 254537.37, 76904)]
    d.insiders.note = "showing the 25 most recent of 40 Form 4s filed " \
                      "in the window"
    fig3 = insider_card(d, dpi=80, width_in=8.0)
    texts3 = [t.get_text() for ax in fig3.axes for t in ax.texts]
    assert any("Miller Jamie S" in t for t in texts3)
    assert any("audited-filing" in t and "25 most recent" in t
               for t in texts3)

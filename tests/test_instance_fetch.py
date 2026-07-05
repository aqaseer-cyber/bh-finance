"""FIX-10b: N-year instance fetch — ordering, /A fallback, discovery,
size guard. No network: _SecSession.get_text/get_json are monkeypatched."""
import datetime as dt

import pytest

from forensic_viz import config
from forensic_viz import edgar
from forensic_viz.edgar import (
    AnnualFiling, AnnualFundamentals, EdgarError, fetch_segment_instances,
    instance_url,
)


def _f(form, filed, report, accn, doc):
    return AnnualFiling(form=form, filed=dt.date.fromisoformat(filed),
                        report_date=dt.date.fromisoformat(report),
                        accession=accn, document=doc)


def _annual(filings, tenq_accn="q26", tenq_doc="q.htm"):
    return AnnualFundamentals(
        cik=999, entity_name="T", fy_ends=[], series={},
        latest_10q_accession=tenq_accn, latest_10q_document=tenq_doc,
        annual_filings=filings)


@pytest.fixture
def fake_sec(monkeypatch):
    """Canned URL -> text map; unknown URLs raise like a 404. A declared UA
    is simulated so the FIX-13a Archives gate lets the fetch run."""
    monkeypatch.setattr(config, "UA_IS_PLACEHOLDER", False)
    canned = {}

    def get_text(self, url, ttl):
        if url in canned:
            return canned[url]
        raise EdgarError(f"404 {url}")

    def get_json(self, url, ttl):
        if url in canned:
            return canned[url]
        raise EdgarError(f"404 {url}")

    monkeypatch.setattr(edgar._SecSession, "get_text", get_text)
    monkeypatch.setattr(edgar._SecSession, "get_json", get_json)
    return canned


def test_ordering_annuals_oldest_first_then_tenq(fake_sec):
    filings = [_f("10-K", f"{y + 1}-02-15", f"{y}-12-31", f"k{y}", f"k{y}.htm")
               for y in (2023, 2024, 2025)]
    for y in (2023, 2024, 2025):
        fake_sec[instance_url(999, f"k{y}", f"k{y}.htm")] = f"<xml FY{y}/>"
    fake_sec[instance_url(999, "q26", "q.htm")] = "<xml Q/>"
    got, skipped = fetch_segment_instances(_annual(filings))
    assert [lbl.split()[0] for lbl, _ in got] == ["10-K"] * 3 + ["10-Q"]
    assert [xml for _, xml in got] == \
        ["<xml FY2023/>", "<xml FY2024/>", "<xml FY2025/>", "<xml Q/>"]
    assert "(FY2023)" in got[0][0] and skipped == []


def test_amendment_without_xbrl_falls_back_to_sibling_10k(fake_sec):
    filings = [
        _f("10-K", "2025-02-15", "2024-12-31", "k24", "k24.htm"),
        _f("10-K/A", "2025-06-30", "2024-12-31", "a24", "a24.htm"),  # no XBRL
    ]
    fake_sec[instance_url(999, "k24", "k24.htm")] = "<xml k24/>"
    fake_sec[instance_url(999, "q26", "q.htm")] = "<xml Q/>"
    got, skipped = fetch_segment_instances(_annual(filings))
    labels = [lbl for lbl, _ in got]
    assert any("10-K k24" in lbl for lbl in labels)  # sibling used
    assert not any("a24" in lbl for lbl in labels)
    assert skipped == []


def test_conventional_miss_falls_through_to_index_discovery(fake_sec):
    filings = [_f("10-K", "2026-02-15", "2025-12-31", "0001-26-9", "odd.htm")]
    # conventional …_htm.xml missing; index.json lists the real instance
    base = "https://www.sec.gov/Archives/edgar/data/999/0001269"
    fake_sec[f"{base}/index.json"] = {
        "directory": {"item": [{"name": "FilingSummary.xml"},
                               {"name": "real-instance_htm.xml"}]}}
    fake_sec[f"{base}/real-instance_htm.xml"] = "<xml discovered/>"
    fake_sec[instance_url(999, "q26", "q.htm")] = "<xml Q/>"
    got, skipped = fetch_segment_instances(_annual(filings))
    assert ("10-K 0001-26-9 (FY2025)", "<xml discovered/>") in got
    assert skipped == []


def test_size_guard_and_unreachable_are_skip_logged(fake_sec, monkeypatch):
    monkeypatch.setattr(config, "SEGMENT_MAX_INSTANCE_MB", 1e-5)  # ~10 bytes
    filings = [_f("10-K", "2026-02-15", "2025-12-31", "k25", "k25.htm"),
               _f("10-K", "2025-02-15", "2024-12-31", "gone", "gone.htm")]
    fake_sec[instance_url(999, "k25", "k25.htm")] = "<xml too large/>"
    got, skipped = fetch_segment_instances(_annual(filings, tenq_accn=""))
    assert got == []
    assert any("MB > " in s and "k25" in s for s in skipped)
    assert any("unreachable" in s and "gone" in s for s in skipped)


def test_backcompat_without_filing_history(fake_sec):
    ann = AnnualFundamentals(
        cik=999, entity_name="T", fy_ends=[], series={},
        latest_10k_accession="k25", latest_10k_document="k25.htm",
        latest_10q_accession="q26", latest_10q_document="q.htm")
    fake_sec[instance_url(999, "k25", "k25.htm")] = "<xml k/>"
    fake_sec[instance_url(999, "q26", "q.htm")] = "<xml q/>"
    got, skipped = fetch_segment_instances(ann)
    assert [xml for _, xml in got] == ["<xml k/>", "<xml q/>"]
    assert skipped == []

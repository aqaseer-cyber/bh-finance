"""FIX-10a: annual-filing enumeration and per-fiscal-year selection."""
import datetime as dt

from forensic_viz.edgar import (
    AnnualFiling, _collect_annual_filings, select_annual_filings,
    sibling_annual_filing,
)


def _f(form, filed, report, accn="0001-2", doc="x.htm"):
    return AnnualFiling(form=form, filed=dt.date.fromisoformat(filed),
                        report_date=dt.date.fromisoformat(report),
                        accession=accn, document=doc)


def test_amendment_wins_within_a_fiscal_year():
    filings = [
        _f("10-K", "2024-02-15", "2023-12-31", accn="k23"),
        _f("10-K/A", "2024-06-30", "2023-12-31", accn="a23"),  # later /A wins
        _f("10-K", "2025-02-15", "2024-12-31", accn="k24"),
    ]
    sel = select_annual_filings(filings, years=10)
    assert [f.accession for f in sel] == ["a23", "k24"]  # oldest first


def test_truncates_to_newest_years_oldest_first():
    filings = [_f("10-K", f"{y + 1}-02-15", f"{y}-12-31", accn=f"k{y}")
               for y in range(2014, 2026)]  # 12 fiscal years
    sel = select_annual_filings(filings, years=10)
    assert len(sel) == 10
    assert sel[0].report_date.year == 2016      # oldest kept
    assert sel[-1].report_date.year == 2025     # newest last
    assert sel == sorted(sel, key=lambda f: f.report_date)


def test_near_duplicate_report_dates_fold_into_one_year():
    # 52/53-week filers: report dates a few days apart are the same FY
    filings = [
        _f("10-K", "2025-02-10", "2024-12-28", accn="k1"),
        _f("10-K", "2025-02-20", "2024-12-30", accn="k2"),  # later filed wins
    ]
    sel = select_annual_filings(filings, years=10)
    assert [f.accession for f in sel] == ["k2"]


def test_collect_drops_unparseable_dates_and_foreign_forms():
    recent = {
        "form": ["10-K", "10-Q", "10-K/A", "10-K", "8-K"],
        "filingDate": ["2025-02-15", "2025-05-01", "not-a-date",
                       "2024-02-15", "2025-03-01"],
        "reportDate": ["2024-12-31", "2025-03-31", "2023-12-31",
                       "2023-12-31", ""],
        "accessionNumber": ["a", "b", "c", "d", "e"],
        "primaryDocument": ["a.htm", "b.htm", "c.htm", "d.htm", "e.htm"],
    }
    got = _collect_annual_filings(recent)
    assert [f.accession for f in got] == ["a", "d"]  # c: bad date; b/e: form


def test_sibling_lookup_finds_same_year_plain_10k():
    filings = [
        _f("10-K", "2024-02-15", "2023-12-31", accn="k23"),
        _f("10-K/A", "2024-06-30", "2023-12-31", accn="a23"),
        _f("10-K", "2025-02-15", "2024-12-31", accn="k24"),
    ]
    amd = filings[1]
    sib = sibling_annual_filing(filings, amd)
    assert sib is not None and sib.accession == "k23"
    assert sibling_annual_filing([filings[1]], amd) is None

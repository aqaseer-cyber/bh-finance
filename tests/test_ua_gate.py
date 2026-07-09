"""FIX-13a: Archives fetches refuse the placeholder UA with an actionable
error (www.sec.gov/Archives returns HTTP 403 for it — proven live on MELI);
data.sec.gov endpoints stay ungated so fundamentals remain usable."""
import datetime as dt

import pytest

from forensic_viz import config, edgar, pipeline
from forensic_viz.edgar import AnnualFundamentals, EdgarError, parse_companyfacts


def _annual_with_filings() -> AnnualFundamentals:
    a = AnnualFundamentals(cik=1099590, entity_name="MELI", fy_ends=[],
                           series={})
    a.latest_10k_accession = "0001099590-25-000007"
    a.latest_10k_document = "meli-20241231.htm"
    return a


def test_placeholder_ua_raises_before_any_network(monkeypatch):
    monkeypatch.setattr(config, "UA_IS_PLACEHOLDER", True)

    class Boom:  # a constructed session would mean network setup happened
        def __init__(self, *a, **k):
            raise AssertionError("session constructed despite the UA gate")

    monkeypatch.setattr(edgar, "_SecSession", Boom)
    with pytest.raises(EdgarError, match="SEC_EDGAR_USER_AGENT"):
        edgar.fetch_segment_instances(_annual_with_filings())


def test_declared_ua_passes_the_gate(monkeypatch):
    monkeypatch.setattr(config, "UA_IS_PLACEHOLDER", False)
    edgar._require_declared_ua()  # must not raise


def test_pipeline_turns_gate_into_actionable_segment_status(
        testco_facts, monkeypatch, tmp_path):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(config, "UA_IS_PLACEHOLDER", True)
    monkeypatch.setattr(
        pipeline, "fetch_fundamentals",
        lambda ticker, cache=None: parse_companyfacts(testco_facts, ticker))
    monkeypatch.setattr(
        pipeline, "fetch_prices",
        lambda *a, **k: (_ for _ in ()).throw(
            pipeline.PriceError("offline fixture")))
    import forensic_viz.estimates as estimates
    import forensic_viz.rates as rates
    monkeypatch.setattr(rates, "build_wacc",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("off")))
    monkeypatch.setattr(estimates, "fetch_growth_estimates",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("off")))
    d = pipeline.build_dashboard_data("TESTCO")
    assert d.segments is not None
    # the preserved failure reason IS the actionable instruction
    assert "SEC_EDGAR_USER_AGENT" in d.segments.status
    assert "403" in d.segments.status

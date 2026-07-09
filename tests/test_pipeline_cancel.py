"""FIX-12g: cooperative cancel in build_dashboard_data — offline, the
network fetch is monkeypatched to the TESTCO fixture."""
import threading

import pytest

from forensic_viz import pipeline
from forensic_viz.edgar import EdgarError, parse_companyfacts


def test_preset_cancel_event_stops_after_fundamentals(
        testco_facts, monkeypatch, tmp_path):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(
        pipeline, "fetch_fundamentals",
        lambda ticker, cache=None: parse_companyfacts(testco_facts, ticker))
    calls = []
    monkeypatch.setattr(  # must never be reached once cancel is set
        pipeline, "fetch_prices",
        lambda *a, **k: calls.append("prices"))
    ev = threading.Event()
    ev.set()  # pre-set: caught at the first boundary, before any prices work
    with pytest.raises(EdgarError, match="cancelled by user"):
        pipeline.build_dashboard_data("TESTCO", cancel=ev)
    assert calls == []


def test_default_none_cancel_changes_nothing(testco_facts, monkeypatch,
                                             tmp_path):
    """The unset-event path is a plain pass-through: fundamentals build and
    the pipeline proceeds into the price stage exactly as with cancel=None
    (the full-run behaviour is covered by the existing pipeline users)."""
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(
        pipeline, "fetch_fundamentals",
        lambda ticker, cache=None: parse_companyfacts(testco_facts, ticker))
    seen = {}

    def fake_prices(*a, **k):
        seen["reached"] = True
        raise pipeline.PriceError("offline fixture — stop here")

    monkeypatch.setattr(pipeline, "fetch_prices", fake_prices)
    # keep the run offline past the price stage: the enrichment blocks are
    # all best-effort, so stub their entry points to fail fast
    import forensic_viz.segments as segments
    import forensic_viz.rates as rates
    import forensic_viz.estimates as estimates
    monkeypatch.setattr(segments, "fetch_segment_data",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("off")))
    monkeypatch.setattr(rates, "build_wacc",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("off")))
    monkeypatch.setattr(estimates, "fetch_growth_estimates",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("off")))
    ev = threading.Event()  # provided but never set
    d = pipeline.build_dashboard_data("TESTCO", cancel=ev)
    assert seen.get("reached") is True
    assert d.ticker == "TESTCO"
    assert d.price_error  # prices waived, not fatal — same as before FIX-12g

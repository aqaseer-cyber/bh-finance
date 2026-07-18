"""FIX-17f: FMP-first consensus (EDGAR-actual base), Yahoo fallback
routing, the anchors readout label, and the estimates card. Offline."""
import datetime as dt
from types import SimpleNamespace

import matplotlib
matplotlib.use("Agg")

import pytest

from forensic_viz import config
from forensic_viz.estimates import parse_fmp_estimates
from forensic_viz.metrics import DashboardData

ROWS = [
    {"date": "2028-12-31", "revenueAvg": 40e9},
    {"date": "2027-12-31", "revenueAvg": 37e9, "revenueLow": 35e9,
     "revenueHigh": 39e9},
    {"date": "2026-12-31", "revenueAvg": 34.7e9, "revenueLow": 33.9e9,
     "revenueHigh": 36.1e9, "numAnalystsRevenue": 32},
    {"date": "2025-12-31", "revenueAvg": 33.5e9},   # archived consensus
    {"date": "2024-12-31", "revenueAvg": 31.4e9},
]


def test_parse_fmp_estimates_grounds_on_edgar_actual():
    est = parse_fmp_estimates(ROWS, actual_rev=33.2e9,
                              actual_fy_year=2025)
    assert est is not None
    assert est["g_avg"] == pytest.approx(34.7e9 / 33.2e9 - 1.0)
    assert est["g_low"] == pytest.approx(33.9e9 / 33.2e9 - 1.0)
    assert est["g_high"] == pytest.approx(36.1e9 / 33.2e9 - 1.0)
    assert est["n_analysts"] == 32
    assert est["source"] == "FMP consensus"
    assert "EDGAR base" in est["period"]


def test_parse_fmp_estimates_guards():
    assert parse_fmp_estimates([], 33e9, 2025) is None
    assert parse_fmp_estimates(ROWS, None, 2025) is None
    assert parse_fmp_estimates(ROWS, 33e9, 2019) is None  # no next-FY row
    # degenerate spread rejected
    bad = [{"date": "2026-12-31", "revenueAvg": 34e9,
            "revenueLow": 40e9, "revenueHigh": 30e9}]
    assert parse_fmp_estimates(bad, 33e9, 2025) is None


def test_fetch_growth_estimates_prefers_fmp(monkeypatch):
    from forensic_viz import estimates as est_mod
    monkeypatch.setattr(config, "FMP_API_KEY", "k")
    monkeypatch.setattr(est_mod, "fetch_estimates_rows",
                        lambda ticker, cache=None: ROWS)
    out = est_mod.fetch_growth_estimates(
        "PYPL", cache=None, actual_rev=33.2e9, actual_fy_year=2025)
    assert out["source"] == "FMP consensus"


def test_anchor_readout_names_fmp():
    from forensic_viz.anchors import anchor_readout
    a = SimpleNamespace(
        seeds={"Bull": 0.045}, consensus=0.045,
        consensus_range=(0.02, 0.09), n_analysts=32,
        hist_cagr=0.09, fundamental=None, binding=None,
        details={"consensus": "FMP consensus (Rung 4)"})
    line = anchor_readout(a)
    assert "(FMP, n=32, Rung 4)" in line

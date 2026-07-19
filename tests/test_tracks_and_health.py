"""Track selection, solvency parsing, fluff filter, and PDF export."""
import datetime as dt

import pytest

from forensic_viz.dashboard import render_business, render_quality
from forensic_viz.edgar import parse_companyfacts
from forensic_viz.export import export_pdf
from forensic_viz.metrics import (
    DashboardData, apply_track, build_fundamental_metrics, compute_altman,
    set_adjusted_ni,
)
from tests.conftest import FY_YEARS, NI, _instant, _usd


def _metrics(testco_facts, track="auto", sic="3571"):
    d = DashboardData(ticker="T", company="T Inc", subtitle="",
                      generated=dt.date(2026, 7, 3))
    d.sic_code = sic
    apply_track(d, track)
    build_fundamental_metrics(parse_companyfacts(testco_facts, "T"), d)
    return d


def test_solvency_ratios_normalized_from_percent_units(testco_facts):
    gaap = testco_facts["facts"]["us-gaap"]
    # one filer tags 13.2 (percent), another 0.132 (decimal) — both must land
    # as fractions
    gaap["CommonEquityTierOneCapitalToRiskWeightedAssets"] = {
        "units": {"pure": [_instant(2024, 13.2), _instant(2025, 0.128)]}}
    d = _metrics(testco_facts, track="bank", sic="6022")
    assert d.track == "bank" and d.is_financial_sector
    assert d.cet1_ratio[-2] == pytest.approx(0.132)
    assert d.cet1_ratio[-1] == pytest.approx(0.128)
    # equity/assets fallback always computed
    assert d.equity_to_assets[-1] is not None


def test_track_override_changes_health_rendering(tmp_path, testco_facts):
    bank = _metrics(testco_facts, track="bank")
    compute_altman(bank)
    assert all(z is None for z in bank.altman_z)  # suppressed for financials
    out = tmp_path / "bank_health.png"
    render_quality(bank, str(out))
    assert out.exists()

    standard = _metrics(testco_facts, track="standard")
    standard.fy_prices = [10.0] * len(standard.fy_labels)
    compute_altman(standard)
    assert any(z is not None for z in standard.altman_z)


def test_adjustment_burden_fluff_filter(testco_facts):
    d = _metrics(testco_facts)
    gaap_ni = NI[2025]
    set_adjusted_ni(d, gaap_ni * 1.35)  # 35% adjusted-over-GAAP gap
    assert d.adjustment_burden == pytest.approx(0.35)
    set_adjusted_ni(d, None)
    assert d.adjustment_burden is None


def test_pdf_export_bundles_pages(tmp_path, testco_facts):
    d = _metrics(testco_facts)
    fig1 = render_business(d)
    fig2 = render_quality(d)
    out = tmp_path / "report.pdf"
    export_pdf([fig1, fig2, None], str(out))  # None page skipped
    blob = out.read_bytes()
    assert blob[:5] == b"%PDF-"
    assert blob.count(b"/Type /Page\n") == 2 or b"/Count 2" in blob

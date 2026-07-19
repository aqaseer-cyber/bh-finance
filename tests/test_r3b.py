"""v3 R3b — the six-section report (docs/V3_R3_EXPORT_DESIGN.md).

P1 base-quality box above the rating · DRAFT watermark discipline ·
delta-vs-prior · run identity · exit `trimmed (raw)` + divergence note ·
principle-7 Altman suppression · a3 stale guard on the SBC panel ·
zero-ellipsis gate · untruncated appendix · portrait fill tool.
"""
import datetime as dt
import json
from pathlib import Path

import pytest

from conftest import build_testco_companyfacts
from forensic_viz import config
from forensic_viz.dashboard import (
    A4P_H, FIG_W, render_appendix, render_decision, render_expectations,
    render_quality, render_report,
)
from forensic_viz.edgar import parse_companyfacts
from forensic_viz.export import export_pdf
from forensic_viz.metrics import (
    DashboardData, apply_track, build_fundamental_metrics,
    build_price_metrics, compute_altman,
)
from forensic_viz.prices import PriceSeries
from forensic_viz.reconcile import AuditEntry, AuditReport
from forensic_viz.valuation import CaseInputs, ValuationInputs, build_valuation
from forensic_viz.verdict import build_verdict

FIXTURES = Path(__file__).parent / "fixtures"


def _testco(with_prices=True, thesis=""):
    d = DashboardData(ticker="TESTCO", company="TESTCO INC", subtitle="fx",
                      generated=dt.date(2026, 7, 19))
    d.sic_code = "3571"
    apply_track(d, "auto")
    build_fundamental_metrics(
        parse_companyfacts(build_testco_companyfacts(), "TESTCO"), d)
    if with_prices:
        prices = json.loads((FIXTURES / "aapl_weekly_5y.json").read_text())
        build_price_metrics(PriceSeries(
            symbol="TESTCO",
            dates=[dt.date.fromisoformat(s) for s in prices["dates"]],
            closes=prices["close"], source="fixture"), d)
        compute_altman(d)
    if thesis:
        d.thesis = thesis
        d.terminal_risk = "fixture terminal risk"
    return d


def _valued(d, rating="Buy"):
    inputs = ValuationInputs(
        method="dcf", discount_rate=0.09,
        cases={"Bear": CaseInputs(g0=0.02, g_term=0.02),
               "Base": CaseInputs(g0=0.05, g_term=0.025),
               "Bull": CaseInputs(g0=0.08, g_term=0.03)})
    res = build_valuation(d, inputs)
    return res, build_verdict(d, inputs, res, rating=rating)


def _all_texts(figs):
    if not isinstance(figs, list):
        figs = [figs]
    out = []
    for fig in figs:
        out += [t.get_text() for t in fig.texts]
        out += [t.get_text() for ax in fig.axes for t in ax.texts]
    return out


# ------------------------------------------------------ pages & geometry

def test_report_is_at_least_six_portrait_pages():
    d = _testco(thesis="t")
    res, v = _valued(d)
    figs = render_report(d, res, v)
    assert len(figs) >= 6
    for fig in figs:
        w, h = fig.get_size_inches()
        assert (w, h) == (pytest.approx(FIG_W), pytest.approx(A4P_H))


def test_fill_tool_default_is_portrait_per_page(tmp_path):
    from tools.check_pdf_fill import check
    d = _testco(thesis="t")
    out = tmp_path / "r.pdf"
    export_pdf(render_report(d), str(out))
    assert check(str(out), None) == 0


# --------------------------------------------------- P1 decision content

def test_base_quality_box_renders_above_the_rating():
    """Principle 3: a challenged base prints its red-keyed box BEFORE the
    rating (the MELI shape — a financial signature inside a printed Buy)."""
    d = _testco(thesis="t")
    d.sic_code = "6199"                       # financial signature (a1)
    res, v = _valued(d, rating="Buy")
    fig = render_decision(d, res, v)
    per_axes = [" ".join(t.get_text() for t in ax.texts) for ax in fig.axes]
    i_quality = next(i for i, s in enumerate(per_axes)
                     if "BASE QUALITY — CHALLENGED" in s)
    i_rating = next(i for i, s in enumerate(per_axes) if "Buy" in s)
    assert i_quality < i_rating
    joined = " ".join(per_axes)
    assert "conditional on the base" in joined


def test_unchallenged_base_is_still_declared():
    d = _testco(thesis="t")
    res, v = _valued(d)
    texts = " ".join(_all_texts(render_decision(d, res, v)))
    assert "Base quality: unchallenged" in texts   # no silent absence


def test_delta_vs_prior_and_first_run_lines():
    d = _testco(thesis="t")
    res, v = _valued(d)
    prior = {"fv_avg": v.fv_avg / 1.10, "recorded_at": "2026-06-30T09:00:00"}
    texts = " ".join(_all_texts(render_decision(d, res, v, prior=prior)))
    assert "on 2026-06-30" in texts and "Δ+10.0%" in texts
    texts2 = " ".join(_all_texts(render_decision(d, res, v, prior=None)))
    assert "first recorded run" in texts2


def test_run_identity_deterministic_and_never_leaks_keys(monkeypatch):
    from forensic_viz.runid import provider_set, run_identity
    monkeypatch.setattr(config, "FMP_API_KEY", "sekret-key-material")
    d = _testco()
    res, v = _valued(d)
    rid1, ih1 = run_identity(d, res)
    rid2, ih2 = run_identity(d, res)
    assert (rid1, ih1) == (rid2, ih2)
    assert len(rid1) == 8 and len(ih1) == 10
    # a different valuation is a different input set
    res2, _ = _valued(d, rating="Hold")
    res2._inputs.discount_rate = 0.10
    assert run_identity(d, res2)[1] != ih1
    # provider names only — never key material
    prov = provider_set(d)
    assert "FMP" in prov and "sekret" not in prov
    texts = " ".join(_all_texts(render_decision(d, res, v)))
    assert f"Run {rid1}" in texts and ih1 in texts
    assert "sekret" not in texts


# ------------------------------------------------------- DRAFT discipline

def test_draft_watermark_on_every_page_until_inputs_land():
    d = _testco()                       # no thesis, no terminal risk
    figs = render_report(d)
    for fig in figs:
        assert any(t.get_text() == "DRAFT" for t in fig.texts)
    texts = " ".join(_all_texts(figs[0]))
    assert "analyst inputs missing" in texts
    d2 = _testco(thesis="a real thesis")
    for fig in render_report(d2):
        assert not any(t.get_text() == "DRAFT" for t in fig.texts)


# ------------------------------------------------- P2 exit check (a2 note)

def test_exit_check_shows_trimmed_raw_and_divergence_note():
    d = _testco(thesis="t")
    res, v = _valued(d)
    res.exit_check = {
        "multiple": 12.0, "ebit5": 5e8, "eq5_ps": 55.0,
        "fv_today": v.fv_avg * 1.6, "return_5y": 0.09,
        "multiple_trimmed": 15.0, "fv_today_trimmed": v.fv_avg * 1.9,
        "return_5y_trimmed": 0.12,
    }
    texts = " ".join(_all_texts(render_expectations(d, res, v)))
    assert "15.0x trimmed (12.0x raw median)" in texts
    assert "Divergence:" in texts and "reconcile before sizing" in texts
    res.exit_check["fv_today"] = v.fv_avg * 1.05
    res.exit_check["fv_today_trimmed"] = v.fv_avg * 0.95
    texts2 = " ".join(_all_texts(render_expectations(d, res, v)))
    assert "Divergence:" not in texts2


# ------------------------------------------- P4 principle-7 + a3 guard

def test_altman_suppressed_for_financial_signature_filer():
    d = _testco(thesis="t")
    d.sic_code = "6199"        # standard track, finance SIC (MELI shape)
    fig = render_quality(d)
    texts = " ".join(_all_texts(fig))
    assert "Altman Standard-Mfg suppressed" in texts
    assert "principle 7" in texts


def test_sbc_panel_carries_stale_note_when_series_dies():
    d = _testco(thesis="t")
    d.sbc = list(d.sbc)
    d.sbc[-1] = d.sbc[-2] = None       # the tag dies two years early
    texts = " ".join(_all_texts(render_quality(d)))
    assert "series ends FY2023" in texts


# ------------------------------------------------------- P6 + ellipses

def test_appendix_prints_every_audit_row_including_restated():
    d = _testco(thesis="t")
    rep = AuditReport(checked=50, matched=10, sources=["FMP"])
    for i in range(40):
        rep.entries.append(AuditEntry(
            f"Item {i}", f"FY{1986 + i}", 1e9 + i, 2e9,
            "FMP", "restated" if i % 2 else "divergent"))
    d.audit_report = rep
    figs = render_appendix(d)
    texts = " ".join(_all_texts(figs))
    for i in range(40):
        assert f"Item {i}" in texts       # untruncated by construction
    assert "RESTATED (EDGAR carries the recast" in texts


def test_zero_ellipsis_gate_across_the_whole_report():
    """Principle 5: ellipses in a deliverable are a defect."""
    d = _testco(thesis="t")
    d.tags_used = dict(d.tags_used)
    d.tags_used["fake_concept"] = "A" * 400   # would have been clipped once
    res, v = _valued(d)
    res.warnings = ["w" * 300]
    figs = render_report(d, res, v)
    offenders = [t for t in _all_texts(figs) if "…" in t]
    assert offenders == []

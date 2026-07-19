"""FIX-12c: per-page A4 orientation + fill guarantees."""
import datetime as dt

import pytest

from forensic_viz.dashboard import (
    A4_ASPECT, A4L_H, A4P_H, FIG_W, render_report,
)
from forensic_viz.export import A4_PT, export_pdf, page_size_for


def test_orientation_choice():
    assert page_size_for(12.8, 18.10) == A4_PT              # portrait
    assert page_size_for(12.8, 9.05) == (A4_PT[1], A4_PT[0])  # landscape
    assert page_size_for(10.0, 12.0) == A4_PT               # ratio 1.2 edge
    assert page_size_for(10.0, 11.9) == (A4_PT[1], A4_PT[0])


def test_tuned_heights_fill_a4():
    # the five page heights land ≥ 99% fill by construction
    assert A4P_H / FIG_W == pytest.approx(A4_ASPECT, rel=1e-2)
    assert FIG_W / A4L_H == pytest.approx(A4_ASPECT, rel=1e-2)


def test_fill_check_tool_on_synthetic_pdf(tmp_path):
    from matplotlib.figure import Figure

    from tools.check_pdf_fill import check, page_fill
    figs = [Figure(figsize=(FIG_W, A4P_H)), Figure(figsize=(FIG_W, A4L_H))]
    out = tmp_path / "two.pdf"
    export_pdf(figs, str(out))
    rc = check(str(out), [(FIG_W, A4P_H), (FIG_W, A4L_H)])
    assert rc == 0
    assert page_fill(FIG_W, A4P_H) >= 0.99
    assert page_fill(FIG_W, A4L_H) >= 0.99
    # the old worst offender (verdict at 7.9in on portrait) was 44%
    assert page_fill(FIG_W, 7.9) >= 0.85  # landscape now rescues it


def test_report_pages_all_portrait_a4(testco_facts):
    """v3 R3b: A4 portrait THROUGHOUT — every section, appendix included."""
    from forensic_viz.edgar import parse_companyfacts
    from forensic_viz.metrics import (
        DashboardData, apply_track, build_fundamental_metrics,
    )
    d = DashboardData(ticker="T", company="T Inc", subtitle="",
                      generated=dt.date(2026, 7, 3))
    d.sic_code = "3571"
    apply_track(d, "auto")
    build_fundamental_metrics(parse_companyfacts(testco_facts, "T"), d)
    figs = render_report(d)
    assert len(figs) >= 6
    for fig in figs:
        w, h = fig.get_size_inches()
        assert w == pytest.approx(FIG_W)
        assert h == pytest.approx(A4P_H)

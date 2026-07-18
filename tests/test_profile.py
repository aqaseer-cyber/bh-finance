"""FIX-17d: company profile — merge precedence (EDGAR identity wins),
employee parsing, keyless degradation, and the card render. Offline."""
import datetime as dt

import matplotlib
matplotlib.use("Agg")

import pytest

from forensic_viz import config
from forensic_viz.metrics import DashboardData
from forensic_viz.profile import CompanyProfile, build_profile, fetch_profile

FMP_ROW = {
    "companyName": "PayPal Holdings, Inc. (FMP spelling)",
    "description": "PayPal Holdings, Inc. provides a worldwide "
                   "technological framework that facilitates digital "
                   "financial transactions costing $0.30 per unit " * 20,
    "website": "https://www.paypal.com",
    "fullTimeEmployees": "24,400",
    "country": "US",
    "exchangeShortName": "NASDAQ",
    "sector": "Financial Services",
    "industry": "Financial - Credit Services",
    "ipoDate": "2015-07-06",
}


def _d():
    d = DashboardData(ticker="PYPL", company="PayPal Holdings, Inc.",
                      subtitle="", generated=dt.date(2026, 7, 18))
    d.sic_code = "7389"
    return d


def test_build_profile_merges_with_edgar_identity_winning():
    p = build_profile(_d(), FMP_ROW)
    assert p.name == "PayPal Holdings, Inc."       # EDGAR name, not FMP's
    assert p.employees == 24400                    # "24,400" parsed
    assert p.website == "https://www.paypal.com"
    assert p.exchange == "NASDAQ"
    assert p.sic_code == "7389"
    assert p.ipo_date == "2015-07-06"
    assert "SEC EDGAR" in p.sources and "FMP profile" in p.sources
    assert "display only" in p.sources


def test_build_profile_without_provider_row():
    p = build_profile(_d(), None)
    assert p.name == "PayPal Holdings, Inc."
    assert p.description == "" and p.employees is None
    assert "FMP" not in p.sources


def test_employee_parsing_edges():
    assert build_profile(_d(), {"fullTimeEmployees": "0"}).employees is None
    assert build_profile(_d(), {"fullTimeEmployees": "n/a"}).employees is None
    assert build_profile(_d(), {"fullTimeEmployees": 91}).employees == 91


def test_fetch_profile_keyless_is_edgar_only(monkeypatch):
    monkeypatch.setattr(config, "FMP_API_KEY", "")
    p = fetch_profile(_d(), cache=None)
    assert isinstance(p, CompanyProfile)
    assert p.name and "FMP" not in p.sources


def test_profile_card_renders_and_clips():
    from forensic_viz.explore import PROFILE_CLIP_LINES, profile_card
    d = _d()
    d.profile = build_profile(d, FMP_ROW)
    fig = profile_card(d, dpi=80, width_in=8.0)
    texts = [t.get_text() for ax in fig.axes for t in ax.texts]
    assert any("PayPal Holdings" in t for t in texts)
    assert any("24,400" in t for t in texts)
    assert any("feeds no calculation" in t for t in texts)
    # clipped: exactly the clip budget of description lines + ellipsis
    desc_lines = [t for t in texts if "\\$0.30" in t or "worldwide" in t]
    assert len(desc_lines) <= PROFILE_CLIP_LINES
    assert any(t.rstrip().endswith("…") for t in texts)
    assert any("full description" in t for t in texts)   # click hint

    bare = DashboardData(ticker="T", company="", subtitle="",
                         generated=dt.date(2026, 7, 18))
    fig2 = profile_card(bare, dpi=80, width_in=8.0)
    texts2 = [t.get_text() for ax in fig2.axes for t in ax.texts]
    assert any("profile unavailable" in t.lower() for t in texts2)


def test_profile_card_expands_with_dynamic_height():
    """FIX-17d.1: expanded=True renders EVERY wrapped line on a taller
    figure — layout is cursor-based, so nothing can overlap."""
    from forensic_viz.explore import PROFILE_CLIP_LINES, profile_card
    d = _d()
    d.profile = build_profile(d, FMP_ROW)
    clipped = profile_card(d, dpi=80, width_in=8.0, expanded=False)
    full = profile_card(d, dpi=80, width_in=8.0, expanded=True)

    def desc_lines(fig):
        return [t.get_text() for ax in fig.axes for t in ax.texts
                if "framework" in t.get_text()
                or "\\$0.30" in t.get_text()]

    assert len(desc_lines(full)) > PROFILE_CLIP_LINES
    assert full.get_figheight() > clipped.get_figheight()
    texts = [t.get_text() for ax in full.axes for t in ax.texts]
    assert any("collapse" in t for t in texts)
    assert not any(t.rstrip().endswith("…") for t in texts
                   if "framework" in t or "\\$0.30" in t)

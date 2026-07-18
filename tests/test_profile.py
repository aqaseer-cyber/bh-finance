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

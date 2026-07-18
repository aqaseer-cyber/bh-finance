"""Forensic Stock Viz — five-phase forensic stock report from primary sources.

Fundamentals from SEC EDGAR XBRL (as filed), daily prices from Tiingo
(keyed) with Stooq fallback,
rendered as a five-page report (A4 PDF / desktop GUI with Explore cards) and
an exporter that fills the forensic_valuation_model_v3.xlsx shell.
"""
from .config import APP_VERSION as __version__  # noqa: F401

"""Runtime configuration.

The SEC requires a User-Agent that identifies the requester and gives a
contact address (https://www.sec.gov/os/accessing-edgar-data). Set the
SEC_EDGAR_USER_AGENT environment variable to override the default.
"""
from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "ForensicStockViz"
APP_VERSION = "2.0.0"

SEC_USER_AGENT = os.environ.get(
    "SEC_EDGAR_USER_AGENT",
    f"{APP_NAME}/{APP_VERSION} (contact: redacted@example.com)",
)

# Number of fiscal years shown on the dashboard; one extra is fetched for
# year-over-year growth and average-asset calculations.
DISPLAY_YEARS = 10
FETCH_YEARS = DISPLAY_YEARS + 1

PRICE_YEARS = 10

# Phase-3 health-check defaults. house_assumptions.md is not part of this
# export, so these are labeled ASSUMPTIONs (shown on the report) until the
# house file is provided.
RND_LIFE_YEARS = 5          # straight-line R&D capitalization life (n)
RND_MATERIALITY = 0.05      # capitalize only if avg R&D/revenue exceeds this
SLOAN_FLAG = 0.10           # |Sloan| flag threshold (master prompt §3.3)
ALTMAN_DISTRESS = 1.81      # Altman Z zone boundaries (original 1968 model)
ALTMAN_SAFE = 2.99

HTTP_TIMEOUT = 30  # seconds per request
HTTP_RETRIES = 3
SEC_MIN_INTERVAL = 0.15  # polite spacing between SEC calls (10 req/s cap)

# Cache TTLs in seconds
TTL_TICKER_MAP = 7 * 86400
TTL_SUBMISSIONS = 7 * 86400
TTL_COMPANYFACTS = 86400
TTL_PRICES = 6 * 3600
TTL_RATES = 12 * 3600

# Discount-rate build (master §4.0) — labeled ASSUMPTIONs until the house
# assumptions file is attached.
ERP_ASSUMPTION = 0.046        # Damodaran-style implied equity risk premium
DEBT_SPREAD_ASSUMPTION = 0.015  # r_d fallback spread over r_f
BETA_MIN_OBS = 40             # minimum weekly observations for the regression


def cache_dir() -> Path:
    """Per-user cache directory (LOCALAPPDATA on Windows, ~/.cache elsewhere)."""
    base = os.environ.get("LOCALAPPDATA")
    if base:
        root = Path(base)
    else:
        root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    d = root / APP_NAME / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d

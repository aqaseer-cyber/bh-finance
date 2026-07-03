"""Runtime configuration.

The SEC requires a User-Agent that identifies the requester and gives a
contact address (https://www.sec.gov/os/accessing-edgar-data). Set the
SEC_EDGAR_USER_AGENT environment variable to override the default.
"""
from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "ForensicStockViz"
APP_VERSION = "1.0.0"

SEC_USER_AGENT = os.environ.get(
    "SEC_EDGAR_USER_AGENT",
    f"{APP_NAME}/{APP_VERSION} (contact: redacted@example.com)",
)

# Number of fiscal years shown on the dashboard; one extra is fetched for
# year-over-year growth and average-asset calculations.
DISPLAY_YEARS = 5
FETCH_YEARS = DISPLAY_YEARS + 1

PRICE_YEARS = 5

HTTP_TIMEOUT = 30  # seconds per request
HTTP_RETRIES = 3
SEC_MIN_INTERVAL = 0.15  # polite spacing between SEC calls (10 req/s cap)

# Cache TTLs in seconds
TTL_TICKER_MAP = 7 * 86400
TTL_SUBMISSIONS = 7 * 86400
TTL_COMPANYFACTS = 86400
TTL_PRICES = 6 * 3600


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

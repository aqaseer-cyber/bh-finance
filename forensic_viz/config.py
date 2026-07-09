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

_UA_PLACEHOLDER = f"{APP_NAME}/{APP_VERSION} (contact: set SEC_EDGAR_USER_AGENT)"
SEC_USER_AGENT = os.environ.get("SEC_EDGAR_USER_AGENT") or _UA_PLACEHOLDER
UA_IS_PLACEHOLDER = SEC_USER_AGENT == _UA_PLACEHOLDER

UA_WARNING = ("SEC requires an identifying User-Agent — set SEC_EDGAR_USER_AGENT "
              "to 'name email' before heavy use.")

# Number of fiscal years shown on the dashboard; one extra is fetched for
# year-over-year growth and average-asset calculations.
DISPLAY_YEARS = 10
FETCH_YEARS = DISPLAY_YEARS + 1

PRICE_YEARS = 10

# GUI defaults persisted via the Settings dialog (FIX-12e)
GUI_DEFAULT_YEARS = DISPLAY_YEARS
USER_HOUSE_FILE = ""  # display-only echo of settings.json's house_file


def _app_data_dir() -> Path:
    """Per-user app-data root (LOCALAPPDATA on Windows, ~/.cache elsewhere) —
    the cache, ledger and settings.json all live under here."""
    base = os.environ.get("LOCALAPPDATA")
    if base:
        root = Path(base)
    else:
        root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return root / APP_NAME


def settings_path() -> Path:
    """settings.json next to the cache and ledger (FIX-12e)."""
    return _app_data_dir() / "settings.json"


def load_user_settings() -> dict:
    """Read settings.json; absence or corruption is never an error → {}."""
    import json

    try:
        with open(settings_path(), "r", encoding="utf-8") as fh:
            out = json.load(fh)
        return out if isinstance(out, dict) else {}
    except Exception:
        return {}


def save_user_settings(s: dict) -> None:
    import json

    p = settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(s, indent=2), encoding="utf-8")


def apply_user_settings(s: dict) -> None:
    """Apply persisted settings. Precedence: env var > settings.json >
    placeholder — an env var always wins; a saved value only fills the gap.
    edgar builds its HTTP session per fetch and reads config.SEC_USER_AGENT
    at that moment, so mutating the module attribute here reaches every
    later request."""
    global SEC_USER_AGENT, UA_IS_PLACEHOLDER, GUI_DEFAULT_YEARS, USER_HOUSE_FILE
    ua = str(s.get("sec_user_agent") or "").strip()
    if ua and not os.environ.get("SEC_EDGAR_USER_AGENT"):
        SEC_USER_AGENT = ua
        UA_IS_PLACEHOLDER = False
    USER_HOUSE_FILE = str(s.get("house_file") or "")
    try:
        yrs = int(s.get("default_years", 0))
    except (TypeError, ValueError):
        yrs = 0
    if yrs in (3, 5, 7, 10):  # mirrors gui.YEAR_CHOICES
        GUI_DEFAULT_YEARS = yrs


def _load_house() -> dict:
    """Load house_assumptions.toml if present (env override, cwd, or repo root).

    Real house values are never committed — only house_assumptions.example.toml
    (with the code defaults) ships. When a file is found, its keys override the
    ASSUMPTION defaults below and the report labels flip ASSUMPTION -> house.
    """
    import pathlib

    cands = []
    env = os.environ.get("HOUSE_ASSUMPTIONS_FILE")
    if env:
        cands.append(pathlib.Path(env))
    saved = load_user_settings().get("house_file")  # Settings dialog (FIX-12e)
    if saved:
        cands.append(pathlib.Path(saved))
    cands += [pathlib.Path.cwd() / "house_assumptions.toml",
              pathlib.Path(__file__).resolve().parent.parent / "house_assumptions.toml"]
    for c in cands:
        try:
            if c.is_file():
                try:
                    import tomllib
                except ModuleNotFoundError:
                    import tomli as tomllib  # py3.10
                with open(c, "rb") as fh:
                    out = dict(tomllib.load(fh))
                out["_path"] = str(c)
                return out
        except Exception:
            continue
    return {}


_HOUSE = _load_house()
HOUSE_LOADED = bool(_HOUSE)
HOUSE_PATH = _HOUSE.get("_path", "")

# Phase-3 health-check defaults + discount-rate/stress ASSUMPTIONs. Overridable
# via house_assumptions.toml (FIX-7); labeled on the report as ASSUMPTION when
# no house file is loaded, "house" when one is.
ERP_ASSUMPTION          = float(_HOUSE.get("erp", 0.046))
DEBT_SPREAD_ASSUMPTION  = float(_HOUSE.get("debt_spread", 0.015))
GDP_CAP                 = float(_HOUSE.get("gdp_cap", 0.035))
RND_LIFE_YEARS          = int(_HOUSE.get("rnd_life_years", 5))
RND_MATERIALITY         = float(_HOUSE.get("rnd_materiality", 0.05))
SLOAN_FLAG              = float(_HOUSE.get("sloan_flag", 0.10))
BETA_WINDOW_YEARS       = int(_HOUSE.get("beta_window_years", 5))
STANDARD_FCFF_SHOCK     = float(_HOUSE.get("standard_fcff_shock", -0.05))
BANK_NIM_SHOCK          = float(_HOUSE.get("bank_nim_shock", -0.01))
INSURANCE_CR_SHOCK      = float(_HOUSE.get("insurance_cr_shock", 0.05))
REIT_YIELD_SHOCK        = float(_HOUSE.get("reit_yield_shock", 0.01))

# FIX-11: income-statement basis coherence tolerance (house-overridable)
IS_TIE_TOL = float(_HOUSE.get("is_tie_tol", 0.02))

ALTMAN_DISTRESS = 1.81      # Altman Z zone boundaries (original 1968 model —
ALTMAN_SAFE = 2.99          # a fixed academic constant, not a house parameter)
BETA_MIN_OBS = 40           # minimum weekly observations for the regression

HTTP_TIMEOUT = 30  # seconds per request
HTTP_RETRIES = 3
SEC_MIN_INTERVAL = 0.15  # polite spacing between SEC calls (10 req/s cap)

# Cache TTLs in seconds
TTL_TICKER_MAP = 7 * 86400
# Filed artifacts (instances, linkbases, FilingSummary) are immutable —
# FIX-13d; FIX-10b reuses this key for the instance-history fetch.
TTL_FILING_INSTANCE = 365 * 86400
TTL_SUBMISSIONS = 7 * 86400
TTL_COMPANYFACTS = 86400
TTL_PRICES = 6 * 3600
TTL_RATES = 12 * 3600

# FIX-10: segment history — house-overridable (FIX-10e;
# TTL_FILING_INSTANCE is defined once above, at FIX-13d)
SEGMENT_HISTORY_YEARS   = int(_HOUSE.get("segment_history_years", 10))
SEGMENT_TIE_TOL         = float(_HOUSE.get("segment_tie_tol", 0.02))
SEGMENT_MAX_INSTANCE_MB = float(_HOUSE.get("segment_max_instance_mb", 40))
# ticker -> {old member label: canonical label}; analyst-declared identity
# across a segment recast — never fuzzy-matched
SEGMENT_ALIASES = {
    str(t).upper(): {str(k): str(v) for k, v in (m or {}).items()}
    for t, m in (_HOUSE.get("segment_aliases", {}) or {}).items()}

def cache_dir() -> Path:
    """Per-user cache directory (LOCALAPPDATA on Windows, ~/.cache elsewhere)."""
    d = _app_data_dir() / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d

"""Discount-rate build (master §4.0) from open, keyless sources.

    WACC = E/V·r_e + D/V·r_d·(1−τ),   r_e = r_f + β·ERP

- r_f  — live 10-Y UST: FRED fredgraph CSV (keyless), Stooq 10-year yield as
         fallback. Stamped with value/date/source per master §2 (rate refresh).
- β    — Blume-adjusted regression beta (0.67·β_raw + 0.33) from weekly
         returns of the stock vs the S&P 500 over the shared price history
         (the master's stated fallback when bottom-up relevering isn't
         available; the sector unlevered-beta table isn't in this export).
- ERP  — house ASSUMPTION (config.ERP_ASSUMPTION), Damodaran-style implied
         premium; override in config or the dialog.
- r_d  — effective: interest expense / average total debt; falls back to
         r_f + spread ASSUMPTION when interest isn't tagged.
- τ    — effective tax rate from the filing (metrics).

Every leg is labeled in `notes`; anything missing degrades gracefully and the
analyst can always override the final number in the dialog / CLI.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import requests

from . import config
from .cache import Cache
from .metrics import DashboardData, fmt_pct

FRED_DGS10_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10"
STOOQ_10Y_URL = "https://stooq.com/q/d/l/?s=10usy.b&i=d"
STOOQ_SPX_URL = "https://stooq.com/q/d/l/?s=%5Espx&i=d"
YAHOO_SPX_URL = ("https://query1.finance.yahoo.com/v8/finance/chart/"
                 "%5EGSPC?range=10y&interval=1d")


@dataclass
class WaccBuild:
    r_f: Optional[float] = None
    r_f_date: Optional[dt.date] = None
    r_f_source: str = ""
    beta_raw: Optional[float] = None
    beta: Optional[float] = None           # Blume-adjusted
    erp: float = config.ERP_ASSUMPTION
    r_e: Optional[float] = None
    r_d: Optional[float] = None
    tax: Optional[float] = None
    e_weight: Optional[float] = None
    d_weight: Optional[float] = None
    wacc: Optional[float] = None
    notes: List[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.wacc is None and self.r_e is None:
            return "discount-rate build unavailable — enter the rate manually"
        parts = []
        if self.r_f is not None:
            src = f"{self.r_f_source} {self.r_f_date.isoformat()}" if self.r_f_date else self.r_f_source
            parts.append(f"r_f {fmt_pct(self.r_f)} ({src})")
        if self.beta is not None:
            parts.append(f"β {self.beta:.2f} (Blume, raw {self.beta_raw:.2f})")
        parts.append(f"ERP {fmt_pct(self.erp)} "
                     f"({'house' if config.HOUSE_LOADED else 'ASSUMPTION'})")
        if self.r_e is not None:
            parts.append(f"r_e {fmt_pct(self.r_e)}")
        if self.wacc is not None:
            parts.append(f"r_d {fmt_pct(self.r_d)}, τ {fmt_pct(self.tax)}, "
                         f"E/V {fmt_pct(self.e_weight)} → WACC {fmt_pct(self.wacc)}")
        return " · ".join(parts)


# ---------------------------------------------------------------- fetchers

def _get_text(url: str, cache: Cache, ttl: float) -> Optional[str]:
    cached = cache.get(url, ttl)
    if cached is not None:
        return cached
    try:
        resp = requests.get(url, timeout=config.HTTP_TIMEOUT, headers={
            "User-Agent": f"{config.APP_NAME}/{config.APP_VERSION}"})
        resp.raise_for_status()
        text = resp.text
        cache.put(url, text)
        return text
    except requests.RequestException:
        return None


def parse_fred_csv(text: str) -> Optional[Tuple[float, dt.date]]:
    """fredgraph.csv: DATE,DGS10 rows; '.' marks holidays. Yield in percent."""
    last = None
    for row in csv.reader(io.StringIO(text)):
        if len(row) != 2 or row[0].lower() in ("date", "observation_date"):
            continue
        try:
            d = dt.date.fromisoformat(row[0])
            v = float(row[1])
        except ValueError:
            continue
        if 0.0 < v < 25.0:
            last = (v / 100.0, d)
    return last


def parse_stooq_yield_csv(text: str) -> Optional[Tuple[float, dt.date]]:
    last = None
    for row in csv.DictReader(io.StringIO(text)):
        try:
            d = dt.date.fromisoformat(row["Date"])
            v = float(row["Close"])
        except (KeyError, TypeError, ValueError):
            continue
        if 0.0 < v < 25.0:
            last = (v / 100.0, d)
    return last


def fetch_risk_free(cache: Optional[Cache] = None):
    """(rate, date, source) for the 10-Y UST, or (None, None, '')."""
    cache = cache or Cache()
    text = _get_text(FRED_DGS10_URL, cache, config.TTL_RATES)
    if text:
        parsed = parse_fred_csv(text)
        if parsed:
            return parsed[0], parsed[1], "FRED DGS10"
    text = _get_text(STOOQ_10Y_URL, cache, config.TTL_RATES)
    if text:
        parsed = parse_stooq_yield_csv(text)
        if parsed:
            return parsed[0], parsed[1], "Stooq 10USY.B"
    return None, None, ""


def fetch_index_closes(cache: Optional[Cache] = None):
    """S&P 500 daily closes as {date: close} for the beta regression."""
    cache = cache or Cache()
    text = _get_text(STOOQ_SPX_URL, cache, config.TTL_PRICES)
    if text:
        out = {}
        for row in csv.DictReader(io.StringIO(text)):
            try:
                out[dt.date.fromisoformat(row["Date"])] = float(row["Close"])
            except (KeyError, TypeError, ValueError):
                continue
        if len(out) > 250:
            return out
    try:  # Yahoo fallback
        resp = requests.get(YAHOO_SPX_URL, timeout=config.HTTP_TIMEOUT, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        resp.raise_for_status()
        payload = resp.json()
        result = payload["chart"]["result"][0]
        out = {}
        for ts, c in zip(result["timestamp"],
                         result["indicators"]["quote"][0]["close"]):
            if c:
                out[dt.datetime.fromtimestamp(ts, dt.timezone.utc).date()] = float(c)
        if len(out) > 250:
            return out
    except Exception:
        pass
    return None


# ------------------------------------------------------------------- beta

def compute_beta(stock_dates, stock_closes, index_closes: dict,
                 week_step: int = 5) -> Optional[float]:
    """Raw regression beta on weekly log-ish returns over the common history."""
    if not stock_dates or not index_closes:
        return None
    common = [(d, c, index_closes[d]) for d, c in zip(stock_dates, stock_closes)
              if d in index_closes and c > 0 and index_closes[d] > 0]
    if len(common) < config.BETA_MIN_OBS * 2:
        return None
    sampled = common[::week_step]
    rs, rm = [], []
    for (d0, s0, m0), (d1, s1, m1) in zip(sampled, sampled[1:]):
        rs.append(s1 / s0 - 1.0)
        rm.append(m1 / m0 - 1.0)
    n = len(rs)
    if n < config.BETA_MIN_OBS:
        return None
    mean_s, mean_m = sum(rs) / n, sum(rm) / n
    var_m = sum((x - mean_m) ** 2 for x in rm) / n
    if var_m <= 0:
        return None
    cov = sum((a - mean_s) * (b - mean_m) for a, b in zip(rs, rm)) / n
    return cov / var_m


def blume_adjust(beta_raw: float) -> float:
    return 0.67 * beta_raw + 0.33


# ------------------------------------------------------------------- build

def _latest(seq):
    for v in reversed(seq or []):
        if v is not None:
            return v
    return None


def build_wacc(d: DashboardData, cache: Optional[Cache] = None,
               offline: bool = False, price_dates=None, price_closes=None) -> WaccBuild:
    """Assemble the §4.0 discount-rate build; every gap becomes a note.

    The beta regression uses `price_dates`/`price_closes` when provided (the
    pipeline passes a fixed BETA_WINDOW_YEARS slice so the display `--years`
    trim can't move WACC); otherwise it falls back to `d.price_*` for
    back-compatibility with direct callers and tests.
    """
    b = WaccBuild()
    cache = cache or Cache()
    if config.HOUSE_LOADED:
        b.notes.append(f"house assumptions loaded from {config.HOUSE_PATH}")
    beta_dates = price_dates if price_dates is not None else d.price_dates
    beta_closes = price_closes if price_closes is not None else d.price_closes

    if not offline:
        b.r_f, b.r_f_date, b.r_f_source = fetch_risk_free(cache)
    if b.r_f is None:
        b.notes.append("live 10-Y UST unavailable — enter WACC/r_e manually "
                       "(master §2: never compute off a stored rate)")
        return b

    index = None if offline else fetch_index_closes(cache)
    raw = compute_beta(beta_dates, beta_closes, index) if index else None
    if raw is not None and -1.0 < raw < 4.0:
        b.beta_raw = raw
        b.beta = blume_adjust(raw)
        b.notes.append("β: Blume-adjusted regression vs S&P 500 (bottom-up "
                       "relevered preferred but sector table not available)")
        label = "house" if config.HOUSE_LOADED else "ASSUMPTION"
        b.notes.append(
            f"β window {config.BETA_WINDOW_YEARS}y weekly ({label}; house "
            "prefers bottom-up relevered)")
    else:
        b.beta_raw, b.beta = None, 1.0
        b.notes.append("β regression unavailable — β=1.0 ASSUMPTION")

    b.r_e = b.r_f + b.beta * b.erp
    b.tax = d.effective_tax_rate if d.effective_tax_rate is not None else 0.21

    interest = _latest(d.interest_expense)
    debt_now = _latest(d.total_debt)
    debt_prev = None
    if d.total_debt and len(d.total_debt) >= 2:
        debt_prev = d.total_debt[-2]
    if interest is not None and debt_now and debt_now > 0:
        avg_debt = (debt_now + debt_prev) / 2 if debt_prev else debt_now
        raw_rd = interest / avg_debt
        b.r_d = min(max(raw_rd, b.r_f * 0.5), 0.20)  # clamp pathological ratios
        if abs(b.r_d - raw_rd) > 1e-9:
            b.notes.append(
                f"r_d clamped {fmt_pct(raw_rd)} → {fmt_pct(b.r_d)} — interest/avg-debt "
                "outside [r_f/2, 20%]; check the interest tag against the debt base")
    else:
        b.r_d = b.r_f + config.DEBT_SPREAD_ASSUMPTION
        b.notes.append(f"r_d = r_f + {fmt_pct(config.DEBT_SPREAD_ASSUMPTION)} "
                       "spread ASSUMPTION (no interest tag)")

    shares = _latest(d.diluted_shares)
    if d.last_close and shares:
        e_val = d.last_close * shares
        d_val = debt_now or 0.0
        v = e_val + d_val
        b.e_weight, b.d_weight = e_val / v, d_val / v
        b.wacc = b.e_weight * b.r_e + b.d_weight * b.r_d * (1 - b.tax)
    else:
        b.notes.append("market cap unavailable — r_e computed, WACC weights not")
    return b

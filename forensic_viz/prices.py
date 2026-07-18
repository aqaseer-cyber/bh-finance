"""Daily price history (FIX-17b): Tiingo primary (keyed), Stooq CSV
fallback (keyless). The Yahoo chart scrape is retired (owner-ratified —
undocumented endpoint, the stack's least reliable leg).

House basis: SPLIT-adjusted closes, dividends NOT backed out — an FY-end
close × diluted shares must equal the real market cap of that day, so a
total-return series (Tiingo's adjClose) would misstate history. Tiingo
serves raw closes plus per-day split factors; the split-only adjustment
is derived here and pinned by tests.

Price failure stays non-fatal to the dashboard — fundamentals render
without the price panels.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
from dataclasses import dataclass
from typing import List, Optional

import requests

from . import config
from .cache import Cache
from .providers.base import ProviderError
from .providers.tiingo import TiingoClient

STOOQ_URL = "https://stooq.com/q/d/l/?s={symbol}&d1={d1}&d2={d2}&i=d"


class PriceError(RuntimeError):
    pass


@dataclass
class PriceSeries:
    symbol: str
    dates: List[dt.date]  # ascending
    closes: List[float]
    source: str

    def __post_init__(self):
        if len(self.dates) != len(self.closes):
            raise ValueError("dates/closes length mismatch")


def _stooq_symbol(ticker: str) -> str:
    return ticker.strip().lower().replace(".", "-") + ".us"


def _dash_symbol(ticker: str) -> str:
    """Tiingo symbol form: uppercase, class dots as dashes (BRK.B -> BRK-B)."""
    return ticker.strip().upper().replace(".", "-")


def parse_stooq_csv(text: str, symbol: str) -> PriceSeries:
    if not text or text.strip().lower() in ("no data", "brak danych"):
        raise PriceError("Stooq returned no data")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "Close" not in reader.fieldnames:
        raise PriceError(f"Unexpected Stooq response: {text[:80]!r}")
    dates, closes = [], []
    for row in reader:
        try:
            d = dt.date.fromisoformat(row["Date"])
            c = float(row["Close"])
        except (KeyError, TypeError, ValueError):
            continue
        if c > 0:
            dates.append(d)
            closes.append(c)
    if len(dates) < 30:
        raise PriceError(f"Stooq returned too few rows ({len(dates)})")
    pairs = sorted(zip(dates, closes))
    return PriceSeries(
        symbol=symbol,
        dates=[p[0] for p in pairs],
        closes=[p[1] for p in pairs],
        source="Stooq",
    )


def parse_tiingo_daily(rows, symbol: str) -> PriceSeries:
    """Tiingo daily rows -> split-only-adjusted closes.

    `close` is as-traded; a row's `splitFactor` (ex-date) applies to all
    OLDER rows. Walking newest -> oldest and dividing by the factors
    accumulated from strictly newer rows reproduces the house basis;
    `divCash` is deliberately ignored (see module docstring)."""
    if not isinstance(rows, list):
        raise PriceError("Unexpected Tiingo response (not a list)")
    pairs = []
    for r in rows:
        try:
            d = dt.date.fromisoformat(str(r["date"])[:10])
            c = float(r["close"])
            sf = float(r.get("splitFactor") or 1.0)
        except (KeyError, TypeError, ValueError):
            continue
        if c > 0:
            pairs.append((d, c, sf))
    if len(pairs) < 30:
        raise PriceError(f"Tiingo returned too few rows ({len(pairs)})")
    pairs.sort()
    closes = [0.0] * len(pairs)
    factor = 1.0
    for i in range(len(pairs) - 1, -1, -1):
        _, c, sf = pairs[i]
        closes[i] = c / factor
        if sf and sf != 1.0:
            factor *= sf
    return PriceSeries(symbol=symbol, dates=[p[0] for p in pairs],
                       closes=closes, source="Tiingo")


def _fetch_tiingo(ticker: str, cache: Cache, start: dt.date,
                  today: dt.date) -> PriceSeries:
    sym = _dash_symbol(ticker)
    ckey = (f"tiingo://daily/{sym}"
            f"?start={start.isoformat()}&end={today.isoformat()}")
    cached = cache.get(ckey, config.TTL_PRICES)
    if cached is not None:
        try:
            return parse_tiingo_daily(cached, ticker.upper())
        except PriceError:
            pass  # poisoned/stale cache entry — fall through to a fetch
    rows = TiingoClient().daily_prices(sym, start=start.isoformat(),
                                       end=today.isoformat())
    series = parse_tiingo_daily(rows, ticker.upper())
    cache.put(ckey, rows)  # cache only bodies that parsed successfully
    return series


def fetch_prices(
    ticker: str,
    cache: Optional[Cache] = None,
    years: int = config.PRICE_YEARS,
    today: Optional[dt.date] = None,
) -> PriceSeries:
    """Daily closes, Tiingo -> Stooq; raises PriceError if all fail."""
    cache = cache or Cache()
    today = today or dt.date.today()
    start = today - dt.timedelta(days=int(years * 365.25) + 7)
    errors: List[str] = []

    if config.TIINGO_API_KEY:
        try:
            return _fetch_tiingo(ticker, cache, start, today)
        except (PriceError, ProviderError) as exc:
            errors.append(f"Tiingo: {exc}")
    else:
        errors.append("Tiingo: no API key (see README 'Provider keys')")

    stooq_sym = _stooq_symbol(ticker)
    url = STOOQ_URL.format(
        symbol=stooq_sym, d1=start.strftime("%Y%m%d"), d2=today.strftime("%Y%m%d")
    )
    cached = cache.get(url, config.TTL_PRICES)
    if cached is not None:
        try:
            return parse_stooq_csv(cached, ticker.upper())
        except PriceError:
            pass  # poisoned/stale cache entry — fall through to a fresh fetch
    try:
        resp = requests.get(
            url,
            timeout=config.HTTP_TIMEOUT,
            headers={"User-Agent": f"{config.APP_NAME}/{config.APP_VERSION}"},
        )
        resp.raise_for_status()
        series = parse_stooq_csv(resp.text, ticker.upper())
        cache.put(url, resp.text)  # cache only bodies that parsed successfully
        return series
    except (requests.RequestException, PriceError) as exc:
        errors.append(f"Stooq: {exc}")

    raise PriceError("; ".join(errors))

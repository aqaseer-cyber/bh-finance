"""Daily price history: Stooq CSV first (keyless), Yahoo chart API fallback.

Both sources return split-adjusted closes. Price failure is non-fatal to the
dashboard — fundamentals render without the price panels.
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

STOOQ_URL = "https://stooq.com/q/d/l/?s={symbol}&d1={d1}&d2={d2}&i=d"
YAHOO_URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/"
    "{symbol}?range={years}y&interval=1d"
)


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


def _yahoo_symbol(ticker: str) -> str:
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


def parse_yahoo_chart(payload: dict, symbol: str) -> PriceSeries:
    try:
        result = payload["chart"]["result"][0]
        timestamps = result["timestamp"]
        quote = result["indicators"]["quote"][0]
        adj = result["indicators"].get("adjclose", [{}])[0].get("adjclose")
        closes_raw = adj if adj else quote["close"]
    except (KeyError, IndexError, TypeError) as exc:
        err = None
        try:
            err = payload["chart"]["error"]["description"]
        except Exception:
            pass
        raise PriceError(f"Unexpected Yahoo response ({err or exc})")
    dates, closes = [], []
    for ts, c in zip(timestamps, closes_raw):
        if c is None:
            continue
        dates.append(dt.datetime.fromtimestamp(ts, dt.timezone.utc).date())
        closes.append(float(c))
    if len(dates) < 30:
        raise PriceError(f"Yahoo returned too few rows ({len(dates)})")
    return PriceSeries(symbol=symbol, dates=dates, closes=closes, source="Yahoo Finance")


def fetch_prices(
    ticker: str,
    cache: Optional[Cache] = None,
    years: int = config.PRICE_YEARS,
    today: Optional[dt.date] = None,
) -> PriceSeries:
    """5 years of daily closes; raises PriceError if every source fails."""
    cache = cache or Cache()
    today = today or dt.date.today()
    start = today - dt.timedelta(days=int(years * 365.25) + 7)
    errors: List[str] = []

    stooq_sym = _stooq_symbol(ticker)
    url = STOOQ_URL.format(
        symbol=stooq_sym, d1=start.strftime("%Y%m%d"), d2=today.strftime("%Y%m%d")
    )
    cached = cache.get(url, config.TTL_PRICES)
    try:
        if cached is None:
            resp = requests.get(
                url,
                timeout=config.HTTP_TIMEOUT,
                headers={"User-Agent": f"{config.APP_NAME}/{config.APP_VERSION}"},
            )
            resp.raise_for_status()
            cached = resp.text
            if cached and len(cached) > 40:  # don't cache "No data" stubs
                cache.put(url, cached)
        return parse_stooq_csv(cached, ticker.upper())
    except (requests.RequestException, PriceError) as exc:
        errors.append(f"Stooq: {exc}")

    yurl = YAHOO_URL.format(symbol=_yahoo_symbol(ticker), years=years)
    cached = cache.get(yurl, config.TTL_PRICES)
    try:
        if cached is None:
            resp = requests.get(
                yurl,
                timeout=config.HTTP_TIMEOUT,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            )
            resp.raise_for_status()
            cached = resp.json()
            cache.put(yurl, cached)
        return parse_yahoo_chart(cached, ticker.upper())
    except (requests.RequestException, ValueError, PriceError) as exc:
        errors.append(f"Yahoo: {exc}")

    raise PriceError("; ".join(errors))

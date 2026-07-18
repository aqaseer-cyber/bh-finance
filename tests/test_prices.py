"""FIX-17b price stack: Stooq parsing (unchanged), the Tiingo split-only
adjustment (house basis: real market caps, dividends not backed out),
and the Tiingo -> Stooq fetch order. All offline."""
import datetime as dt
import json

import pytest

from forensic_viz import config, prices
from forensic_viz.cache import Cache
from forensic_viz.prices import (
    PriceError, fetch_prices, parse_stooq_csv, parse_tiingo_daily,
)

STOOQ_HEAD = "Date,Open,High,Low,Close,Volume\n"


def _stooq_rows(n):
    return "".join(
        f"2024-01-{(i % 28) + 1:02d},10,11,9,{10 + i * 0.1:.2f},1000\n" for i in range(n)
    )


def test_stooq_parse_ok():
    series = parse_stooq_csv(STOOQ_HEAD + _stooq_rows(40), "TEST")
    assert len(series.closes) == 40
    assert series.source == "Stooq"
    assert series.dates == sorted(series.dates)


def test_stooq_no_data_raises():
    with pytest.raises(PriceError):
        parse_stooq_csv("No data", "TEST")


def test_stooq_too_few_rows_raises():
    with pytest.raises(PriceError):
        parse_stooq_csv(STOOQ_HEAD + _stooq_rows(5), "TEST")


# ---------------------------------------------------- Tiingo (FIX-17b)

def _tiingo_rows(n, split_at=None, split=2.0, base=100.0):
    """n ascending daily rows; optional split on index `split_at`
    (as-traded closes halve from that row on, like a real 2:1)."""
    rows = []
    for i in range(n):
        c = base + i
        if split_at is not None and i >= split_at:
            c = (base + i) / split
        rows.append({"date": f"2024-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}"
                             "T00:00:00.000Z",
                     "close": c,
                     "adjClose": c * 0.9,     # divs backed out — must be IGNORED
                     "splitFactor": split if i == split_at else 1.0,
                     "divCash": 0.5 if i % 10 == 0 else 0.0})
    return rows


def test_tiingo_split_only_adjustment():
    """2:1 split mid-series: pre-split closes halve, post-split closes
    stay as traded, and adjClose (dividend-adjusted) is never used."""
    n, split_at = 40, 20
    series = parse_tiingo_daily(_tiingo_rows(n, split_at=split_at), "TEST")
    assert series.source == "Tiingo"
    assert len(series.closes) == n
    # post-split rows: exactly the as-traded close
    assert series.closes[-1] == pytest.approx((100.0 + n - 1) / 2.0)
    # pre-split rows: as-traded close divided by the later 2:1
    assert series.closes[0] == pytest.approx(100.0 / 2.0)
    assert series.closes[split_at - 1] == pytest.approx(
        (100.0 + split_at - 1) / 2.0)
    # continuity: no artificial cliff at the split
    ratio = series.closes[split_at] / series.closes[split_at - 1]
    assert 0.9 < ratio < 1.1


def test_tiingo_no_split_passthrough_and_zero_drop():
    rows = _tiingo_rows(40)
    rows[0]["close"] = 0.0            # glitch row -> dropped
    series = parse_tiingo_daily(rows, "TEST")
    assert len(series.closes) == 39
    assert min(series.closes) > 0
    assert series.closes[-1] == pytest.approx(139.0)


def test_tiingo_too_few_rows_raises():
    with pytest.raises(PriceError):
        parse_tiingo_daily(_tiingo_rows(5), "TEST")
    with pytest.raises(PriceError):
        parse_tiingo_daily({"detail": "not a list"}, "TEST")


class _StubTiingo:
    """Stands in for TiingoClient inside prices._fetch_tiingo."""
    calls = []

    def __init__(self, *a, **k):
        pass

    def daily_prices(self, symbol, start=None, end=None):
        _StubTiingo.calls.append((symbol, start, end))
        return _tiingo_rows(40)


def test_fetch_prefers_tiingo_when_keyed(monkeypatch):
    monkeypatch.setattr(config, "TIINGO_API_KEY", "k")
    monkeypatch.setattr(prices, "TiingoClient", _StubTiingo)
    _StubTiingo.calls = []
    series = fetch_prices("brk.b", cache=Cache(enabled=False),
                          today=dt.date(2026, 7, 18))
    assert series.source == "Tiingo"
    assert _StubTiingo.calls[0][0] == "BRK-B"   # dash symbol form


def test_fetch_without_key_falls_back_to_stooq(monkeypatch):
    monkeypatch.setattr(config, "TIINGO_API_KEY", "")

    class _Resp:
        status_code = 200
        text = STOOQ_HEAD + _stooq_rows(40)

        def raise_for_status(self):
            pass

    monkeypatch.setattr(prices.requests, "get",
                        lambda *a, **k: _Resp())
    series = fetch_prices("TEST", cache=Cache(enabled=False),
                          today=dt.date(2026, 7, 18))
    assert series.source == "Stooq"


def test_fetch_error_names_both_legs(monkeypatch):
    monkeypatch.setattr(config, "TIINGO_API_KEY", "")

    def _boom(*a, **k):
        raise prices.requests.ConnectionError("offline")

    monkeypatch.setattr(prices.requests, "get", _boom)
    with pytest.raises(PriceError) as exc:
        fetch_prices("TEST", cache=Cache(enabled=False),
                     today=dt.date(2026, 7, 18))
    msg = str(exc.value)
    assert "Tiingo: no API key" in msg and "Stooq:" in msg


def test_tiingo_cache_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TIINGO_API_KEY", "k")
    monkeypatch.setattr(prices, "TiingoClient", _StubTiingo)
    _StubTiingo.calls = []
    cache = Cache(directory=tmp_path)
    kw = dict(cache=cache, today=dt.date(2026, 7, 18))
    first = fetch_prices("TEST", **kw)
    second = fetch_prices("TEST", **kw)     # served from cache
    assert len(_StubTiingo.calls) == 1
    assert first.closes == second.closes
    # the cached body is the raw JSON rows, JSON-serializable
    assert json.dumps(_tiingo_rows(2))      # sanity: fixture serializes

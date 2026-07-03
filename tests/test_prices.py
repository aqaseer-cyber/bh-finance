import pytest

from forensic_viz.prices import PriceError, parse_stooq_csv, parse_yahoo_chart

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


def test_yahoo_parse_ok():
    n = 40
    payload = {"chart": {"result": [{
        "timestamp": [1700000000 + i * 86400 for i in range(n)],
        "indicators": {
            "quote": [{"close": [100.0 + i for i in range(n)]}],
            "adjclose": [{"adjclose": [99.0 + i for i in range(n)]}],
        },
    }], "error": None}}
    series = parse_yahoo_chart(payload, "TEST")
    assert series.closes[0] == 99.0  # adjusted close preferred
    assert len(series.dates) == n


def test_yahoo_error_payload_raises():
    with pytest.raises(PriceError):
        parse_yahoo_chart(
            {"chart": {"result": None,
                       "error": {"description": "No data found"}}}, "TEST")

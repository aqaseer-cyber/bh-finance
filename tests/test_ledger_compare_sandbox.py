"""Verdict ledger (§5.7), comparison HTML, and the live DCF sandbox."""
import datetime as dt
import json

import pytest

from forensic_viz.compare import build_compare_html
from forensic_viz.edgar import parse_companyfacts
from forensic_viz.interactive import build_html
from forensic_viz.ledger import Ledger
from forensic_viz.metrics import (
    DashboardData, apply_track, build_fundamental_metrics, build_price_metrics,
)
from forensic_viz.prices import PriceSeries
from forensic_viz.valuation import CaseInputs, ValuationInputs, build_valuation
from forensic_viz.verdict import build_verdict


def _data(testco_facts, ticker="TESTCO", aapl_prices=None):
    d = DashboardData(ticker=ticker, company=f"{ticker} Inc", subtitle="sub",
                      generated=dt.date(2026, 7, 3))
    d.sic_code = "3571"
    apply_track(d, "auto")
    build_fundamental_metrics(parse_companyfacts(testco_facts, ticker), d)
    if aapl_prices:
        build_price_metrics(PriceSeries(
            symbol=ticker,
            dates=[dt.date.fromisoformat(s) for s in aapl_prices["dates"]],
            closes=aapl_prices["close"], source="fixture"), d)
    else:
        d.last_close = 100.0
        d.price_dates = [dt.date(2026, 7, 1)]
        d.price_closes = [100.0]
    return d


def _verdict(d):
    inputs = ValuationInputs(
        method="dcf", discount_rate=0.09,
        cases={"Bear": CaseInputs(g0=0.02, g_term=0.02),
               "Base": CaseInputs(g0=0.05, g_term=0.025),
               "Bull": CaseInputs(g0=0.09, g_term=0.03)})
    res = build_valuation(d, inputs)
    return res, build_verdict(d, inputs, res, rating="Buy")


def test_ledger_upsert_list_and_staleness(tmp_path, testco_facts):
    led = Ledger(path=str(tmp_path / "ledger.db"))
    d = _data(testco_facts)
    res, v = _verdict(d)
    led.upsert_verdict(d, res=res, verdict=v)
    rows = led.list_verdicts()
    assert len(rows) == 1
    r = rows[0]
    assert r["ticker"] == "TESTCO" and r["rating"] == "Buy"
    assert r["fv_avg"] == pytest.approx(v.fv_avg)
    assert r["age_days"] == 0 and not r["stale"]  # written just now
    # re-upsert replaces, never duplicates
    led.upsert_verdict(d, res=res, verdict=v)
    assert len(led.list_verdicts()) == 1
    led.remove("TESTCO")
    assert led.list_verdicts() == []


def test_ledger_triggers(tmp_path, testco_facts):
    led = Ledger(path=str(tmp_path / "ledger.db"))
    d = _data(testco_facts)
    res, v = _verdict(d)
    led.upsert_verdict(d, res=res, verdict=v)
    led.add_trigger("TESTCO", "FY2026 print: DSI must normalize below 100d")
    assert led.list_verdicts()[0]["open_triggers"] == 1
    tid = led.open_triggers("TESTCO")[0]["id"]
    led.close_trigger(tid)
    assert led.open_triggers("TESTCO") == []


def test_ledger_seed_import(tmp_path):
    seed = [{"ticker": "OUST", "rating": "Buy", "fv": 12.5, "mos": 0.3,
             "triggers": ["Q3 gross margin > 35%"]},
            {"ticker": "RELY", "verdict": "Hold", "fv_avg": 22.0}]
    p = tmp_path / "seed.json"
    p.write_text(json.dumps(seed))
    led = Ledger(path=str(tmp_path / "ledger.db"))
    assert led.import_seed(str(p)) == 2
    rows = {r["ticker"]: r for r in led.list_verdicts()}
    assert rows["OUST"]["fv_avg"] == 12.5
    assert rows["OUST"]["open_triggers"] == 1
    assert rows["RELY"]["rating"] == "Hold"
    assert "verify" in rows["OUST"]["coherence"]


def test_compare_html_fixed_entity_colors(tmp_path, testco_facts, aapl_prices):
    d1 = _data(testco_facts, "AAA", aapl_prices)
    d2 = _data(testco_facts, "BBB", aapl_prices)
    out = tmp_path / "cmp.html"
    build_compare_html([d1, d2], str(out),
                       ledger_rows={"AAA": {"rating": "Buy", "fv_avg": 90.0,
                                            "mos": -0.1}})
    body = out.read_text(encoding="utf-8")
    assert "AAA" in body and "BBB" in body
    from forensic_viz import palette as P
    assert body.count(P.SERIES[0]) > body.count(P.SERIES[2])  # slot colors used
    assert "indexed to 100" in body
    assert "Ledger rating" in body and "Buy" in body


def test_sandbox_embedded_with_constants(tmp_path, testco_facts, aapl_prices):
    d = _data(testco_facts, aapl_prices=aapl_prices)
    res, _v = _verdict(d)
    out = tmp_path / "r.html"
    build_html(d, str(out), res=res)
    body = out.read_text(encoding="utf-8")
    assert "Valuation sandbox" in body and "function dcf" in body
    assert "sandbox-chart" in body
    # base-case growths seeded the sliders
    assert 'id="g0" type="range"' in body and 'value="5.0"' in body


def test_sandbox_suppressed_for_banks(tmp_path, testco_facts, aapl_prices):
    d = _data(testco_facts, aapl_prices=aapl_prices)
    apply_track(d, "bank")
    out = tmp_path / "r.html"
    build_html(d, str(out))
    assert "Valuation sandbox" not in out.read_text(encoding="utf-8")

"""v3 R0 contract tests — every endpoint, offline, fixture-driven.

The service is a thin adapter: parity tests assert the API returns
EXACTLY what the engine functions return, serialized. No analytics in
the web layer means nothing here may recompute anything."""
import datetime as dt

import matplotlib
matplotlib.use("Agg")

import pytest
from fastapi.testclient import TestClient

from forensic_viz.edgar import parse_companyfacts
from forensic_viz.metrics import DashboardData, apply_track, \
    build_fundamental_metrics
from test_model_export import _facts_with_quarters
from webui.serialize import SCHEMA_VERSION, to_jsonable
from webui.server import create_app

TOKEN = "test-token"


def _testco():
    from test_explore import _with_prices
    d = DashboardData(ticker="TESTCO", company="TESTCO Inc", subtitle="",
                      generated=dt.date(2026, 8, 10))
    d.sic_code = "3571"
    apply_track(d, "auto")
    build_fundamental_metrics(
        parse_companyfacts(_facts_with_quarters(), "TESTCO"), d)
    _with_prices(d)          # closes + drawdown + source (render-ready)
    d.last_close = d.price_closes[-1]
    return d


def fixture_pipeline(ticker, progress):
    progress("fixture: fundamentals")
    progress("fixture: prices")
    return _testco()


@pytest.fixture()
def client():
    app = create_app(pipeline=fixture_pipeline, token=TOKEN)
    return TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"})


def _sse_events(client, url):
    events = []
    with client.stream("POST", url) as r:
        assert r.status_code == 200
        for line in r.iter_lines():
            if line.startswith("event: "):
                events.append(line[7:])
    return events


def test_token_guard():
    app = create_app(pipeline=fixture_pipeline, token=TOKEN)
    bare = TestClient(app)
    assert bare.get("/api/health").status_code == 401
    assert bare.get(f"/api/health?token={TOKEN}").status_code == 200
    ok = TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"})
    assert ok.get("/api/health").json()["ok"] is True


def test_run_streams_progress_then_done_and_stores(client):
    events = _sse_events(client, "/api/run/testco")
    assert "progress" in events and events[-1] == "done"
    resp = client.get("/api/data/TESTCO")
    assert resp.status_code == 200
    body = resp.json()
    assert body["schema"] == SCHEMA_VERSION
    assert body["kind"] == "dashboard_data"
    data = body["data"]
    assert data["ticker"] == "TESTCO"
    assert data["fy_labels"]
    # the raw companyfacts payload is excluded by the serializer
    assert "raw_facts" not in (data.get("fundamentals") or {})


def test_data_404_before_run(client):
    r = client.get("/api/data/NOPE")
    assert r.status_code == 404
    assert "POST /api/run" in r.json()["detail"]


def test_valuation_parity_with_direct_engine_call(client):
    from forensic_viz.valuation import (
        CaseInputs, ValuationInputs, build_valuation,
    )
    _sse_events(client, "/api/run/TESTCO")
    body = {"ticker": "TESTCO", "method": "dcf", "discount_rate": 0.09,
            "cases": {"Bear": {"g0": 0.02, "g_term": 0.02},
                      "Base": {"g0": 0.05, "g_term": 0.025},
                      "Bull": {"g0": 0.09, "g_term": 0.03}}}
    r = client.post("/api/valuation", json=body)
    assert r.status_code == 200
    got = r.json()["data"]["result"]
    direct = build_valuation(_testco(), ValuationInputs(
        method="dcf", discount_rate=0.09,
        cases={"Bear": CaseInputs(g0=0.02, g_term=0.02),
               "Base": CaseInputs(g0=0.05, g_term=0.025),
               "Bull": CaseInputs(g0=0.09, g_term=0.03)}))
    by_name = {c["name"]: c for c in got["cases"]}
    for c in direct.cases:
        assert by_name[c.name]["fv_ps"] == pytest.approx(c.fv_ps)
    assert r.json()["data"]["verdict"]["fv_avg"] is not None
    # bad case name -> 422, engine error (empty manual) -> 422
    bad = client.post("/api/valuation", json={
        "ticker": "TESTCO", "cases": {"Wat": {}}})
    assert bad.status_code == 422


def test_sandbox_parity(client):
    from forensic_viz.explore import sandbox_compute
    body = {"base": 5e8, "wacc": 0.09, "g0": 0.05, "g_term": 0.02,
            "bridge": 6e8, "shares": 100e6, "sbc": 0.0,
            "ex_sbc": False, "price": 80.0}
    r = client.post("/api/sandbox", json=body)
    assert r.status_code == 200
    direct = sandbox_compute(5e8, 0.09, 0.05, 0.02, 6e8, 100e6, 0.0,
                             False, price=80.0)
    assert r.json()["data"]["fv_ps"] == pytest.approx(direct["fv_ps"])
    assert r.json()["data"]["implied_g"] == \
        pytest.approx(direct["implied_g"])
    assert client.post("/api/sandbox", json={}).status_code == 422


def test_ledger_endpoints(client):
    r = client.get("/api/ledger")
    assert r.status_code == 200
    assert r.json()["kind"] == "ledger"
    assert isinstance(r.json()["data"], list)
    h = client.get("/api/ledger/TESTCO")
    assert h.status_code == 200


def test_export_model_and_csv(client, tmp_path):
    _sse_events(client, "/api/run/TESTCO")
    for kind, suffix in (("model", ".xlsx"), ("csv", ".csv")):
        r = client.post(f"/api/export/{kind}",
                        json={"ticker": "TESTCO",
                              "out_dir": str(tmp_path)})
        assert r.status_code == 200
        from pathlib import Path
        p = Path(r.json()["data"]["path"])
        assert p.exists() and p.suffix == suffix and p.stat().st_size
    assert client.post("/api/export/wat",
                       json={"ticker": "TESTCO"}).status_code == 404


# ------------------------------------------------------- serializer

def test_serializer_rules():
    import math
    out = to_jsonable({
        ("a", "b"): {dt.date(2024, 12, 31): float("nan")},
        "s": {"x", "a"},
        "f": math.inf,
        "d": dt.date(2025, 1, 1),
        "raw_facts": "never",
        "_private": "never",
    })
    assert out["a|b"] == {"2024-12-31": None}
    assert out["s"] == ["a", "x"]
    assert out["f"] is None
    assert out["d"] == "2025-01-01"
    assert "raw_facts" not in out and "_private" not in out

"""FIX-17a: provider layer — key discipline (headers only, tail-4
display, env > settings), probe status mapping, and the verdict lines
that lock the FIX-17f design. Everything offline via fake transports."""
import json

import pytest

from forensic_viz import config
from forensic_viz.providers import (
    FinnhubClient, FMPClient, ProbeResult, TiingoClient, key_tail,
    probe_all, render_probe,
)
from forensic_viz.providers.base import ProviderError, run_check

FAKE_FMP = "FMPKEYxxxxxxxxxxxxxxxxxxxxxxxx1234"
FAKE_TII = "TIIKEYxxxxxxxxxxxxxxxxxxxxxxxx5678"
FAKE_FNH = "FNHKEYxxxxxxxxxxxxxxxxxxxxxxxx9abc"


@pytest.fixture()
def keys(monkeypatch):
    monkeypatch.setattr(config, "FMP_API_KEY", FAKE_FMP)
    monkeypatch.setattr(config, "TIINGO_API_KEY", FAKE_TII)
    monkeypatch.setattr(config, "FINNHUB_API_KEY", FAKE_FNH)
    yield


class Recorder:
    """Fake transport: records every request, serves canned bodies by
    URL substring; default 200 []."""

    def __init__(self, routes=None, status=200, body="[]"):
        self.routes = routes or {}
        self.default = (status, body)
        self.calls = []

    def __call__(self, url, headers, params, timeout):
        self.calls.append((url, dict(headers), dict(params)))
        for frag, resp in self.routes.items():
            if frag in url:
                return resp
        return self.default


def test_keys_travel_in_headers_never_in_urls(keys):
    routes = {"profile": (200, json.dumps([{"companyName": "P"}]))}
    rec = Recorder(routes)
    FMPClient(transport=rec).profile("PYPL")
    TiingoClient(transport=rec).meta("PYPL")
    FinnhubClient(transport=rec).quote("PYPL")
    assert len(rec.calls) == 3
    for url, headers, params in rec.calls:
        blob = url + json.dumps(params)
        for k in (FAKE_FMP, FAKE_TII, FAKE_FNH):
            assert k not in blob
    assert rec.calls[0][1]["apikey"] == FAKE_FMP
    assert rec.calls[1][1]["Authorization"] == f"Token {FAKE_TII}"
    assert rec.calls[2][1]["X-Finnhub-Token"] == FAKE_FNH


def test_missing_key_short_circuits_without_a_request(monkeypatch):
    monkeypatch.setattr(config, "FMP_API_KEY", "")
    rec = Recorder()
    with pytest.raises(ProviderError) as exc:
        FMPClient(transport=rec).profile("PYPL")
    assert exc.value.status == 0
    assert rec.calls == []


def test_run_check_status_mapping(keys):
    c = FMPClient(transport=Recorder(
        {"income": (200, json.dumps([{"date": "2025-12-31"},
                                     {"date": "2016-12-31"}]))}))
    ok = run_check("FMP", "inc", lambda: c.income_statement("X"),
                   lambda j: f"{len(j)} records")
    assert (ok.status, ok.detail) == ("OK", "2 records")
    empty = run_check("FMP", "est",
                      lambda: FMPClient(transport=Recorder())
                      .analyst_estimates("X"),
                      lambda j: f"{len(j)} records" if j else None)
    assert empty.status == "EMPTY"
    denied = run_check("FMP", "est",
                       lambda: FMPClient(transport=Recorder(
                           status=402, body="Premium Endpoint"))
                       .analyst_estimates("X"), lambda j: "x")
    assert denied.status == "DENIED" and "402" in denied.detail
    badkey = run_check("FMP", "any",
                       lambda: FMPClient(transport=Recorder(
                           status=401, body="Invalid API KEY"))
                       .profile("X"), lambda j: "x")
    assert badkey.status == "KEY?"
    nonjson = run_check("FMP", "any",
                        lambda: FMPClient(transport=Recorder(
                            body="<html>oops</html>")).profile("X"),
                        lambda j: "x")
    assert nonjson.status == "ERROR"
    nokey = run_check("FMP", "any", lambda: (_ for _ in ()).throw(
        ProviderError("no key", status=0)), lambda j: "x")
    assert nokey.status == "NO KEY"


def _routes_all_ok():
    stmt = json.dumps([{"date": "2025-12-31"}, {"date": "2021-12-31"}])
    return {
        "FMP": Recorder({
            "profile": (200, json.dumps([{"companyName": "PayPal",
                                          "country": "US",
                                          "fullTimeEmployees": "24400"}])),
            "income-statement": (200, stmt),
            "cash-flow-statement": (200, stmt),
            "balance-sheet-statement": (200, stmt),
            "analyst-estimates": (200, stmt),
            "price-target-consensus": (200, json.dumps(
                {"consensus": 80.0})),
            "grades-consensus": (200, json.dumps({"consensus": "Buy"})),
            "historical-price-eod": (200, json.dumps(
                [{"date": "2026-07-17"}, {"date": "2008-01-02"}])),
        }),
        "Tiingo": Recorder({
            "/prices": (200, json.dumps([{"date": "2002-01-02T00:00:00Z"},
                                         {"date": "2026-07-17T00:00:00Z"}])),
            "/tiingo/daily/": (200, json.dumps(
                {"startDate": "2002-01-02", "endDate": "2026-07-17"})),
        }),
        "Finnhub": Recorder({
            "profile2": (200, json.dumps({"name": "PayPal",
                                          "country": "US",
                                          "weburl": "https://x"})),
            "/quote": (200, json.dumps({"c": 56.7})),
            "recommendation": (200, json.dumps(
                [{"period": "2026-07-01", "buy": 20, "hold": 12,
                  "sell": 2}])),
            "eps-estimate": (200, json.dumps(
                {"data": [{"period": "2026-12-31"}]})),
            "revenue-estimate": (200, json.dumps(
                {"data": [{"period": "2026-12-31"}]})),
            "financials-reported": (200, json.dumps(
                {"data": [{"year": 2025}, {"year": 2024}]})),
            "insider-transactions": (200, json.dumps(
                {"data": [{"name": "A"}]})),
        }),
    }


def test_probe_matrix_and_verdicts_available(keys):
    out = render_probe(probe_all("PYPL", transports=_routes_all_ok()),
                       "PYPL")
    assert "analyst growth estimates AVAILABLE via FMP + Finnhub" in out
    assert "Tiingo OK" in out
    assert "Finnhub as-reported OK" in out
    # ordering note: Tiingo /prices route must match before the meta
    # route, both contain /tiingo/daily/ — depth check proves it did
    assert "2 daily bars since 2002-01-02" in out
    # the full keys never appear anywhere in probe output
    for k in (FAKE_FMP, FAKE_TII, FAKE_FNH):
        assert k not in out
    assert key_tail(FAKE_FMP) in out


def test_fmp_statement_probe_retries_at_free_depth(keys):
    """Probe-verified free-plan behavior: limit>5 answers 402 naming the
    'limit' parameter, but the endpoint IS served at limit<=5 — the
    probe must report OK (free-plan depth), not DENIED."""
    class LimitAware(Recorder):
        def __call__(self, url, headers, params, timeout):
            self.calls.append((url, dict(headers), dict(params)))
            if "income-statement" in url:
                if int(params.get("limit", 0)) > 5:
                    return (402, "Premium Query Parameter: 'limit' must "
                                 "be between 0 and 5")
                return (200, json.dumps([{"date": f"{y}-12-31"}
                                         for y in range(2025, 2020, -1)]))
            return self.default

    routes = _routes_all_ok()
    routes["FMP"] = LimitAware()
    out = render_probe(probe_all("PYPL", transports=routes), "PYPL")
    assert "5 records 2021..2025 (free-plan depth)" in out
    assert "FMP statements OK" in out


def test_probe_verdict_when_estimates_denied(keys):
    routes = _routes_all_ok()
    routes["FMP"].routes["analyst-estimates"] = (402, "Premium Endpoint")
    routes["Finnhub"].routes["eps-estimate"] = (403, "premium")
    routes["Finnhub"].routes["revenue-estimate"] = (403, "premium")
    out = render_probe(probe_all("PYPL", transports=routes), "PYPL")
    assert "NOT served by the configured keys" in out
    assert "FMP Starter" in out


def test_key_tail_never_shows_more_than_four():
    assert key_tail("") == "not set"
    assert key_tail("abcdefgh") == "...efgh"


def test_settings_fill_key_gap_env_wins(monkeypatch, tmp_path):
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    monkeypatch.setattr(config, "FMP_API_KEY", "")
    config.apply_user_settings({"fmp_api_key": "from-settings"})
    assert config.FMP_API_KEY == "from-settings"
    monkeypatch.setenv("FMP_API_KEY", "from-env")
    monkeypatch.setattr(config, "FMP_API_KEY", "from-env")
    config.apply_user_settings({"fmp_api_key": "from-settings"})
    assert config.FMP_API_KEY == "from-env"


def test_probe_cli_exits_zero_with_fake_probe(monkeypatch, capsys):
    import forensic_viz.providers as prov
    from forensic_viz.__main__ import main
    monkeypatch.setattr(prov, "probe_all",
                        lambda t, transports=None: [
                            ProbeResult("FMP", "profile", "OK", "x")])
    assert main(["--probe", "ZZZT"]) == 0
    out = capsys.readouterr().out
    assert "Provider capability probe — ZZZT" in out

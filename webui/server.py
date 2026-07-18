"""v3 R0: the FastAPI service — a THIN adapter over the frozen engine.

Charter rules enforced here:
- No analytics in the web layer: every endpoint calls the existing
  pipeline/valuation/verdict/sandbox/export functions verbatim and
  serializes their results. If a computation is not importable from
  `forensic_viz`, it does not exist for the API.
- Localhost + bearer-token guard: `create_app(token=...)` rejects any
  request without the token (the R1 shell injects it into the page
  bootstrap; no other local process can drive the API).
- Injectable pipeline: `create_app(pipeline=...)` lets the smoke
  script and contract tests drive /api/run on the TESTCO fixture fully
  offline; the default is the real `build_dashboard_data`.

Run registry: one DashboardData per ticker, in memory, replaced on
each /api/run. Valuation results attach to the run so /api/export can
produce the same artifacts the Tk GUI does.
"""
from __future__ import annotations

import json
import queue
import threading
from typing import Callable, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from .serialize import SCHEMA_VERSION, payload


def _default_pipeline(ticker: str, progress: Callable[[str], None]):
    from forensic_viz.cache import Cache
    from forensic_viz.pipeline import build_dashboard_data
    return build_dashboard_data(ticker, cache=Cache(), progress=progress)


def create_app(pipeline: Optional[Callable] = None,
               token: Optional[str] = None) -> FastAPI:
    from pathlib import Path

    from fastapi.responses import HTMLResponse
    from fastapi.staticfiles import StaticFiles

    app = FastAPI(title="bh-finance service", docs_url=None,
                  redoc_url=None, openapi_url=None)
    app.state.runs = {}          # ticker -> DashboardData
    app.state.valuations = {}    # ticker -> (res, verdict)
    run_pipeline = pipeline or _default_pipeline

    static_dir = Path(__file__).resolve().parent / "static"
    if static_dir.is_dir():   # R1 frontend (absent in minimal installs)
        app.mount("/static", StaticFiles(directory=str(static_dir)),
                  name="static")

        @app.get("/", response_class=HTMLResponse)
        async def index():
            # the ONLY place the token reaches the page (charter §4:
            # random bearer in the page bootstrap)
            html = (static_dir / "index.html").read_text("utf-8")
            return html.replace("%%TOKEN%%", token or "")

    async def auth(request: Request) -> None:
        if token is None:
            return
        got = request.headers.get("authorization", "")
        if got == f"Bearer {token}" \
                or request.query_params.get("token") == token:
            return
        raise HTTPException(status_code=401, detail="bad token")

    def _run(ticker: str):
        d = app.state.runs.get(ticker.upper())
        if d is None:
            raise HTTPException(status_code=404,
                                detail=f"no run for {ticker!r} — POST "
                                       f"/api/run/{ticker} first")
        return d

    @app.get("/api/health", dependencies=[Depends(auth)])
    async def health():
        return {"schema": SCHEMA_VERSION, "ok": True}

    @app.post("/api/run/{ticker}", dependencies=[Depends(auth)])
    async def run(ticker: str):
        """Kick the pipeline; stream progress as SSE; store the run."""
        ticker = ticker.strip().upper()
        q: "queue.Queue[tuple]" = queue.Queue()

        def worker():
            try:
                data = run_pipeline(ticker,
                                    progress=lambda m: q.put(("p", m)))
                app.state.runs[ticker] = data
                app.state.valuations.pop(ticker, None)
                q.put(("done", None))
            except Exception as exc:
                q.put(("error", str(exc)[:300]))

        threading.Thread(target=worker, daemon=True).start()

        async def events():
            import asyncio
            while True:
                try:
                    kind, msg = q.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.05)
                    continue
                if kind == "p":
                    yield ("event: progress\ndata: "
                           + json.dumps({"message": msg}) + "\n\n")
                elif kind == "done":
                    yield ("event: done\ndata: "
                           + json.dumps({"ticker": ticker}) + "\n\n")
                    return
                else:
                    yield ("event: error\ndata: "
                           + json.dumps({"message": msg}) + "\n\n")
                    return

        return StreamingResponse(events(),
                                 media_type="text/event-stream")

    @app.get("/api/data/{ticker}", dependencies=[Depends(auth)])
    async def data(ticker: str):
        return payload("dashboard_data", _run(ticker))

    @app.post("/api/valuation", dependencies=[Depends(auth)])
    async def valuation(body: dict):
        from forensic_viz.valuation import (
            CASE_NAMES, CaseInputs, ValuationError, ValuationInputs,
            build_valuation,
        )
        from forensic_viz.verdict import build_verdict
        d = _run(str(body.get("ticker", "")))
        case_fields = {"g0", "g_term", "roe", "affo_ps", "target_yield",
                       "fv_ps"}
        cases = {}
        for name, raw in (body.get("cases") or {}).items():
            if name not in CASE_NAMES or not isinstance(raw, dict):
                raise HTTPException(status_code=422,
                                    detail=f"bad case {name!r}")
            cases[name] = CaseInputs(**{k: float(v)
                                        for k, v in raw.items()
                                        if k in case_fields
                                        and v is not None})
        inputs = ValuationInputs(
            method=str(body.get("method", "dcf")).lower(),
            cases=cases,
            discount_rate=body.get("discount_rate"),
            base_value=body.get("base_value"),
            ex_sbc=bool(body.get("ex_sbc", False)),
        )
        try:
            res = build_valuation(d, inputs)
            verdict = build_verdict(d, inputs, res,
                                    rating=str(body.get("rating", "")),
                                    optionality=str(
                                        body.get("optionality", "")))
        except ValuationError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        app.state.valuations[d.ticker] = (res, verdict)
        # v3 R2: the verdict page's own sensitivity grid + open triggers
        # ride along (existing engine code, serialized verbatim)
        from forensic_viz.dashboard import verdict_sensitivity
        try:
            sens = verdict_sensitivity(res, verdict)
        except Exception:
            sens = None
        triggers = []
        try:
            from forensic_viz.ledger import Ledger
            triggers = Ledger().open_triggers(d.ticker)
        except Exception:
            pass
        return {"schema": SCHEMA_VERSION, "kind": "valuation",
                "data": {"result": payload("valuation_result", res)["data"],
                         "verdict": payload("verdict", verdict)["data"],
                         "sensitivity": payload("sensitivity",
                                                sens)["data"],
                         "triggers": payload("triggers",
                                             triggers)["data"]}}

    @app.get("/api/anchors/{ticker}", dependencies=[Depends(auth)])
    async def anchors(ticker: str):
        """FIX-14a growth-anchor ladder + method suggestion — prefills
        for the Valuation screen (engine functions, serialized)."""
        from forensic_viz.anchors import anchor_readout, \
            build_growth_anchors
        from forensic_viz.valuation import suggest_method
        d = _run(ticker)
        a = build_growth_anchors(d)
        return {"schema": SCHEMA_VERSION, "kind": "anchors",
                "data": {"anchors": payload("growth_anchors", a)["data"],
                         "readout": anchor_readout(a),
                         "suggested_method": suggest_method(d.track),
                         "wacc_build": payload(
                             "wacc", getattr(d, "wacc_build",
                                             None))["data"]}}

    @app.post("/api/sandbox", dependencies=[Depends(auth)])
    async def sandbox(body: dict):
        from forensic_viz.explore import sandbox_compute
        try:
            out = sandbox_compute(
                float(body["base"]), float(body["wacc"]),
                float(body["g0"]), float(body["g_term"]),
                float(body.get("bridge", 0.0)),
                float(body.get("shares", 0.0)),
                float(body.get("sbc", 0.0)),
                bool(body.get("ex_sbc", False)),
                price=(float(body["price"])
                       if body.get("price") is not None else None),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return payload("sandbox", out)

    @app.get("/api/ledger", dependencies=[Depends(auth)])
    async def ledger():
        from forensic_viz.ledger import Ledger
        return payload("ledger", Ledger().list_verdicts())

    @app.get("/api/ledger/{ticker}", dependencies=[Depends(auth)])
    async def ledger_history(ticker: str):
        from forensic_viz.ledger import Ledger
        return payload("ledger_history",
                       Ledger().history(ticker.strip().upper()))

    @app.post("/api/export/{kind}", dependencies=[Depends(auth)])
    async def export(kind: str, body: dict):
        import tempfile
        from pathlib import Path
        d = _run(str(body.get("ticker", "")))
        out_dir = Path(body.get("out_dir")
                       or tempfile.mkdtemp(prefix="bhf_export_"))
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = d.generated.isoformat()
        if kind == "model":
            from forensic_viz.model_export import export_financial_model
            path = out_dir / f"{d.ticker}_financial_model_{stamp}.xlsx"
            export_financial_model(d, str(path))
        elif kind == "csv":
            from forensic_viz.export import export_fundamentals_csv
            path = out_dir / f"{d.ticker}_fundamentals_{stamp}.csv"
            export_fundamentals_csv(d, str(path))
        elif kind == "pdf":
            from forensic_viz.dashboard import (
                render_dashboard, render_health_report,
                render_unit_economics, render_valuation, render_verdict,
            )
            from forensic_viz.export import export_pdf
            figs = [render_dashboard(d), render_unit_economics(d),
                    render_health_report(d)]
            held = app.state.valuations.get(d.ticker)
            if held is not None:
                res, verdict = held
                figs.append(render_valuation(d, res))
                figs.append(render_verdict(d, res, verdict))
            path = out_dir / f"{d.ticker}_{d.display_years}y_report_" \
                             f"{stamp}.pdf"
            export_pdf(figs, str(path))
        else:
            raise HTTPException(status_code=404,
                                detail=f"unknown export kind {kind!r}")
        return {"schema": SCHEMA_VERSION, "kind": f"export_{kind}",
                "data": {"path": str(path)}}

    return app

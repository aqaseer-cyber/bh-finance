"""FIX-5 — numeric JS↔Python DCF parity.

Executes the sandbox's extracted JS engine in a real JS runtime and asserts it
matches valuation.dcf_fcff over a randomized grid. A skipping test would be the
same lie as no test, so this FAILS (not skips) if no JS engine is importable.
"""
import json
import random

import pytest

from forensic_viz.interactive import SANDBOX_DCF_JS
from forensic_viz.valuation import ValuationError, dcf_fcff


def _js_engine():
    try:
        import quickjs
        ctx = quickjs.Context()
        ctx.eval(SANDBOX_DCF_JS)
        return lambda b, w, g0, g: ctx.eval(
            f"JSON.stringify(dcf({b!r},{w!r},{g0!r},{g!r}))")
    except ImportError:
        import dukpy
        return lambda b, w, g0, g: dukpy.evaljs(
            SANDBOX_DCF_JS + f"; JSON.stringify(dcf({b!r},{w!r},{g0!r},{g!r}))")


def test_js_matches_python_over_grid():
    run = _js_engine()
    rng = random.Random(20260704)
    for _ in range(200):
        base = rng.uniform(1e8, 5e10)
        g = rng.uniform(0.0, 0.035)
        wacc = rng.uniform(g + 0.005, 0.15)
        g0 = rng.uniform(-0.05, 0.20)
        js = json.loads(run(base, wacc, g0, g))
        py = dcf_fcff(base, wacc, g0, g)
        assert js["ev"] == pytest.approx(py["ev"], rel=1e-9)
        assert js["tvShare"] == pytest.approx(py["tv_share"], rel=1e-9)


def test_js_guard_matches_python():
    run = _js_engine()
    assert json.loads(run(1e9, 0.05, 0.03, 0.06)) is None  # wacc <= g → null
    with pytest.raises(ValuationError):
        dcf_fcff(1e9, 0.05, 0.03, 0.06)

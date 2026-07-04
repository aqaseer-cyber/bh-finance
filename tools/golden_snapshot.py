"""Dump deterministic valuation outputs from the offline fixtures.

Usage: python tools/golden_snapshot.py docs/golden_pre_fix.json
Run once before FIX-1 and once after FIX-9 (as golden_post_fix.json).
The snapshot must use EXACTLY the same facts dict as the test suite —
it imports the conftest builder directly.
"""
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forensic_viz.edgar import parse_companyfacts  # noqa: E402
from forensic_viz.metrics import (  # noqa: E402
    DashboardData, apply_track, build_fundamental_metrics,
)
from forensic_viz.valuation import (  # noqa: E402
    CaseInputs, ValuationInputs, build_valuation,
)
from forensic_viz.verdict import build_verdict  # noqa: E402
from tests.conftest import build_testco_companyfacts  # noqa: E402


def main(out_path: str) -> None:
    facts = build_testco_companyfacts()
    d = DashboardData(ticker="TESTCO", company="TESTCO Inc", subtitle="",
                      generated=dt.date(2026, 7, 3))
    d.sic_code = "3571"
    apply_track(d, "auto")
    build_fundamental_metrics(parse_companyfacts(facts, "TESTCO"), d)
    d.last_close = 100.0
    d.price_dates = [dt.date(2026, 7, 1)]
    d.price_closes = [100.0]
    inputs = ValuationInputs(method="dcf", discount_rate=0.09, cases={
        "Bear": CaseInputs(g0=0.02, g_term=0.02),
        "Base": CaseInputs(g0=0.05, g_term=0.025),
        "Bull": CaseInputs(g0=0.09, g_term=0.03)})
    res = build_valuation(d, inputs)
    v = build_verdict(d, inputs, res, rating="Buy")
    out = {
        "cases": {c.name: {"fv_ps": c.fv_ps, "mos": c.mos, "tv_share": c.tv_share}
                  for c in res.cases},
        "implied_g": res.implied_g, "market_ev": res.market_ev,
        "net_debt": res.net_debt,
        "verdict": {"fv_a": v.fv_a, "fv_b": v.fv_b, "fv_avg": v.fv_avg,
                    "mos": v.mos, "stressed_mos": v.stressed_mos,
                    "coherence": v.coherence},
    }
    Path(out_path).write_text(json.dumps(out, indent=2))
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "docs/golden_pre_fix.json")

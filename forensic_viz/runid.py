"""v3 R3b — run identity: one run, three artifacts, zero divergence.

Every run mints a `run_id` and an `input hash` (design principle 2). The
hash covers what went IN — ticker, fiscal window, display years, track,
price, discount-rate build, provider set, and the valuation inputs when
one is attached — so two artifacts carrying the same run_id are claims
about the same inputs. The R3d slice adds the cross-artifact FV/MoS
equality assertion and the run manifest; this module only mints the
identity and never touches key material (provider NAMES only).
"""
from __future__ import annotations

import hashlib
import json
from typing import Optional, Tuple

from . import config


def provider_set(d) -> str:
    """The run's source line: EDGAR always, plus each configured provider
    that can have contributed (names only — never key material)."""
    parts = ["EDGAR"]
    if getattr(d, "price_source", ""):
        parts.append(str(d.price_source))
    for key, name in ((config.FMP_API_KEY, "FMP"),
                      (config.TIINGO_API_KEY, "Tiingo"),
                      (config.FINNHUB_API_KEY, "Finnhub")):
        if key and name not in " ".join(parts):
            parts.append(name)
    return " + ".join(parts)


def _valuation_inputs(res) -> Optional[dict]:
    inputs = getattr(res, "_inputs", None) if res is not None else None
    if inputs is None:
        return None
    return {
        "method": inputs.method,
        "discount_rate": inputs.discount_rate,
        "base_value": inputs.base_value,
        "ex_sbc": inputs.ex_sbc,
        "cases": {name: [c.g0, c.g_term, c.roe, c.affo_ps,
                         c.target_yield, c.fv_ps]
                  for name, c in sorted(inputs.cases.items())},
    }


def run_identity(d, res=None) -> Tuple[str, str]:
    """(run_id, input_hash) — deterministic for identical inputs.

    input_hash (10 hex) covers the analytical inputs; run_id (8 hex) adds
    the run date and app version, so a re-run on a later day is a new run
    even when nothing else moved (identical inputs on the SAME day are
    the same run — they would produce byte-identical artifacts)."""
    build = getattr(d, "wacc_build", None)
    payload = {
        "ticker": d.ticker,
        "fy_ends": [e.isoformat() for e in
                    (getattr(getattr(d, "fundamentals", None), "fy_ends",
                             None) or [])],
        "display_years": getattr(d, "display_years", None),
        "track": getattr(d, "track", ""),
        "price": getattr(d, "last_close", None),
        "price_date": (d.price_dates[-1].isoformat()
                       if getattr(d, "price_dates", None) else ""),
        "rates": ([build.r_f, build.beta, build.erp, build.wacc]
                  if build is not None else None),
        "providers": provider_set(d),
        "valuation": _valuation_inputs(res),
    }
    blob = json.dumps(payload, sort_keys=True, default=str).encode()
    input_hash = hashlib.sha256(blob).hexdigest()[:10]
    rid = hashlib.sha256(
        f"{input_hash}|{d.generated.isoformat()}|{config.APP_VERSION}"
        .encode()).hexdigest()[:8]
    return rid, input_hash

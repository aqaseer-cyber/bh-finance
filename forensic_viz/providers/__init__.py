"""FIX-17a: provider registry + the capability probe.

`probe_all` live-tests every configured key against the endpoints
FIX-17b..f intend to use; `render_probe` prints the matrix plus verdict
lines that lock later design decisions on recorded fact (most
importantly: which key, if any, serves analyst estimates)."""
from __future__ import annotations

from .. import config
from .base import ProbeResult, ProviderError, key_tail
from .finnhub import FinnhubClient
from .finnhub import probe as _probe_finnhub
from .fmp import FMPClient
from .fmp import probe as _probe_fmp
from .tiingo import TiingoClient
from .tiingo import probe as _probe_tiingo

__all__ = [
    "FMPClient", "TiingoClient", "FinnhubClient", "ProviderError",
    "ProbeResult", "key_tail", "probe_all", "render_probe",
]


def probe_all(ticker: str, transports: dict | None = None):
    """Run every provider's probe. `transports` maps provider name ->
    fake transport (tests); None means live HTTP."""
    t = transports or {}
    results: list[ProbeResult] = []
    results += _probe_fmp(ticker, transport=t.get("FMP"))
    results += _probe_tiingo(ticker, transport=t.get("Tiingo"))
    results += _probe_finnhub(ticker, transport=t.get("Finnhub"))
    return results


def _ok(results, provider: str, check_substr: str) -> bool:
    return any(r.provider == provider and check_substr in r.check
               and r.status == "OK" for r in results)


def render_probe(results, ticker: str) -> str:
    lines = [
        f"Provider capability probe — {ticker}",
        (f"keys: FMP {key_tail(config.FMP_API_KEY)} | "
         f"Tiingo {key_tail(config.TIINGO_API_KEY)} | "
         f"Finnhub {key_tail(config.FINNHUB_API_KEY)}"),
        "-" * 72,
    ]
    for r in results:
        lines.append(f"[{r.provider:<7}] {r.check:<28} {r.status:<7} "
                     f"{r.detail}")
    lines.append("-" * 72)

    est_fmp = _ok(results, "FMP", "ANALYST ESTIMATES")
    est_fnh = (_ok(results, "Finnhub", "EPS ESTIMATES")
               or _ok(results, "Finnhub", "REVENUE ESTIMATES"))
    if est_fmp or est_fnh:
        via = " + ".join(p for p, on in (("FMP", est_fmp),
                                         ("Finnhub", est_fnh)) if on)
        lines.append(f"verdict: analyst growth estimates AVAILABLE via "
                     f"{via} — FIX-17f ships the estimates panel")
    else:
        lines.append("verdict: analyst estimates NOT served by the "
                     "configured keys — FIX-17f decision: FMP Starter "
                     "plan, or ship recommendation-trends only")
    lines.append(f"verdict: recheck sources — FMP statements "
                 f"{'OK' if _ok(results, 'FMP', 'income-statement') else 'unavailable'}"
                 f", Finnhub as-reported "
                 f"{'OK' if _ok(results, 'Finnhub', 'financials as reported') else 'unavailable'}")
    lines.append(f"verdict: price history — Tiingo "
                 f"{'OK' if _ok(results, 'Tiingo', 'daily price depth') else 'unavailable'}")
    lines.append("note: keys are shown as ...tail4 only; paste this "
                 "output back verbatim — it contains no secrets")
    return "\n".join(lines)

"""FIX-17a: pluggable market-data providers — shared plumbing.

Doctrine (owner-ratified): SEC EDGAR remains the single displayed source
of truth. A provider value never replaces an EDGAR number silently — it
confirms it, flags a divergence, or fills a hole EDGAR left empty while
saying so on-page. Every provider declares a provenance grade:

  audited-filing  parsed directly from an SEC filing (EDGAR itself)
  aggregator      a commercial normalization of filings or exchange
                  data (FMP, Finnhub, Tiingo) — convenient, not auditable
  scrape          an HTML page read (grade reserved; none shipped)

Key discipline: API keys come from environment variables first
(FMP_API_KEY, TIINGO_API_KEY, FINNHUB_API_KEY), settings.json (per-user
app data, outside the repo) as fallback. Keys travel in request HEADERS,
never in URLs, so they cannot leak into logs or exception text, and are
only ever displayed as a ...tail4 via `key_tail`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Optional

from .. import config

Transport = Callable[[str, dict, dict, float], "tuple[int, str]"]


class ProviderError(RuntimeError):
    """HTTP or configuration failure from a provider. `status` carries
    the HTTP code (0 = no key configured, -1 = transport error)."""

    def __init__(self, message: str, status: int = -1):
        super().__init__(message)
        self.status = status


def key_tail(key: str) -> str:
    """The only permitted rendering of a key: its last four characters."""
    return f"...{key[-4:]}" if key else "not set"


def _default_transport(url: str, headers: dict, params: dict,
                       timeout: float):
    import requests
    resp = requests.get(url, headers=headers, params=params,
                        timeout=timeout)
    return resp.status_code, resp.text


class BaseClient:
    """Minimal JSON-over-HTTPS client. Subclasses set `name`,
    `provenance`, the key property and auth headers."""

    name = "?"
    provenance = "aggregator"

    def __init__(self, transport: Optional[Transport] = None,
                 timeout: Optional[float] = None):
        self._transport = transport or _default_transport
        self._timeout = timeout or config.HTTP_TIMEOUT

    @property
    def key(self) -> str:  # pragma: no cover - overridden
        return ""

    def has_key(self) -> bool:
        return bool(self.key)

    def _headers(self) -> dict:  # pragma: no cover - overridden
        return {}

    def get_json(self, url: str, params: Optional[dict] = None):
        if not self.has_key():
            raise ProviderError(f"{self.name} API key not configured",
                                status=0)
        try:
            status, body = self._transport(url, self._headers(),
                                           params or {}, self._timeout)
        except Exception as exc:
            raise ProviderError(f"transport: {exc}", status=-1)
        if status == 200:
            try:
                return json.loads(body)
            except ValueError:
                raise ProviderError("non-JSON response", status=200)
        raise ProviderError(str(body)[:120].replace("\n", " "),
                            status=status)


# ------------------------------------------------------------ probing

@dataclass
class ProbeResult:
    provider: str
    check: str
    status: str          # OK | EMPTY | DENIED | KEY? | NO KEY | ERROR
    detail: str = ""


def run_check(provider: str, check: str, fn, describe) -> ProbeResult:
    """Run one live endpoint check. 401 renders as KEY? (auth problem),
    402/403 as DENIED (plan does not include the endpoint) — the probe's
    whole point is telling those two apart."""
    try:
        data = fn()
    except ProviderError as exc:
        if exc.status == 0:
            return ProbeResult(provider, check, "NO KEY")
        if exc.status == 401:
            return ProbeResult(provider, check, "KEY?",
                               f"HTTP 401: {exc}")
        if exc.status in (402, 403):
            return ProbeResult(provider, check, "DENIED",
                               f"HTTP {exc.status}: {exc}")
        return ProbeResult(provider, check, "ERROR",
                           f"HTTP {exc.status}: {exc}")
    except Exception as exc:  # never let one check kill the matrix
        return ProbeResult(provider, check, "ERROR", str(exc)[:100])
    try:
        detail = describe(data)
    except Exception:
        detail = None
    if detail:
        return ProbeResult(provider, check, "OK", detail)
    return ProbeResult(provider, check, "EMPTY", "no records returned")

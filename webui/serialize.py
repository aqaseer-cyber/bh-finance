"""v3 R0: versioned JSON serialization of the engine's dataclasses.

One generic, lossless-where-it-matters encoder instead of per-field
hand mapping: dataclasses become dicts, dates become ISO strings,
tuple dict-keys join on '|', sets sort into lists, NaN/inf become null
(JSON has no honest spelling for them, and the UI's dash IS the honest
rendering). Bulk raw payloads are excluded by name — the frontend
never needs the untrimmed companyfacts JSON.

Every payload is wrapped as {"schema": SCHEMA_VERSION, "kind": ...,
"data": ...}; bump SCHEMA_VERSION on any breaking shape change.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import math
from types import SimpleNamespace
from typing import Any

SCHEMA_VERSION = 1

# bulk or private fields never serialized (raw companyfacts payload,
# quarterly parse caches)
_SKIP_FIELDS = {"raw_facts", "_qdata_cache"}

_MAX_DEPTH = 24


def to_jsonable(obj: Any, _depth: int = 0) -> Any:
    if _depth > _MAX_DEPTH:
        return str(obj)
    if obj is None or isinstance(obj, (bool, int, str)):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, (dt.datetime, dt.date)):
        return obj.isoformat()
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {
            f.name: to_jsonable(getattr(obj, f.name), _depth + 1)
            for f in dataclasses.fields(obj)
            if f.name not in _SKIP_FIELDS
            and not f.name.startswith("_")
        }
    if isinstance(obj, SimpleNamespace):
        return {k: to_jsonable(v, _depth + 1)
                for k, v in vars(obj).items()
                if k not in _SKIP_FIELDS and not k.startswith("_")}
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(k, tuple):
                key = "|".join(str(p) for p in k)
            else:
                key = k.isoformat() if isinstance(k, (dt.date,)) \
                    else str(k)
            if key in _SKIP_FIELDS or key.startswith("_"):
                continue
            out[key] = to_jsonable(v, _depth + 1)
        return out
    if isinstance(obj, (set, frozenset)):
        return sorted(str(x) for x in obj)
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(x, _depth + 1) for x in obj]
    return str(obj)


def payload(kind: str, obj: Any) -> dict:
    return {"schema": SCHEMA_VERSION, "kind": kind,
            "data": to_jsonable(obj)}

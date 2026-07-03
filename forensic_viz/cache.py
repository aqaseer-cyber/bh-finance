"""Tiny JSON file cache with per-entry TTL."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Optional

from . import config


class Cache:
    def __init__(self, directory: Optional[Path] = None, enabled: bool = True):
        self.enabled = enabled
        self.directory = directory or config.cache_dir()

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
        return self.directory / f"{digest}.json"

    def get(self, key: str, ttl: float) -> Optional[Any]:
        if not self.enabled:
            return None
        path = self._path(key)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if time.time() - raw["saved_at"] > ttl:
                return None
            return raw["value"]
        except (OSError, ValueError, KeyError):
            return None

    def put(self, key: str, value: Any) -> None:
        if not self.enabled:
            return
        path = self._path(key)
        try:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps({"key": key, "saved_at": time.time(), "value": value}),
                encoding="utf-8",
            )
            tmp.replace(path)
        except OSError:
            pass  # cache is best-effort

"""FIX-17h: fact store round-trips, ParsedInstance serialization
fidelity, memoized parse (hit / miss / version bump), and the parallel
cache-warmer. All offline."""
import datetime as dt
import json

import pytest

from forensic_viz import config, segments
from forensic_viz.factstore import FactStore
from forensic_viz.segments import (
    ParsedInstance, _dump_parsed, _load_parsed, stored_parse,
)

D1, D2 = dt.date(2024, 1, 1), dt.date(2024, 12, 31)


def _sample_parsed():
    return ParsedInstance(
        singles={("Segments", "Optum", "revenue"): {(D1, D2): 1.25e9}},
        crosses={("Segments", "Optum", "Geography", "US", "revenue"):
                 {(D1, D2): 9.9e8}},
        n_multi=3,
        member_qnames={("Segments", "Optum"): {"unh:OptumMember"}},
        conflicts=["one warning"],
    )


def test_factstore_round_trip_and_misses(tmp_path):
    store = FactStore(path=tmp_path / "facts.db")
    assert store.get("nope") is None
    store.put("k", {"a": [1, 2.5, "x"]})
    assert store.get("k") == {"a": [1, 2.5, "x"]}
    store.put("k", {"b": 1})                      # overwrite
    assert store.get("k") == {"b": 1}
    # non-serializable payloads are dropped silently
    store.put("bad", {"x": dt.date(2024, 1, 1)})
    assert store.get("bad") is None
    # a corrupted db degrades to misses, never raises
    (tmp_path / "facts.db").write_bytes(b"not a database")
    assert FactStore(path=tmp_path / "facts.db").get("k") is None


def test_parsed_instance_serialization_fidelity():
    p = _sample_parsed()
    # through actual JSON, exactly as the store transports it
    q = _load_parsed(json.loads(json.dumps(_dump_parsed(p))))
    assert q == p
    assert q.singles[("Segments", "Optum", "revenue")][(D1, D2)] == \
        pytest.approx(1.25e9)
    assert isinstance(next(iter(q.member_qnames.values())), set)


def test_stored_parse_hits_and_version_bump(tmp_path, monkeypatch):
    store = FactStore(path=tmp_path / "facts.db")
    calls = []
    real = segments.parse_instance

    def counting(xml):
        calls.append(1)
        return real(xml)

    monkeypatch.setattr(segments, "parse_instance", counting)
    xml = "<xbrl></xbrl>"                        # parses to empty facts
    parse = stored_parse(store)
    first = parse(xml)
    second = parse(xml)                          # served from the store
    assert len(calls) == 1
    assert first == second
    monkeypatch.setattr(segments, "SEG_PARSER_VERSION", 999)
    parse(xml)                                   # version bump -> re-parse
    assert len(calls) == 2


class _FakeSession:
    """Stands in for _SecSession: cache-backed, records fetches."""

    def __init__(self, cache):
        self.cache = cache
        self.fetched = []

    def get_text(self, url, ttl):
        hit = self.cache.get(url, ttl)
        if hit is not None:
            return hit
        self.fetched.append(url)
        if "boom" in url:
            raise RuntimeError("unreachable")
        body = f"body-of-{url}"
        self.cache.put(url, body)
        return body


def test_prefetch_warms_cache_and_swallows_failures(tmp_path):
    from forensic_viz.cache import Cache
    from forensic_viz.edgar import prefetch_texts

    cache = Cache(directory=tmp_path)
    cache.put("u1", "already-cached")
    sec = _FakeSession(cache)
    urls = ["u1", "u2", "u3", "boom://x", "u2", None]
    prefetch_texts(sec, urls, ttl=3600)
    # cached + duplicate + None skipped; failure swallowed
    assert sorted(sec.fetched) == ["boom://x", "u2", "u3"]
    assert cache.get("u2", 3600) == "body-of-u2"
    assert cache.get("u3", 3600) == "body-of-u3"
    # the serial pass now hits cache for everything that worked
    assert sec.get_text("u2", 3600) == "body-of-u2"
    assert len(sec.fetched) == 3


def test_prefetch_skips_trivial_batches(tmp_path):
    from forensic_viz.cache import Cache
    from forensic_viz.edgar import prefetch_texts

    cache = Cache(directory=tmp_path)
    sec = _FakeSession(cache)
    prefetch_texts(sec, ["only-one"], ttl=3600)   # < 2 misses: no pool
    assert sec.fetched == []


def test_build_segment_data_default_parse_is_pure(tmp_path, monkeypatch):
    """Offline callers (tests, fixtures) must never touch the store."""
    opened = []
    monkeypatch.setattr(FactStore, "_connect",
                        lambda self: opened.append(1) or (_ for _ in ())
                        .throw(AssertionError("store touched")))
    segments.build_segment_data([("10-K test", "<xbrl></xbrl>")])
    assert opened == []

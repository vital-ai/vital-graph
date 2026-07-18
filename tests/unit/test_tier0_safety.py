"""P1 / Tier 0 safety gates (L0 — no DB): the caps that prevent OOM/DoS at scale.

- term cache is LRU-bounded (was an unbounded dict → OOM risk at 1B, see
  100x_scalability_analysis.md §5.1)
- property-path depth is fenced low (runaway recursive CTE fence, §7)
"""

import pytest

from vitalgraph.db.sparql_sql.generator import (
    _LRUCache, _term_cache, _TERM_CACHE_MAX, invalidate_term_cache)
from vitalgraph.db.sparql_sql.emit_path import MAX_PATH_DEPTH

pytestmark = pytest.mark.unit


def test_lru_cache_evicts_oldest_at_cap():
    c = _LRUCache(3)
    for i in range(5):
        c[i] = i
    assert len(c) == 3
    assert set(c.keys()) == {2, 3, 4}      # 0,1 evicted


def test_lru_get_refreshes_recency():
    c = _LRUCache(3)
    c[1], c[2], c[3] = 1, 2, 3
    assert c.get(1) == 1                    # touch 1 → most-recently-used
    c[4] = 4                                # evicts the now-oldest (2)
    assert 1 in c and 2 not in c and 4 in c


def test_lru_get_missing_returns_default():
    c = _LRUCache(2)
    assert c.get(("nope",)) is None
    assert c.get(("nope",), 42) == 42


def test_term_cache_is_bounded():
    assert isinstance(_term_cache, _LRUCache)
    assert _term_cache._maxsize == _TERM_CACHE_MAX == 50_000


def test_invalidate_term_cache_scoped_and_full():
    _term_cache[("spaceX", "t", "U")] = "u1"
    _term_cache[("spaceY", "t", "U")] = "u2"
    invalidate_term_cache("spaceX")
    assert ("spaceX", "t", "U") not in _term_cache
    assert ("spaceY", "t", "U") in _term_cache
    invalidate_term_cache()                 # full clear
    assert len(_term_cache) == 0


def test_property_path_depth_is_finite_and_nesting_safe():
    # Two-sided: it must be a FINITE backstop (not unbounded recursion), but ALSO
    # high enough not to truncate legitimate deep-but-narrow traversals like
    # arbitrary-depth frame nesting (frame_entity_integrity_plan.md §7). A cap too
    # low silently under-counts nested-frame relation queries; the real runaway
    # fence is statement_timeout/temp_file_limit, not this value.
    assert 16 <= MAX_PATH_DEPTH <= 128

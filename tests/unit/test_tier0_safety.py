"""P1 / Tier 0 safety gates (L0 — no DB): the caps that prevent OOM/DoS at scale.

- term cache is LRU-bounded (was an unbounded dict → OOM risk at 1B, see
  100x_scalability_analysis.md §5.1)
- recursive property-path CTEs TERMINATE (they deduplicate, §7)
"""

import pytest

from vitalgraph.db.sparql_sql.generator import (
    _LRUCache, _term_cache, _TERM_CACHE_MAX, invalidate_term_cache)


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


def test_recursive_path_ctes_deduplicate_so_they_terminate():
    """A recursive path must terminate on cyclic data BY CONSTRUCTION.

    This used to assert `16 <= MAX_PATH_DEPTH <= 128` — a finite depth cap as
    the backstop against unbounded recursion. That cap was removed in
    `issues/123`, and the reason is worth keeping: it was containing a runaway
    the depth column itself created.

    `UNION` deduplicates, which is what terminates a transitive closure over a
    cycle — revisiting a pair adds no row. But `depth` was part of the CTE
    tuple, so `(s,e,1)` and `(s,e,2)` were distinct, the dedup never fired, and
    only the cap stopped the recursion. On a three-node cycle: 300 rows with
    the depth column, 9 without.

    With `depth` gone, termination is guaranteed by the finiteness of the
    graph — there are only so many distinct (start, end) pairs — which is a
    STRONGER property than a magic constant. This asserts the mechanism that
    provides it, so a change to `UNION ALL` fails here rather than hanging a
    query.

    The cap never was the runaway fence, and the comment it carried said so.
    `100x_scalability_analysis.md` §7 shows the 1B-row blowup reaching "tens of
    billions of rows" WITH the cap in place; work is bounded by
    `statement_timeout` and `temp_file_limit`, which is what the rest of this
    file tests.
    """
    import pathlib as _pl
    src = _pl.Path("vitalgraph/db/sparql_sql/emit_path.py").read_text()

    # Every recursive CTE body in this file must use deduplicating UNION.
    bodies = [m for m in src.split("rec_body = (")[1:]]
    assert bodies, "no recursive CTE bodies found — has emit_path been restructured?"
    for body in bodies:
        head = body[:1200]
        assert "UNION ALL" not in head, (
            "a recursive property-path CTE uses UNION ALL. Without dedup it "
            "cannot terminate on cyclic data, and the depth cap that used to "
            "stop it was removed in issues/123.")

    # And no depth column may come back, since that is what defeats the dedup.
    assert "depth" not in src.split("def _path_to_sql")[-1].lower(), (
        "a `depth` column reappeared in the recursive CTEs. It makes "
        "(s,e,1) and (s,e,2) distinct rows, which defeats the UNION dedup that "
        "terminates a cycle — and then a cap is needed again (issues/123).")

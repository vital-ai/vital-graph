"""Scaling and staleness in `estimate_range` — the pure half, no database.

`apply_freshness` needs a connection and is covered by the integration and
scratch-space work. What is tested here is the contract it writes into the stats
dict and how `estimate_range` consumes it, because that is where a mistake is
silent: a scale of 0, or a stale flag that returns 0 instead of None, would look
like "this criterion matches almost nothing" — the exact direction that gets a
filter applied last.
"""

import pytest

from vitalgraph.db.sparql_sql.sync_value_stats import (
    DRIFT_EPSILON, SHAPE_TOLERANCE, estimate_range)

PRED = "11111111-1111-5111-8111-111111111111"


def _stats(total=60_000, scale=1.0, stale=False, nb=32):
    """A uniform 0..100 histogram with `nb` buckets."""
    return {(PRED, "num"): {
        "bounds": [i * (100.0 / nb) for i in range(nb + 1)],
        "total": total, "pred_rows": total, "scale": scale, "stale": stale,
    }}


def test_unscaled_is_the_old_behaviour():
    """scale 1.0 must reproduce exactly what shipped before freshness existed."""
    assert estimate_range(_stats(), PRED, "num", ">=", 50) == 30_000


def test_growth_is_corrected_by_the_scale():
    """The measured case: 2.00x growth, same distribution.

    The boundaries are still right, so the fraction is still right and only the
    multiplier is behind. Scaling recovers the live answer.
    """
    at_build = estimate_range(_stats(), PRED, "num", ">=", 50)
    scaled = estimate_range(_stats(scale=2.0), PRED, "num", ">=", 50)
    assert at_build == 30_000
    assert scaled == 60_000, "growth must be corrected, not merely detected"


def test_scale_never_produces_zero():
    """A zero estimate is what makes a filter get applied last."""
    tiny = estimate_range(_stats(total=4, scale=0.001), PRED, "num", ">=", 99)
    assert tiny is not None and tiny >= 1


def test_stale_returns_none_not_zero():
    """None means UNKNOWN, and the caller falls back to an exact count.

    Returning a number here is what the whole guard exists to prevent — at 2.00x
    drift with a shifted distribution the estimate was 92.4% wrong, and still
    84.8% wrong after scaling, which is why a shifted histogram is withdrawn
    rather than corrected.
    """
    assert estimate_range(_stats(stale=True), PRED, "num", ">=", 50) is None
    assert estimate_range(_stats(stale=True, scale=2.0), PRED, "num", "<=", 50) is None


def test_missing_freshness_keys_are_inert():
    """An entry from a loader that never ran freshness must behave as before."""
    bare = {(PRED, "num"): {"bounds": [i * 3.125 for i in range(33)],
                            "total": 60_000}}
    assert estimate_range(bare, PRED, "num", ">=", 50) == 30_000


def test_thresholds_sit_where_the_measurement_put_them():
    """Guard the two constants against a well-meaning tweak.

    Measured (`bench_histogram_drift_curve.py`): pure GROWTH moves the median
    split by 0.008 at every drift ratio out to 3.00x; a SHIFT moves it 0.051 at
    1.10x drift. A tolerance outside this band either fires on benign growth or
    misses a real shift at the smallest drift tested.
    """
    assert 0.008 < SHAPE_TOLERANCE < 0.051
    # The pre-filter only decides whether a probe is worth a query, so it just
    # has to be small enough that a real shift is never skipped.
    assert 0 < DRIFT_EPSILON <= 0.05


@pytest.mark.parametrize("op,expected", [(">=", 60_000), ("<=", 60_000)])
def test_scaling_applies_to_both_directions(op, expected):
    assert estimate_range(_stats(scale=2.0), PRED, "num", op, 50) == expected


# ---------------------------------------------------------------------------
# The probe cache — see the note on `_probe_cache`
# ---------------------------------------------------------------------------

class _FakeConn:
    """Counts the probe queries `apply_freshness` issues.

    The probe asks for three quantiles in ONE pass, so `counts` is the number
    of scans — one per probe, not two as the first version issued.
    `fracs` is the live fraction below each of (Q1, median, Q3); the histogram
    is uniform, so (0.25, 0.5, 0.75) is a perfectly fresh shape.
    """

    def __init__(self, pred_rows, fracs=(0.25, 0.5, 0.75), total=120_000):
        self.pred_rows, self.fracs, self.total = pred_rows, fracs, total
        self.counts = 0

    async def fetch(self, sql, *args):
        return [{"predicate_uuid": PRED, "row_count": self.pred_rows}]

    async def fetchrow(self, sql, *args):
        self.counts += 1
        row = {f"b{i}": int(f * self.total) for i, f in enumerate(self.fracs)}
        row["total"] = self.total
        return row


@pytest.fixture(autouse=True)
def _clear_probe_cache():
    from vitalgraph.db.sparql_sql.sync_value_stats import invalidate_freshness_cache
    invalidate_freshness_cache()
    yield
    invalidate_freshness_cache()


async def _apply(conn, stats):
    from vitalgraph.db.sparql_sql.sync_value_stats import apply_freshness
    return await apply_freshness(conn, "sp_test", stats)


@pytest.mark.asyncio
async def test_the_probe_runs_once_per_drift_level_not_once_per_query():
    """Two count(*) scans per predicate per QUERY is what this avoids.

    Drift persists until a rebuild, so an uncached probe repeats a scan
    proportional to the predicate's row count on every query the space serves.
    """
    conn = _FakeConn(pred_rows=120_000)
    for _ in range(5):
        s = _stats()
        s[(PRED, "num")]["pred_rows"] = 60_000     # 2.00x drift
        summary = await _apply(conn, s)
    assert conn.counts == 1, (
        f"probed {conn.counts} times for one drift level; the cache is not "
        f"holding")
    assert summary["cached"] >= 1


@pytest.mark.asyncio
async def test_a_cached_stale_verdict_still_withdraws_the_estimate():
    """The cache must carry the VERDICT, not just skip the work."""
    # Mass piled below Q1: a large shape move at the first quantile.
    conn = _FakeConn(pred_rows=120_000, fracs=(0.90, 0.95, 0.98))
    s = _stats()
    s[(PRED, "num")]["pred_rows"] = 60_000
    await _apply(conn, s)
    assert s[(PRED, "num")]["stale"] is True

    s2 = _stats()
    s2[(PRED, "num")]["pred_rows"] = 60_000
    await _apply(conn, s2)                          # served from cache
    assert s2[(PRED, "num")]["stale"] is True, (
        "a cached stale verdict was dropped, so the estimate is used again")


@pytest.mark.asyncio
async def test_a_materially_different_drift_level_re_probes():
    """The verdict is valid for a band, not forever."""
    conn = _FakeConn(pred_rows=120_000)
    s = _stats()
    s[(PRED, "num")]["pred_rows"] = 60_000          # 2.00x
    await _apply(conn, s)
    assert conn.counts == 1

    conn.pred_rows = 200_000                        # 3.33x — well outside the band
    s2 = _stats()
    s2[(PRED, "num")]["pred_rows"] = 60_000
    await _apply(conn, s2)
    assert conn.counts == 2, "drift moved materially and was not re-probed"


@pytest.mark.asyncio
async def test_no_drift_means_no_probe_at_all():
    """The free pre-filter: a distribution cannot move without writing rows."""
    conn = _FakeConn(pred_rows=60_000, total=60_000)
    s = _stats()
    s[(PRED, "num")]["pred_rows"] = 60_000          # 1.00x
    summary = await _apply(conn, s)
    assert conn.counts == 0
    assert summary["probes"] == 0 and summary["scaled"] == 0

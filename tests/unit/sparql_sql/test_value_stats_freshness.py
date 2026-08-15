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

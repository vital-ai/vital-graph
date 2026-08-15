"""Equi-depth value histograms, for estimating RANGE criteria.

`rdf_stats` answers "how many quads have predicate P and object O" exactly, and
that is enough for equality against a small value set. It cannot answer a RANGE
over a large one, because it is a frequent-value list capped per predicate:

    predicate    distinct objects   in rdf_stats   coverage
    score                     100            100     100.0%
    category                    8              8     100.0%
    occurred               68,502            196       0.3%
    weight                 64,525          2,000       3.1%

Summing it for `occurred >= 2024-07-01` estimated 244 rows where the answer was
53,455 — a 99.5% error, and in the direction that matters, since a criterion
believed tiny gets applied last, after the traversal has expanded (issues/090).

WHY EQUI-DEPTH

Bucket boundaries are drawn at quantiles, so every bucket holds the same number
of rows and only the boundaries need storing. The selectivity of `val >= X` is
then (buckets wholly above X) / (bucket count), plus a linear interpolation
inside the bucket that straddles X. Equi-WIDTH would need the counts stored and
would degrade exactly where these values are worst — a lognormal score or an
exponential timestamp puts most rows in a few narrow buckets.

Bounded by construction: `buckets` rows per (predicate, lane), a few hundred per
space, against one row per distinct value for a complete histogram.

WHAT IT DOES NOT DO

It estimates the number of QUADS matching a value predicate. It says nothing
about how those quads join to anything else — the join cardinality through
nested subqueries is a separate problem, and extended statistics on the
correlated quad columns moved that estimate from 1 to 2 (issues/090). This is
the input to a decision the GENERATOR makes, not something PostgreSQL can be
told.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Buckets per (predicate, lane). 32 puts the interpolation error inside a
# bucket at ~3% of the predicate's rows, which is far below the error that
# changes a plan choice, and keeps the table small enough to load whole.
DEFAULT_BUCKETS = 32

# Above this many rows for one predicate, sample rather than sort everything.
# The boundaries of an equi-depth histogram are stable under sampling long
# before the exact values are.
SAMPLE_THRESHOLD = 2_000_000
SAMPLE_ROWS = 200_000

NUM = "num"
DT = "dt"


async def resync_value_stats(conn, space_id: str,
                             buckets: int = DEFAULT_BUCKETS) -> Dict[str, int]:
    """Rebuild the value histograms for every predicate that has values.

    Returns {"num_predicates": n, "dt_predicates": n, "rows": n}.
    """
    vstats = f"{space_id}_rdf_value_stats"
    quad = f"{space_id}_rdf_quad"
    term = f"{space_id}_term"

    await conn.execute(f"TRUNCATE {vstats}")

    # The freshness reference, captured once per rebuild. See the column comment
    # in the schema for why this is pred_stats and not total_rows.
    pred_rows: Dict = {}
    try:
        for r in await conn.fetch(
                f"SELECT predicate_uuid, row_count FROM {space_id}_rdf_pred_stats"):
            pred_rows[r["predicate_uuid"]] = r["row_count"]
    except Exception as exc:
        logger.debug("resync_value_stats(%s): no pred_stats, freshness "
                     "reference will be NULL: %s", space_id, exc)

    written = 0
    counts = {NUM: 0, DT: 0}

    for lane, col in ((NUM, "num_val"), (DT, "dt_val")):
        # Which predicates carry values in this lane, and how many. Done first
        # so a predicate with three numeric rows does not get 32 buckets.
        preds = await conn.fetch(f"""
            SELECT q.predicate_uuid, count(*) AS n
            FROM {quad} q
            JOIN {term} t ON t.term_uuid = q.object_uuid
            WHERE t.{col} IS NOT NULL
            GROUP BY 1
            HAVING count(*) >= $1
        """, buckets)

        for row in preds:
            pred, total = row["predicate_uuid"], row["n"]
            nb = min(buckets, max(2, total // 2))

            src = f"""
                SELECT t.{col} AS v
                FROM {quad} q
                JOIN {term} t ON t.term_uuid = q.object_uuid
                WHERE q.predicate_uuid = $1 AND t.{col} IS NOT NULL
            """
            if total > SAMPLE_THRESHOLD:
                # ORDER BY random() would sort the whole set, which is the cost
                # being avoided. A modulo on the uuid text is deterministic,
                # index-free and uncorrelated with the value.
                frac = max(1, total // SAMPLE_ROWS)
                src += f" AND ('x' || substr(q.object_uuid::text, 1, 8))::bit(32)::bigint % {frac} = 0"

            # nb+1 boundaries: the nb quantile starts AND the maximum. Without
            # the top boundary the last bucket is open-ended and a value inside
            # it cannot be interpolated — `score >= 90` estimated 1 row against
            # 1,547, because nothing was above the highest stored boundary and
            # the tail collapsed to a single bucket.
            fracs = [i / nb for i in range(nb)] + [1.0]
            bounds = await conn.fetchval(
                f"SELECT percentile_disc($2::float8[]) WITHIN GROUP (ORDER BY v) "
                f"FROM ({src}) s", pred, fracs)
            if not bounds:
                continue

            pr = pred_rows.get(pred)
            rows = [(pred, lane, i, b, total, pr) for i, b in enumerate(bounds)]
            if lane == NUM:
                await conn.executemany(
                    f"INSERT INTO {vstats} (predicate_uuid, lane, bucket, "
                    f"lower_num, total_rows, pred_rows) VALUES ($1,$2,$3,$4,$5,$6) "
                    f"ON CONFLICT DO NOTHING", rows)
            else:
                await conn.executemany(
                    f"INSERT INTO {vstats} (predicate_uuid, lane, bucket, "
                    f"lower_dt, total_rows, pred_rows) VALUES ($1,$2,$3,$4,$5,$6) "
                    f"ON CONFLICT DO NOTHING", rows)
            written += len(rows)
            counts[lane] += 1

    logger.info("resync_value_stats(%s): %d numeric, %d temporal predicates, "
                "%d rows", space_id, counts[NUM], counts[DT], written)
    return {"num_predicates": counts[NUM], "dt_predicates": counts[DT],
            "rows": written}


async def load_value_stats(conn, space_id: str) -> Dict[Tuple[str, str], dict]:
    """Read the histograms into memory, keyed by (predicate_uuid, lane).

    Shaped for the generator: one dict, loaded once, read many times while
    planning. Missing table is not an error — a space whose auxiliary tables
    predate this returns nothing and every caller falls back to no estimate,
    which is the behaviour before this existed.
    """
    try:
        rows = await conn.fetch(
            f"SELECT predicate_uuid::text AS p, lane, bucket, lower_num, "
            f"lower_dt, total_rows, pred_rows FROM {space_id}_rdf_value_stats "
            f"ORDER BY predicate_uuid, lane, bucket")
    except Exception as exc:
        logger.debug("value stats unavailable for %s: %s", space_id, exc)
        return {}

    out: Dict[Tuple[str, str], dict] = {}
    for r in rows:
        key = (r["p"], r["lane"])
        entry = out.setdefault(key, {
            "bounds": [], "total": r["total_rows"],
            "pred_rows": r["pred_rows"],
            # Set by `apply_freshness`. Until it runs these are the inert
            # defaults — scale 1.0 and not stale — so an estimator that never
            # calls it behaves exactly as before.
            "scale": 1.0, "stale": False,
        })
        entry["bounds"].append(r["lower_num"] if r["lane"] == NUM else r["lower_dt"])
    return out


# Below this the row count has not moved enough for a shape probe to be worth a
# query. Pure book-keeping: at 1.00x nothing changed, and a distribution cannot
# move without writing rows.
DRIFT_EPSILON = 0.02

# How far the live data may split away from the stored median before the
# boundaries are declared wrong. Measured (`bench_histogram_drift_curve.py`):
# pure GROWTH moves this by 0.008 at every drift ratio out to 3.00x, while a
# SHIFT moves it 0.051 at 1.10x drift and 0.336 at 3.00x. Anything in 0.02-0.04
# separates them; 0.03 sits in the middle with 3.75x margin below and 1.7x above
# at the smallest drift tested.
SHAPE_TOLERANCE = 0.03

# (space_id, predicate, lane) -> (drift ratio when probed, was_stale)
#
# The probe is two `count(*)`s over a predicate's quads joined to term, which is
# a SCAN, not a lookup — and drift persists until something rebuilds the
# histogram, so an uncached probe would repeat that scan on EVERY query for as
# long as the space is drifted. The guard is supposed to make staleness safe,
# not make it expensive.
#
# Caching it per drift LEVEL rather than per query is sound because a verdict
# can only go wrong as fast as new rows can move the distribution. Re-probing
# once the ratio has moved by more than DRIFT_EPSILON bounds the lag to 2% of
# rows, and the measured shift arm moves the median split by 0.051 for a 10%
# addition — so ~0.010 for 2%, comfortably inside the 0.03 tolerance. The
# verdict cannot silently go stale within its own band.
_probe_cache: Dict[Tuple[str, str, str], Tuple[float, bool]] = {}


def invalidate_freshness_cache(space_id: Optional[str] = None) -> None:
    """Drop cached probe verdicts. Call after a rebuild changes the reference."""
    if space_id is None:
        _probe_cache.clear()
        return
    for key in [k for k in _probe_cache if k[0] == space_id]:
        _probe_cache.pop(key, None)


async def apply_freshness(conn, space_id: str,
                          stats: Dict[Tuple[str, str], dict]) -> Dict[str, int]:
    """Mark each histogram with a scale factor and a staleness verdict.

    Mutates `stats` in place and returns a small summary for logging.

    WHY THERE ARE TWO SIGNALS AND NOT ONE
    -------------------------------------
    `estimate_range` computes a FRACTION from the bucket boundaries and
    multiplies it by the stored row count, so a histogram goes stale in two
    unrelated ways:

      * **Growth** — more rows, same distribution. The boundaries are still
        right, so the fraction is still right, and only the multiplier is
        behind. Multiplying by (live / stored) recovers the estimate almost
        exactly: measured, raw error climbs to 72% at 3.00x drift while the
        scaled error stays FLAT at ~16.5%, which is the histogram's own
        resolution and matches its FRESH baseline.
      * **Shift** — rows arrive in a new part of the range. The boundaries are
        wrong and no scaling helps: 92.4% raw and still 84.8% scaled at 2.00x.

    The ROW COUNT CANNOT TELL THESE APART, and an earlier version of the plan
    believed it could. At 1.10x drift a shifted histogram is already 58.9% wrong
    while a merely grown one is 16.6% — the same ratio, opposite verdicts. So a
    threshold on the ratio is not a guard; it is only a cheap way to notice that
    SOMETHING happened.

    What does tell them apart is one indexed count: does the live data still
    split at the stored MEDIAN boundary? Half the rows were below it at build
    time by construction. Growth leaves that fraction alone; a shift moves it,
    monotonically and in step with the error.

    So: the ratio is the PRE-FILTER (free, skips the query when nothing has
    changed), the probe is the GUARD, and the ratio doubles as the scale factor
    for the growth it does describe.
    """
    # `no_reference` is reported, not swallowed. A histogram with no `pred_rows`
    # gets neither scaling nor a staleness verdict — it silently reverts to the
    # behaviour this exists to replace, and "the guard is not running" reads
    # exactly like "the guard found nothing wrong".
    #
    # It is not hypothetical: both loaded fixtures had `rdf_pred_stats` holding
    # 21 of 24 predicates after a bulk load, so three predicates with 10,000
    # rows each had no reference at all. A `resync_stats_tables` restores it.
    summary = {"checked": 0, "scaled": 0, "stale": 0, "probes": 0,
               "cached": 0, "no_reference": 0}
    if not stats:
        return summary

    try:
        live = {str(r["predicate_uuid"]): r["row_count"] for r in await conn.fetch(
            f"SELECT predicate_uuid, row_count FROM {space_id}_rdf_pred_stats")}
    except Exception as exc:
        logger.debug("apply_freshness(%s): no pred_stats, leaving histograms "
                     "unscaled: %s", space_id, exc)
        return summary

    for (pred, lane), entry in stats.items():
        stored = entry.get("pred_rows")
        summary["checked"] += 1
        if not stored:
            summary["no_reference"] += 1
            continue                      # built before this existed: unknown
        now = live.get(pred)
        if not now:
            summary["no_reference"] += 1
            continue                      # predicate absent from pred_stats
        ratio = now / stored
        if abs(ratio - 1.0) <= DRIFT_EPSILON:
            continue                      # nothing has changed; no probe needed

        # The count moved. Scale for it, then ask whether the SHAPE moved too.
        entry["scale"] = ratio
        summary["scaled"] += 1

        bounds = [b for b in entry["bounds"] if b is not None]
        if len(bounds) < 3:
            continue

        # A verdict taken at a nearby drift level still holds — see the note on
        # `_probe_cache`. This is what keeps a drifted space from paying two
        # count(*) scans per predicate on every query it serves.
        ck = (space_id, pred, lane)
        cached = _probe_cache.get(ck)
        if cached is not None and abs(ratio - cached[0]) <= DRIFT_EPSILON:
            summary["cached"] += 1
            if cached[1]:
                entry["stale"] = True
                summary["stale"] += 1
            continue

        mid = bounds[len(bounds) // 2]
        col = "num_val" if lane == NUM else "dt_val"
        try:
            below = await conn.fetchval(f"""
                SELECT count(*) FROM {space_id}_rdf_quad q
                JOIN {space_id}_term t ON t.term_uuid = q.object_uuid
                WHERE q.predicate_uuid = $1::uuid AND t.{col} IS NOT NULL
                  AND t.{col} < $2""", pred, mid)
            total_live = await conn.fetchval(f"""
                SELECT count(*) FROM {space_id}_rdf_quad q
                JOIN {space_id}_term t ON t.term_uuid = q.object_uuid
                WHERE q.predicate_uuid = $1::uuid AND t.{col} IS NOT NULL""",
                pred)
        except Exception as exc:
            logger.debug("apply_freshness(%s): probe failed for %s/%s: %s",
                         space_id, pred, lane, exc)
            continue
        summary["probes"] += 1
        if not total_live:
            continue
        expected = (len(bounds) // 2) / (len(bounds) - 1)
        moved = abs(below / total_live - expected)
        _probe_cache[ck] = (ratio, moved > SHAPE_TOLERANCE)
        if moved > SHAPE_TOLERANCE:
            # The boundaries no longer describe the data. Scaling cannot fix
            # that, so the estimate is withdrawn rather than corrected — the
            # caller's fallback is a bounded COUNT, which is exact.
            entry["stale"] = True
            summary["stale"] += 1
            logger.info("value stats for %s/%s are STALE: the median split "
                        "moved %.3f (tolerance %.3f), drift %.2fx",
                        pred[:8], lane, moved, SHAPE_TOLERANCE, ratio)

    if summary["scaled"] or summary["stale"]:
        logger.info("apply_freshness(%s): %s", space_id, summary)
    if summary["no_reference"]:
        logger.warning(
            "apply_freshness(%s): %d of %d histogram(s) have no freshness "
            "reference, so they are neither scaled nor guarded — run "
            "resync_stats_tables then resync_value_stats",
            space_id, summary["no_reference"], summary["checked"])
    return summary


def estimate_range(stats: Dict[Tuple[str, str], dict], predicate_uuid: str,
                   lane: str, op: str, value) -> Optional[int]:
    """Estimated number of quads with this predicate whose value satisfies op.

    Returns None when there is nothing to go on. **None means "unknown", never
    "zero"** — a caller treating a missing estimate as small would reproduce the
    defect this exists to fix, where a criterion believed tiny is applied after
    the traversal has already expanded.

    Boundaries are `nb + 1` quantiles spanning min..max, so bucket i covers
    [b[i], b[i+1]) and holds 1/nb of the rows. A value inside a bucket is
    interpolated linearly across it; counting whole buckets instead put
    `score >= 90` at 1 row where the answer was 1,547, since the entire tail sat
    inside the final bucket.

    `op` is one of >=, >, <=, <, =.
    """
    entry = stats.get((predicate_uuid, lane))
    if not entry or len(entry["bounds"]) < 2 or value is None:
        return None

    # `apply_freshness` found the boundaries no longer describe the data. No
    # scaling repairs that — measured at 84.8% error even after scaling — so the
    # estimate is withdrawn. None is "unknown", and the caller's fallback is an
    # exact bounded count.
    if entry.get("stale"):
        return None

    bounds = [b for b in entry["bounds"] if b is not None]
    if len(bounds) < 2:
        return None
    total = entry["total"]
    nb = len(bounds) - 1                      # buckets, not boundaries

    def _span(lo, hi):
        """hi - lo as a float, for numbers and for timestamps alike."""
        try:
            d = hi - lo
        except TypeError:
            return None
        return d.total_seconds() if hasattr(d, "total_seconds") else float(d)

    # A threshold AT or BEYOND an extreme boundary selects the mass sitting at
    # that extreme, and the histogram does not record it. Quantile boundaries
    # say where the data is divided, not how many rows share the end value.
    #
    # Reporting a number here was badly wrong on DISCRETE data. `hasScore` on
    # graph_synth_100k runs 0..99 with 6,032 rows at exactly 99; `>= 99` fell
    # into `frac_below = 1.0`, produced `max(1, 0)`, and estimated ONE row for
    # six thousand — a 6,000x underestimate, in the direction that makes a
    # criterion look perfectly selective and get applied last. Continuous data
    # hides this, because ties at the maximum are negligible there.
    #
    # None sends the caller to the counted form, which is exact. That is the
    # right trade precisely here: a tail predicate matches few rows, so the
    # count is cheap and nowhere near `_PAIR_COUNT_CAP`.
    #
    # Inside the try because the comparison itself can fail: a datetime value
    # against numeric bounds raises TypeError, and that has to stay "unknown"
    # rather than propagating out of an estimator.
    try:
        if op in (">=", ">") and value >= bounds[-1]:
            return None
        if op in ("<=", "<") and value <= bounds[0]:
            return None
    except TypeError:
        return None

    try:
        if value <= bounds[0]:
            frac_below = 0.0
        elif value >= bounds[-1]:
            frac_below = 1.0
        else:
            i = 0
            while i < nb and value >= bounds[i + 1]:
                i += 1
            width = _span(bounds[i], bounds[i + 1])
            inside = _span(bounds[i], value)
            if width is None or inside is None:
                return None
            # Each bucket holds 1/nb of the rows; position within it is linear.
            within = (inside / width) if width else 0.0
            frac_below = (i + within) / nb
    except TypeError:
        return None                            # value not comparable to bounds

    if op in (">=", ">"):
        frac = 1.0 - frac_below
    elif op in ("<=", "<"):
        frac = frac_below
    elif op == "=":
        frac = 1.0 / nb
    else:
        return None

    # Scale for rows written since the build. `total` is the count the histogram
    # was built from; `scale` is how much the predicate has grown since, and
    # under growth the fraction above is still correct, so the product is the
    # live answer. 1.0 when nothing has changed or when freshness was never
    # applied.
    #
    # Measured: at 2.00x drift `>= 10` is 107,861 actual against 53,750
    # unscaled and 107,500 scaled.
    total = total * entry.get("scale", 1.0)

    # Never report zero. The boundaries are quantiles, so beyond the last one
    # there are still rows, and a zero estimate is exactly what makes a filter
    # get applied last.
    return max(1, int(round(frac * total)))

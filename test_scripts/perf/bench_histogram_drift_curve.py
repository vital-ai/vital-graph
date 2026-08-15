"""How wrong does a stale histogram get, and is the drift CORRECTABLE?

`stats_table_freshness_plan.md` decided the mechanism (drift-triggered rebuild
plus a read-time guard) and left one thing explicitly open: the threshold.
"2.00x drift gave 92% error and 1.00x gave 14%; the curve between them is
unmeasured. Measuring it is a smaller experiment than the one above and should
precede picking a number."

This measures that curve — and separates a variable the original experiment
conflated, which turns out to change the design.

TWO KINDS OF DRIFT, AND ONLY ONE OF THEM IS A SHAPE PROBLEM

`estimate_range` computes a FRACTION from the bucket boundaries and multiplies
it by the stored `total_rows`:

    return max(1, int(round(frac * total)))

So the two ways a histogram goes stale are not alike:

  * **GROWTH** — more rows, same distribution. The boundaries stay correct, so
    `frac` stays correct; only `total` is behind. The estimate is wrong by
    exactly the row-count ratio, which means multiplying by (live / stored)
    should recover it EXACTLY. Declining here would throw away a good estimate.
  * **SHIFT** — rows arrive in a new part of the range. The boundaries are now
    wrong, `frac` is wrong, and no amount of scaling fixes it.

The plan's experiment added 60,000 rows at 90..99 to a uniform 0..99 space: that
is both at once, and it reported 92.4%. It could not say how much of that a free
correction would have removed.

The row count cannot tell GROWTH from SHIFT — that is the objection recorded and
answered in the plan. But if scaling is never worse and sometimes exact, it is
worth applying BEFORE the threshold is consulted, and the threshold then only
has to protect against shape change. That is a different (and higher) number
than one which also has to protect against growth.

    VG_TEST_PG_PORT=5433 python test_scripts/perf/bench_histogram_drift_curve.py
"""

import asyncio
import os
import random
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

import asyncpg  # noqa: E402

from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema  # noqa: E402
from vitalgraph.db.sparql_sql.sync_value_stats import (  # noqa: E402
    estimate_range, load_value_stats, resync_value_stats)

SPACE = "sp_hist_drift"
GRAPH = "urn:hist_drift"
SCORE = "http://vital.ai/ontology/haley-ai-kg#hasScore"
XSD_INT = "http://www.w3.org/2001/XMLSchema#integer"
_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

BASE_ROWS = 60_000
# Drift ratios to sample between fresh and the plan's 2.00x, plus beyond it.
RATIOS = [1.10, 1.25, 1.50, 1.75, 2.00, 2.50, 3.00]
THRESHOLDS = [10, 25, 50, 75, 90, 95]


def _u(text, ttype="U", dtype=None):
    key = f"{text}\x00{ttype}" + (f"\x00{dtype}" if dtype else "")
    return uuid.uuid5(_NS, key)


async def _ensure_space(conn):
    await conn.execute(
        "INSERT INTO space (space_id, space_name, space_description, update_time) "
        "VALUES ($1,$1,'histogram drift curve experiment',CURRENT_TIMESTAMP) "
        "ON CONFLICT (space_id) DO NOTHING", SPACE)
    try:
        await SparqlSQLSchema.drop_space(conn, SPACE)
    except Exception:
        pass
    await SparqlSQLSchema.create_space(conn, SPACE)


async def _insert(conn, scores, start_index):
    """Write `scores` as hasScore quads, and the terms they need."""
    t_term = f"{SPACE}_term"
    t_quad = f"{SPACE}_rdf_quad"
    pred_u, ctx_u = _u(SCORE), _u(GRAPH)
    dt_id = await conn.fetchval(
        f"SELECT datatype_id FROM {SPACE}_datatype WHERE datatype_uri = $1",
        XSD_INT)

    terms, quads, seen = [], [], set()
    for i, s in enumerate(scores):
        subj = f"urn:hd:s:{start_index + i}"
        su = _u(subj)
        if su not in seen:
            terms.append((su, subj, "U", None, None))
            seen.add(su)
        vu = _u(str(s), "L", XSD_INT)
        if vu not in seen:
            terms.append((vu, str(s), "L", dt_id, None))
            seen.add(vu)
        quads.append((su, pred_u, vu, ctx_u))

    for u_, txt, tt, dtid, lang in ((pred_u, SCORE, "U", None, None),
                                    (ctx_u, GRAPH, "U", None, None)):
        terms.append((u_, txt, tt, dtid, lang))

    await conn.executemany(
        f"INSERT INTO {t_term} (term_uuid, term_text, term_type, datatype_id, lang) "
        f"VALUES ($1,$2,$3,$4,$5) ON CONFLICT (term_uuid) DO NOTHING", terms)
    await conn.executemany(
        f"INSERT INTO {t_quad} (subject_uuid, predicate_uuid, object_uuid, "
        f"context_uuid) VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING", quads)


async def _actual(conn, threshold):
    return await conn.fetchval(f"""
        SELECT count(*) FROM {SPACE}_rdf_quad q
        JOIN {SPACE}_term t ON t.term_uuid = q.object_uuid
        WHERE q.predicate_uuid = $1 AND t.num_val >= $2""",
        _u(SCORE), threshold)


async def _errors(conn, stats, live_total, stored_total):
    """Worst |error| over the thresholds, raw and scaled by live/stored."""
    pu = str(_u(SCORE))
    worst_raw = worst_scaled = 0.0
    detail = []
    scale = (live_total / stored_total) if stored_total else 1.0
    for th in THRESHOLDS:
        act = await _actual(conn, th)
        est = estimate_range(stats, pu, "num", ">=", th)
        if est is None or act == 0:
            continue
        raw = abs(est - act) / act
        sc = abs(est * scale - act) / act
        worst_raw, worst_scaled = max(worst_raw, raw), max(worst_scaled, sc)
        detail.append((th, act, est, round(est * scale)))
    return worst_raw, worst_scaled, detail


async def _median_probe(conn, stats, live_total):
    """One indexed COUNT: does the live data still split at the stored median?

    The row-count ratio cannot tell GROWTH from SHIFT — both just add rows. This
    can, and costs one count per predicate. The histogram's middle boundary is
    by construction the value half the rows sit below; if the live fraction
    below it is still ~0.5 the shape has held, and if it has moved the
    boundaries are wrong no matter what the row count says.

    Returns (stored_frac, live_frac). Stored is 0.5 by construction; it is
    returned rather than assumed so a change in how boundaries are built shows
    up here instead of being silently baked in.
    """
    entry = stats[(str(_u(SCORE)), "num")]
    bounds = [b for b in entry["bounds"] if b is not None]
    mid = bounds[len(bounds) // 2]
    below = await conn.fetchval(f"""
        SELECT count(*) FROM {SPACE}_rdf_quad q
        JOIN {SPACE}_term t ON t.term_uuid = q.object_uuid
        WHERE q.predicate_uuid = $1 AND t.num_val < $2""", _u(SCORE), mid)
    stored_frac = (len(bounds) // 2) / (len(bounds) - 1)
    return stored_frac, (below / live_total if live_total else 0.0)


async def run_arm(conn, label, shift: bool):
    rng = random.Random(12345)
    await _ensure_space(conn)
    base = [rng.randrange(0, 100) for _ in range(BASE_ROWS)]
    await _insert(conn, base, 0)
    await conn.execute(f"ANALYZE {SPACE}_rdf_quad")
    await resync_value_stats(conn, SPACE)
    stats = await load_value_stats(conn, SPACE)
    stored_total = stats[(str(_u(SCORE)), "num")]["total"]

    print(f"\n=== {label}  (stored total_rows = {stored_total:,})")
    print(f"{'drift':>7s} {'live rows':>10s} {'worst err raw':>14s} "
          f"{'worst err scaled':>17s} {'median probe':>14s} {'shape move':>11s}")
    added = 0
    for ratio in RATIOS:
        want = int(BASE_ROWS * ratio) - BASE_ROWS - added
        if want <= 0:
            continue
        new = ([rng.randrange(90, 100) for _ in range(want)] if shift
               else [rng.randrange(0, 100) for _ in range(want)])
        await _insert(conn, new, BASE_ROWS + added)
        added += want
        await conn.execute(f"ANALYZE {SPACE}_rdf_quad")
        live = await conn.fetchval(
            f"SELECT count(*) FROM {SPACE}_rdf_quad WHERE predicate_uuid = $1",
            _u(SCORE))
        raw, scaled, detail = await _errors(conn, stats, live, stored_total)
        s_frac, l_frac = await _median_probe(conn, stats, live)
        print(f"{live / stored_total:6.2f}x {live:10,} {raw:13.1%} "
              f"{scaled:16.1%} {l_frac:13.3f} {abs(l_frac - s_frac):10.3f}")
        if abs(ratio - 2.00) < 1e-9:
            for th, act, est, sc in detail:
                print(f"          >= {th:3d}: actual {act:7,}  "
                      f"raw {est:7,}  scaled {sc:7,}")


async def main():
    conn = await asyncpg.connect(
        host=os.environ.get("VG_TEST_PG_HOST", "localhost"),
        port=int(os.environ.get("VG_TEST_PG_PORT", "5433")),
        database=os.environ.get("VG_TEST_PG_DATABASE", "sparql_sql_graph"),
        user=os.environ.get("VG_TEST_PG_USER", "postgres"),
        password=os.environ.get("VG_TEST_PG_PASSWORD", "testpass"))
    await conn.execute("SET statement_timeout = '600s'")
    try:
        await run_arm(conn, "GROWTH — same distribution, more rows", shift=False)
        await run_arm(conn, "SHIFT — new rows land in 90..99", shift=True)
    finally:
        try:
            await SparqlSQLSchema.drop_space(conn, SPACE)
            await conn.execute("DELETE FROM space WHERE space_id = $1", SPACE)
        except Exception as exc:
            print("cleanup failed:", exc)
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

"""Can an `rdf:type` constraint on an edge be answered by `edge.edge_type_uuid`?

`{space}_edge.edge_type_uuid` is populated from **vitaltype** (`sync_edge_table`),
so it answers a `vitaltype` constraint by definition and an `rdf:type` one only
when the two agree for every edge in the space. They often do; they do not
always. `sync_edge_table` documents the counterexample itself — `wordnet_exp`
has 1,536,485 `type` quads and zero `vitaltype`, so every edge row there would
read NULL.

WHY THIS IS WORTH ASKING. `issues/182` bisected the reference CONSTRUCT by type
constraint class:

    all type patterns      6,185,137 buffers
    minus ENTITY types     6,182,837      (~0)
    minus FRAME type       4,051,066      (1.5x)
    minus EDGE types         914,457      (6.8x)   <- this one
    minus SLOT types       6,185,133      (0, already dropped)

The edge type constraint is essentially the whole of the type cost. Absorbing it
into a column that already exists and is already populated turns a per-row quad
join into a column predicate — the trade `issues/060` made when it added the
column, and then never used for this.

WHY IT IS A QUERY AND NOT AN ARGUMENT. The same reason `slot_type_tautology`
gives: "vitaltype is single-valued by design" is a statement about the model,
not about a given store. Absorbing when the two DISAGREE is a wrong answer in
both directions — an edge with `rdf:type T` but a different vitaltype would be
dropped, and one with `vitaltype T` but no `rdf:type T` would be added.

None means DO NOT ABSORB. Every failure path returns it.
"""

from __future__ import annotations

import logging
import os as _os
import time as _time
from typing import Optional

from .db_provider import bounded_lock_wait

logger = logging.getLogger(__name__)

# (space_id, type_predicate) -> (edge_rows_when_computed, agrees)
_CACHE: dict = {}

RDF_TYPE_URI = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
VITALTYPE_URI = "http://vital.ai/ontology/vital-core#vitaltype"

# An optimisation INPUT, and no such input is worth seconds of a user's query.
#
# 250 ms, not the 2,000 ms this used to carry. Measured on `wordnet_frames`,
# the frame check costs **2,128 ms** — it EXCEEDS the old budget, so it timed
# out and returned None every time, and the caller then kept the join anyway.
# The 2,000 ms was therefore pure latency spent on an answer never obtained:
# half of a 4.0 s generation for a query that executes in 39 ms.
#
# Resolving the predicate to a uuid first (below) did not rescue it — the scan
# is genuinely expensive, not merely opaque to the planner.
#
# Lowering the budget keeps the same OUTCOME at an eighth of the cost. A
# sampled scan cannot replace it: a sample can DISPROVE agreement but never
# prove it, and absorbing on a false "agrees" is a wrong answer, not a slow one.
#
# The durable fix is to stop asking this on the query path at all. Whether
# `rdf:type` agrees with `vitaltype` is a per-SPACE data property that changes
# only on write, so it belongs in the maintenance job, written to a stats
# table and read for free. Until then, bounded and usually None.
AGREEMENT_TIMEOUT_MS = 250

# How long the row count backing `_CACHE`'s key may be reused without re-reading
# it. See the note in `frame_type_absorbable`: the count is a full scan and runs
# per query, where the verdict it guards is a schema-level property that changes
# only when the frames in a space stop agreeing about their own type.
COUNT_MEMO_TTL_S = 30.0
_COUNT_MEMO: dict = {}

# How long a verdict of UNKNOWN is believed, ignoring the row count entirely.
#
# The cache above keys a verdict on the table's row count so a changed table
# re-derives it. For an unknown verdict that is exactly wrong. Measured on
# production 2026-09-22: the frame check needs **122,488 ms** — it scans
# 3,007,724 mirror rows against 7,143,296 type quads, 10.2 MILLION buffers —
# against a 250 ms budget. It can never succeed here. But the row count of a
# space taking writes changes constantly, so every change re-derived the same
# unknown: `plan_decisions` on production carried `"type": null` on every single
# generation, each having paid the full 250 ms budget to learn nothing, plus
# ~236 ms for the count that invalidated it. Together that was the largest
# single cost in SQL generation — a 512 ms median on EVERY query, 101 s of
# wall-clock in a 42-minute window — spent re-answering "I don't know".
#
# A check that cannot finish in 250 ms will not finish in 250 ms because three
# rows were inserted. Believing the unknown is also SAFE IN ONE DIRECTION ONLY,
# which is the safe one: unknown means DO NOT ABSORB, so a stale unknown costs
# an optimisation and can never produce a wrong row. A stale TRUE could, and
# that is still keyed on the count.
#
# This does not make the verdict obtainable — the answer on production is
# actually "they agree", worth 6.8x on the edge constraint, and nothing here can
# prove it in time. The durable fix is still to compute it in the maintenance
# job and read it from a stats table, as the note above says. This only stops
# the query path from buying the same failure over and over.
UNKNOWN_TTL_S = 900.0
_UNKNOWN: dict = {}

#: How long "this space has no usable stored verdict" is believed without
#: re-asking. Seconds, so a verdict written by an explicit refresh starts being
#: used promptly, but a busy space stops paying a round trip per query to be
#: told the same thing. See `_stored_verdict`.
NO_VERDICT_TTL_S = float(_os.getenv("VG_TYPE_AGREEMENT_MISS_TTL_S", "30"))
_NO_VERDICT: dict = {}


def clear_cache() -> None:
    _CACHE.clear()
    _COUNT_MEMO.clear()
    _UNKNOWN.clear()
    _NO_VERDICT.clear()


#: Returned by `_stored_verdict` when the space has no `type_agreement` table,
#: i.e. the migration has not run. Distinct from None, which is a real verdict
#: of "unknown" from a table that does exist.
NOT_MIGRATED = object()

#: (kind, source table suffix, the column the type is read from).
_SOURCES = {"frame": ("frame_slot", "frame_type_uuid"),
            "edge": ("edge", "edge_type_uuid")}


async def change_token(conn, table: str) -> Optional[str]:
    """A cheap reading of "has this table changed since", or None.

    Tuple churn plus `relfilenode`, both from the catalog and the statistics
    collector, so it costs a catalog read rather than the `count(*)` over
    millions of rows this replaces. It does not need to be a hash of the data:
    it only has to CHANGE when the table does. A statistics reset moves it, and
    so does a TRUNCATE (new relfilenode); both then read as "unknown", which is
    the conservative answer rather than a wrong one.
    """
    try:
        row = await conn.fetchrow(
            "SELECT s.n_tup_ins + s.n_tup_upd + s.n_tup_del AS churn, "
            "       c.relfilenode "
            "FROM pg_stat_all_tables s JOIN pg_class c ON c.oid = s.relid "
            "WHERE s.relid = to_regclass($1)", table)
    except Exception as exc:
        logger.debug("type agreement: change token failed for %s: %s", table, exc)
        return None
    if row is None or row["relfilenode"] is None:
        return None
    return f"{row['churn']}:{row['relfilenode']}"


async def _stored_verdict(conn, space_id: str, kind: str, predicate_uri: str):
    """The maintenance job's verdict, if it still describes the table.

    Returns True/False, None for unknown, or NOT_MIGRATED when there is no
    table to read — which is what keeps a deployment that has not run the
    migration on exactly its old behaviour.
    """
    import asyncpg
    suffix, _col = _SOURCES[kind]
    # NO ROUND TRIP for the common answer.
    #
    # The SQL costs 0.11 ms server-side; the 20.9 ms this showed in production
    # `timings_ms` is the round trip and the pool, not the query, so making the
    # query faster barely moves it. What moves it is not asking.
    #
    # Only the NEGATIVE is cached, and only that direction is safe: "no usable
    # verdict" means DO NOT ABSORB, so a stale negative costs an optimisation
    # for a few seconds and can never produce a wrong row. A cached POSITIVE
    # would be exactly the stale TRUE the change token exists to prevent, so a
    # positive is re-validated on every query.
    #
    # This is now the common path by design: the refresh is off the automatic
    # cycle, so most spaces have no usable verdict and this returns without
    # touching the database at all.
    ckey = (space_id, kind, predicate_uri)
    miss = _NO_VERDICT.get(ckey)
    if miss is not None and (_time.monotonic() - miss) < NO_VERDICT_TTL_S:
        return None
    # ONE round trip, and the token is compared IN the query. Read separately
    # this cost two round trips on every query, and left a window in which the
    # verdict and the token it was checked against came from different moments.
    # A row comes back only when a verdict exists AND still describes the table;
    # "no verdict", "unsure" and "the table moved" are all absence, and all mean
    # do not absorb.
    try:
        agrees = await conn.fetchval(
            # The stat functions are called on ONE oid rather than filtering
            # `pg_stat_all_tables`, which is a view that evaluates every table
            # in the database before the filter applies. Measured server-side
            # on production: 0.31 ms for the view form, 0.11 ms for this one.
            "SELECT ta.agrees FROM type_agreement ta, LATERAL ("
            "  SELECT pg_stat_get_tuples_inserted(c.oid)"
            "       + pg_stat_get_tuples_updated(c.oid)"
            "       + pg_stat_get_tuples_deleted(c.oid) AS churn,"
            "         c.relfilenode"
            "  FROM pg_class c WHERE c.oid = to_regclass($4)) t "
            "WHERE ta.space_id = $1 AND ta.kind = $2 AND ta.predicate_uri = $3 "
            "  AND ta.agrees IS NOT NULL "
            "  AND ta.change_token = t.churn || ':' || t.relfilenode",
            space_id, kind, predicate_uri, f"{space_id}_{suffix}")
    except asyncpg.UndefinedTableError:
        return NOT_MIGRATED
    except Exception as exc:
        # Reachable table, unreadable row. Unknown, not "fall back to the
        # two-minute question on the query path".
        logger.debug("type agreement: read failed for %s/%s: %s",
                     space_id, kind, exc)
        return None
    if agrees is None:
        _NO_VERDICT[ckey] = _time.monotonic()
        return None
    _NO_VERDICT.pop(ckey, None)
    return bool(agrees)


def _unknown_is_fresh(key) -> bool:
    at = _UNKNOWN.get(key)
    return at is not None and (_time.monotonic() - at) < UNKNOWN_TTL_S


def _remember_unknown(key) -> None:
    _UNKNOWN[key] = _time.monotonic()


async def frame_type_absorbable(space_id: str, type_predicate: str,
                                conn) -> Optional[bool]:
    """True when `?f <type_predicate> <T>` can be read off `frame_slot.frame_type_uuid`.

    Same question as `edge_type_absorbable`, asked of frames. The column is
    populated from `vitaltype`, so `rdf:type` is equivalent only where the two
    agree for every frame in this space.

    `issues/183` measured why this matters: `?frame a KGFrame` unabsorbed is
    **5,120,000 buffers** of the reference CONSTRUCT's 6,032,427 — the entire
    remaining gap against the table the collapse replaced. Absorbed, the same
    query measures ~908,000.
    """
    if conn is None:
        return None
    if type_predicate == VITALTYPE_URI:
        return True
    if type_predicate != RDF_TYPE_URI:
        return None

    t_fs = f"{space_id}_frame_slot"
    key = (space_id, "frame", type_predicate)

    # THE MIGRATED PATH, and the only one that can actually answer TRUE on a
    # large space. The maintenance job decides this without a budget and stores
    # it; here it costs one indexed row plus a catalog read. Once the table
    # exists it is AUTHORITATIVE — an absent row means "not looked at yet" and
    # reads as do-not-absorb, rather than falling through to a question this
    # path has already been measured unable to answer.
    stored = await _stored_verdict(conn, space_id, "frame", type_predicate)
    if stored is not NOT_MIGRATED:
        return stored

    # Before the count: the count exists only to key a verdict this cannot
    # reach, so paying for it first would be paying for the answer twice.
    if _unknown_is_fresh(key):
        return None

    # THE COUNT IS THE EXPENSIVE PART, not the verdict it guards.
    #
    # `_CACHE` keys the verdict on the table's row count, so a changed table
    # re-derives it. But the count is a full scan, and this runs on EVERY query
    # that mentions a frame type: measured on `lead_nurture_grouped`
    # (4,077,000 rows / 1,779 MB) at ~180 ms, which was 98% of SQL GENERATION
    # for an ordinary 25-entity page — 185 ms of generation against 68 ms of
    # execution. The cache was saving a 250 ms verdict by paying 180 ms to ask
    # whether it was still valid.
    #
    # So the count itself is memoised for a short window. This does NOT weaken
    # the guard as much as it appears: the existing cache already reuses a
    # verdict whenever the row count is unchanged, so a change that PRESERVES
    # the count already yields a stale verdict. The window only adds staleness
    # for a change that alters it.
    #
    # Short, and deliberately so. The dangerous direction is a table that became
    # EMPTY being answered from a cached TRUE — the vacuous agreement that
    # returned zero rows on eight tests in `issues/182`. A truncate followed by a
    # query inside the window would do that, so the window is seconds rather than
    # minutes, and a resync is far slower than it either way.
    now = _time.monotonic()
    memo = _COUNT_MEMO.get(key)
    if memo is not None and (now - memo[0]) < COUNT_MEMO_TTL_S:
        rows = memo[1]
    else:
        try:
            async with bounded_lock_wait(conn):
                rows = await conn.fetchval(f"SELECT count(*) FROM {t_fs}")
        except Exception as exc:
            logger.debug("frame-type agreement: count failed: %s", exc)
            return None
        _COUNT_MEMO[key] = (now, rows)

    if not rows:
        # VACUOUS, not agreement. An empty table produces no counterexample, so
        # the check would answer "they agree" and the rewrite would fire against
        # nothing. That is how `edge_type_absorbable` came to return zero rows
        # on 8 integration tests (`issues/182`).
        logger.debug("frame-type agreement: %s is empty — declining rather "
                     "than answering vacuously", t_fs)
        return None

    cached = _CACHE.get(key)
    if cached is not None and cached[0] == rows:
        return cached[1]

    # The predicate is resolved to a uuid FIRST, not joined by `term_text`
    # inside the query. A subquery the planner cannot fold hides the
    # selectivity of `(predicate_uuid, object_uuid)` — it cannot use statistics
    # for a value it does not know — so the check costs more than its own
    # budget, times out, and returns None. `slot_type_tautology` had exactly
    # this defect: 1,805 ms against a 2,000 ms budget, and the verdict then
    # flipped run to run. Measured here at 2,140.8 ms against the same 2,000 ms
    # budget, so `rdf:type` was ALWAYS returning None and the frame type
    # constraint was never absorbed (`issues/178`).
    try:
        pred_uuid = await conn.fetchval(
            f"SELECT term_uuid FROM {space_id}_term WHERE term_text = $1",
            type_predicate)
    except Exception as exc:
        logger.debug("frame-type agreement: predicate lookup failed: %s", exc)
        return None
    if pred_uuid is None:
        # The predicate is absent from this space, so nothing carries it and
        # no frame can disagree. That is a REAL agreement, not a vacuous one.
        _CACHE[key] = (rows, True)
        return True

    sql = f"""
        SELECT 1 FROM (SELECT DISTINCT frame_uuid, context_uuid, frame_type_uuid
                       FROM {t_fs}) f
        LEFT JOIN {space_id}_rdf_quad rt
               ON rt.subject_uuid = f.frame_uuid
              AND rt.context_uuid = f.context_uuid
              AND rt.predicate_uuid = $1
        WHERE rt.object_uuid IS DISTINCT FROM f.frame_type_uuid
        LIMIT 1"""

    prev = await conn.fetchval("SHOW statement_timeout")
    await conn.execute(f"SET statement_timeout = '{int(AGREEMENT_TIMEOUT_MS)}ms'")
    try:
        async with conn.transaction():
            row = await conn.fetchval(sql, pred_uuid)
        agrees = row is None
    except Exception as exc:
        logger.debug("frame-type agreement: gave up (%s)", type(exc).__name__)
        # `_UNKNOWN` is the SOLE owner of an unknown verdict. Writing it into
        # `_CACHE` too would pin it to this row count, and the count-keyed
        # entry would keep answering None after the TTL expired — so the retry
        # would depend on the table changing rather than on time passing.
        _remember_unknown(key)
        return None
    finally:
        try:
            await conn.execute(f"SET statement_timeout = '{prev}'")
        except Exception:  # pragma: no cover - abort path
            logger.debug("could not restore statement_timeout to %s", prev)

    _CACHE[key] = (rows, agrees)
    logger.info("frame-type agreement: %s rdf:type vs frame_type_uuid -> %s",
                space_id, "ABSORBABLE" if agrees else "differs, keeping the join")
    return agrees


async def edge_type_absorbable(space_id: str, type_predicate: str,
                               conn) -> Optional[bool]:
    """True when `?e <type_predicate> <T>` can be read off `edge_type_uuid`.

    `vitaltype` is True without asking — that is what the column holds.
    `rdf:type` is answered against the data, per space, and cached.
    """
    if conn is None:
        return None
    if type_predicate == VITALTYPE_URI:
        return True
    if type_predicate != RDF_TYPE_URI:
        return None

    t_edge = f"{space_id}_edge"
    stored = await _stored_verdict(conn, space_id, "edge", type_predicate)
    if stored is not NOT_MIGRATED:
        return stored
    if _unknown_is_fresh((space_id, type_predicate)):
        return None
    try:
        async with bounded_lock_wait(conn):
            edge_rows = await conn.fetchval(f"SELECT count(*) FROM {t_edge}")
    except Exception as exc:
        logger.debug("edge-type agreement: edge count failed: %s", exc)
        return None

    cached = _CACHE.get((space_id, type_predicate))
    if cached is not None and cached[0] == edge_rows:
        return cached[1]

    # One counterexample is enough, so LIMIT 1 — but as in `slot_type_tautology`
    # the USEFUL verdict (they agree) is the one that has to scan everything,
    # which is why this is bounded.
    sql = f"""
        SELECT 1 FROM {t_edge} e
        LEFT JOIN {space_id}_rdf_quad rt
               ON rt.subject_uuid = e.edge_uuid
              AND rt.predicate_uuid = (SELECT term_uuid FROM {space_id}_term
                                       WHERE term_text = $1)
        WHERE rt.object_uuid IS DISTINCT FROM e.edge_type_uuid
        LIMIT 1"""

    prev = await conn.fetchval("SHOW statement_timeout")
    await conn.execute(
        f"SET statement_timeout = '{int(AGREEMENT_TIMEOUT_MS)}ms'")
    try:
        async with conn.transaction():
            row = await conn.fetchval(sql, RDF_TYPE_URI)
        agrees = row is None
    except Exception as exc:
        logger.debug("edge-type agreement: gave up (%s)", type(exc).__name__)
        _remember_unknown((space_id, type_predicate))
        return None
    finally:
        try:
            await conn.execute(f"SET statement_timeout = '{prev}'")
        except Exception:  # pragma: no cover - abort path
            logger.debug("could not restore statement_timeout to %s", prev)

    _CACHE[(space_id, type_predicate)] = (edge_rows, agrees)
    logger.info("edge-type agreement: %s rdf:type vs edge_type_uuid -> %s",
                space_id, "ABSORBABLE" if agrees else "differs, keeping the join")
    return agrees


#: The maintenance job's budget. Generous because it is not on anyone's query:
#: the frame form measured 122,488 ms on production, and a verdict obtained in
#: three minutes once an hour is worth more than one never obtained at all.
REFRESH_TIMEOUT_MS = int(_os.getenv("VG_TYPE_AGREEMENT_REFRESH_TIMEOUT_MS",
                                    "300000"))

#: The CLIENT-side bound, and it is not optional. TWO fences guard a long read
#: here and raising only one does nothing:
#:
#:   * the server's `statement_timeout`, which production's RDS parameter group
#:     pins at 1min and `SET` above overrides;
#:   * asyncpg's `command_timeout=60` on the pool, which fires in the DRIVER,
#:     independently of the server, and raises a bare `TimeoutError`.
#:
#: Shipped without the second one, this failed on production at 00:49 and 00:50
#: on 2026-09-23 — three refreshes, each dying at almost exactly 60 s with an
#: EMPTY error message, which is what `str(asyncio.TimeoutError())` is. The
#: small space (13.3 s) succeeded and the two that need ~120 s never could, so
#: the fix worked precisely where it was not needed. `sync_entity_slot_sort`
#: documents the same trap costing `issues/149` a probe that had never once run.
#:
#: Kept ABOVE the server fence so the server cancels first: a PostgreSQL
#: cancellation says what was cancelled, a driver timeout says nothing.
REFRESH_CLIENT_TIMEOUT_S = REFRESH_TIMEOUT_MS / 1000.0 + 30.0


async def refresh_type_agreement(conn, space_id: str) -> list:
    """Decide frame and edge type agreement for *space_id* and store it.

    For the MAINTENANCE JOB, not the query path. This is the durable half of
    the fix the module header asks for: the question is a per-space data
    property that changes only on write, so it is answered off to the side and
    read for free.

    THE TOKEN IS TAKEN BEFORE THE SCAN, deliberately. If the table is written
    while the scan runs, the stored token is the pre-scan one and no longer
    matches, so every reader treats the verdict as unknown until the next
    refresh re-derives it. Taking it afterwards would stamp a verdict computed
    over older data with a token that says it is current — the one direction
    that returns wrong rows.

    Returns one dict per kind for the caller to log. Never raises: a space that
    cannot be measured keeps whatever verdict it had, which ages out by token.
    """
    import asyncpg
    out = []
    for kind, (suffix, col) in _SOURCES.items():
        table = f"{space_id}_{suffix}"
        record = {"space_id": space_id, "kind": kind, "agrees": None}
        try:
            token = await change_token(conn, table)
            if token is None:
                record["skipped"] = "no such table"
                out.append(record)
                continue
            rows = await conn.fetchval(f"SELECT count(*) FROM {table}",
                                       timeout=REFRESH_CLIENT_TIMEOUT_S)
            if not rows:
                # Vacuous, not agreement: an empty table produces no
                # counterexample, so it would answer TRUE against nothing.
                record["skipped"] = "empty"
                out.append(record)
                continue
            pred_uuid = await conn.fetchval(
                f"SELECT term_uuid FROM {space_id}_term WHERE term_text = $1",
                RDF_TYPE_URI)
            started = _time.monotonic()
            if pred_uuid is None:
                # Nothing in the space carries the predicate, so nothing can
                # disagree. A real agreement, not a vacuous one.
                agrees = True
            else:
                if kind == "frame":
                    sql = f"""
                        SELECT 1 FROM (SELECT DISTINCT frame_uuid, context_uuid,
                                              {col}
                                       FROM {table}) f
                        LEFT JOIN {space_id}_rdf_quad rt
                               ON rt.subject_uuid = f.frame_uuid
                              AND rt.context_uuid = f.context_uuid
                              AND rt.predicate_uuid = $1
                        WHERE rt.object_uuid IS DISTINCT FROM f.{col}
                        LIMIT 1"""
                else:
                    sql = f"""
                        SELECT 1 FROM {table} e
                        LEFT JOIN {space_id}_rdf_quad rt
                               ON rt.subject_uuid = e.edge_uuid
                              AND rt.predicate_uuid = $1
                        WHERE rt.object_uuid IS DISTINCT FROM e.{col}
                        LIMIT 1"""
                prev = await conn.fetchval("SHOW statement_timeout")
                await conn.execute(
                    f"SET statement_timeout = '{int(REFRESH_TIMEOUT_MS)}ms'")
                try:
                    agrees = await conn.fetchval(
                        sql, pred_uuid,
                        timeout=REFRESH_CLIENT_TIMEOUT_S) is None
                finally:
                    try:
                        await conn.execute(f"SET statement_timeout = '{prev}'")
                    except Exception:  # pragma: no cover - abort path
                        pass
            ms = int((_time.monotonic() - started) * 1000)
            await conn.execute(
                "INSERT INTO type_agreement (space_id, kind, predicate_uri, "
                "  agrees, change_token, source_rows, computed_at, compute_ms) "
                "VALUES ($1,$2,$3,$4,$5,$6,NOW(),$7) "
                "ON CONFLICT (space_id, kind, predicate_uri) DO UPDATE SET "
                "  agrees = EXCLUDED.agrees, "
                "  change_token = EXCLUDED.change_token, "
                "  source_rows = EXCLUDED.source_rows, "
                "  computed_at = EXCLUDED.computed_at, "
                "  compute_ms = EXCLUDED.compute_ms",
                space_id, kind, RDF_TYPE_URI, agrees, token, rows, ms)
            record.update(agrees=agrees, rows=rows, compute_ms=ms)
            logger.info(
                "type agreement: %s %s rdf:type vs %s -> %s (%d rows, %d ms)",
                space_id, kind, col,
                "ABSORBABLE" if agrees else "differs, keeping the join", rows, ms)
        except asyncpg.UndefinedTableError as exc:
            record["skipped"] = f"missing table ({exc.__class__.__name__})"
        except Exception as exc:
            # A space that cannot be measured keeps whatever it had. The stored
            # token ages it out on its own as the table changes.
            record["error"] = f"{type(exc).__name__}: {exc}"
            logger.warning("type agreement: %s %s refresh failed: %s",
                           space_id, kind, exc)
        out.append(record)
    return out

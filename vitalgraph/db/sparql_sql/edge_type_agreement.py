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


def clear_cache() -> None:
    _CACHE.clear()


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
    try:
        async with bounded_lock_wait(conn):
            rows = await conn.fetchval(f"SELECT count(*) FROM {t_fs}")
    except Exception as exc:
        logger.debug("frame-type agreement: count failed: %s", exc)
        return None

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
        _CACHE[key] = (rows, None)
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
        _CACHE[(space_id, type_predicate)] = (edge_rows, None)
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

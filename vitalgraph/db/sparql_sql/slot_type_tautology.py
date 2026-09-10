"""Is a slot TYPE constraint able to exclude anything in this space?

`rewrite_frame_entity_table` absorbs `?slot a <T>` as a role-scoped semi-join back
through the edge, which is correct and costs three index probes per surviving
`frame_entity` row. With a criterion few rows survive and it is free; with none,
every row survives and it is the whole cost — 4.2x to 5.2x against the open walk
(`issues/048` Problem 4).

When no role slot in the space lacks `T`, the check cannot exclude anything and
can be dropped entirely. Measured worth: **7.4x**, 627,418 buffers to 84,573 on
identical rows.

WHY THIS IS A QUERY AND NOT AN ARGUMENT

`issues/048` twice proposed proving the redundancy by reasoning, and both were
wrong:

  * "a slot reached through `hasEntitySlotValue` from a `frame_entity` row IS a
    KGEntitySlot" — false. `sync_frame_slot_table` requires an edge, a
    source/dest role and `hasEntitySlotValue`, and never looks at the type.
  * comparing `rdf_stats` counts — necessary, not sufficient. On
    `sp_graph_skew_2k` the counts matched exactly while the conclusion was still
    unproven; two sets of equal size are not the same set.

So it is answered by an anti-join against the data, per space, and the counts are
used only as a free pre-filter.

STALENESS. A write can introduce the first differently-typed role slot at any
time, and then a dropped check returns rows that should have been excluded —
wrong answers, not slow ones. The cache is therefore keyed by the predicate's
`rdf_pred_stats` row count, so it is discarded the moment the slot-type predicate
changes size. That is the same freshness signal `sync_value_stats` uses, and it
is deliberately conservative: a write that leaves the count unchanged (an update
in place) will not invalidate it, so the cache is only sound for a space whose
slot types are append-mostly. Pass `enabled=False` to switch the whole
optimisation off if that is ever not true.
"""

from __future__ import annotations

import logging
from typing import Optional

from .db_provider import bounded_lock_wait

logger = logging.getLogger(__name__)

# (space_id, type_uri, roles) -> (predicate_rows_when_computed, excludes_nothing)
_CACHE: dict = {}

# How long the anti-join may run before the optimisation gives up on itself.
#
# 2000 ms was WORSE THAN EITHER OUTCOME, because it sat on top of the cost. The
# check measures ~1,805 ms warm on `wordnet_frames` with the terms resolved, so
# a 2 s budget flipped between succeeding and expiring from one run to the next
# — and the two answers produce plans 22x apart, measured on the reference
# CONSTRUCT with the verdict forced each way, three runs each:
#
#     verdict DROPS the constraint    5,722,181 buffers    3.4-3.7 s
#     verdict KEEPS it (expired)    126,593,820 buffers   41-42 s
#
# A bimodal plan is worse than a consistently slow one: it cannot be measured,
# and `issues/178` records several conclusions that were wrong because of it.
# The budget now sits well clear of the cost, so the common case is stable.
#
# The check is worth 7.4x, and measured on `wordnet_frames` it cost 58s / 26s /
# 3.9s in three successive cold processes and ~20ms warm (`issues/178`). The
# spread is PostgreSQL's buffer cache, not our own — so the 58s is the
# post-deploy cost, and it was being charged to whichever user's query arrived
# first. No optimisation input is worth a minute of someone's query.
#
# 5,000 ms, reduced from the 15,000 ms that first replaced the 2,000 ms.
#
# 2,000 ms was the real defect: it sat ON TOP OF the check's own 1,805 ms warm
# cost, so the verdict expired on some runs and not others and the plan flipped
# an order of magnitude with it. Determinism needs the budget clearly AWAY from
# the cost — above or below, but not on it — and 5,000 ms is ~2.8x clear of
# 1,805 ms, which the query-shape audit confirms is stable.
#
# 15,000 ms bought no more determinism than 5,000 ms and made the FALLBACK
# ruinous: a constraint whose check genuinely cannot finish burns the whole
# budget before giving up, and `scripts/query_shape_audit.py` measured exactly
# that — a 17.4 s generation on a space with no maintenance cycle behind it,
# 15 s of which was this check expiring.
#
# A space that HAS had a maintenance cycle reads the precomputed verdict and
# pays none of this. The budget bounds what an un-maintained space costs the
# first user through the door; it is not where the optimisation is meant to
# come from.
TAUTOLOGY_TIMEOUT_MS = 5000

SLOT_TYPE_URI = "http://vital.ai/ontology/haley-ai-kg#hasKGSlotType"
VITALTYPE_URI = "http://vital.ai/ontology/vital-core#vitaltype"
RDF_TYPE_URI = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"


def clear_cache() -> None:
    _CACHE.clear()


async def _anti_join(space_id: str, type_uri: str, roles: tuple,
                     type_predicate: str, conn,
                     timeout_ms: Optional[int] = None) -> Optional[bool]:
    """Does any role slot in this space LACK `type_uri`? True = none does.

    None means the question was not answered — a failure, or the budget ran out.
    Callers must read that as "keep the check", never as "nothing excluded".

    The `LIMIT 1` short-circuits the moment a counterexample turns up — but that
    is the verdict which DISABLES the optimisation. Proving the useful answer,
    "no role slot lacks this type", means scanning all of them, so the outcome
    worth having is by construction the expensive one. `timeout_ms=None` runs
    unbounded and is for the maintenance cycle, off the request path.
    """
    # RESOLVE the terms first, then compare uuid to uuid.
    #
    # Joining `{space}_term` by `term_text` inside the anti-join hides the
    # selectivity from the planner: it cannot use the statistics on
    # `(predicate_uuid, object_uuid)` for a value it does not know, so it
    # estimates blind. Resolved, the same check measured 1,805 ms against
    # 2,149 ms and — more importantly — becomes estimable.
    ids = {}
    try:
        for uri in (SLOT_TYPE_URI, type_predicate, type_uri, *roles):
            if uri in ids:
                continue
            ids[uri] = await conn.fetchval(
                f"SELECT term_uuid FROM {space_id}_term WHERE term_text = $1",
                uri)
    except Exception as exc:
        logger.debug("slot-type tautology: term resolution failed: %s", exc)
        return None
    if any(ids.get(u) is None for u in (SLOT_TYPE_URI, type_predicate, type_uri)):
        # A term that is absent cannot be lacked by anything, but saying so
        # here would be a guess about which direction that cuts. None keeps the
        # check, which is the safe direction.
        return None
    role_ids = [ids[r] for r in roles if ids.get(r) is not None]
    if not role_ids:
        return None

    placeholders = ", ".join(f"${i + 3}" for i in range(len(role_ids)))
    sql = f"""SELECT count(*) FROM (
                  SELECT 1 FROM {space_id}_rdf_quad q
                  WHERE q.predicate_uuid = $1
                    AND q.object_uuid IN ({placeholders})
                    AND NOT EXISTS (
                      SELECT 1 FROM {space_id}_rdf_quad ty
                      WHERE ty.subject_uuid = q.subject_uuid
                        AND ty.predicate_uuid = $2
                        AND ty.object_uuid = ${len(role_ids) + 3})
                  LIMIT 1) x"""
    args = (ids[SLOT_TYPE_URI], ids[type_predicate], *role_ids, ids[type_uri])

    if timeout_ms is None:
        try:
            return (await conn.fetchval(sql, *args)) == 0
        except Exception as exc:
            logger.debug("slot-type tautology: anti-join failed: %s", exc)
            return None

    # Plain SET with save/restore, not SET LOCAL: `create_transaction()` can
    # hand us a connection with a transaction already open, asyncpg nests ours
    # as a savepoint, and SET LOCAL survives the savepoint RELEASE to the end of
    # the OUTER transaction — silently imposing this timeout on the caller's
    # remaining statements. Same reasoning as `bounded_lock_wait`.
    #
    # The transaction wrapper is what makes the timeout survivable at all: a
    # statement_timeout is enforced SERVER-side and ABORTS the transaction, so
    # without a savepoint to roll back to, every later statement on this
    # connection would fail with InFailedSQLTransactionError — a bound that
    # trades a slow query for a broken one, which is `issues/177`.
    prev = await conn.fetchval("SHOW statement_timeout")
    await conn.execute(f"SET statement_timeout = '{int(timeout_ms)}ms'")
    try:
        async with conn.transaction():
            return (await conn.fetchval(sql, *args)) == 0
    except Exception as exc:
        logger.debug("slot-type tautology: anti-join gave up: %s", exc)
        return None
    finally:
        try:
            await conn.execute(f"SET statement_timeout = '{prev}'")
        except Exception:  # pragma: no cover - abort path
            logger.debug("could not restore statement_timeout to %s", prev)


async def excludes_nothing(space_id: str, type_uri: str, roles: tuple,
                           type_predicate: str, conn) -> Optional[bool]:
    """True when NO role slot in this space lacks `type_uri`.

    None when it cannot be answered — no connection, a term missing, a failed
    query. None must be treated as "keep the check": the whole risk here is
    dropping a constraint that does exclude something.
    """
    if conn is None or not roles:
        return None
    key = (space_id, type_uri, tuple(sorted(roles)), type_predicate)

    # Bounded lock wait: this reads the stats tables, which the maintenance
    # rebuild truncates under an AccessExclusiveLock. Sampling prod during a
    # rebuild, this query was 100 of 144 observed blocked-reader samples — the
    # single most-blocked read on the box (`issues/145`). Returning None costs
    # one kept-but-unnecessary constraint; waiting the pool-wide 10s costs the
    # user 10s and then returns None regardless.
    try:
        async with bounded_lock_wait(conn):
            pred_rows = await conn.fetchval(
                f"""SELECT s.row_count FROM {space_id}_rdf_pred_stats s
                    JOIN {space_id}_term t ON t.term_uuid = s.predicate_uuid
                    WHERE t.term_text = $1""", SLOT_TYPE_URI)
    except Exception as exc:
        logger.debug("slot-type tautology: pred stat lookup failed: %s", exc)
        return None

    cached = _CACHE.get(key)
    if cached is not None and cached[0] == pred_rows:
        return cached[1]

    verdict = await _anti_join(space_id, type_uri, roles, type_predicate,
                               conn, timeout_ms=TAUTOLOGY_TIMEOUT_MS)
    if verdict is None:
        # Cached as "could not answer" on purpose. Not caching would re-pay the
        # full timeout on EVERY query of this shape for the life of the process,
        # which is a worse trade than losing the 7.4x: the check is an
        # optimisation input, the timeout is not. It is re-evaluated when the
        # predicate's row count changes or the process restarts.
        _CACHE[key] = (pred_rows, None)
        logger.warning(
            "slot-type tautology: %s %s over %s gave up after %dms — the check "
            "is KEPT, so answers are correct and this query is slower. The "
            "maintenance cycle precomputes this; a space that has never had one "
            "pays here instead (issues/178).",
            space_id, type_uri, sorted(roles), TAUTOLOGY_TIMEOUT_MS)
        return None

    _CACHE[key] = (pred_rows, verdict)
    # No counterexample COUNT any more: `_anti_join` returns the verdict, not
    # the row it was derived from, and the query stops at `LIMIT 1` regardless —
    # so the old "(%d counterexample(s))" could only ever print 0 or 1.
    logger.info("slot-type tautology: %s %s over %s -> %s",
                space_id, type_uri, sorted(roles),
                "excludes nothing" if verdict else "EXCLUDES")
    return verdict


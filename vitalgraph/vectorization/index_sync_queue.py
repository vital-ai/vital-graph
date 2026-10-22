"""The per-space index sync queue: enqueue, claim, complete, retry (`issues/291`).

Every write that changes what a subject's vector, geo, fuzzy or FTS rows
should hold enqueues the subject here. Consumers (`index_sync_worker`) in ANY
app process claim rows, re-derive those rows, and delete the queue rows they
finished. The table is `{space}_index_sync_queue` (`sparql_sql_schema`).

THE GENERATION RULE. One row per `(context_uuid, subject_uuid)`. Enqueueing an
existing row bumps its `generation`, resets its retry state and records the
latest operation. A consumer remembers the generation it claimed and, when
done, deletes the row only if the generation is unchanged. A write that landed
while the sync was running therefore leaves the row behind and it is synced
again, from the data as it now is. This is what lets a consumer release its
connection across the embedding call: what it read may be overtaken, but never
silently.

LEASES, not locks. A claim commits at once, stamping `claimed_by` and
`claimed_until`. A row is claimable when it is due and its lease is absent or
expired, so a consumer that dies mid-batch gives its rows back when the lease
runs out. A lease that expires while its consumer is still working costs a
duplicate sync, never a lost one.

Rows are written and claimed in key order, so two multi-row statements cannot
lock the same rows in opposite orders.

THE CONSUMER NEVER WAITS ON A ROW LOCK (`issues/294`). Key order holds within
one statement, not across a writer's transaction: a frame delete queues its
frames' rows in its first statement and its owner entity's row in a later
one (the modification stamp), so it locks them out of key order. A consumer
that deleted its finished batch with a plain DELETE took the entity's row,
then waited on a frame row the writer held, while the writer's stamp waited
on the entity's: 15 deadlocks in two days on the test stack, one of them
killing a user's frame delete. `complete`, `fail` and `release` therefore
lock their rows with `FOR UPDATE SKIP LOCKED` first and touch only what they
hold. A transaction that never waits cannot be part of a cycle, whatever any
writer does. A row a writer holds is retried briefly outside the transaction
and, if still held, left to its lease: a duplicate sync, never a lost one.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple
from vitalgraph.db.sparql_sql.space_names import space_prefix

logger = logging.getLogger(__name__)

NOTIFY_CHANNEL = "vg_index_sync"

# Seconds a claim is held before another consumer may take the rows.
DEFAULT_LEASE_SECONDS = 300
# Retry backoff: BASE * 2^(attempts-1), capped.
_BACKOFF_BASE_SECONDS = 5
_BACKOFF_MAX_SECONDS = 600


def queue_table(space_id: str) -> str:
    return f"{space_prefix(space_id)}_index_sync_queue"


@dataclass(frozen=True)
class Claimed:
    context_uuid: uuid.UUID
    subject_uuid: uuid.UUID
    operation: str
    generation: int
    attempts: int


def _sorted_keys(context_uuid: uuid.UUID, subject_uuids: Iterable[uuid.UUID]):
    subs = sorted({uuid.UUID(str(s)) for s in subject_uuids})
    return [context_uuid] * len(subs), subs


async def enqueue(conn, space_id: str, context_uuid: uuid.UUID,
                  subject_uuids: Sequence[uuid.UUID], operation: str) -> int:
    """Queue `subject_uuids` in one graph for a sync. Returns the row count.

    Run on the caller's connection: inside a write's transaction it commits
    with the write, which is the point. The NOTIFY is transactional too, so
    consumers wake only once the rows are visible.
    """
    if operation not in ("upsert", "delete"):
        raise ValueError(f"operation must be upsert or delete, not {operation!r}")
    ctxs, subs = _sorted_keys(context_uuid, subject_uuids)
    if not subs:
        return 0
    t = queue_table(space_id)
    await conn.execute(
        f"INSERT INTO {t} AS q (context_uuid, subject_uuid, operation) "
        f"SELECT * FROM unnest($1::uuid[], $2::uuid[], "
        f"                     array_fill($3::text, ARRAY[cardinality($1::uuid[])])) "
        f"ON CONFLICT (context_uuid, subject_uuid) DO UPDATE SET "
        f"  generation = q.generation + 1, operation = EXCLUDED.operation, "
        f"  attempts = 0, next_attempt_at = NOW(), last_error = NULL",
        ctxs, subs, operation)
    # The payload is the space's name PREFIX, as the trigger sends it.
    await conn.execute("SELECT pg_notify($1, $2)", NOTIFY_CHANNEL,
                       space_prefix(space_id))
    return len(subs)


async def claim(conn, space_id: str, consumer: str, limit: int,
                lease_seconds: int = DEFAULT_LEASE_SECONDS) -> List[Claimed]:
    """Claim up to `limit` due rows for `consumer`; committed at once."""
    t = queue_table(space_id)
    rows = await conn.fetch(
        f"WITH due AS ("
        f"  SELECT context_uuid, subject_uuid FROM {t} "
        f"  WHERE next_attempt_at <= NOW() "
        f"    AND (claimed_until IS NULL OR claimed_until < NOW()) "
        f"  ORDER BY next_attempt_at, context_uuid, subject_uuid "
        f"  LIMIT $1 FOR UPDATE SKIP LOCKED) "
        f"UPDATE {t} q SET claimed_by = $2, "
        f"  claimed_until = NOW() + make_interval(secs => $3), "
        f"  attempts = q.attempts + 1 "
        f"FROM due WHERE q.context_uuid = due.context_uuid "
        f"  AND q.subject_uuid = due.subject_uuid "
        f"RETURNING q.context_uuid, q.subject_uuid, q.operation, q.generation, q.attempts",
        limit, consumer, float(lease_seconds))
    return sorted((Claimed(r["context_uuid"], r["subject_uuid"], r["operation"],
                           r["generation"], r["attempts"]) for r in rows),
                  key=lambda c: (c.context_uuid, c.subject_uuid))


def _arrays(claimed: Sequence[Claimed]) -> Tuple[list, list, list]:
    return ([c.context_uuid for c in claimed], [c.subject_uuid for c in claimed],
            [c.generation for c in claimed])


# Retries for rows a writer holds when a consumer finishes: short, outside any
# transaction. A writer's transaction is milliseconds unless it is slow, and a
# row still held after these waits out its lease instead.
_HELD_RETRIES = 4
_HELD_BACKOFF_SECONDS = 0.05


async def _lock_held(conn, t: str, ctxs: list, subs: list):
    """Lock what can be locked of these keys, in key order, WITHOUT waiting.

    Returns (locked, held): `locked` are the keys this transaction now holds;
    `held` are keys that exist but another transaction holds. A key that is in
    neither no longer exists. Must run inside a transaction.
    """
    rows = await conn.fetch(
        f"SELECT q.context_uuid, q.subject_uuid FROM {t} q "
        f"JOIN unnest($1::uuid[], $2::uuid[]) AS d(c, s) "
        f"  ON q.context_uuid = d.c AND q.subject_uuid = d.s "
        f"ORDER BY q.context_uuid, q.subject_uuid "
        f"FOR UPDATE OF q SKIP LOCKED", ctxs, subs)
    locked = {(r["context_uuid"], r["subject_uuid"]) for r in rows}
    rest = [(c, s) for c, s in zip(ctxs, subs) if (c, s) not in locked]
    held = set()
    if rest:
        # A plain read does not wait on row locks, so this tells a row another
        # transaction holds from one that is gone.
        rows = await conn.fetch(
            f"SELECT q.context_uuid, q.subject_uuid FROM {t} q "
            f"JOIN unnest($1::uuid[], $2::uuid[]) AS d(c, s) "
            f"  ON q.context_uuid = d.c AND q.subject_uuid = d.s",
            [c for c, _ in rest], [s for _, s in rest])
        held = {(r["context_uuid"], r["subject_uuid"]) for r in rows}
    return locked, held


async def _without_waiting(conn, t: str, claimed: Sequence[Claimed], step):
    """Run `step(conn, claimed_subset)` on the rows that can be locked now,
    retrying rows another transaction holds. Returns (step results, still held)."""
    import asyncio
    remaining = sorted(claimed, key=lambda c: (c.context_uuid, c.subject_uuid))
    results = []
    for attempt in range(_HELD_RETRIES + 1):
        async with conn.transaction():
            locked, held = await _lock_held(
                conn, t, [c.context_uuid for c in remaining],
                [c.subject_uuid for c in remaining])
            mine = [c for c in remaining if (c.context_uuid, c.subject_uuid) in locked]
            if mine:
                results.append(await step(conn, mine))
        remaining = [c for c in remaining if (c.context_uuid, c.subject_uuid) in held]
        if not remaining or attempt == _HELD_RETRIES:
            break
        await asyncio.sleep(_HELD_BACKOFF_SECONDS * 2 ** attempt)
    return results, remaining


async def complete(conn, space_id: str, consumer: str,
                   claimed: Sequence[Claimed]) -> int:
    """Finish `claimed`. Returns how many rows were overtaken by a newer write
    and so stay queued (released from this claim, due now).

    Never waits on a row lock (see the module note). A row a writer still holds
    after the retries keeps its claim and is synced again when the lease runs
    out; the writer is bumping it, so it would have stayed queued anyway.
    """
    if not claimed:
        return 0
    t = queue_table(space_id)

    async def step(c, rows):
        ctxs, subs, gens = _arrays(rows)
        await c.execute(
            f"DELETE FROM {t} q USING unnest($1::uuid[], $2::uuid[], $3::bigint[]) "
            f"  AS d(c, s, g) "
            f"WHERE q.context_uuid = d.c AND q.subject_uuid = d.s AND q.generation = d.g",
            ctxs, subs, gens)
        status = await c.execute(
            f"UPDATE {t} q SET claimed_by = NULL, claimed_until = NULL "
            f"FROM unnest($1::uuid[], $2::uuid[]) AS d(c, s) "
            f"WHERE q.context_uuid = d.c AND q.subject_uuid = d.s AND q.claimed_by = $3",
            ctxs, subs, consumer)
        return int(status.split()[-1]) if status else 0

    results, held = await _without_waiting(conn, t, claimed, step)
    if held:
        logger.info("index sync %s: %d finished row(s) held by a writer; left to "
                    "their lease", space_id, len(held))
    return sum(results)


def backoff_seconds(attempts: int) -> int:
    return min(_BACKOFF_MAX_SECONDS, _BACKOFF_BASE_SECONDS * 2 ** max(0, attempts - 1))


async def fail(conn, space_id: str, consumer: str, claimed: Sequence[Claimed],
               error: str) -> None:
    """Give `claimed` back for a retry after a backoff from its attempt count.

    A row a newer write has bumped (attempts reset to 0) is due at once; the
    backoff is for the failure, and the new write is a new request. Never
    waits on a row lock; a row a writer holds keeps its claim until the lease
    runs out, and is retried then.
    """
    if not claimed:
        return
    t = queue_table(space_id)

    async def step(c, rows):
        ctxs, subs, gens = _arrays(rows)
        await c.execute(
            f"UPDATE {t} q SET claimed_by = NULL, claimed_until = NULL, "
            f"  last_error = left($4, 2000), "
            f"  next_attempt_at = CASE WHEN q.generation = d.g "
            f"    THEN NOW() + make_interval(secs => LEAST($5::float8, "
            f"         $6::float8 * power(2, GREATEST(q.attempts - 1, 0)))) "
            f"    ELSE NOW() END "
            f"FROM unnest($1::uuid[], $2::uuid[], $3::bigint[]) AS d(c, s, g) "
            f"WHERE q.context_uuid = d.c AND q.subject_uuid = d.s AND q.claimed_by = $7",
            ctxs, subs, gens, error, float(_BACKOFF_MAX_SECONDS),
            float(_BACKOFF_BASE_SECONDS), consumer)

    await _without_waiting(conn, t, claimed, step)


async def release(conn, space_id: str, consumer: str) -> int:
    """Give back every row `consumer` holds, due now -- at shutdown, so a
    deploy does not leave them waiting out their lease."""
    t = queue_table(space_id)
    async with conn.transaction():
        # Locked without waiting, like `complete`: a row a writer holds keeps
        # this claim until its lease runs out.
        status = await conn.execute(
            f"UPDATE {t} q SET claimed_by = NULL, claimed_until = NULL "
            f"FROM (SELECT context_uuid, subject_uuid FROM {t} WHERE claimed_by = $1 "
            f"      ORDER BY context_uuid, subject_uuid FOR UPDATE SKIP LOCKED) h "
            f"WHERE q.context_uuid = h.context_uuid AND q.subject_uuid = h.subject_uuid",
            consumer)
    return int(status.split()[-1]) if status else 0


async def has_due(conn, space_id: str) -> bool:
    t = queue_table(space_id)
    return bool(await conn.fetchval(
        f"SELECT EXISTS (SELECT 1 FROM {t} WHERE next_attempt_at <= NOW() "
        f"  AND (claimed_until IS NULL OR claimed_until < NOW()))"))


async def pending(conn, space_id: str, context_uuid: uuid.UUID,
                  subject_uuids: Sequence[uuid.UUID]) -> int:
    """How many of these subjects are still queued (due, claimed or backing off)."""
    t = queue_table(space_id)
    return await conn.fetchval(
        f"SELECT count(*) FROM {t} WHERE context_uuid = $1 "
        f"AND subject_uuid = ANY($2::uuid[])",
        context_uuid, [uuid.UUID(str(s)) for s in subject_uuids])


async def table_exists(conn, space_id: str) -> bool:
    return bool(await conn.fetchval("SELECT to_regclass($1) IS NOT NULL",
                                    queue_table(space_id)))


async def stats(conn, space_id: str) -> Optional[dict]:
    """Depth, oldest due row's age and the failing count, for monitoring."""
    if not await table_exists(conn, space_id):
        return None
    r = await conn.fetchrow(
        f"SELECT count(*) AS depth, "
        f"  count(*) FILTER (WHERE claimed_until > NOW()) AS claimed, "
        f"  count(*) FILTER (WHERE last_error IS NOT NULL) AS failing, "
        f"  EXTRACT(EPOCH FROM NOW() - min(enqueued_at)) AS oldest_seconds "
        f"FROM {queue_table(space_id)}")
    return dict(r)

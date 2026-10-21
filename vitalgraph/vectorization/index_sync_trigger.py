"""The `rdf_quad` trigger that fills the index sync queue (`issues/291` step 2).

Every write statement on a space's `rdf_quad` records the `(context, subject)`
pairs it inserted or deleted into `{space}_index_sync_queue`, IN THE WRITE'S
OWN TRANSACTION. That is the outbox: the sync request commits with the write
or not at all, so no crash, deploy or cancelled task between a commit and a
later enqueue can lose it -- which `schedule_sync`, called after the write
returned, could.

It covers every write path, including those Python never sees the subjects
of: SPARQL UPDATE's WHERE-bound deletes, the objects endpoint, relations. From
2026-10-20 those keep vectors and FTS in step too; they did not before.

STATEMENT-LEVEL, with transition tables: one `INSERT ... SELECT DISTINCT` per
write statement, not one per quad. Proven on PostgreSQL 18 for a
HASH-partitioned `rdf_quad` and for COPY.

Rows are always queued as `'upsert'`. A statement cannot tell a deleted subject
from one whose quads were replaced, so the consumer decides from the data
(`index_sync_worker`): present means re-derive, absent means remove.

OPTING OUT. A transaction that must not queue per subject -- an import, a
restore, the server-property backfill -- runs `suppress(conn)`, which sets
`vitalgraph.index_sync = 'off'` for that transaction only. Every such site
says what keeps its index rows correct instead.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import Dict, List, Tuple
from vitalgraph.db.sparql_sql.space_names import space_prefix

GUC = "vitalgraph.index_sync"


def function_name(space_id: str) -> str:
    return f"{space_prefix(space_id)}_isq_capture"


def trigger_names(space_id: str) -> Tuple[str, str]:
    return f"trg_{space_prefix(space_id)}_isq_ins", f"trg_{space_prefix(space_id)}_isq_del"


def create_sql(space_id: str) -> List[str]:
    """The function and both triggers. Idempotent.

    THE BODY NAMES NO SPACE. It derives the space from `TG_TABLE_NAME` (the
    parent table, for a partitioned `rdf_quad`) and reaches the queue with
    dynamic SQL, which sees the transition tables. A body that spelled out
    `{space}_index_sync_queue` would survive a space rename -- which renames
    objects, not function bodies -- pointing at a table that no longer
    exists, and every write to the renamed space would fail.
    """
    fn = function_name(space_id)
    ins, dele = trigger_names(space_id)
    quad = f"{space_prefix(space_id)}_rdf_quad"
    return [
        f"""CREATE OR REPLACE FUNCTION {fn}() RETURNS trigger
            LANGUAGE plpgsql AS $isq$
            DECLARE
              sp text := regexp_replace(TG_TABLE_NAME, '_rdf_quad$', '');
            BEGIN
              IF current_setting('{GUC}', true) = 'off' THEN
                RETURN NULL;
              END IF;
              -- ORDER BY: two writers upserting overlapping subjects lock the
              -- queue rows in the same order, so they cannot deadlock on them.
              EXECUTE format(
                'INSERT INTO %I AS q (context_uuid, subject_uuid, operation) '
                'SELECT DISTINCT context_uuid, subject_uuid, ''upsert'' FROM %I '
                'ORDER BY 1, 2 '
                'ON CONFLICT (context_uuid, subject_uuid) DO UPDATE SET '
                'generation = q.generation + 1, attempts = 0, '
                'next_attempt_at = NOW(), last_error = NULL',
                sp || '_index_sync_queue',
                CASE WHEN TG_OP = 'INSERT' THEN 'isq_new' ELSE 'isq_old' END);
              -- Deduplicated within the transaction, delivered at commit.
              PERFORM pg_notify('vg_index_sync', sp);
              RETURN NULL;
            END $isq$""",
        f"DROP TRIGGER IF EXISTS {ins} ON {quad}",
        f"CREATE TRIGGER {ins} AFTER INSERT ON {quad} "
        f"REFERENCING NEW TABLE AS isq_new FOR EACH STATEMENT EXECUTE FUNCTION {fn}()",
        f"DROP TRIGGER IF EXISTS {dele} ON {quad}",
        f"CREATE TRIGGER {dele} AFTER DELETE ON {quad} "
        f"REFERENCING OLD TABLE AS isq_old FOR EACH STATEMENT EXECUTE FUNCTION {fn}()",
    ]


def drop_function_sql(space_id: str) -> str:
    """The triggers go with the table; the function does not."""
    return f"DROP FUNCTION IF EXISTS {function_name(space_id)}() CASCADE"


async def suppress(conn) -> None:
    """No queueing for the rest of this transaction.

    Refuses outside one: `SET LOCAL` there is a silent no-op (`issues/275`),
    and a bulk load that believed itself suppressed would queue every subject.
    """
    if not conn.is_in_transaction():
        raise RuntimeError("index sync suppress() needs an open transaction")
    await conn.execute(f"SET LOCAL {GUC} = 'off'")


@asynccontextmanager
async def suppressed(conn):
    """No queueing for the duration, inside a transaction or not.

    Inside one: `SET LOCAL`, which ends with it. Outside: a session setting,
    RESET on the way out -- a pooled connection must not go back to the pool
    with the trigger switched off.
    """
    if conn.is_in_transaction():
        await suppress(conn)
        yield
        return
    await conn.execute(f"SET {GUC} = 'off'")
    try:
        yield
    finally:
        await conn.execute(f"RESET {GUC}")


@asynccontextmanager
async def captured_explicitly(conn, space_id: str, pairs):
    """Run a multi-row write with the trigger off, then queue `pairs` ONCE.

    A statement-level trigger fires per EXECUTION, and `executemany` executes
    once per row: measured on a 44-quad entity graph, the trigger fired 44
    times and added 26% to the insert (34 -> 43 ms median) and 30% to a
    replace. The hot bulk paths therefore switch it off for their own
    statements and queue the distinct `(context_uuid, subject_uuid)` pairs they
    already hold, on the same connection, in the same transaction -- the same
    outbox guarantee in one statement. The previous setting is restored after,
    so the rest of a caller's transaction is still captured by the trigger.

    Only inside a transaction, where `set_config(..., true)` holds; outside
    one the trigger simply fires per row, which is slower but still correct.
    An enclosing `suppress` (an import, a restore) is honoured: nothing is
    queued. A space without the trigger queues nothing here either --
    `schedule_sync` covers it after the write.
    """
    if not conn.is_in_transaction():
        yield
        return
    prev = await conn.fetchval("SELECT current_setting($1, true)", GUC)
    await conn.execute("SELECT set_config($1, 'off', true)", GUC)
    try:
        yield
    finally:
        await conn.execute("SELECT set_config($1, $2, true)", GUC, prev or "")
    if prev == "off" or not await installed_cached(conn, space_id):
        return
    from . import index_sync_queue as q
    by_ctx: Dict = {}
    for ctx, subj in pairs:
        by_ctx.setdefault(ctx, set()).add(subj)
    for ctx in sorted(by_ctx):
        await q.enqueue(conn, space_id, ctx, sorted(by_ctx[ctx]), "upsert")


async def installed(conn, space_id: str) -> bool:
    """Both triggers present and enabled on the space's `rdf_quad`."""
    ins, dele = trigger_names(space_id)
    n = await conn.fetchval(
        "SELECT count(*) FROM pg_trigger WHERE tgname = ANY($1::text[]) "
        "AND tgenabled <> 'D'", [ins, dele])
    return n == 2


# Per-process cache of `installed`, so a write's post-commit `schedule_sync`
# can skip without a catalog query each time. Short-lived: the migration adds
# the triggers to a running fleet, and a stale False only costs a duplicate
# enqueue (merged), never a missed one.
_CACHE: Dict[str, Tuple[bool, float]] = {}
_CACHE_SECONDS = 60.0


async def installed_cached(conn, space_id: str) -> bool:
    hit = _CACHE.get(space_id)
    now = time.monotonic()
    if hit is not None and now - hit[1] < _CACHE_SECONDS:
        return hit[0]
    ok = await installed(conn, space_id)
    _CACHE[space_id] = (ok, now)
    return ok

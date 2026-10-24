"""The per-space write log: which transactions have written a space's quads.

A stored verdict about the data ("every subject with p has the triple q T",
planning_planner/09, implied-pattern elimination) is only usable while nothing
has written the space since it was checked. This is how that is known, from
the database side and for EVERY write path: no writer has to cooperate, and
none can opt out.

    {space}_write_log (xid xid8 PRIMARY KEY, n bigint)

A statement-level trigger on `{space}_rdf_quad` (`AFTER INSERT OR UPDATE OR
DELETE OR TRUNCATE`) inserts one row per writing TRANSACTION, keyed by
`pg_current_xact_id()`. The write count is `sum(n)`, read in a snapshot.

WHY THIS AND NOT A COUNTER. It is transactional, so a reader sees a write's
log row exactly when it sees the write's quads; and every transaction inserts
its own key, so concurrent writers never wait on each other. A counter row per
space is transactional but serialises the space's writers on its row lock; a
sequence is not transactional (bumped before the writer commits, so a check
can read the bump without seeing the rows); `pg_stat` counters are flushed
asynchronously (a second, up to a minute under contention).

WHY A COUNT IS ENOUGH. A snapshot taken later sees a superset of the committed
transactions an earlier one saw, and the log only grows (compaction folds rows
into one row of their sum in one transaction, so no snapshot's count changes).
Equal counts in the earlier and the later snapshot therefore mean the same
committed writes.

NO OPT-OUT, unlike `vectorization/index_sync_trigger.suppress`: an import or a
restore is exactly the kind of write a verdict must not survive.

THE BODY NAMES NO SPACE: it derives the space from `TG_TABLE_NAME` (the parent,
for a partitioned `rdf_quad`), so a space rename, which renames objects and not
function bodies, leaves it working.

A table swap (`partition_migrate` drops and recreates `rdf_quad` with `LIKE`,
which copies no triggers) loses the trigger. So a verdict records the quad
table's OID and a reader checks the trigger is present and enabled
(`guard_state`): either failing reads as "unknown", never as "unchanged".
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from .space_names import space_prefix

#: The compacted row's key: InvalidTransactionId, never a real transaction's.
COMPACTED_XID = "0"


def table_name(space_id: str) -> str:
    return f"{space_prefix(space_id)}_write_log"


def function_name(space_id: str) -> str:
    return f"{space_prefix(space_id)}_wlog_capture"


def trigger_name(space_id: str) -> str:
    return f"trg_{space_prefix(space_id)}_wlog"


def create_sql(space_id: str) -> List[str]:
    """The table, the function and the trigger, in that order. Idempotent.

    The marker (`vitalgraph.wlog_<prefix>`, transaction-local) skips the
    insert for a transaction's later statements: a statement trigger fires per
    EXECUTION, and `executemany` executes once per row. A rolled-back
    savepoint reverts both the row and the marker, so the next statement
    inserts again.
    """
    tbl, fn = table_name(space_id), function_name(space_id)
    quad = f"{space_prefix(space_id)}_rdf_quad"
    return [
        f"CREATE TABLE IF NOT EXISTS {tbl} (xid xid8 PRIMARY KEY, n bigint NOT NULL)",
        f"""CREATE OR REPLACE FUNCTION {fn}() RETURNS trigger
            LANGUAGE plpgsql AS $wlog$
            DECLARE
              sp text := regexp_replace(TG_TABLE_NAME, '_rdf_quad$', '');
              x xid8 := pg_current_xact_id();
            BEGIN
              IF current_setting('vitalgraph.wlog_' || sp, true) IS DISTINCT FROM x::text THEN
                EXECUTE format('INSERT INTO %I (xid, n) VALUES ($1, 1) ON CONFLICT (xid) DO NOTHING',
                               sp || '_write_log') USING x;
                PERFORM set_config('vitalgraph.wlog_' || sp, x::text, true);
              END IF;
              RETURN NULL;
            END $wlog$""",
        f"DROP TRIGGER IF EXISTS {trigger_name(space_id)} ON {quad}",
        f"CREATE TRIGGER {trigger_name(space_id)} AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE "
        f"ON {quad} FOR EACH STATEMENT EXECUTE FUNCTION {fn}()",
    ]


def drop_function_sql(space_id: str) -> str:
    """The trigger goes with the table; the function does not."""
    return f"DROP FUNCTION IF EXISTS {function_name(space_id)}() CASCADE"


def _state_sql(space_id: str) -> str:
    quad = f"{space_prefix(space_id)}_rdf_quad"
    return (
        f"SELECT (SELECT coalesce(sum(n), 0) FROM {table_name(space_id)})::bigint AS writes, "
        f"to_regclass('{quad}')::oid AS quad_oid, "
        f"EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid = to_regclass('{quad}') "
        f"AND tgname = '{trigger_name(space_id)}' AND tgenabled <> 'D') AS trigger_ok")


async def installed(conn, space_id: str) -> bool:
    """The log table exists and the trigger is present and enabled."""
    if not await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", table_name(space_id)):
        return False
    return bool((await conn.fetchrow(_state_sql(space_id)))["trigger_ok"])


async def guard_state(conn, space_id: str) -> Optional[Tuple[int, int]]:
    """(write count, quad table OID) in the caller's snapshot, or None when the
    log cannot vouch for anything (no table, or the trigger missing/disabled).
    Read it in the same snapshot as whatever it guards: a REPEATABLE READ
    transaction, for a check and the statement it protects."""
    if not await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", table_name(space_id)):
        return None
    r = await conn.fetchrow(_state_sql(space_id))
    if not r["trigger_ok"]:
        return None
    return int(r["writes"]), int(r["quad_oid"])


def compact_sql(table: str) -> str:
    """Fold every committed row into the one compacted row. One statement, so
    one snapshot: a reader before it and a reader after it count the same.
    Returns the rows folded."""
    return (f"WITH d AS (DELETE FROM {table} WHERE xid <> '{COMPACTED_XID}'::xid8 RETURNING n), "
            f"s AS (SELECT count(*) AS rows, sum(n) AS n FROM d), "
            f"i AS (INSERT INTO {table} AS w (xid, n) SELECT '{COMPACTED_XID}'::xid8, n FROM s WHERE rows > 0 "
            f"ON CONFLICT (xid) DO UPDATE SET n = w.n + excluded.n) "
            f"SELECT rows FROM s")


async def compact(conn, space_id: str) -> int:
    return await conn.fetchval(compact_sql(table_name(space_id)))

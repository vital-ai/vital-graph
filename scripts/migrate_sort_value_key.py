#!/usr/bin/env python3
"""Move the sort tables' text indexes onto the bounded `value_key` (issues/283).

`entity_slot_sort`, `entity_prop_sort` and `frame_prop_sort` indexed the whole
`value_text` in a btree, and `value_all` in a GIN. Both cap an entry near
2.7 KB, so any value longer than that failed the write that carried it:

    index row size 3320 exceeds btree version 4 maximum 2704 for index
    "idx_<space>_ess_text"

New spaces get the bounded schema from `create_space_tables_sql`. This brings an
existing space to it, per table present:

  1. ADD the generated `value_key` column. A STORED generated column REWRITES
     the table under an ACCESS EXCLUSIVE lock -- this reports each table's size
     first so the cost is known rather than discovered.
  2. BOUND `value_all` elements on the two prop-sort tables. Only rows holding
     an element past the bound are touched; on most spaces that is none.
  3. BUILD the seven text indexes on `value_key`, from
     `create_space_indexes_sql` rather than restated here -- a second
     definition is how the ensure_* modules drifted from the schema. The old
     index is RENAMED to `<name>_pre283`, not dropped (see below).
  4. ANALYZE, so the planner has statistics for the new column.

TWO PHASES, because production deploys separately from this script. The code
released before the fix sorts on `value_text`; dropping its index before that
code is replaced would turn every text-sorted listing into a full sort until
the deploy lands. So:

    before the deploy   --apply      both indexes exist; old code uses the old
                                     one, new code the new one
    after the deploy    --drop-old --apply
                                     drops the `_pre283` indexes

Until `--drop-old`, the old index is still there and still rejects a long value,
so the write failures this fixes stop only after phase two.

Either order of code and schema is CORRECT. Old code on a migrated space ignores
`value_key` (the column is generated, so its inserts need no change). New code
on an unmigrated space fails its fast-path query and every reader falls back to
the general pipeline -- correct, slow, and logged.

All of it for one space runs in ONE transaction: a space is either wholly on
the old schema or wholly on the new, never between. Idempotent -- a space
already migrated is reported and skipped.

No resync is needed. The column is generated from `value_text`, which is
already correct, and the `value_all` bound is applied in place.

RUN AS THE TABLES' OWNER. ALTER TABLE requires it, and on production that is the
app role, not the RDS master.

DEFAULT IS A DRY RUN.

    python scripts/migrate_sort_value_key.py --all
    python scripts/migrate_sort_value_key.py --space lead_prod --apply
    python scripts/migrate_sort_value_key.py --all --drop-old --apply
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time

# The repo root ahead of site-packages: an installed copy resolves a different
# cluster (see `migrate_quad_ctx_pred_index.py`).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from devtools.target import add_pg_arguments, describe_target  # noqa: E402
from vitalgraph.db.sparql_sql.space_names import space_id_for_prefix, space_prefix  # noqa: E402
from vitalgraph.db.sparql_sql.space_storage_key import load_storage_keys  # noqa: E402

logger = logging.getLogger("migrate_sort_value_key")

TABLES = ("entity_slot_sort", "entity_prop_sort", "frame_prop_sort")
WITH_VALUE_ALL = ("entity_prop_sort", "frame_prop_sort")
# The index suffixes whose key includes the text value.
TEXT_INDEXES = ("ess_text", "eps_text", "eps_any_text", "eps_text_desc",
                "fps_text", "fps_any_text", "fps_form_text")
# What phase one renames the old indexes to. 7 bytes: the longest name,
# `idx_<34-byte id>_eps_text_desc_pre283`, is 59 of PostgreSQL's 63.
OLD_SUFFIX = "_pre283"


async def _table_exists(conn, table: str) -> bool:
    return bool(await conn.fetchval(
        "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename=$1",
        table))


async def _has_column(conn, table: str, column: str) -> bool:
    return bool(await conn.fetchval(
        "SELECT 1 FROM information_schema.columns WHERE table_schema='public' "
        "AND table_name=$1 AND column_name=$2", table, column))


async def plan_space(conn, space_id: str) -> dict:
    """What the migration would do to this space, without doing it."""
    from vitalgraph.db.sparql_sql.sort_value_key import (
        VALUE_KEY_CHARS, VALUE_KEY_COLUMN)

    plan = {"space": space_id, "add_column": [], "bound_value_all": {},
            "rebuild_index": [], "sizes": {}}
    for name in TABLES:
        t = f"{space_prefix(space_id)}_{name}"
        if not await _table_exists(conn, t):
            continue
        if not await _has_column(conn, t, VALUE_KEY_COLUMN):
            plan["add_column"].append(t)
            plan["sizes"][t] = await conn.fetchval(
                f"SELECT pg_size_pretty(pg_total_relation_size('{t}'))")
        if name in WITH_VALUE_ALL:
            n = await conn.fetchval(
                f"SELECT count(*) FROM {t} WHERE EXISTS "
                f"(SELECT 1 FROM unnest(value_all) e "
                f" WHERE length(e) > {VALUE_KEY_CHARS})")
            if n:
                plan["bound_value_all"][t] = n
    for suffix in TEXT_INDEXES:
        idx = f"idx_{space_prefix(space_id)}_{suffix}"
        d = await conn.fetchval(
            "SELECT indexdef FROM pg_indexes WHERE schemaname='public' "
            "AND indexname=$1", idx)
        if d is not None and "value_text" in d:
            plan["rebuild_index"].append(idx)
    return plan


def _is_noop(plan: dict) -> bool:
    return not (plan["add_column"] or plan["bound_value_all"]
                or plan["rebuild_index"])


async def apply_plan(conn, plan: dict) -> float:
    from vitalgraph.db.sparql_sql.sort_value_key import (
        VALUE_KEY_CHARS, value_key_column_sql)
    from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema

    space_id = plan["space"]
    create = {}
    for stmt in SparqlSQLSchema().create_space_indexes_sql(space_id):
        for idx in plan["rebuild_index"]:
            if f"INDEX IF NOT EXISTS {idx} " in stmt:
                create[idx] = stmt
    missing = set(plan["rebuild_index"]) - set(create)
    if missing:
        raise RuntimeError(f"no schema definition found for {sorted(missing)}")

    t0 = time.monotonic()
    async with conn.transaction():
        # The session's timeout would kill the rewrite part-way on production,
        # where the parameter group sets 60 s; LOCAL so it ends with the
        # transaction.
        await conn.execute("SET LOCAL statement_timeout = 0")
        for t in plan["add_column"]:
            await conn.execute(f"ALTER TABLE {t} ADD COLUMN {value_key_column_sql()}")
        for t in plan["bound_value_all"]:
            # Same element form and order the sync's `array_agg(DISTINCT ...)`
            # produces, so a migrated row is identical to a re-derived one.
            await conn.execute(
                f"UPDATE {t} SET value_all = ARRAY("
                f"  SELECT DISTINCT left(e, {VALUE_KEY_CHARS}) "
                f"  FROM unnest(value_all) e ORDER BY 1) "
                f"WHERE EXISTS (SELECT 1 FROM unnest(value_all) e "
                f"              WHERE length(e) > {VALUE_KEY_CHARS})")
        for idx in plan["rebuild_index"]:
            # Renamed, not dropped: the code still deployed reads it. Phase
            # two (`--drop-old`) removes it after the deploy.
            await conn.execute(f"ALTER INDEX {idx} RENAME TO {idx}{OLD_SUFFIX}")
            await conn.execute(create[idx])
    for name in TABLES:
        t = f"{space_prefix(space_id)}_{name}"
        if await _table_exists(conn, t):
            await conn.execute(f"ANALYZE {t}")
    return time.monotonic() - t0


async def old_indexes(conn, space_id: str) -> list:
    """The `_pre283` indexes phase one left behind on this space."""
    names = [f"idx_{space_prefix(space_id)}_{s}{OLD_SUFFIX}" for s in TEXT_INDEXES]
    return [r["indexname"] for r in await conn.fetch(
        "SELECT indexname FROM pg_indexes WHERE schemaname='public' "
        "AND indexname = ANY($1::text[]) ORDER BY 1", names)]


async def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--space")
    g.add_argument("--all", action="store_true")
    ap.add_argument("--apply", action="store_true",
                    help="phase one: migrate (default is a dry run)")
    ap.add_argument("--drop-old", action="store_true",
                    help="phase two, after the deploy: drop the _pre283 "
                         "indexes (with --apply; a dry run otherwise)")
    add_pg_arguments(ap)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(f"\U0001F5C4  target: {describe_target(a)}", flush=True)
    logger.info("%s", "APPLY" if a.apply else "DRY RUN")

    import asyncpg
    conn = await asyncpg.connect(host=a.host, port=a.port, database=a.database,
                                 user=a.user, password=a.password or None)
    await load_storage_keys(conn)
    try:
        spaces = ([space_id_for_prefix(r[0]) for r in await conn.fetch(
            "SELECT replace(tablename,'_rdf_quad','') FROM pg_tables "
            "WHERE schemaname='public' AND tablename LIKE '%\\_rdf\\_quad' "
            "ORDER BY 1")] if a.all else [a.space])
        if a.drop_old:
            dropped = 0
            for sp in spaces:
                for idx in await old_indexes(conn, sp):
                    if a.apply:
                        await conn.execute(f"DROP INDEX IF EXISTS {idx}")
                    dropped += 1
                    logger.info("    %s %s", "dropped" if a.apply else "would drop", idx)
            logger.info("\n%d old index(es) %s", dropped,
                        "dropped" if a.apply else "to drop -- re-run with --apply")
            return 0

        pending = done = 0
        for sp in spaces:
            plan = await plan_space(conn, sp)
            if _is_noop(plan):
                continue
            pending += 1
            logger.info("%s:", sp)
            for t in plan["add_column"]:
                logger.info("    add value_key to %s (%s) -- table REWRITTEN",
                            t, plan["sizes"][t])
            for t, n in plan["bound_value_all"].items():
                logger.info("    bound value_all in %s: %s row(s)", t, f"{n:,}")
            for idx in plan["rebuild_index"]:
                logger.info("    rebuild %s", idx)
            if a.apply:
                secs = await apply_plan(conn, plan)
                done += 1
                logger.info("    done in %.1fs", secs)
        logger.info("\n%d of %d space(s) %s", done if a.apply else pending,
                    len(spaces), "migrated" if a.apply else "need migration")
        if not a.apply and pending:
            logger.info("Dry run. Re-run with --apply.")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

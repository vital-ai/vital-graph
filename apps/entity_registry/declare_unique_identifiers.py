#!/usr/bin/env python3
"""Report on, and apply, DECLARED-unique identifiers — `issues/227`.

A (type_key, namespace) pair in `EntityRegistrySchema.DECLARED_UNIQUE_IDENTIFIERS`
is declared unique: a partial unique index on `entity_identifier`, so at most
one ACTIVE identifier row per value for entities of that type, on every write
path, and `resolve_or_create_entity` works for it.

    --report   every pair in use: rows, rows still without entity_type_id, and
               the values held by MORE THAN ONE active entity of that type —
               which is exactly what blocks a declaration. Read-only.
    --apply    build each declared pair's index, CONCURRENTLY (no write lock on
               the table). A pair whose data still contradicts it FAILS to
               build — the expected outcome until its duplicates are merged —
               and is reported with the values in the way, its invalid
               leftover index dropped.

A declaration is only ever made true by the data: there is no option to force
one, and no bypass for internal writes. A bulk correction drops the index, runs,
and re-applies — the rebuild fails loudly if the correction broke it.

    python apps/entity_registry/declare_unique_identifiers.py --report
    python apps/entity_registry/declare_unique_identifiers.py --apply
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import asyncpg  # noqa: E402

from apps.entity_registry.migrate import get_pool  # noqa: E402
from vitalgraph.entity_registry.entity_registry_schema import EntityRegistrySchema  # noqa: E402

S = EntityRegistrySchema


async def _duplicates(conn, namespace: str, type_id: int, limit: int = 10):
    """(value, n_entities) held by more than one ACTIVE entity of the type."""
    return await conn.fetch(
        "SELECT ei.identifier_value AS value, count(DISTINCT ei.entity_id) AS n "
        "FROM entity_identifier ei JOIN entity e ON e.entity_id = ei.entity_id "
        "WHERE ei.identifier_namespace = $1 AND e.entity_type_id = $2 "
        "AND ei.status = 'active' "
        "GROUP BY ei.identifier_value HAVING count(DISTINCT ei.entity_id) > 1 "
        "ORDER BY 2 DESC, 1 LIMIT $3", namespace, type_id, limit)


async def _index_state(conn, name: str):
    """None (no index), True (valid: in force) or False (invalid: enforces nothing)."""
    return await conn.fetchval(
        "SELECT i.indisvalid FROM pg_class c JOIN pg_index i ON i.indexrelid = c.oid "
        "WHERE c.relname = $1", name)


async def _read_only_pool(prefix: str, use_ssl: bool):
    """A read-only pool from PREFIX_DB_HOST/_PORT/_NAME/_USER/_PASSWORD (for --report)."""
    import os
    import ssl as _ssl
    ctx = None
    if use_ssl:
        ctx = _ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = _ssl.CERT_NONE

    async def _init(conn):
        await conn.execute("SET default_transaction_read_only = on")
        await conn.execute("SET statement_timeout = '10min'")
    return await asyncpg.create_pool(
        host=os.environ[f"{prefix}_DB_HOST"], port=int(os.environ.get(f"{prefix}_DB_PORT", "5432")),
        database=os.environ[f"{prefix}_DB_NAME"], user=os.environ[f"{prefix}_DB_USER"],
        password=os.environ[f"{prefix}_DB_PASSWORD"], ssl=ctx, min_size=1, max_size=2,
        init=_init)


async def report(pool) -> int:
    declared = set(S.DECLARED_UNIQUE_IDENTIFIERS)
    async with pool.acquire() as conn:
        has_col = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE "
            "table_name = 'entity_identifier' AND column_name = 'entity_type_id')")
        if not has_col:
            print("entity_identifier.entity_type_id does not exist yet (run migrate.py); "
                  "'untyped' is shown as n/a.\n")
        pairs = await conn.fetch(
            "SELECT et.type_key, et.type_id, ei.identifier_namespace AS ns, count(*) AS n "
            "FROM entity_identifier ei JOIN entity e ON e.entity_id = ei.entity_id "
            "JOIN entity_type et ON et.type_id = e.entity_type_id "
            "WHERE ei.status = 'active' GROUP BY 1, 2, 3 ORDER BY 3, 1")
        print(f"{'type':12} {'namespace':22} {'rows':>9} {'untyped':>8} "
              f"{'dup values':>10}  declared")
        for p in pairs:
            dup_n = await conn.fetchval(
                "SELECT count(*) FROM (SELECT 1 FROM entity_identifier ei "
                "JOIN entity e ON e.entity_id = ei.entity_id "
                "WHERE ei.identifier_namespace = $1 AND e.entity_type_id = $2 "
                "AND ei.status = 'active' GROUP BY ei.identifier_value "
                "HAVING count(DISTINCT ei.entity_id) > 1) x", p['ns'], p['type_id'])
            untyped = (await conn.fetchval(
                "SELECT count(*) FROM entity_identifier WHERE identifier_namespace = $1 "
                "AND entity_type_id IS NULL", p['ns'])) if has_col else None
            state = await _index_state(conn, S.declared_index_name(p['type_key'], p['ns']))
            mark = {None: "", True: "IN FORCE", False: "INVALID INDEX"}[state]
            if (p['type_key'], p['ns']) in declared and state is not True:
                mark = "DECLARED, NOT BUILT"
            ut = f"{untyped:>8,}" if untyped is not None else f"{'n/a':>8}"
            print(f"{p['type_key']:12} {p['ns']:22} {p['n']:>9,} {ut} "
                  f"{dup_n:>10,}  {mark}")
    print("\nA pair can be declared when 'dup values' and 'untyped' are both 0.")
    return 0


async def apply(pool) -> int:
    failed = 0
    if not S.DECLARED_UNIQUE_IDENTIFIERS:
        print("No pairs declared (EntityRegistrySchema.DECLARED_UNIQUE_IDENTIFIERS is empty).")
        return 0
    async with pool.acquire() as conn:
        for type_key, ns in S.DECLARED_UNIQUE_IDENTIFIERS:
            type_id = await conn.fetchval(
                "SELECT type_id FROM entity_type WHERE type_key = $1", type_key)
            if type_id is None:
                print(f"✗ ({type_key}, {ns}): no entity type {type_key!r} in this database")
                failed += 1
                continue
            name = S.declared_index_name(type_key, ns)
            if await _index_state(conn, name) is True:
                print(f"✓ ({type_key}, {ns}): {name} already in force")
                continue
            untyped = await conn.fetchval(
                "SELECT count(*) FROM entity_identifier WHERE identifier_namespace = $1 "
                "AND entity_type_id IS NULL", ns)
            if untyped:
                print(f"✗ ({type_key}, {ns}): {untyped:,} row(s) have no entity_type_id and "
                      f"would escape the index — run backfill_identifier_entity_type.py first")
                failed += 1
                continue
            # A previous failed CONCURRENTLY build leaves an INVALID index that
            # `IF NOT EXISTS` would happily keep. Clear it first.
            if await _index_state(conn, name) is False:
                await conn.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
            try:
                await conn.execute(S.declared_index_sql(type_key, ns, type_id))
                print(f"✓ ({type_key}, {ns}): {name} built — declared unique, in force")
            except asyncpg.UniqueViolationError:
                await conn.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
                dups = await _duplicates(conn, ns, type_id)
                print(f"✗ ({type_key}, {ns}): the data contradicts the declaration; "
                      f"merge these first (showing up to 10):")
                for d in dups:
                    print(f"      {d['value']!r} held by {d['n']} entities")
                failed += 1
    return 1 if failed else 0


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--report", action="store_true")
    g.add_argument("--apply", action="store_true")
    ap.add_argument("--db", metavar="PREFIX",
                    help="--report only: read PREFIX_DB_HOST/_PORT/_NAME/_USER/_PASSWORD, "
                         "read-only, instead of the server config")
    ap.add_argument("--ssl", action="store_true", help="SSL for --db")
    a = ap.parse_args()
    if a.db and a.apply:
        ap.error("--db is for --report; --apply uses the server's own config")
    pool = await (_read_only_pool(a.db, a.ssl) if a.db else get_pool())
    try:
        return await (report(pool) if a.report else apply(pool))
    finally:
        await pool.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

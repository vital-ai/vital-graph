#!/usr/bin/env python3
"""Add `distance_metric` and `description` to a space's vector_index table.

`{space}_vector_index` registers each vector index: its name, dimensions,
provider, model, and — since a later schema revision — the distance metric it
was built with and a free-text description. Spaces created before that revision
have neither column. Measured on the local cluster 2026-08-14: **13 of 77
spaces**.

WHY THIS IS NOT `migrate_space_schema.py`

That script reconciles a space with the schema by creating missing tables and
recreating drifted DERIVED ones — tables rebuilt from rdf_quad, where the
definition is the only thing of value. `vector_index` is neither. It holds
REGISTRATIONS: the record of which indexes exist, at what dimension, from which
provider. Nothing can reconstruct that from the quad table, and dropping it
would orphan every `{space}_vec_*` data table it names.

So it needs this: an ALTER with a considered backfill, in the shape of
`migrate_edge_type_column.py`.

THE BACKFILL

`distance_metric` is NOT NULL, so every existing row needs a value, and the
value has to be the metric the index was ACTUALLY built with. Defaulting the
column would assert `cosine` for rows that might not be — and the registration
is what later code reads when it rebuilds or queries the index, so a wrong
value there is a wrong operator class, not a cosmetic mislabel.

The truth is recoverable: each registration names an index whose data table is
`{space}_vec_{index_name}`, carrying an HNSW index whose operator class states
the metric. This reads that back and inverts the map the schema uses to write
it (`vector_cosine_ops` -> `cosine`, and so on). Where no physical index is
found — a registration whose data table was never built — it falls back to the
schema default and REPORTS the row rather than quietly assuming.

Every affected table on the local cluster is currently EMPTY, so the derivation
path is untested against real rows here. It is written for deployed spaces,
which is where registrations actually exist, and reports per-row what it
decided so the result can be checked rather than trusted.

`description` is nullable and gets no backfill; absent is the honest value.

    python scripts/migrate_vector_index_columns.py --space wordnet_frames --dry-run
    python scripts/migrate_vector_index_columns.py --all
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from devtools.target import add_pg_arguments, describe_target  # noqa: E402

logger = logging.getLogger("migrate_vector_index_columns")

# Inverse of the map `create_vector_data_table_sql` uses when it BUILDS the
# index, so a value written by the schema reads back as the same name.
OPS_TO_METRIC = {
    "vector_cosine_ops": "cosine",
    "vector_l2_ops": "l2",
    "vector_ip_ops": "inner_product",
}

DEFAULT_METRIC = "cosine"


async def _has_column(conn, table: str, column: str) -> bool:
    return bool(await conn.fetchval(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=$1 AND column_name=$2",
        table, column))


async def _metric_from_physical_index(conn, space_id: str, index_name: str):
    """The metric an index was really built with, or None if it has no table."""
    from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema

    vec_table = SparqlSQLSchema.vec_table_name(space_id, index_name)
    defs = [r["indexdef"] for r in await conn.fetch(
        "SELECT indexdef FROM pg_indexes "
        "WHERE schemaname='public' AND tablename=$1", vec_table)]
    for d in defs:
        for ops, metric in OPS_TO_METRIC.items():
            if ops in d:
                return metric
    return None


async def migrate_space(conn, space_id: str, dry_run: bool = True) -> dict:
    table = f"{space_id}_vector_index"
    if not await conn.fetchval(
            "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename=$1",
            table):
        return {"space": space_id, "skipped": "no vector_index table"}

    need_metric = not await _has_column(conn, table, "distance_metric")
    need_desc = not await _has_column(conn, table, "description")
    if not (need_metric or need_desc):
        return {"space": space_id, "skipped": "already current"}

    rows = await conn.fetch(f"SELECT index_name FROM {table}")
    derived, defaulted = {}, []
    if need_metric:
        for r in rows:
            m = await _metric_from_physical_index(conn, space_id, r["index_name"])
            if m is None:
                defaulted.append(r["index_name"])
                m = DEFAULT_METRIC
            derived[r["index_name"]] = m

    summary = {
        "space": space_id,
        "registrations": len(rows),
        "add_distance_metric": need_metric,
        "add_description": need_desc,
        "derived": derived,
        "defaulted": defaulted,
    }
    if dry_run:
        return summary

    if need_metric:
        # NOT NULL with a DEFAULT is metadata-only on PG11+, so this does not
        # rewrite the table. The default then gets CORRECTED per row below for
        # any index that was actually built with something else.
        await conn.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS distance_metric "
            f"VARCHAR(20) NOT NULL DEFAULT '{DEFAULT_METRIC}'")
        for name, metric in derived.items():
            if metric != DEFAULT_METRIC:
                await conn.execute(
                    f"UPDATE {table} SET distance_metric = $1 WHERE index_name = $2",
                    metric, name)
    if need_desc:
        await conn.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS description TEXT")
    return summary


async def spaces_on(conn):
    return [r["tablename"][: -len("_vector_index")] for r in await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' "
        "AND tablename LIKE '%\\_vector\\_index' ORDER BY tablename")]


async def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--space")
    g.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    add_pg_arguments(ap)
    args = ap.parse_args()
    print(f"🗄  target: {describe_target(args)}", flush=True)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    import asyncpg
    conn = await asyncpg.connect(host=args.host, port=args.port,
                                 database=args.database, user=args.user,
                                 password=args.password or None)
    try:
        targets = await spaces_on(conn) if args.all else [args.space]
        changed = 0
        for sid in targets:
            s = await migrate_space(conn, sid, dry_run=args.dry_run)
            if s.get("skipped"):
                continue
            changed += 1
            cols = [c for c, need in (("distance_metric", s["add_distance_metric"]),
                                      ("description", s["add_description"])) if need]
            logger.info("%s%s: add %s (%d registration(s))",
                        "[dry-run] " if args.dry_run else "", sid,
                        ", ".join(cols), s["registrations"])
            for name, metric in s["derived"].items():
                logger.info("    %-30s -> %s", name, metric)
            if s["defaulted"]:
                logger.info("    %d registration(s) have no physical index; "
                            "defaulted to %s and NOT verified: %s",
                            len(s["defaulted"]), DEFAULT_METRIC,
                            ", ".join(s["defaulted"]))
        logger.info("\n%d space(s) %s of %d examined", changed,
                    "need migration" if args.dry_run else "migrated", len(targets))
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

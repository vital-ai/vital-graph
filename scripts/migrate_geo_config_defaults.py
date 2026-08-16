#!/usr/bin/env python3
"""Realign `{space}_geo_config` column DEFAULTs with the schema.

THE DRIFT. `geo_config` carries three TEXT[] columns whose DDL default names the
predicates and datatypes geo population recognises. Tables created under an
older schema kept that generation's defaults, and nothing has ever corrected
them: `ALTER TABLE ... ADD COLUMN` fixes a MISSING column, but a column that
exists with the wrong default is invisible to every check we run.

Measured on the local host cluster 2026-08-15: 16 of 77 `geo_config` tables
defaulted `lat_predicates` / `lon_predicates` to the two-URI `wgs84_pos` +
`haley-ai-kg` set, against the schema's single `vital-aimp` URI.

WHY `migrate_space_schema.py` DOES NOT SEE THIS. It selects `column_name` and
compares presence. A wrong type, a wrong nullability and a wrong default all
read as "matches". Its "0 spaces need changes" means NO MISSING COLUMNS, not
"agrees with the schema" — this script covers one specific gap in that, it does
not close it.

WHAT THIS IS AND IS NOT SAFE TO ASSUME. A DEFAULT applies to future INSERTs
that omit the column; it never rewrites existing rows, so this cannot change
data. Whether the SCHEMA or the DEPLOYED value is the correct one is a real
question and the answer here is neither obvious nor universal:

  * `lat_predicates` / `lon_predicates` — the deployed default is WIDER (two
    URIs vs one), so aligning to the schema NARROWS it. That is safe only
    because the sole insert path, `GeoConfigManager.ensure_config`, passes both
    columns explicitly from `DEFAULT_LAT_PREDICATES` / `DEFAULT_LON_PREDICATES`.
    The column default is dead metadata for these two: never exercised.
  * `geo_datatype_uris` — the opposite. `ensure_config` does NOT pass it, so
    this column's value comes from the DDL default on every insert. It is the
    one geo_config default that is load-bearing.

So this changes nothing observable today; it removes a false signal, and stops
`geo_datatype_uris` from silently inheriting a stale value on any space whose
table predates a change to it.

    python scripts/migrate_geo_config_defaults.py --all --dry-run
    python scripts/migrate_geo_config_defaults.py --all
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger("migrate_geo_config_defaults")

# The array columns whose DDL default this reconciles.
ARRAY_COLUMNS = ("geo_datatype_uris", "lat_predicates", "lon_predicates")


def schema_defaults() -> dict[str, str]:
    """The canonical `ARRAY[...]` default for each column, LIFTED from the DDL.

    Not restated here. There were already two copies of this CREATE TABLE in the
    tree and they had drifted from each other; a third copy is how that keeps
    happening. Reading the schema's own text means this cannot go stale.
    """
    from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema

    probe = "\x00SPACE\x00"
    tbl = f"{probe}_geo_config"
    stmts = [s for s in SparqlSQLSchema().create_space_tables_sql(probe)
             if f"{tbl} (" in s]
    if len(stmts) != 1:
        raise AssertionError(
            f"expected exactly one geo_config CREATE TABLE, found {len(stmts)}")
    out = {}
    for col in ARRAY_COLUMNS:
        m = re.search(rf"{col}\s+TEXT\[\]\s+NOT NULL DEFAULT (ARRAY\[[^\]]*\])",
                      stmts[0], re.S)
        if not m:
            raise AssertionError(f"could not lift the default for {col}")
        out[col] = " ".join(m.group(1).split())
    return out


def _uris(default_sql: str | None) -> tuple[str, ...]:
    """The URIs in a default, so `ARRAY['a'::text]` compares equal to `ARRAY['a']`.

    PostgreSQL renders a stored default with explicit casts and its own spacing;
    comparing the raw strings would report every table as drifted.
    """
    return tuple(re.findall(r"'([^']+)'", default_sql or ""))


async def survey_table(conn, table: str, want: dict[str, str]) -> dict[str, str]:
    """Columns whose default differs from the schema. Missing columns are skipped:
    adding one is a different operation, handled by migrate_space_schema."""
    rows = await conn.fetch(
        "SELECT column_name, column_default FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=$1 "
        "AND column_name = ANY($2::text[])", table, list(ARRAY_COLUMNS))
    return {r["column_name"]: r["column_default"] for r in rows
            if _uris(r["column_default"]) != _uris(want[r["column_name"]])}


async def geo_config_tables(conn) -> list[str]:
    return [r["tablename"] for r in await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' "
        "AND tablename LIKE '%\\_geo\\_config' ORDER BY tablename")]


async def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--space")
    g.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--host", default=os.environ.get("VG_PG_HOST", "localhost"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("VG_PG_PORT", "5432")))
    ap.add_argument("--database", default=os.environ.get("VG_PG_DATABASE", "sparql_sql_graph"))
    ap.add_argument("--user", default=os.environ.get("VG_PG_USER", "hadfield"))
    ap.add_argument("--password", default=os.environ.get("VG_PG_PASSWORD", ""))
    a = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    import asyncpg
    conn = await asyncpg.connect(host=a.host, port=a.port, database=a.database,
                                 user=a.user, password=a.password or None)
    try:
        want = schema_defaults()
        targets = (await geo_config_tables(conn) if a.all
                   else [f"{a.space}_geo_config"])
        drifted = 0
        for tbl in targets:
            diffs = await survey_table(conn, tbl, want)
            if not diffs:
                continue
            drifted += 1
            for col, actual in sorted(diffs.items()):
                if a.dry_run:
                    logger.info("[dry-run] %s.%s\n    actual: %s\n    schema: %s",
                                tbl, col, _uris(actual), _uris(want[col]))
                else:
                    # SET DEFAULT is catalogue-only: it applies to future
                    # INSERTs and never touches an existing row.
                    await conn.execute(
                        f"ALTER TABLE {tbl} ALTER COLUMN {col} SET DEFAULT {want[col]}")
            if not a.dry_run:
                logger.info("%s: realigned %s", tbl, ", ".join(sorted(diffs)))
        logger.info("\n%d table(s) %s of %d examined", drifted,
                    "need realignment" if a.dry_run else "realigned", len(targets))
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)

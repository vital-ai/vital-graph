#!/usr/bin/env python3
"""Install the database's `vitalgraph_*` SQL functions that are missing.

The pre-deploy step for a database initialised before a function existed.
`SparqlSQLAdmin.init_tables` and `perf_init_db` install every function in
`sparql_sql_admin.FUNCTIONS` on a NEW database; nothing installs one added
later on an existing database, so a release that adds one ships this step.
Today that is the `vitalgraph_cjk_*` family (`issues/333`), which an FTS index
needs before it may name the `cjk` language. Until the step runs, the server
REFUSES `cjk` with a message naming this script, so the order is safe: an
index is never created that cannot be written to.

Creates only what is MISSING (`to_regprocedure`). An existing function is left
alone unless `--replace` is given, because replacing a `cjk` function body
changes what every `cjk` index row should hold: after `--replace`, refresh
every `cjk` index (`vitalgraphsearchutil` `refresh-fts`).

Refuses a database whose encoding is not UTF8: the `cjk` functions call
`normalize`, which requires it.

Also prints a CENSUS of FTS indexes whose stored languages fail validation.
Before 333 an unknown language was accepted at creation and every write into
the index then failed silently inside auto-sync, so any such index is
unindexed today; this lists them (it changes nothing).

RUN AS THE APP ROLE, not the RDS master: objects the master creates are
unusable by `vitalgraph_user`. Idempotent.

DEFAULT IS A DRY RUN.

    python scripts/install_sql_functions.py
    python scripts/install_sql_functions.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

# The repo root ahead of site-packages: an installed copy resolves a different
# cluster (see `migrate_quad_ctx_pred_index.py`).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from devtools.target import add_pg_arguments, describe_target  # noqa: E402

logger = logging.getLogger("install_sql_functions")


async def missing_functions(conn):
    from vitalgraph.db.sparql_sql.sparql_sql_admin import FUNCTIONS
    out = []
    for sig, ddl in FUNCTIONS:
        if not await conn.fetchval("SELECT to_regprocedure($1) IS NOT NULL", sig):
            out.append((sig, ddl))
    return out


async def invalid_stored_languages(conn):
    """(space, index, languages, reason) for every FTS index that fails
    validation as the database stands now."""
    from vitalgraph.db.sparql_sql.fts_languages import validate_fts_languages
    from vitalgraph.db.sparql_sql.space_names import space_id_for_prefix
    out = []
    for r in await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
            "AND tablename LIKE '%\\_fts\\_index' ORDER BY 1"):
        table = r["tablename"]
        space = space_id_for_prefix(table[: -len("_fts_index")])
        for row in await conn.fetch(f"SELECT index_name, languages FROM {table}"):
            langs = list(row["languages"] or [])
            reason = await validate_fts_languages(conn, langs)
            if reason:
                out.append((space, row["index_name"], langs, reason))
    return out


async def main() -> int:
    from vitalgraph.db.sparql_sql.sparql_sql_admin import FUNCTIONS
    from vitalgraph.db.sparql_sql.space_storage_key import load_storage_keys
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="create what is missing (default is a dry run)")
    ap.add_argument("--replace", action="store_true",
                    help="also CREATE OR REPLACE functions that exist; "
                         "refresh every cjk index afterwards")
    add_pg_arguments(ap)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(f"\U0001F5C4  target: {describe_target(a)}", flush=True)
    logger.info("%s", "APPLY" if a.apply else "DRY RUN")

    import asyncpg
    conn = await asyncpg.connect(host=a.host, port=a.port, database=a.database,
                                 user=a.user, password=a.password or None)
    try:
        encoding = await conn.fetchval("SHOW server_encoding")
        if encoding != "UTF8":
            logger.error("refusing: server_encoding is %s, the cjk functions "
                         "need UTF8 (`normalize`)", encoding)
            return 2
        logger.info("connected as %s", await conn.fetchval("SELECT current_user"))

        todo = list(FUNCTIONS) if a.replace else await missing_functions(conn)
        if not todo:
            logger.info("all %d functions present", len(FUNCTIONS))
        for sig, ddl in todo:
            logger.info("%s: %s", sig, "replace" if a.replace else "create")
            if a.apply:
                # One transaction per function, in dependency order: a
                # failure leaves the ones before it installed and says which.
                async with conn.transaction():
                    await conn.execute(ddl)
        if todo and not a.apply:
            logger.info("Dry run. Re-run with --apply.")

        await load_storage_keys(conn)
        bad = await invalid_stored_languages(conn)
        if bad:
            logger.warning("\n%d FTS index(es) with languages that fail "
                           "validation (nothing is indexed into them):", len(bad))
            for space, index, langs, reason in bad:
                logger.warning("  %s / %s  %s  — %s", space, index, langs, reason)
        else:
            logger.info("census: every stored FTS language list is valid")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

#!/usr/bin/env python3
"""Install the per-space write log (`vitalgraph/db/sparql_sql/write_log.py`)
and the database's `pattern_verdict` table (`pattern_verdict.py`).

Creates, where missing, `{space}_write_log`, `{space}_wlog_capture()` and the
trigger `trg_{space}_wlog` on `{space}_rdf_quad`, in ONE transaction per space,
table before trigger: a trigger without its table would fail every write to
the space.

Also REPAIRS: a space whose table exists but whose trigger is gone or disabled
(a partition migration recreates `rdf_quad` without triggers) gets the trigger
back. Until it does, nothing reads the log as vouching for that space.

CREATE TRIGGER takes a SHARE ROW EXCLUSIVE lock on `rdf_quad` for an instant:
it waits for in-flight writes and blocks new ones only while the catalog
changes. Idempotent: a space with everything is skipped.

RUN AS THE TABLES' OWNER, which on production is the app role, not the RDS
master: objects the master creates are unreadable by `vitalgraph_user`.

DEFAULT IS A DRY RUN.

    python scripts/install_write_log.py --all
    python scripts/install_write_log.py --space uw_prodshape2 --apply
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
from vitalgraph.db.sparql_sql.space_names import space_id_for_prefix  # noqa: E402
from vitalgraph.db.sparql_sql.space_storage_key import load_storage_keys  # noqa: E402

logger = logging.getLogger("install_write_log")


async def main() -> int:
    from vitalgraph.db.sparql_sql import pattern_verdict, write_log
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--space")
    g.add_argument("--all", action="store_true")
    ap.add_argument("--apply", action="store_true",
                    help="create what is missing (default is a dry run)")
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
            "SELECT regexp_replace(tablename, '_rdf_quad$', '') FROM pg_tables "
            "WHERE schemaname='public' AND tablename LIKE '%\\_rdf\\_quad' "
            "ORDER BY 1")] if a.all else [a.space])
        if not await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", pattern_verdict.TABLE):
            logger.info("database: create %s", pattern_verdict.TABLE)
            if a.apply:
                for stmt in pattern_verdict.CREATE_SQL:
                    await conn.execute(stmt)
        pending = done = 0
        for sp in spaces:
            if await write_log.installed(conn, sp):
                continue
            pending += 1
            logger.info("%s: install the write log", sp)
            if a.apply:
                async with conn.transaction():
                    for stmt in write_log.create_sql(sp):
                        await conn.execute(stmt)
                done += 1
        logger.info("\n%d of %d space(s) %s", done if a.apply else pending,
                    len(spaces), "installed" if a.apply else "need it")
        if not a.apply and pending:
            logger.info("Dry run. Re-run with --apply.")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

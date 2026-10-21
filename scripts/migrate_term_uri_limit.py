#!/usr/bin/env python3
"""Add the URI length limit to existing term tables (issues/283).

New spaces get `ck_<space>_term_uri_len` from `create_space_tables_sql`:

    CHECK (term_type <> 'U' OR octet_length(term_text) <= 1024)

It is the backstop for writes that intern terms in SQL alone; the Python
writers refuse an over-long URI before any SQL runs (`uri_limit.check_uri`).
This adds the same constraint to an existing space's term table:

  1. ADD ... NOT VALID -- a catalog change, under a brief ACCESS EXCLUSIVE lock;
     from here every NEW row is checked.
  2. VALIDATE -- scans the existing rows under SHARE UPDATE EXCLUSIVE, which
     does not block reads or writes. A space holding a URI over the limit fails
     here and is reported with its longest; the NOT VALID constraint stays, so
     new writes are still checked, and the space is listed for a decision.

Either order of code and schema is correct: old code on a migrated space just
gets the database's refusal instead of the Python one.

Idempotent -- a space whose constraint exists and is validated is skipped.

RUN AS THE TABLES' OWNER. ALTER TABLE requires it, and on production that is
the app role, not the RDS master.

DEFAULT IS A DRY RUN.

    python scripts/migrate_term_uri_limit.py --all
    python scripts/migrate_term_uri_limit.py --space lead_prod --apply
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
from vitalgraph.db.sparql_sql.space_names import space_prefix  # noqa: E402

logger = logging.getLogger("migrate_term_uri_limit")


async def constraint_state(conn, space_id: str):
    """None (absent), False (NOT VALID) or True (validated)."""
    from vitalgraph.db.sparql_sql.uri_limit import uri_limit_constraint_name
    return await conn.fetchval(
        "SELECT convalidated FROM pg_constraint WHERE conname = $1",
        uri_limit_constraint_name(space_id))


async def apply_space(conn, space_id: str) -> tuple:
    """`(ok, seconds, detail)`."""
    from vitalgraph.db.sparql_sql.uri_limit import (
        MAX_URI_BYTES, uri_limit_check_sql, uri_limit_constraint_name)
    name = uri_limit_constraint_name(space_id)
    t = f"{space_prefix(space_id)}_term"
    t0 = time.monotonic()
    if await constraint_state(conn, space_id) is None:
        await conn.execute(
            f"ALTER TABLE {t} ADD CONSTRAINT {name} "
            f"CHECK ({uri_limit_check_sql()}) NOT VALID")
    try:
        async with conn.transaction():
            # Production's parameter group sets 60 s; the scan of a large term
            # table takes longer. LOCAL so it ends with the transaction.
            await conn.execute("SET LOCAL statement_timeout = 0")
            await conn.execute(f"ALTER TABLE {t} VALIDATE CONSTRAINT {name}")
    except Exception as e:
        longest = await conn.fetchval(
            f"SELECT max(octet_length(term_text)) FROM {t} WHERE term_type = 'U'")
        return False, time.monotonic() - t0, (
            f"VALIDATE failed ({type(e).__name__}): longest URI {longest} bytes, "
            f"limit {MAX_URI_BYTES}; NOT VALID constraint kept for new writes")
    return True, time.monotonic() - t0, ""


async def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--space")
    g.add_argument("--all", action="store_true")
    ap.add_argument("--apply", action="store_true",
                    help="add and validate the constraint (default is a dry run)")
    add_pg_arguments(ap)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(f"\U0001F5C4  target: {describe_target(a)}", flush=True)
    logger.info("%s", "APPLY" if a.apply else "DRY RUN")

    import asyncpg
    conn = await asyncpg.connect(host=a.host, port=a.port, database=a.database,
                                 user=a.user, password=a.password or None)
    failed = []
    try:
        spaces = ([r[0] for r in await conn.fetch(
            "SELECT regexp_replace(tablename, '_rdf_quad$', '') FROM pg_tables "
            "WHERE schemaname='public' AND tablename LIKE '%\\_rdf\\_quad' "
            "ORDER BY 1")] if a.all else [a.space])
        pending = done = 0
        for sp in spaces:
            state = await constraint_state(conn, sp)
            if state is True:
                continue
            pending += 1
            logger.info("%s: %s", sp, "validate the existing NOT VALID constraint"
                        if state is False else "add and validate the constraint")
            if a.apply:
                ok, secs, detail = await apply_space(conn, sp)
                if ok:
                    done += 1
                    logger.info("    done in %.1fs", secs)
                else:
                    failed.append(sp)
                    logger.info("    %s", detail)
        logger.info("\n%d of %d space(s) %s", done if a.apply else pending,
                    len(spaces), "migrated" if a.apply else "need migration")
        if failed:
            logger.info("NOT validated: %s", ", ".join(failed))
        if not a.apply and pending:
            logger.info("Dry run. Re-run with --apply.")
    finally:
        await conn.close()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

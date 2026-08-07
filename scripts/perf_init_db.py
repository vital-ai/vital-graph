#!/usr/bin/env python
"""Create the admin/registry schema in the vg-test database.

Why this exists: `docker-compose.test.yml` creates the 10 admin tables (install,
space, graph, user, process, agent_*) via the **app** service's `VG_AUTO_INIT`.
`scripts/run-perf-tests.sh` only starts `postgres` + `sparql-compiler`, so on a
clean stack those tables never exist — and every perf test that creates a real
space (`SparqlSQLSchema.create_space`, the space manager, or `drop_space` in
teardown) dies with `relation "space" does not exist`.

Schema is created only by an explicit action, never as a side effect of a data
path, so the runner calls this step outright rather than having the suite
ensure-create tables behind the scenes.

Idempotent: safe to run against an already-initialized database.

    VG_TEST_PG_PORT=5433 VG_TEST_PG_PASSWORD=testpass python scripts/perf_init_db.py
"""

from __future__ import annotations

import asyncio
import os
import sys

import asyncpg

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema  # noqa: E402
from vitalgraph.db.sparql_sql.sparql_sql_admin import _VITALGRAPH_TERM_UUID_DDL  # noqa: E402

EXTENSIONS = ["pg_trgm", "pgcrypto", "vector", "postgis"]


async def connect_with_retry(timeout_s: int = 60):
    """Connect over TCP, retrying until the server is actually serving.

    The runner's readiness probe runs `psql` *inside* the container over the unix
    socket, which goes green before the published TCP port is accepting — and the
    entrypoint also bounces the server once during init. Retrying here over the
    same TCP path the tests use is what actually proves readiness.
    """
    params = dict(
        host=os.environ.get("VG_TEST_PG_HOST", "localhost"),
        port=int(os.environ.get("VG_TEST_PG_PORT", "5432")),
        database=os.environ.get("VG_TEST_PG_DATABASE", "sparql_sql_graph"),
        user=os.environ.get("VG_TEST_PG_USER", "postgres"),
        password=os.environ.get("VG_TEST_PG_PASSWORD", ""),
    )
    deadline = timeout_s
    last: Exception | None = None
    while deadline > 0:
        try:
            return await asyncpg.connect(**params)
        except Exception as exc:                       # connreset / db missing / refused
            last = exc
            await asyncio.sleep(1)
            deadline -= 1
    raise SystemExit(f"❌ could not connect to {params['host']}:{params['port']}"
                     f"/{params['database']} within {timeout_s}s: {last}")


async def main() -> int:
    conn = await connect_with_retry()
    try:
        for ext in EXTENSIONS:
            try:
                await conn.execute(f"CREATE EXTENSION IF NOT EXISTS {ext}")
            except Exception as exc:                      # optional extensions
                print(f"  ⚠️  extension {ext}: {exc}")

        await conn.execute(_VITALGRAPH_TERM_UUID_DDL)

        schema = SparqlSQLSchema()
        for stmt in schema.create_admin_tables_sql():
            await conn.execute(stmt)
        for stmt in schema.create_admin_indexes_sql():
            await conn.execute(stmt)
        for stmt in schema.get_admin_seed_sql():
            await conn.execute(stmt)

        present = await conn.fetchval(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = ANY($1)",
            list(SparqlSQLSchema.ADMIN_TABLE_NAMES))
        print(f"✅ admin schema ready ({present}/{len(SparqlSQLSchema.ADMIN_TABLE_NAMES)} tables)")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

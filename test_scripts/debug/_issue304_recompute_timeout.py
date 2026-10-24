"""issues/304 — does the object_count migration's recompute survive a 60 s ceiling?

Runs `migrate_space` from the migration script, the HEAD copy (unfixed) and the
working-tree copy (fixed), on a connection whose SESSION DEFAULT is
`statement_timeout = 60s`, which is how production's parameter group reaches it.
No database-level setting is changed.

The script skips a space whose `object_count` is already filled, and the vg
stack's are. Rather than NULL them, a proxy answers that one probe "not filled",
so the recompute path runs. The recompute rewrites the stats tables from the
quads, as a maintenance cycle would; a cancelled one rolls back.

    SPACE=<space> /opt/homebrew/anaconda3/envs/vital-graph/bin/python \
        test_scripts/debug/_issue304_recompute_timeout.py [unfixed|fixed|both]
"""
import asyncio
import importlib.util
import os
import subprocess
import sys
import tempfile
import time

import asyncpg

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
from vitalgraph.db.sparql_sql.space_storage_key import load_storage_keys  # noqa: E402

SCRIPT = "scripts/migrate_pred_stats_object_count.py"
SPACE = os.environ["SPACE"]
CEILING = os.environ.get("CEILING", "60s")
DSN = dict(host="localhost", port=int(os.environ.get("VG_TEST_PG_PORT", 5433)),
           user="postgres", password=os.environ.get("VG_TEST_PG_PASSWORD", "testpass"),
           database="sparql_sql_graph")


def load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class NotFilled:
    """Delegates to the connection, except the script's "already filled" probe."""

    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    async def fetchval(self, sql, *args, **kw):
        if "bool_and(object_count IS NOT NULL)" in sql:
            return False
        return await self._conn.fetchval(sql, *args, **kw)


async def run(label: str, mod) -> None:
    conn = await asyncpg.connect(**DSN, server_settings={"statement_timeout": CEILING})
    try:
        await load_storage_keys(conn)
        print(f"{label}: session statement_timeout = {await conn.fetchval('SHOW statement_timeout')}",
              flush=True)
        t0 = time.monotonic()
        try:
            out = await mod.migrate_space(NotFilled(conn), SPACE, dry_run=False, recompute=True)
            print(f"{label}: OK in {time.monotonic() - t0:.1f}s -> {out}", flush=True)
        except Exception as exc:
            print(f"{label}: FAILED after {time.monotonic() - t0:.1f}s -> "
                  f"{type(exc).__name__}: {str(exc).splitlines()[0]}", flush=True)
        print(f"{label}: session statement_timeout after = "
              f"{await conn.fetchval('SHOW statement_timeout')}", flush=True)
    finally:
        await conn.close()


async def main(which: str) -> None:
    with tempfile.TemporaryDirectory() as d:
        head = os.path.join(d, "migrate_head.py")
        with open(head, "w") as f:
            f.write(subprocess.check_output(["git", "-C", ROOT, "show", f"HEAD:{SCRIPT}"], text=True))
        if which in ("unfixed", "both"):
            await run("unfixed", load("migrate_head", head))
        if which in ("fixed", "both"):
            await run("fixed", load("migrate_fixed", os.path.join(ROOT, SCRIPT)))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "both"))

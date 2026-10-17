"""Write latency at the DATABASE, every statement timed, nothing kept — issues/271, 273.

Runs the real bulk write path (`add_rdf_quads_batch_bulk`, the write step of an
entity upsert) for a UW-decision-shaped graph (~993 objects, ~6,300 quads) INSIDE
A TRANSACTION THAT IS ALWAYS ROLLED BACK. Nothing persists — no quads, terms,
derived rows or graph rows — yet the database does the real work: index
maintenance, WAL (full-page images included), derived-table syncs. So it can be
pointed at a production space to see what a write costs there, without the
API, the network hop to it, or any cleanup.

Per run it prints: total, time inside SQL, the statement count, the slowest
statements with an estimate of their SERVER time (client time minus the
measured round trip), the `BULK insert` phase line, WAL bytes written, and the
age of the last checkpoint — WAL per write falls as that age grows (a page's
first change after a checkpoint logs the whole page), so compare runs at
similar ages, e.g. before and after a `checkpoint_timeout` change.

    PGPASSWORD=... python test_scripts/perf/direct_write_probe.py \\
        --host <rds host> --database vitalgraphdb --user vitalgraph_user \\
        --space <space> --runs 5 --gap 20

Writes and rolls back; the rollback leaves dead tuples for VACUUM, nothing more.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import statistics
import sys
import time
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "test_scripts", "perf"))


class _Timed:
    """An asyncpg connection whose statements are timed."""

    def __init__(self, conn):
        self._c = conn
        self.log = []

    def __getattr__(self, name):
        return getattr(self._c, name)

    def _wrap(name):
        async def call(self, sql, *args, **kw):
            t0 = time.perf_counter()
            try:
                return await getattr(self._c, name)(sql, *args, **kw)
            finally:
                self.log.append(((time.perf_counter() - t0) * 1000,
                                 re.sub(r"\s+", " ", sql).strip()[:110]))
        return call

    execute = _wrap("execute")
    fetch = _wrap("fetch")
    fetchval = _wrap("fetchval")
    fetchrow = _wrap("fetchrow")

    async def executemany(self, sql, args, **kw):
        t0 = time.perf_counter()
        try:
            return await self._c.executemany(sql, args, **kw)
        finally:
            self.log.append(((time.perf_counter() - t0) * 1000,
                             "EXECUTEMANY " + re.sub(r"\s+", " ", sql).strip()[:98]))


def _lsn(text: str) -> int:
    hi, lo = text.split("/")
    return (int(hi, 16) << 32) + int(lo, 16)


async def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=5432)
    ap.add_argument("--database", required=True)
    ap.add_argument("--user", required=True)
    ap.add_argument("--space", required=True)
    ap.add_argument("--graph", default=None, help="default urn:<space>")
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--gap", type=float, default=20.0, help="seconds between runs")
    ap.add_argument("--top", type=int, default=8)
    a = ap.parse_args()
    password = os.environ.get("PGPASSWORD")
    if not password:
        raise SystemExit("set PGPASSWORD")

    phase_lines = []

    class _Grab(logging.Handler):
        def emit(self, r):
            m = r.getMessage()
            if "BULK insert" in m:
                phase_lines.append(m)

    logging.basicConfig(level=logging.WARNING)
    lg = logging.getLogger("vitalgraph.db.sparql_sql.sparql_sql_space_impl")
    lg.setLevel(logging.INFO)
    lg.addHandler(_Grab())

    from rdflib import URIRef
    from write_latency_bench import entity_graph
    from vitalgraph.db.sparql_sql.sparql_sql_space_impl import SparqlSQLSpaceImpl

    impl = SparqlSQLSpaceImpl(
        postgresql_config={"host": a.host, "port": a.port, "database": a.database,
                           "username": a.user, "password": password,
                           "min_pool_size": 1, "max_pool_size": 6},
        sidecar_config={"url": "http://localhost:7070"})
    assert await impl.connect(), "could not connect"
    graph = URIRef(a.graph or f"urn:{a.space}")
    pool = impl.db_impl.connection_pool
    try:
        async with pool.acquire() as c:
            who = await c.fetchval("SELECT current_user || '@' || inet_server_addr() || "
                                   "' ' || current_database()")
            rtts = []
            for _ in range(7):
                t0 = time.perf_counter(); await c.fetchval("SELECT 1")
                rtts.append((time.perf_counter() - t0) * 1000)
        rtt = statistics.median(rtts)
        print(f"target {who}, space {a.space}; round trip median {rtt:.1f} ms "
              f"(server time ≈ statement time − {rtt:.1f} ms)")

        for i in range(a.runs):
            ent, objs = entity_graph(f"probe{uuid.uuid4().hex[:10]}", 4000 + i)
            for o in objs:
                o.kGGraphURI = ent
            quads = [(s, p, o, graph) for ob in objs for (s, p, o) in ob.to_triples()]
            async with pool.acquire() as raw:
                tr = raw.transaction()
                await tr.start()
                try:
                    # Age of the last checkpoint: WAL per write depends on it
                    # (first change to a page after a checkpoint logs the whole
                    # page), so runs are only comparable at similar ages.
                    try:
                        ck_age = await raw.fetchval(
                            "SELECT EXTRACT(EPOCH FROM now() - checkpoint_time)::int "
                            "FROM pg_control_checkpoint()")
                    except Exception:
                        ck_age = None
                    l0 = _lsn(await raw.fetchval("SELECT pg_current_wal_insert_lsn()::text"))
                    c = _Timed(raw)
                    t0 = time.perf_counter()
                    await impl.add_rdf_quads_batch_bulk(a.space, quads, connection=c)
                    total = (time.perf_counter() - t0) * 1000
                    l1 = _lsn(await raw.fetchval("SELECT pg_current_wal_insert_lsn()::text"))
                finally:
                    await tr.rollback()            # ALWAYS: nothing is kept
            sql_ms = sum(ms for ms, _ in c.log)
            print(f"\n=== run {i + 1}: {len(quads)} quads, {total:.0f} ms total, "
                  f"{len(c.log)} statements, {sql_ms:.0f} ms in SQL "
                  f"(≈ {sql_ms - rtt * len(c.log):.0f} ms server), "
                  f"WAL {(l1 - l0) / 1e6:.1f} MB, checkpoint age "
                  f"{'?' if ck_age is None else f'{ck_age}s'} — rolled back")
            if phase_lines:
                print("  " + re.sub(r".*BULK insert: ", "", phase_lines[-1])[:330])
            for ms, sql in sorted(c.log, key=lambda x: -x[0])[:a.top]:
                print(f"  {ms:7.1f} ms (≈{max(ms - rtt, 0):6.1f} server)  {sql}")
            if i + 1 < a.runs:
                await asyncio.sleep(a.gap)
    finally:
        await impl.disconnect()


if __name__ == "__main__":
    asyncio.run(main())

"""Multi-process write scaling, for the issues/115 ceiling.

The in-process harness could not answer this. It drove every writer from one
event loop, so term classification and dedup — all Python — serialised before
Postgres was involved, and the 1.67x / 1.97x it produced measured the client.

Each writer here is its own OS process. Workers report their own start and end
timestamps so process startup stays out of the number, and the parent samples
pg_stat_activity throughout so waiting can be attributed rather than inferred.

    python test_scripts/perf/write_scaling.py            # 1,2,4,8 x on/off
    python test_scripts/perf/write_scaling.py --worker … # internal
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rdflib import URIRef, Literal          # noqa: E402

H = "http://vital.ai/ontology/haley-ai-kg#"
V = "http://vital.ai/ontology/vital-core#"
BATCH = 1500          # subjects per batch; 3 quads each
ROUNDS = 4            # batches per worker

PG = dict(host=os.getenv("VG_PG_HOST", "localhost"),
          port=int(os.getenv("VG_PG_PORT", "5433")),
          database=os.getenv("VG_PG_DB", "sparql_sql_graph"),
          username=os.getenv("VG_PG_USER", "postgres"),
          password=os.getenv("VG_PG_PASS", "testpass"))


def _quads(worker, rnd):
    """Shaped like real ingest: every subject carries the two hot predicates."""
    g = URIRef("urn:scale:g")
    out = []
    for i in range(BATCH):
        s = URIRef(f"urn:scale:w{worker}:r{rnd}:s{i}")
        out += [(s, URIRef(f"{V}vitaltype"), URIRef(f"{H}KGEntity"), g),
                (s, URIRef(f"{H}hasKGGraphURI"), URIRef("urn:scale:root"), g),
                (s, URIRef(f"{H}hasName"), Literal(f"n{worker}_{i}"), g)]
    return out


async def _impl():
    from vitalgraph.db.sparql_sql.sparql_sql_space_impl import SparqlSQLSpaceImpl
    impl = SparqlSQLSpaceImpl(
        postgresql_config={**PG, "min_pool_size": 1, "max_pool_size": 3},
        sidecar_config={"url": os.getenv("VG_SIDECAR", "http://localhost:7071")})
    await impl.connect()
    return impl


async def worker_main(space_id, worker_id, stats_on):
    if not stats_on:
        from vitalgraph.db.sparql_sql import sync_stats_tables

        async def _noop(conn, sid, rows):
            return 0
        sync_stats_tables.sync_stats_after_insert = _noop

    impl = await _impl()
    try:
        batches = [_quads(worker_id, r) for r in range(ROUNDS)]   # build first
        t0 = time.time()
        for b in batches:
            await impl.add_rdf_quads_batch_bulk(space_id, b)
        t1 = time.time()
    finally:
        await impl.disconnect()
    print(json.dumps({"start": t0, "end": t1, "quads": ROUNDS * BATCH * 3}))


async def sample_locks(stop, out):
    import asyncpg
    conn = await asyncpg.connect(host=PG["host"], port=PG["port"],
                                 user=PG["username"], password=PG["password"],
                                 database=PG["database"])
    try:
        while not stop.is_set():
            rows = await conn.fetch(
                "SELECT wait_event_type, wait_event FROM pg_stat_activity "
                "WHERE state = 'active' AND pid <> pg_backend_pid()")
            for r in rows:
                # NULL wait_event_type means the backend is ON CPU, not waiting.
                # Recorded as such, so an empty wait breakdown can be told apart
                # from a sampler that is seeing nothing at all.
                out.append((r["wait_event_type"] or "RUNNING",
                            r["wait_event"] or "cpu"))
            await asyncio.sleep(0.05)
    finally:
        await conn.close()


async def run_cell(sm, workers, stats_on):
    space_id = f"inttest_scale_{uuid.uuid4().hex[:8]}"
    await sm.create_space_with_tables(space_id, space_id)
    try:
        env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2])}
        args = [sys.executable, __file__, "--worker", "--space", space_id,
                "--stats", "on" if stats_on else "off"]
        stop = asyncio.Event()
        samples: list = []
        sampler = asyncio.create_task(sample_locks(stop, samples))

        procs = [subprocess.Popen(args + ["--id", str(i)], env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                 for i in range(workers)]
        # communicate() BLOCKS, so it has to leave the event loop free or the
        # sampler never gets scheduled and reports a confident zero from no
        # samples at all.
        def _collect(proc):
            out, _ = proc.communicate()
            return out.decode()

        outs = await asyncio.gather(*[asyncio.to_thread(_collect, p) for p in procs])
        results = []
        for out in outs:
            line = [l for l in out.splitlines() if l.startswith("{")]
            if line:
                results.append(json.loads(line[-1]))
        stop.set()
        await sampler

        if len(results) != workers:
            return None
        span = max(r["end"] for r in results) - min(r["start"] for r in results)
        total = sum(r["quads"] for r in results)
        locks = sum(1 for t, _ in samples if t == "Lock")
        from collections import Counter
        top = Counter(f"{t}:{e}" for t, e in samples).most_common(3)
        return {"rate": total / span, "span": span, "top": top,
                "lock_samples": locks, "samples": len(samples)}
    finally:
        await sm.delete_space_with_tables(space_id)


async def parent_main():
    from vitalgraph.space.space_manager import SpaceManager
    impl = await _impl()
    sm = SpaceManager(db_impl=impl.db_impl, space_backend=impl)
    try:
        print(f"  {ROUNDS} batches x {BATCH*3} quads per worker\n")
        print("  stats | procs | quads/s   | wall   | scaling | locks    | top waits")
        for stats_on in (True, False):
            base = None
            for w in (1, 2, 4, 8):
                r = await run_cell(sm, w, stats_on)
                if not r:
                    print(f"   {'on ' if stats_on else 'off'}  |   {w}   | worker failed")
                    continue
                base = base or r["rate"]
                pct = (100.0 * r["lock_samples"] / r["samples"]) if r["samples"] else 0
                top = ", ".join(f"{k} x{v}" for k, v in r["top"]) or "nothing"
                print(f"   {'on ' if stats_on else 'off'}  |   {w}   | {r['rate']:9,.0f} "
                      f"| {r['span']:5.2f}s |  {r['rate']/base:.2f}x  | "
                      f"Lock:{r['lock_samples']:3d}  | {top}")
            print()
    finally:
        await impl.disconnect()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--worker", action="store_true")
    ap.add_argument("--space")
    ap.add_argument("--id", type=int, default=0)
    ap.add_argument("--stats", default="on")
    a = ap.parse_args()
    if a.worker:
        asyncio.run(worker_main(a.space, a.id, a.stats == "on"))
    else:
        asyncio.run(parent_main())

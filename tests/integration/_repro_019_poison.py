"""Throwaway repro for issue 019 defense-in-depth follow-up.

Drives the REAL code paths (execute_sparql_update + add_rdf_quads_batch +
query_quads) under a SMALL pool with sustained concurrent writers colliding on
shared terms/graph URIs, to try to trigger a poisoned-connection empty-read /
pool stall on the CURRENT code.

Run:
  VG_TEST_PG_HOST=localhost VG_TEST_PG_PORT=5433 \
  VG_TEST_PG_DATABASE=sparql_sql_graph VG_TEST_PG_USER=postgres \
  VG_TEST_PG_PASSWORD=testpass VG_TEST_SIDECAR_URL=http://localhost:7071 \
  python tests/integration/_repro_019_poison.py
"""
from __future__ import annotations

import asyncio
import os
import time

from rdflib import URIRef, Literal

PG = dict(
    host=os.environ["VG_TEST_PG_HOST"],
    port=int(os.environ["VG_TEST_PG_PORT"]),
    database=os.environ["VG_TEST_PG_DATABASE"],
    username=os.environ["VG_TEST_PG_USER"],
    password=os.environ["VG_TEST_PG_PASSWORD"],
    min_pool_size=1,
    max_pool_size=3,
    command_timeout=15,
)
SIDECAR = {"url": os.environ["VG_TEST_SIDECAR_URL"]}

GRAPH = "urn:repro019:graph"
PRED = "http://vital.ai/ontology/vital-core#hasName"
TYPE = "http://vital.ai/ontology/vital-core#VITAL_Node"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"


def _subject_query(subject: str) -> str:
    return (
        f"SELECT ?s ?p ?o WHERE {{ GRAPH <{GRAPH}> {{ ?s ?p ?o }} "
        f"FILTER(?s = <{subject}>) }} LIMIT 10"
    )


async def main() -> int:
    from vitalgraph.db.sparql_sql.sparql_sql_space_impl import SparqlSQLSpaceImpl
    from vitalgraph.space.space_manager import SpaceManager

    impl = SparqlSQLSpaceImpl(postgresql_config=PG, sidecar_config=SIDECAR)
    assert await impl.connect(), "connect failed"

    sm = SpaceManager(db_impl=getattr(impl, "db_impl", None), space_backend=impl)
    space_id = "repro019_poison"
    try:
        await sm.delete_space_with_tables(space_id)
    except Exception:
        pass
    assert await sm.create_space_with_tables(space_id, space_id)

    failures: list = []
    misses: list = []
    stalls: list = []

    # Writers via SPARQL UPDATE all share PRED + GRAPH + rdf:type/TYPE terms.
    async def sparql_writer(wid: int):
        for i in range(20):
            subj = f"urn:repro019:s:{wid}:{i}"
            update = (
                f"INSERT DATA {{ GRAPH <{GRAPH}> {{ "
                f'<{subj}> <{RDF_TYPE}> <{TYPE}> . '
                f'<{subj}> <{PRED}> "val-{wid}-{i}" . }} }}'
            )
            ok = await impl.execute_sparql_update(space_id, update)
            if not ok:
                failures.append(("sparql", subj))
                continue
            rows = await impl.query_quads(space_id, _subject_query(subj))
            if len(rows) == 0:
                misses.append(("sparql", subj))

    # REST-path writers (add_rdf_quads_batch) also colliding on the same shared terms.
    async def rest_writer(wid: int):
        for i in range(20):
            subj = f"urn:repro019:r:{wid}:{i}"
            quads = [
                (URIRef(subj), URIRef(RDF_TYPE), URIRef(TYPE), URIRef(GRAPH)),
                (URIRef(subj), URIRef(PRED), Literal(f"rv-{wid}-{i}"), URIRef(GRAPH)),
            ]
            n = await impl.add_rdf_quads_batch(space_id, quads)
            if n == 0:
                failures.append(("rest", subj))
                continue
            rows = await impl.query_quads(space_id, _subject_query(subj))
            if len(rows) == 0:
                misses.append(("rest", subj))

    # Independent readers that must not hang / go empty on committed data.
    done = asyncio.Event()

    async def reader():
        # probe a fixed committed subject repeatedly + generic list read
        while not done.is_set():
            try:
                t0 = time.monotonic()
                await asyncio.wait_for(
                    impl.query_quads(
                        space_id,
                        f"SELECT ?s ?p ?o WHERE {{ GRAPH <{GRAPH}> {{ ?s ?p ?o }} }} LIMIT 5",
                    ),
                    timeout=20,
                )
                dt = time.monotonic() - t0
                if dt > 10:
                    stalls.append(dt)
            except asyncio.TimeoutError:
                stalls.append(999)
            await asyncio.sleep(0)

    # Concurrent deleters that stress edge/frame sync + orphan cleanup on the
    # same shared subjects (INSERT then DELETE DATA racing).
    async def sparql_deleter(wid: int):
        for i in range(20):
            subj = f"urn:repro019:d:{wid}:{i}"
            ins = (
                f"INSERT DATA {{ GRAPH <{GRAPH}> {{ "
                f'<{subj}> <{RDF_TYPE}> <{TYPE}> . '
                f'<{subj}> <{PRED}> "d-{wid}-{i}" . }} }}'
            )
            await impl.execute_sparql_update(space_id, ins)
            dele = (
                f"DELETE DATA {{ GRAPH <{GRAPH}> {{ "
                f'<{subj}> <{PRED}> "d-{wid}-{i}" . }} }}'
            )
            if not await impl.execute_sparql_update(space_id, dele):
                failures.append(("del", subj))

    readers = [asyncio.create_task(reader()) for _ in range(3)]
    t0 = time.monotonic()
    try:
        await asyncio.wait_for(
            asyncio.gather(
                *[sparql_writer(w) for w in range(12)],
                *[rest_writer(w) for w in range(12)],
                *[sparql_deleter(w) for w in range(6)],
            ),
            timeout=240,
        )
        hung = False
    except asyncio.TimeoutError:
        hung = True
    done.set()
    for r in readers:
        r.cancel()
    await asyncio.gather(*readers, return_exceptions=True)
    elapsed = time.monotonic() - t0

    print(f"\n=== repro019 result (elapsed {elapsed:.1f}s) ===")
    print(f"writer failures : {len(failures)}  {failures[:5]}")
    print(f"read-after-write misses: {len(misses)}  {misses[:5]}")
    print(f"reader stalls/timeouts : {len(stalls)}  {stalls[:5]}")
    print(f"overall writers hung   : {hung}")

    try:
        await sm.delete_space_with_tables(space_id)
    except Exception:
        pass
    await impl.disconnect()

    reproduced = bool(failures or misses or stalls or hung)
    print(f"REPRODUCED POISON/STALL: {reproduced}")
    return 1 if reproduced else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

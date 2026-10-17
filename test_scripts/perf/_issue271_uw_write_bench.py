"""UW decision-write latency through the real API — issues/271.

Drives `POST /api/graphs/kgentities?operation_mode=upsert` on the vg test stack
(:8002) with synthetic graphs of the production UW decision shape: one entity,
~124 frames with a text, an integer and a datetime slot each, and their edges —
~993 objects, ~6,300 quads, ~1,400 terms, close to the 989-object /
6,947-quad / 1,457-term write measured on production on 2026-10-16.

Cells, each repeated `--runs` times (min/med/max reported):

  new      a never-seen entity graph (the production case for big writes)
  same     the previous graph re-upserted unchanged
  changed  the previous graph with ~5 % of slot values changed

Optionally under `--churn`: a second connection keeps doing random subject
lookups on the 74M-quad lead fixture, evicting the bench space from
shared_buffers the way the main KG space does on production. Server-side
phases are read from the app container's log (`upsert_objects_atomic` and the
`BULK insert` line, which carries WAL MB since issues/271).

    python test_scripts/perf/_issue271_uw_write_bench.py --space bench_uw271 --fill 300
    python test_scripts/perf/_issue271_uw_write_bench.py --space bench_uw271 --runs 5 [--churn]

The bench space is created through the API if it does not exist (spaces are
administered through the API, never DDL). It is the bench's own space, so its
writes never disturb a perf fixture.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import re
import statistics
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# The TEST app (:8002), never the dev server on :8001 — the client's default.
os.environ.setdefault("LOCAL_CLIENT_SERVER_URL", "http://localhost:8002")

NS = "http://vital.ai/bench/uw271/"
FRAMES = 124
CHURN_SPACE = "sp_lead_synth_100k"
APP = "vitalgraph-test-app"


def decision_graph(tag: str, seed: int, change_frac: float = 0.0, base_seed: int = None):
    """GraphObjects for one decision. With `change_frac`, the same URIs and values
    as `base_seed`'s graph except that fraction of slot values."""
    from ai_haley_kg_domain.model.KGEntity import KGEntity
    from ai_haley_kg_domain.model.KGFrame import KGFrame
    from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
    from ai_haley_kg_domain.model.KGIntegerSlot import KGIntegerSlot
    from ai_haley_kg_domain.model.KGDateTimeSlot import KGDateTimeSlot
    from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
    from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame

    rng = random.Random(base_seed if base_seed is not None else seed)
    flip = random.Random(seed)
    base = f"{NS}{tag}/"
    entity = f"{base}entity"
    e = KGEntity(); e.URI = entity; e.name = f"decision {tag}"
    e.kGEntityType = f"{NS}DecisionEntity"
    objs = [e]
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for f in range(FRAMES):
        fr = KGFrame(); fr.URI = f"{base}frame{f}"; fr.name = f"rule {f % 40}"
        fr.kGFrameType = f"{NS}RuleFrame{f % 12}"
        link = Edge_hasEntityKGFrame(); link.URI = f"{base}ef{f}"
        link.edgeSource = entity; link.edgeDestination = fr.URI
        objs += [fr, link]
        values = (f"outcome {rng.randrange(10**9)}", rng.randrange(10**6),
                  t0 + timedelta(seconds=rng.randrange(10**7)))
        for k, (cls, attr, v) in enumerate(((KGTextSlot, "textSlotValue", values[0]),
                                             (KGIntegerSlot, "integerSlotValue", values[1]),
                                             (KGDateTimeSlot, "dateTimeSlotValue", values[2]))):
            if change_frac and flip.random() < change_frac:
                v = (f"changed {flip.randrange(10**9)}" if k == 0 else
                     flip.randrange(10**6) if k == 1 else
                     t0 + timedelta(seconds=flip.randrange(10**7)))
            s = cls(); s.URI = f"{base}f{f}s{k}"; s.name = f"slot {k}"
            s.kGSlotType = f"{NS}SlotType{k}"
            setattr(s, attr, v)
            ed = Edge_hasKGSlot(); ed.URI = f"{base}f{f}e{k}"
            ed.edgeSource = fr.URI; ed.edgeDestination = s.URI
            objs += [s, ed]
    return entity, objs


async def ensure_space(client, space_id: str) -> None:
    from vitalgraph.model.spaces_model import Space
    resp = await client.spaces.list_spaces()
    if space_id in [s.space for s in resp.spaces]:
        return
    r = await client.spaces.create_space(Space(space=space_id, space_name=space_id,
                                               space_description="issues/271 UW write bench",
                                               tenant="bench"))
    if not getattr(r, "is_success", True):
        raise SystemExit(f"could not create {space_id}: {r}")


async def upsert(client, space_id, graph_id, objs) -> float:
    t0 = time.perf_counter()
    r = await client.kgentities.upsert_kgentities(space_id=space_id, graph_id=graph_id,
                                                  objects=objs)
    dt = time.perf_counter() - t0
    if not r.is_success:
        raise SystemExit(f"upsert failed: {r.error_message or r.message}")
    return dt


def server_lines(since: str):
    out = subprocess.run(["docker", "logs", "--since", since, APP],
                         capture_output=True, text=True)
    text = out.stdout + out.stderr
    ups = re.findall(r"upsert_objects_atomic: .*", text)
    bulk = re.findall(r"BULK insert: .*", text)
    return ups, bulk


async def churn(stop: asyncio.Event):
    import asyncpg
    c = await asyncpg.connect(host="localhost", port=5433, user="postgres",
                              password="testpass", database="sparql_sql_graph")
    subs = [r[0] for r in await c.fetch(
        f"SELECT subject_uuid FROM {CHURN_SPACE}_rdf_quad TABLESAMPLE SYSTEM (0.5) LIMIT 200000")]
    n = 0
    while not stop.is_set():
        await c.fetchval(f"SELECT count(*) FROM {CHURN_SPACE}_rdf_quad "
                         f"WHERE subject_uuid = ANY($1::uuid[])", random.sample(subs, 2000))
        n += 1
    await c.close()
    return n


def report(name, xs):
    xs = sorted(xs)
    return f"{name:9} n={len(xs)}  min {xs[0]:6.2f}  med {statistics.median(xs):6.2f}  max {xs[-1]:6.2f} s"


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--space", default="bench_uw271")
    ap.add_argument("--fill", type=int, default=0, help="pre-load this many decisions")
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--churn", action="store_true")
    ap.add_argument("--cells", default="new,same,changed")
    a = ap.parse_args()

    from vitalgraph.client.vitalgraph_client import VitalGraphClient
    client = VitalGraphClient()
    await client.open()
    graph = f"urn:{a.space}"
    try:
        await ensure_space(client, a.space)
        if a.fill:
            t = []
            for i in range(a.fill):
                _, objs = decision_graph(f"fill{uuid.uuid4().hex[:10]}", i)
                t.append(await upsert(client, a.space, graph, objs))
                if (i + 1) % 25 == 0:
                    print(f"fill {i + 1}/{a.fill}: last 25 {report('', t[-25:])}", flush=True)
            return

        stop = asyncio.Event()
        churner = asyncio.create_task(churn(stop)) if a.churn else None
        if churner:
            await asyncio.sleep(20)          # let it evict before the first cell
        nobj = None
        results = {c: [] for c in a.cells.split(",")}
        since = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for i in range(a.runs):
            tag = f"run{uuid.uuid4().hex[:10]}"
            _, objs = decision_graph(tag, 1000 + i)
            nobj = len(objs)
            if "new" in results:
                results["new"].append(await upsert(client, a.space, graph, objs))
            else:
                await upsert(client, a.space, graph, objs)
            if "same" in results:
                _, same = decision_graph(tag, 1000 + i)
                results["same"].append(await upsert(client, a.space, graph, same))
            if "changed" in results:
                _, ch = decision_graph(tag, 5000 + i, change_frac=0.05, base_seed=1000 + i)
                results["changed"].append(await upsert(client, a.space, graph, ch))
        if churner:
            stop.set()
            print(f"churn: {await churner} lookup batches of 2,000 subjects")
        print(f"{a.space}, {nobj} objects per decision, churn={'on' if a.churn else 'off'}"
              f" (client wall time per upsert)")
        for c, xs in results.items():
            print("  " + report(c, xs))
        ups, bulk = server_lines(since)
        print("server upsert_objects_atomic:")
        for u in ups:
            print("  " + u[:420])
        print("server BULK insert (>= 1,000 quads):")
        for b in bulk:
            if re.search(r"\+ [0-9]{4,} quads", b):
                print("  " + b[:420])
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())

"""Reads stay fast and CORRECT while writes and their background work run.

`issues/231`. A REGRESSION GUARD, not the bulkhead proof — measured 2026-09-25
and the distinction is load-bearing:

    pool_wait records at a 0.05s threshold, 5-connection pool, 10 writers:  0

Connections are never the scarce resource in this workload. `docker stats`
through the load shows PostgreSQL at up to 300% CPU while the app stays under
100% — entity writes release their connection quickly and saturate PG cores
instead. A capacity-matched A/B (control pool 7 + 0 against treatment pool 5 + 2)
found NO difference; an unmatched one appeared to show a 3x win that was entirely
the two extra connections.

So this file cannot demonstrate pool isolation, and a passing run must not be
cited as evidence of it. The isolation proof is
`tests/load/test_query_is_not_starved_by_internal.py`, which saturates
connections deliberately and carries a control showing it can starve a shared
pool. The failure mode a bulkhead prevents is work that HOLDS a connection — the
six stacked ANALYZE of `issues/230` — which `create_kgentities` does not produce
at any volume.

WHAT THIS IS WORTH: real write load through the real service, asserting reads
stay interactive AND return the right answer. That is the `issues/229` shape,
which no pool-level test can see.

On 2026-09-24 the sequence was exactly this: a bulk copy wrote entities, the
writes triggered auto-sync and ANALYZE, those took request connections, and
ordinary queries went from 0.22s to over 50s. The write path reported 200
throughout.

    MUST BE RUN AGAINST A FRESHLY BUILT IMAGE.

The test stack serves whatever image it was last built with, so running this
against a stale container measures OLD code and reports a pass that means
nothing — the exact failure `tests/api/conftest.py` warns about with the :8001
default. Rebuild, then:

    LOCAL_CLIENT_SERVER_URL=http://localhost:8002 \\
    VG_TEST_PG_PORT=5433 VG_TEST_PG_PASSWORD=testpass \\
    VG_RUN_LOAD_TEST=1 python -m pytest \\
      tests/api/test_query_latency_under_write_load.py -q -s

Opt-in via VG_RUN_LOAD_TEST, matching `tests/load/test_concurrent_query_write_jobs.py`:
it generates real write load and takes tens of seconds, so it does not belong
in an ordinary `tests/api` run.

WHAT IS ASSERTED, and why in this order:

  1. Zero read failures. A read that ERRORS under write load is the `issues/229`
     shape — and there it returned 200 with fewer entities, so a failure count
     of zero is necessary but not sufficient, which is why (4) exists.
  2. p99 read latency, not the mean. 99 fast reads and one 50s read is a good
     mean and an outage.
  3. A hard ceiling no single read may cross.
  4. Reads return the RIGHT ANSWER throughout, not merely a fast one. Isolation
     that degrades correctness is not isolation.
"""

from __future__ import annotations

import asyncio
import os
import statistics
import time
import uuid

import pytest
import pytest_asyncio

from ai_haley_kg_domain.model.KGEntity import KGEntity

pytestmark = pytest.mark.skipif(
    os.environ.get("VG_RUN_LOAD_TEST") != "1",
    reason="load test is opt-in: set VG_RUN_LOAD_TEST=1",
)

NS = "urn:vgload:"

# The read must stay comfortably interactive while writes run. Generous on
# purpose: this is a bulkhead test, not a benchmark, and it should fail because
# reads were STARVED, not because a laptop was busy. Production went from 0.22s
# to >50s, so anything in this range catches it with room to spare.
READ_P99_BUDGET_S = 2.0
READ_CEILING_S = 5.0

WRITE_SECONDS = float(os.environ.get("VG_LOAD_SECONDS", "20"))
WRITE_BATCH = int(os.environ.get("VG_LOAD_BATCH", "25"))

# CONCURRENT WRITERS — the knob that decides whether this run means anything.
#
# A pool of N connections cannot make anyone WAIT until more than N operations
# are in flight at once. At the default 4 writers against a 30-connection pool
# nothing ever queues, so the run measures an uncontended system and a passing
# latency budget says nothing about isolation. Contention is reached by offering
# MORE concurrency than the pool has connections — not by any property of the
# machine.
#
#   VG_LOAD_WRITERS=60 ... to saturate a 30-connection pool
WRITE_CONCURRENCY = int(os.environ.get("VG_LOAD_WRITERS", "4"))


def _entity(i: int) -> KGEntity:
    e = KGEntity()
    e.URI = f"{NS}{uuid.uuid4().hex[:12]}"
    e.name = f"load entity {i}"
    return e


@pytest_asyncio.fixture(loop_scope="session")
async def seeded(vg_client, test_space, test_graph):
    """A small, KNOWN population the reads can be checked against.

    Seeded before the write load starts and never touched by it — the writers
    add new entities under a different name prefix — so a read filtered to this
    prefix has one correct answer for the whole run.
    """
    objs = [_entity(i) for i in range(20)]
    for o in objs:
        o.name = f"seed-{o.name}"
    r = await vg_client.kgentities.create_kgentities(test_space, test_graph, objs)
    assert r.is_success, f"seeding failed: {getattr(r, 'error_message', r)}"
    return [str(o.URI) for o in objs]


@pytest.mark.asyncio(loop_scope="session")
async def test_reads_are_not_starved_by_writes(vg_client, test_space, test_graph, seeded):
    stop_at = time.monotonic() + WRITE_SECONDS
    read_latencies: list[float] = []
    read_failures: list[str] = []
    wrong_answers: list[str] = []
    writes = {"ok": 0, "failed": 0}

    async def writer(worker: int):
        """Sustained writes. Each create also triggers the derived-table
        maintenance and auto-sync that took request connections in production."""
        n = 0
        while time.monotonic() < stop_at:
            objs = [_entity(n + i) for i in range(WRITE_BATCH)]
            n += WRITE_BATCH
            try:
                r = await vg_client.kgentities.create_kgentities(
                    test_space, test_graph, objs)
                if r.is_success:
                    writes["ok"] += len(objs)
                else:
                    writes["failed"] += len(objs)
            except Exception:
                writes["failed"] += len(objs)

    async def reader():
        """A cheap, interactive read — the thing a user is waiting on."""
        while time.monotonic() < stop_at:
            t0 = time.monotonic()
            try:
                r = await vg_client.kgentities.get_kgentities_by_uris(
                    test_space, test_graph, [seeded[0]])
                read_latencies.append(time.monotonic() - t0)
                # CORRECTNESS, not just latency. `issues/229` returned 200 with
                # fewer entities than asked for; a fast wrong answer is the
                # worse failure because nothing surfaces it.
                objs = getattr(r, "objects", None) or []
                if not r.is_success or not objs:
                    wrong_answers.append(
                        f"success={r.is_success} objects={len(objs)}")
            except Exception as e:
                read_failures.append(f"{type(e).__name__}: {e}")
            await asyncio.sleep(0.05)

    await asyncio.gather(
        *[writer(i) for i in range(WRITE_CONCURRENCY)], reader())

    assert read_latencies, "no reads completed at all"
    lat = sorted(read_latencies)
    p50 = statistics.median(lat)
    p99 = lat[int(len(lat) * 0.99)] if len(lat) > 100 else lat[-1]

    print(f"\n  writes ok={writes['ok']} failed={writes['failed']}")
    print(f"  reads n={len(lat)} p50={p50*1000:.0f}ms "
          f"p99={p99*1000:.0f}ms max={lat[-1]*1000:.0f}ms")

    # 1. no read errored
    assert not read_failures, (
        f"{len(read_failures)} reads FAILED under write load: {read_failures[:3]}")
    # 4. and none returned the wrong thing
    assert not wrong_answers, (
        f"{len(wrong_answers)} reads returned a wrong/empty answer under write "
        f"load — a fast wrong answer is worse than a slow right one "
        f"(`issues/229`): {wrong_answers[:3]}")
    # the writers must actually have loaded the system, or this proves nothing
    assert writes["ok"] > 0, "no writes succeeded; there was no load to isolate from"
    # 2. and 3.
    assert p99 < READ_P99_BUDGET_S, (
        f"p99 read latency {p99:.2f}s under write load — reads are being "
        f"starved by writes and their background work")
    assert lat[-1] < READ_CEILING_S, (
        f"worst read {lat[-1]:.2f}s crossed the hard ceiling")

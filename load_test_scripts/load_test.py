#!/usr/bin/env python3
"""VitalGraph service load test — asyncio driver over the official client.

Spawns N concurrent VitalGraphClient "users", each looping weighted random
operations against the seeded load-test space, and reports per-operation latency
percentiles + throughput. Uses the client only (no raw HTTP, no gevent/asyncio
bridging), so the latencies reflect the real client→service path.

    python load_test_scripts/setup.py                       # seed data first
    python load_test_scripts/load_test.py -u 20 -t 60       # 20 users, 60s
    python load_test_scripts/load_test.py -u 20 -t 60 --read-only
    LOAD_TEST_ENV=test python load_test_scripts/load_test.py -u 10 -t 30   # :8002
"""

import argparse
import asyncio
import os
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE.parent))       # repo root — for `import vitalgraph`
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE / "data_gen"))

from load_test_config import load_env
from load_test_data import LOAD_TEST_SPACE_ID, LOAD_TEST_GRAPH_ID, get_entity_uris

SPACE, GRAPH = LOAD_TEST_SPACE_ID, LOAD_TEST_GRAPH_ID


# ── Metrics ──────────────────────────────────────────────────────────
class Metrics:
    def __init__(self):
        self.lat = defaultdict(list)     # op -> [latency_ms]
        self.fail = defaultdict(int)     # op -> failure count

    def record(self, op, ms, ok):
        self.lat[op].append(ms)
        if not ok:
            self.fail[op] += 1

    @staticmethod
    def _pct(xs, p):
        if not xs:
            return 0.0
        s = sorted(xs)
        return s[min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))]

    def report(self, duration, users):
        total = sum(len(v) for v in self.lat.values())
        fails = sum(self.fail.values())
        print(f"\n{'='*96}")
        print(f"  {users} users · {duration:.0f}s · {total} requests · "
              f"{fails} failures ({100*fails/max(total,1):.1f}%) · "
              f"{total/duration:.1f} req/s")
        print(f"{'='*96}")
        print(f"  {'operation':<34} {'reqs':>6} {'fail':>5} {'avg':>7} "
              f"{'p50':>7} {'p95':>7} {'p99':>7} {'max':>7}  (ms)")
        print(f"  {'-'*90}")
        for op in sorted(self.lat):
            xs = self.lat[op]
            print(f"  {op:<34} {len(xs):>6} {self.fail[op]:>5} "
                  f"{sum(xs)/len(xs):>7.0f} {self._pct(xs,50):>7.0f} "
                  f"{self._pct(xs,95):>7.0f} {self._pct(xs,99):>7.0f} "
                  f"{max(xs):>7.0f}")
        print(f"{'='*96}\n")
        return fails


# ── Client + operation set ───────────────────────────────────────────
async def _open_client(cfg):
    os.environ.setdefault("VITALGRAPH_CLIENT_ENVIRONMENT", "test")
    os.environ["TEST_CLIENT_SERVER_URL"] = cfg["url"]
    os.environ["TEST_CLIENT_AUTH_USERNAME"] = cfg["username"]
    os.environ["TEST_CLIENT_AUTH_PASSWORD"] = cfg["password"]
    from vitalgraph.client.vitalgraph_client import VitalGraphClient
    client = VitalGraphClient()
    await client.open()
    return client


def _build_ops(uris, read_only, writes_enabled):
    """Return [(weight, name, async fn(client))]."""
    def pick():
        return random.choice(uris)

    ops = [
        (30, "list_entities",
         lambda c: c.kgentities.list_kgentities(SPACE, GRAPH,
                                                page_size=random.choice([5, 10, 20, 50]))),
        (25, "get_entity",
         lambda c: c.kgentities.get_kgentity(SPACE, GRAPH, uri=pick())),
        (15, "get_entity+graph",
         lambda c: c.kgentities.get_kgentity(SPACE, GRAPH, uri=pick(),
                                             include_entity_graph=True)),
        (10, "list_frames",
         lambda c: c.kgframes.list_kgframes(SPACE, GRAPH, parent_uri=pick(), page_size=20)),
        (5, "list_spaces", lambda c: c.spaces.list_spaces()),
        (5, "list_graphs", lambda c: c.graphs.list_graphs(SPACE)),
    ]
    if not read_only and writes_enabled:
        ops.append((5, "update_frame_slot", _make_write(pick)))
    return ops


def _make_write(pick):
    async def _write(c):
        # list a frame for a random entity, then update one of its text slots
        entity = pick()
        frames = await c.kgframes.list_kgframes(SPACE, GRAPH, parent_uri=entity, page_size=10)
        results = getattr(frames, "results", None) or []
        if not results:
            return frames
        frame_uri = str(getattr(results[0], "URI", "") or "")
        if not frame_uri:
            return frames
        from ai_haley_kg_domain.model.KGFrame import KGFrame
        from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
        import string
        frame = KGFrame(); frame.URI = frame_uri
        frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#CompanyInfoFrame"
        slot = KGTextSlot(); slot.URI = frame_uri + "/slot/industry"
        slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#IndustrySlot"
        slot.textSlotValue = "LoadTest_" + "".join(random.choices(string.ascii_letters, k=8))
        return await c.kgframes.update_kgframes(SPACE, GRAPH, [frame, slot], parent_uri=entity)
    return _write


# ── Driver ───────────────────────────────────────────────────────────
async def _worker(cfg, ops, weights, deadline, metrics, think):
    client = await _open_client(cfg)
    try:
        while time.monotonic() < deadline:
            _, name, fn = random.choices(ops, weights=weights, k=1)[0]
            t0 = time.perf_counter()
            ok = True
            try:
                resp = await fn(client)
                ok = getattr(resp, "is_success", True) is not False
            except Exception:
                ok = False
            metrics.record(name, (time.perf_counter() - t0) * 1000, ok)
            await asyncio.sleep(random.uniform(*think))
    finally:
        await client.close()


async def run(users, duration, ramp, think, read_only):
    cfg = load_env()
    uris = get_entity_uris()
    if not uris:
        print("No entity URIs — run setup.py first.", file=sys.stderr)
        return 1
    ops = _build_ops(uris, read_only, cfg["profile"].get("writes_enabled", True))
    weights = [w for w, _, _ in ops]
    print(f"Load test: {users} users, {duration}s, {'read-only' if read_only else 'read+write'} "
          f"→ {cfg['url']} space={SPACE} ({len(uris)} entities)")
    metrics = Metrics()
    deadline = time.monotonic() + duration
    tasks = []
    for _ in range(users):
        tasks.append(asyncio.create_task(_worker(cfg, ops, weights, deadline, metrics, think)))
        if ramp:
            await asyncio.sleep(ramp / users)
    await asyncio.gather(*tasks)
    fails = metrics.report(duration, users)
    return 1 if fails else 0


def main():
    p = argparse.ArgumentParser(description="VitalGraph asyncio load test")
    p.add_argument("-u", "--users", type=int, default=10)
    p.add_argument("-t", "--time", type=float, default=30, dest="duration")
    p.add_argument("-r", "--ramp", type=float, default=2.0, help="ramp-up seconds")
    p.add_argument("--think-min", type=float, default=0.1)
    p.add_argument("--think-max", type=float, default=0.5)
    p.add_argument("--read-only", action="store_true")
    a = p.parse_args()
    rc = asyncio.run(run(a.users, a.duration, a.ramp, (a.think_min, a.think_max), a.read_only))
    sys.exit(rc)


if __name__ == "__main__":
    main()

"""Write latency through the real API, against any server — issues/271.

Drives the same calls production's writers make, through `VitalGraphClient`,
and reports client wall time per write (min / median / p90 / max). Cells:

  new       a never-seen entity graph of the UW decision shape (~993 objects,
            ~7,300 quads, ~1,450 terms) — `upsert_kgentities`
  same      that graph re-upserted unchanged
  changed   that graph with ~5 % of slot values changed
  small     a new 100-object entity graph (~730 quads)
  frame     a frame upsert on an existing entity (1 frame, 12 slots, their
            edges: ~40 subjects, ~280 quads) — `create_entity_frames(upsert)`,
            the shape of production's frame updates

Optionally reads the server's own phase lines for the run window
(`upsert_objects_atomic`, `BULK insert`, `update_subjects_graph`) from a docker
container's log or from CloudWatch.

SAFETY, because this is meant to be pointed at production:

  * it only ever writes to a space whose id starts with `perfbench_`, created
    through the API if absent (spaces are administered through the API, never
    DDL) — so it cannot touch a real space by a typo;
  * the `prod` profile also requires `--i-mean-production`;
  * `--delete-space` deletes the bench space through the API afterwards;
  * it writes modest volumes (default 5 runs; one cell is ~7k quads).

A REAL SPACE (`--real-space`, e.g. the UW space, to measure writes against its
real size and cache state): the space must already exist and is never created
or deleted. Every bench entity lives under `http://vital.ai/bench/writelat/` with the entity type
`.../writelat/BenchEntity`, so no query by a real type can match one. EVERY entity the
run wrote is deleted with its whole entity graph in a `finally`, even if a write
fails, and each is then read back to prove it is gone; a survivor is reported
and the exit status is non-zero.

    # local dev server (:8001)
    python test_scripts/perf/write_latency_bench.py --env local \\
        --server-url http://localhost:8001 --space perfbench_w1 --server-log docker:vitalgraph-app

    # production, through the PROD_CLIENT_* profile in .env
    python test_scripts/perf/write_latency_bench.py --env prod --i-mean-production \\
        --space perfbench_w1 --server-log cloudwatch --delete-space
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import statistics
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

NS = "http://vital.ai/bench/writelat/"
SPACE_PREFIX = "perfbench_"
ALL_CELLS = ("new", "same", "changed", "small", "frame")


# ---------------------------------------------------------------------------
# Graph shapes
# ---------------------------------------------------------------------------

def _classes():
    from ai_haley_kg_domain.model.KGEntity import KGEntity
    from ai_haley_kg_domain.model.KGFrame import KGFrame
    from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
    from ai_haley_kg_domain.model.KGIntegerSlot import KGIntegerSlot
    from ai_haley_kg_domain.model.KGDateTimeSlot import KGDateTimeSlot
    from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
    from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
    return (KGEntity, KGFrame, KGTextSlot, KGIntegerSlot, KGDateTimeSlot,
            Edge_hasKGSlot, Edge_hasEntityKGFrame)


def _slots(frame_uri, base, f, rng, flip, change_frac, n_slots=3):
    (_E, _F, KGTextSlot, KGIntegerSlot, KGDateTimeSlot, Edge_hasKGSlot, _L) = _classes()
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    kinds = ((KGTextSlot, "textSlotValue", lambda r: f"outcome {r.randrange(10**9)}"),
             (KGIntegerSlot, "integerSlotValue", lambda r: r.randrange(10**6)),
             (KGDateTimeSlot, "dateTimeSlotValue",
              lambda r: t0 + timedelta(seconds=r.randrange(10**7))))
    out = []
    for k in range(n_slots):
        cls, attr, gen = kinds[k % 3]
        v = gen(rng)
        if change_frac and flip.random() < change_frac:
            v = gen(flip)
        s = cls(); s.URI = f"{base}f{f}s{k}"; s.name = f"slot {k}"
        s.kGSlotType = f"{NS}SlotType{k}"
        setattr(s, attr, v)
        e = Edge_hasKGSlot(); e.URI = f"{base}f{f}e{k}"
        e.edgeSource = frame_uri; e.edgeDestination = s.URI
        out += [s, e]
    return out


def entity_graph(tag, seed, frames=124, change_frac=0.0, base_seed=None):
    """(entity_uri, objects). Same URIs and values as `base_seed`'s graph except
    `change_frac` of the slot values."""
    (KGEntity, KGFrame, *_rest) = _classes()
    Edge_hasEntityKGFrame = _classes()[6]
    rng = random.Random(base_seed if base_seed is not None else seed)
    flip = random.Random(seed)
    base = f"{NS}{tag}/"
    entity = f"{base}entity"
    e = KGEntity(); e.URI = entity; e.name = f"bench {tag}"
    e.kGEntityType = f"{NS}BenchEntity"
    objs = [e]
    for f in range(frames):
        fr = KGFrame(); fr.URI = f"{base}frame{f}"; fr.name = f"rule {f % 40}"
        fr.kGFrameType = f"{NS}RuleFrame{f % 12}"
        link = Edge_hasEntityKGFrame(); link.URI = f"{base}ef{f}"
        link.edgeSource = entity; link.edgeDestination = fr.URI
        objs += [fr, link] + _slots(fr.URI, base, f, rng, flip, change_frac)
    return entity, objs


def frame_update(tag, n, slots=12):
    """One frame with `slots` slots and their edges, values varying with `n`."""
    KGFrame = _classes()[1]
    base = f"{NS}{tag}/upd/"
    fr = KGFrame(); fr.URI = f"{base}frame"; fr.name = "decision"
    fr.kGFrameType = f"{NS}DecisionFrame"
    rng = random.Random(n)
    return [fr] + _slots(fr.URI, base, 0, rng, rng, 0.0, n_slots=slots)


# ---------------------------------------------------------------------------
# Server logs
# ---------------------------------------------------------------------------

_PHASE_RE = re.compile(r"(upsert_objects_atomic: .*|BULK insert: .*|update_subjects_graph: .*)")


def server_lines(source, since, until):
    if source == "none":
        return []
    if source.startswith("docker:"):
        out = subprocess.run(["docker", "logs", "--since", since.strftime("%Y-%m-%dT%H:%M:%SZ"),
                              "--until", until.strftime("%Y-%m-%dT%H:%M:%SZ"), source[7:]],
                             capture_output=True, text=True)
        text = (out.stdout + out.stderr).splitlines()
    elif source == "cloudwatch":
        # The phase lines do not name the space, so this reads every phase line
        # in the window: on a shared server, other writers' lines appear too.
        out = subprocess.run([
            "aws", "logs", "filter-log-events",
            *(["--profile", os.environ["AWS_PROFILE"]] if os.getenv("AWS_PROFILE") else []),
            "--region", "us-east-1", "--log-group-name", "/ecs/vitalgraph-prod",
            "--log-stream-name-prefix", "ecs/vitalgraph/",
            "--start-time", str(int(since.timestamp() * 1000)),
            "--end-time", str(int(until.timestamp() * 1000) + 5000),
            "--filter-pattern", '?"upsert_objects_atomic:" ?"BULK insert:" ?"update_subjects_graph:"',
            "--query", "events[].message", "--output", "json"], capture_output=True, text=True)
        text = json.loads(out.stdout or "[]")
    else:
        raise SystemExit(f"unknown --server-log {source}")
    return [m.group(1) for line in text if (m := _PHASE_RE.search(line))]


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def summary(name, xs):
    if not xs:
        return f"{name:8} n=0"
    xs = sorted(xs)
    p90 = xs[min(len(xs) - 1, int(0.9 * len(xs)))]
    return (f"{name:8} n={len(xs):2}  min {xs[0]:6.2f}  med {statistics.median(xs):6.2f}  "
            f"p90 {p90:6.2f}  max {xs[-1]:6.2f} s")


async def ensure_space(client, space_id):
    from vitalgraph.model.spaces_model import Space
    resp = await client.spaces.list_spaces()
    if space_id in [s.space for s in (resp.spaces or [])]:
        return False
    r = await client.spaces.create_space(Space(
        space=space_id, space_name=space_id, tenant="perfbench",
        space_description="write-latency bench (test_scripts/perf/write_latency_bench.py)"))
    if not getattr(r, "is_success", True):
        raise SystemExit(f"could not create {space_id}: {getattr(r, 'error_message', r)}")
    return True


async def timed(coro):
    t0 = time.perf_counter()
    r = await coro
    dt = time.perf_counter() - t0
    if not getattr(r, "is_success", True):
        raise SystemExit(f"write failed: {getattr(r, 'error_message', None) or getattr(r, 'message', r)}")
    return dt


async def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env", default="local", help="client profile: local | prod | ...")
    ap.add_argument("--server-url", default=None, help="override {ENV}_CLIENT_SERVER_URL")
    ap.add_argument("--space", required=True, help=f"bench space id, must start with {SPACE_PREFIX}")
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--cells", default=",".join(ALL_CELLS))
    ap.add_argument("--server-log", default="none",
                    help="none | docker:<container> | cloudwatch")
    ap.add_argument("--delete-space", action="store_true", help="delete the bench space afterwards")
    ap.add_argument("--i-mean-production", action="store_true")
    ap.add_argument("--real-space", action="store_true",
                    help="write into an EXISTING real space; every bench entity is deleted after")
    ap.add_argument("--graph", default=None, help="graph id (default urn:<space>)")
    a = ap.parse_args()

    if a.real_space:
        if a.delete_space:
            raise SystemExit("--real-space never deletes the space; drop --delete-space")
    elif not a.space.startswith(SPACE_PREFIX) or len(a.space) > 34:
        raise SystemExit(f"--space must start with {SPACE_PREFIX!r} and be <= 34 bytes "
                         f"(or pass --real-space to write into an existing space)")
    if a.env.lower() == "prod" and not a.i_mean_production:
        raise SystemExit("--env prod writes to PRODUCTION; pass --i-mean-production")
    cells = [c for c in a.cells.split(",") if c]
    if set(cells) - set(ALL_CELLS):
        raise SystemExit(f"unknown cell(s): {set(cells) - set(ALL_CELLS)}")

    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
    os.environ["VITALGRAPH_CLIENT_ENVIRONMENT"] = a.env.lower()
    if a.server_url:
        os.environ[f"{a.env.upper()}_CLIENT_SERVER_URL"] = a.server_url

    from vitalgraph.client.vitalgraph_client import VitalGraphClient
    client = VitalGraphClient()
    await client.open()
    graph = a.graph or f"urn:{a.space}"
    written: list = []                  # every entity this run wrote, for cleanup
    url = os.environ.get(f"{a.env.upper()}_CLIENT_SERVER_URL")
    print(f"server {url} (profile {a.env}), space {a.space}, {a.runs} runs, cells {cells}")
    results = {c: [] for c in cells}
    created = False
    since = datetime.now(timezone.utc)
    exit_code = 0
    try:
        if a.real_space:
            resp = await client.spaces.list_spaces()
            if a.space not in [sp.space for sp in (resp.spaces or [])]:
                raise SystemExit(f"--real-space: {a.space} does not exist; refusing to create it")
        else:
            created = await ensure_space(client, a.space)
        frame_entity = None
        for i in range(a.runs):
            tag = f"r{uuid.uuid4().hex[:10]}"
            ent, objs = entity_graph(tag, 1000 + i)
            written.append(ent)
            if any(c in cells for c in ("new", "same", "changed", "frame")):
                dt = await timed(client.kgentities.upsert_kgentities(
                    space_id=a.space, graph_id=graph, objects=objs))
                if "new" in results:
                    results["new"].append(dt)
            if "same" in results:
                _, same = entity_graph(tag, 1000 + i)
                results["same"].append(await timed(client.kgentities.upsert_kgentities(
                    space_id=a.space, graph_id=graph, objects=same)))
            if "changed" in results:
                _, ch = entity_graph(tag, 5000 + i, change_frac=0.05, base_seed=1000 + i)
                results["changed"].append(await timed(client.kgentities.upsert_kgentities(
                    space_id=a.space, graph_id=graph, objects=ch)))
            if "small" in results:
                sm_ent, sm = entity_graph(f"s{tag}", 3000 + i, frames=12)
                written.append(sm_ent)
                results["small"].append(await timed(client.kgentities.upsert_kgentities(
                    space_id=a.space, graph_id=graph, objects=sm)))
            if "frame" in results:
                frame_entity = ent
                results["frame"].append(await timed(client.kgentities.create_entity_frames(
                    space_id=a.space, graph_id=graph, entity_uri=frame_entity,
                    objects=frame_update(tag, i), operation_mode="upsert")))
        until = datetime.now(timezone.utc)

        print(f"\nclient wall time per write ({url}):")
        for c in cells:
            print("  " + summary(c, results[c]))
        lines = server_lines(a.server_log, since, until)
        if lines:
            print(f"\nserver phase lines in the window ({len(lines)}; on a shared server "
                  f"they include other writers):")
            for line in lines:
                print("  " + line[:400])
    finally:
        if a.real_space and written:
            exit_code = await cleanup(client, a.space, graph, written)
        if a.delete_space:
            r = await client.spaces.delete_space(a.space)
            print(f"\ndeleted bench space {a.space}: {getattr(r, 'is_success', r)}")
        elif created:
            print(f"\nbench space {a.space} left in place (pass --delete-space to remove it)")
        await client.close()
    return exit_code


async def cleanup(client, space, graph, uris) -> int:
    """Delete every bench entity graph, then prove each is gone."""
    t0 = time.perf_counter()
    for k in range(0, len(uris), 10):
        r = await client.kgentities.delete_kgentities_batch(
            space_id=space, graph_id=graph, uri_list=uris[k:k + 10],
            delete_entity_graph=True)
        if not getattr(r, "is_success", True):
            print(f"  cleanup: delete failed for {uris[k:k + 10]}: "
                  f"{getattr(r, 'error_message', None) or getattr(r, 'message', r)}")
    survivors = []
    for u in uris:
        r = await client.kgentities.get_kgentity(
            space_id=space, graph_id=graph, uri=u, include_entity_graph=True)
        objs = getattr(getattr(r, "objects", None), "objects", None) or []
        if getattr(r, "is_success", False) and objs:
            survivors.append((u, len(objs)))
    print(f"\ncleanup: deleted {len(uris)} bench entity graph(s) from {space} in "
          f"{time.perf_counter() - t0:.1f}s; {len(survivors)} still readable"
          + (f": {survivors}" if survivors else ""))
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

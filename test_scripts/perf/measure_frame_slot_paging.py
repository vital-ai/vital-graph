#!/usr/bin/env python3
"""Baseline timings for frame/slot paging (step 5 of the sequence plan).

Measures the real REST path against the vg-test stack, because that is what a
client actually experiences: SPARQL + response assembly + object rebuild, not
just the SQL plan.

What it answers:
  1. How does the whole-entity-graph fetch (what EntityGraphViewer does today)
     scale against a paged frame fetch?
  2. What does a deep offset cost? Offset paging is O(offset) server-side.
  3. Does sorting by sequence cost materially more than unsorted?
  4. How does one frame's slot page scale with slots-per-frame?

Usage (stack must be up and built):
    docker compose -f docker-compose.test.yml up -d --build --wait
    python test_scripts/perf/measure_frame_slot_paging.py
    python test_scripts/perf/measure_frame_slot_paging.py --frames 5000 --slots 5000

Seeds via SPARQL INSERT (bulk) rather than the CRUD API — seeding thousands of
frames one create-call at a time dominates the run and measures the wrong thing.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("LOCAL_CLIENT_SERVER_URL", "http://localhost:8002")

KG = "http://vital.ai/ontology/haley-ai-kg#"
VC = "http://vital.ai/ontology/vital-core#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
XSD_INT = "http://www.w3.org/2001/XMLSchema#integer"

FRAME_SEQ = f"{KG}hasFrameSequence"
SLOT_SEQ = f"{KG}hasSlotSequence"

SPACE_ID = "perf_frame_slot_paging"
GRAPH_ID = "urn:perf:frameslot"
NS = "urn:perf:fs:"
ENTITY = f"{NS}entity"

# Insert in chunks — one enormous INSERT DATA is slower and can blow limits.
CHUNK_TRIPLES = 4000


def _count(resp) -> int:
    return len(getattr(resp, "objects", None) or [])


def _fmt(ms: float) -> str:
    return f"{ms:8.1f} ms"


async def _timed(coro_factory, runs: int = 3):
    """Run a coroutine factory `runs` times, return (median_ms, result)."""
    timings, result = [], None
    for _ in range(runs):
        t0 = time.perf_counter()
        result = await coro_factory()
        timings.append((time.perf_counter() - t0) * 1000)
    return statistics.median(timings), result


def _frame_triples(n_frames: int, slots_on_first: int):
    """Entity + n_frames frames; the FIRST frame carries slots_on_first slots.

    Sequence is decorrelated from URI order (frame i gets sequence n-i) so a
    sorted run cannot accidentally match insertion/URI order.
    """
    yield f"<{ENTITY}> <{RDF_TYPE}> <{KG}KGEntity> ."
    yield f'<{ENTITY}> <{VC}hasName> "Perf Entity" .'
    for i in range(n_frames):
        f = f"{NS}f{i:07d}"
        yield f"<{f}> <{RDF_TYPE}> <{KG}KGFrame> ."
        yield f'<{f}> <{VC}hasName> "Frame {i}" .'
        yield f'<{f}> <{FRAME_SEQ}> "{n_frames - i}"^^<{XSD_INT}> .'
        # get_entity_graph traverses hasKGGraphURI, not the edges — without it
        # the whole-graph fetch returns only the entity itself.
        yield f"<{f}> <{KG}hasKGGraphURI> <{ENTITY}> ."
        e = f"{NS}ef{i:07d}"
        yield f"<{e}> <{RDF_TYPE}> <{KG}Edge_hasEntityKGFrame> ."
        yield f"<{e}> <{VC}hasEdgeSource> <{ENTITY}> ."
        yield f"<{e}> <{VC}hasEdgeDestination> <{f}> ."
    f0 = f"{NS}f{0:07d}"
    for j in range(slots_on_first):
        s = f"{NS}s{j:07d}"
        yield f"<{s}> <{RDF_TYPE}> <{KG}KGTextSlot> ."
        yield f'<{s}> <{VC}hasName> "Slot {j}" .'
        yield f'<{s}> <{KG}hasTextSlotValue> "value {j}" .'
        yield f'<{s}> <{SLOT_SEQ}> "{slots_on_first - j}"^^<{XSD_INT}> .'
        yield f"<{s}> <{KG}hasKGGraphURI> <{ENTITY}> ."
        yield f"<{s}> <{KG}hasFrameGraphURI> <{f0}> ."
        se = f"{NS}se{j:07d}"
        yield f"<{se}> <{RDF_TYPE}> <{KG}Edge_hasKGSlot> ."
        yield f"<{se}> <{VC}hasEdgeSource> <{f0}> ."
        yield f"<{se}> <{VC}hasEdgeDestination> <{s}> ."


async def seed(client, n_frames: int, n_slots: int):
    from vitalgraph.model.sparql_model import SPARQLUpdateRequest

    triples, chunks, total = [], 0, 0
    t0 = time.perf_counter()

    async def flush():
        nonlocal triples, chunks, total
        if not triples:
            return
        body = "\n".join(triples)
        await client.execute_sparql_update(
            SPACE_ID, SPARQLUpdateRequest(
                update=f"INSERT DATA {{ GRAPH <{GRAPH_ID}> {{\n{body}\n}} }}"))
        total += len(triples)
        chunks += 1
        triples = []

    for t in _frame_triples(n_frames, n_slots):
        triples.append(t)
        if len(triples) >= CHUNK_TRIPLES:
            await flush()
    await flush()
    elapsed = time.perf_counter() - t0
    print(f"  seeded {total:,} triples in {chunks} chunks — {elapsed:.1f}s")


async def run(n_frames: int, n_slots: int, keep: bool):
    from vitalgraph.client.vitalgraph_client import VitalGraphClient
    from vitalgraph.model.spaces_model import Space

    client = VitalGraphClient()
    await client.open()
    try:
        print(f"\n=== setup: {n_frames:,} frames, {n_slots:,} slots on frame 0 ===")
        try:
            await client.add_space(Space(
                space=SPACE_ID, space_name=SPACE_ID, space_description="perf"))
        except Exception as e:
            print(f"  space: {str(e)[:80]}")
        await seed(client, n_frames, n_slots)

        # Warm-up. The FIRST sequence-sorted page costs ~50x a subsequent one
        # (term resolution / buffer warming), so without this the benchmark
        # reports cold-start cost as if it were sort cost — which is how an
        # apparent "16x sort penalty" turned out to be a one-off warm-up.
        # Cold-start is measured separately below.
        print("\n=== cold start (first sequence-sorted page, unwarmed) ===")
        cold_ms, _ = await _timed(lambda: client.get_kgentity_frames(
            space_id=SPACE_ID, graph_id=GRAPH_ID, entity_uri=ENTITY,
            page_size=25, offset=0, sort_by=FRAME_SEQ, sort_order="asc"), runs=1)
        print(f"  first sorted page (cold)                      {_fmt(cold_ms)}")
        for _ in range(3):
            await client.get_kgentity_frames(
                space_id=SPACE_ID, graph_id=GRAPH_ID, entity_uri=ENTITY,
                page_size=25, offset=0, sort_by=FRAME_SEQ, sort_order="asc")

        print(f"\n=== steady state ({n_frames:,} frames / {n_slots:,} slots) ===")
        rows = []

        # 1. Whole entity graph — what EntityGraphViewer does today.
        ms, resp = await _timed(lambda: client.kgentities.get_kgentity(
            space_id=SPACE_ID, graph_id=GRAPH_ID, uri=ENTITY,
            include_entity_graph=True), runs=1)
        # EntityGraphResponse.objects is an EntityGraph wrapper, not a list.
        payload = getattr(resp, "objects", None)
        if not isinstance(payload, list):
            payload = getattr(payload, "objects", None) or []
        rows.append(("whole entity graph (include_entity_graph)", ms,
                     f"{len(payload):,} objects"))

        # 2. First page of frames, unsorted vs sequence-sorted.
        for label, kw in (("frames page 1, unsorted", {}),
                          ("frames page 1, sequence sort",
                           {"sort_by": FRAME_SEQ, "sort_order": "asc"})):
            ms, resp = await _timed(lambda kw=kw: client.get_kgentity_frames(
                space_id=SPACE_ID, graph_id=GRAPH_ID, entity_uri=ENTITY,
                page_size=25, offset=0, **kw))
            rows.append((label, ms, f"{_count(resp)} frames"))

        # 3. Deep offset — offset paging is O(offset).
        sweep = [0, n_frames // 4, n_frames // 2, (3 * n_frames) // 4,
                 max(0, n_frames - 100), max(0, n_frames - 25)]
        for off in sorted(set(sweep)):
            ms, resp = await _timed(lambda off=off: client.get_kgentity_frames(
                space_id=SPACE_ID, graph_id=GRAPH_ID, entity_uri=ENTITY,
                page_size=25, offset=off, sort_by=FRAME_SEQ, sort_order="asc"))
            rows.append((f"frames page at offset {off:,}", ms,
                         f"{_count(resp)} frames"))

        # 4. Slots of the big frame — page 1 vs deep offset vs all.
        f0 = f"{NS}f{0:07d}"
        for label, ps, off in (("slots page 1 (25)", 25, 0),
                               (f"slots at offset {max(0, n_slots - 25):,}",
                                25, max(0, n_slots - 25)),
                               ("all slots in one page", max(n_slots, 1), 0)):
            ms, resp = await _timed(lambda ps=ps, off=off: client.get_entity_frame_slots(
                space_id=SPACE_ID, graph_id=GRAPH_ID, frame_uri=f0,
                page_size=min(ps, 1000), offset=off,
                sort_by=SLOT_SEQ, sort_order="asc"))
            got = len(getattr(resp, "objects", None) or [])
            rows.append((label, ms, f"{got} slots"))

        width = max(len(r[0]) for r in rows) + 2
        for label, ms, note in rows:
            print(f"  {label:<{width}} {_fmt(ms)}  {note}")

    finally:
        if not keep:
            try:
                await client.delete_space(SPACE_ID)
                print("\n  cleaned up space")
            except Exception as e:
                print(f"\n  cleanup failed: {str(e)[:80]}")
        await client.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=1000)
    ap.add_argument("--slots", type=int, default=1000)
    ap.add_argument("--keep", action="store_true", help="do not delete the space")
    a = ap.parse_args()
    asyncio.run(run(a.frames, a.slots, a.keep))


if __name__ == "__main__":
    main()

"""
Benchmark: N-Quads vs JSON Quads serialization/deserialization

Compares the two quad-based wire formats across typical VitalGraph payloads:
  1. Single KGEntity (small)
  2. 10 KGEntities (medium list)
  3. 100 KGEntities (bulk)
  4. Entity + Frame + Slots + Edges (complex graph)

Measures:
  - Serialization time (GraphObjects → wire format)
  - Deserialization time (wire format → GraphObjects)
  - Payload size (raw bytes, gzipped bytes)

Usage:
  python test_scripts_misc/benchmark_serialization_formats.py
"""

import gzip
import json
import time
import statistics
import sys
from typing import List, Tuple

from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGSlot import KGSlot
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from ai_haley_kg_domain.model.Edge_hasKGFrame import Edge_hasKGFrame

from vitalgraph.utils.quad_format_utils import (
    graphobjects_to_quad_list,
    quad_list_to_graphobjects,
    quads_to_nquads_text,
    nquads_text_to_quads,
)
from vitalgraph.model.quad_model import QuadResponse


# ---------------------------------------------------------------------------
# Test data generators
# ---------------------------------------------------------------------------

def _set_props(obj, props: dict):
    """Set properties on a GraphObject, skipping any that fail."""
    for k, v in props.items():
        try:
            setattr(obj, k, v)
        except AttributeError:
            pass


def make_entity(index: int) -> KGEntity:
    e = KGEntity()
    e.URI = f"http://example.org/entity/{index}"
    _set_props(e, {
        "name": f"Test Entity {index}",
        "hasKGraphDescription": f"Description for entity {index} with some additional text to make it realistic.",
        "hasKGIdentifier": f"ent-{index}",
    })
    return e


def make_frame(entity_index: int, frame_index: int) -> KGFrame:
    f = KGFrame()
    f.URI = f"http://example.org/frame/{entity_index}/{frame_index}"
    _set_props(f, {
        "name": f"Frame {frame_index} of entity {entity_index}",
        "hasKGraphDescription": f"Frame description {frame_index}",
    })
    return f


def make_slot(entity_index: int, frame_index: int, slot_index: int) -> KGTextSlot:
    s = KGTextSlot()
    s.URI = f"http://example.org/slot/{entity_index}/{frame_index}/{slot_index}"
    _set_props(s, {
        "name": f"Slot {slot_index}",
        "kGSlotValue": f"Value for slot {slot_index} in frame {frame_index}",
    })
    return s


def make_edge_has_frame(entity_uri: str, frame_uri: str) -> Edge_hasKGFrame:
    edge = Edge_hasKGFrame()
    edge.URI = f"http://example.org/edge/hasFrame/{entity_uri.split('/')[-1]}/{frame_uri.split('/')[-1]}"
    _set_props(edge, {
        "edgeSource": entity_uri,
        "edgeDestination": frame_uri,
    })
    return edge


def make_edge_has_slot(frame_uri: str, slot_uri: str) -> Edge_hasKGSlot:
    edge = Edge_hasKGSlot()
    edge.URI = f"http://example.org/edge/hasSlot/{frame_uri.split('/')[-1]}/{slot_uri.split('/')[-1]}"
    _set_props(edge, {
        "edgeSource": frame_uri,
        "edgeDestination": slot_uri,
    })
    return edge


def build_single_entity() -> List[GraphObject]:
    return [make_entity(1)]


def build_medium_list() -> List[GraphObject]:
    return [make_entity(i) for i in range(10)]


def build_bulk_list() -> List[GraphObject]:
    return [make_entity(i) for i in range(100)]


def build_complex_graph() -> List[GraphObject]:
    """Entity with 3 frames, each with 3 slots, plus all connecting edges."""
    objects = []
    entity = make_entity(1)
    objects.append(entity)
    for fi in range(3):
        frame = make_frame(1, fi)
        objects.append(frame)
        objects.append(make_edge_has_frame(str(entity.URI), str(frame.URI)))
        for si in range(3):
            slot = make_slot(1, fi, si)
            objects.append(slot)
            objects.append(make_edge_has_slot(str(frame.URI), str(slot.URI)))
    return objects


# ---------------------------------------------------------------------------
# Serialization / deserialization for each format
# ---------------------------------------------------------------------------

GRAPH_URI = "http://example.org/graph/benchmark"
ITERATIONS = 50  # per measurement


def bench_nquads_serialize(objects: List[GraphObject]) -> str:
    quads = graphobjects_to_quad_list(objects, GRAPH_URI)
    return quads_to_nquads_text(quads)


def bench_nquads_deserialize(text: str) -> List[GraphObject]:
    quads = nquads_text_to_quads(text)
    return quad_list_to_graphobjects(quads)


def bench_json_quads_serialize(objects: List[GraphObject]) -> str:
    quads = graphobjects_to_quad_list(objects, GRAPH_URI)
    resp = QuadResponse(total_count=len(objects), page_size=len(objects), offset=0, results=quads)
    return resp.model_dump_json()


def bench_json_quads_deserialize(json_str: str) -> List[GraphObject]:
    resp = QuadResponse.model_validate_json(json_str)
    return quad_list_to_graphobjects(resp.results)


# ---------------------------------------------------------------------------
# Timing helper
# ---------------------------------------------------------------------------

def time_fn(fn, *args, iterations=ITERATIONS) -> Tuple[float, float, float]:
    """Run fn(*args) `iterations` times and return (mean_ms, median_ms, min_ms)."""
    times = []
    result = None
    for _ in range(iterations):
        t0 = time.perf_counter()
        result = fn(*args)
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000)  # ms
    return statistics.mean(times), statistics.median(times), min(times), result


def gzip_size(data: str) -> int:
    return len(gzip.compress(data.encode('utf-8')))


# ---------------------------------------------------------------------------
# Run benchmarks
# ---------------------------------------------------------------------------

def run_benchmark(label: str, objects: List[GraphObject]):
    print(f"\n{'=' * 70}")
    print(f"  {label}  ({len(objects)} GraphObject(s))")
    print(f"{'=' * 70}")

    # --- Serialization ---
    mean, median, mn, nq_text = time_fn(bench_nquads_serialize, objects)
    nq_raw = len(nq_text.encode('utf-8'))
    nq_gz = gzip_size(nq_text)
    print(f"\n  N-Quads  serialize:    mean={mean:7.3f} ms  median={median:7.3f} ms  min={mn:7.3f} ms")

    mean, median, mn, jq_text = time_fn(bench_json_quads_serialize, objects)
    jq_raw = len(jq_text.encode('utf-8'))
    jq_gz = gzip_size(jq_text)
    print(f"  JSON Q   serialize:    mean={mean:7.3f} ms  median={median:7.3f} ms  min={mn:7.3f} ms")

    # --- Deserialization ---
    mean, median, mn, _ = time_fn(bench_nquads_deserialize, nq_text)
    print(f"\n  N-Quads  deserialize:  mean={mean:7.3f} ms  median={median:7.3f} ms  min={mn:7.3f} ms")

    mean, median, mn, _ = time_fn(bench_json_quads_deserialize, jq_text)
    print(f"  JSON Q   deserialize:  mean={mean:7.3f} ms  median={median:7.3f} ms  min={mn:7.3f} ms")

    # --- Payload size ---
    print(f"\n  Payload size (bytes):  {'Format':<12} {'Raw':>8}  {'Gzipped':>8}  {'Ratio':>6}")
    print(f"  {'':24} {'':>8}  {'':>8}  (vs NQ)")
    print(f"  {'N-Quads':<24} {nq_raw:>8,}  {nq_gz:>8,}  {1.0:>6.2f}x")
    print(f"  {'JSON Quads':<24} {jq_raw:>8,}  {jq_gz:>8,}  {jq_raw/nq_raw:>6.2f}x")


def main():
    print("=" * 70)
    print("  VitalGraph Serialization Format Benchmark")
    print(f"  Iterations per measurement: {ITERATIONS}")
    print("=" * 70)

    scenarios = [
        ("Single KGEntity", build_single_entity()),
        ("10 KGEntities (medium list)", build_medium_list()),
        ("100 KGEntities (bulk)", build_bulk_list()),
        ("Complex graph (entity + frames + slots + edges)", build_complex_graph()),
    ]

    for label, objects in scenarios:
        run_benchmark(label, objects)

    print(f"\n{'=' * 70}")
    print("  Benchmark complete.")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()

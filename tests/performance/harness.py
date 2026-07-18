"""Scaling-test harness — prove complexity class from query plans, not wall-clock.

The core idea (see planning/planning_performance/scaling_test_strategy.md §3):
you don't need a billion rows to prove a query is O(page) instead of O(N). You
assert the *shape* of the plan and the *work counters* (buffers touched, rows
examined, spill) — these are size-independent and deterministic, so a change
that regresses (index scan → seq scan, bounded → unbounded buffers) fails the
assertion at 100K rows just as it would at 1B.

All helpers take an ``asyncpg`` connection and are async.
"""

from __future__ import annotations

import json
import math
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# EXPLAIN → plan tree
# ---------------------------------------------------------------------------

async def explain_json(conn, sql: str, *params, analyze: bool = True) -> Dict[str, Any]:
    """Run EXPLAIN (… FORMAT JSON) and return the root plan node dict.

    ``analyze=True`` (default) executes the query and captures BUFFERS/actual
    rows — required for work-counter assertions. Use ``analyze=False`` for a
    plan-shape-only check that must not run the query.
    """
    opts = "ANALYZE, BUFFERS, FORMAT JSON" if analyze else "FORMAT JSON"
    rows = await conn.fetch(f"EXPLAIN ({opts}) " + sql, *params)
    raw = rows[0][0]
    doc = json.loads(raw) if isinstance(raw, str) else raw
    # doc is a list with one element: {"Plan": {...}, "Planning Time": ...}
    return doc[0]


def _walk(node: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    """Yield the node and all descendants."""
    yield node
    for child in node.get("Plans", []) or []:
        yield from _walk(child)


def _root(plan: Dict[str, Any]) -> Dict[str, Any]:
    return plan["Plan"] if "Plan" in plan else plan


# ---------------------------------------------------------------------------
# Plan introspection
# ---------------------------------------------------------------------------

def total_shared_buffers(plan: Dict[str, Any]) -> int:
    """Total shared buffers touched (hit + read). Root node values are
    cumulative over the whole subtree in EXPLAIN BUFFERS."""
    r = _root(plan)
    return int(r.get("Shared Hit Blocks", 0)) + int(r.get("Shared Read Blocks", 0))


def shared_read_blocks(plan: Dict[str, Any]) -> int:
    """Blocks read from disk (the cold-cache cost)."""
    return int(_root(plan).get("Shared Read Blocks", 0))


def temp_written_blocks(plan: Dict[str, Any]) -> int:
    """Temp blocks written == sort/hash spilled to disk (should be 0 for
    bounded operations)."""
    return sum(int(n.get("Temp Written Blocks", 0)) for n in _walk(_root(plan)))


def node_types(plan: Dict[str, Any]) -> List[str]:
    return [n.get("Node Type", "") for n in _walk(_root(plan))]


def uses_index(plan: Dict[str, Any], index_name: Optional[str] = None) -> bool:
    """True if any node uses an index (optionally a specific one)."""
    for n in _walk(_root(plan)):
        idx = n.get("Index Name")
        if idx and (index_name is None or idx == index_name):
            return True
    return False


def has_seq_scan_on(plan: Dict[str, Any], relations: Sequence[str]) -> Optional[str]:
    """Return the first relation in `relations` that gets a Seq Scan, else None."""
    rels = set(relations)
    for n in _walk(_root(plan)):
        if n.get("Node Type") == "Seq Scan" and n.get("Relation Name") in rels:
            return n.get("Relation Name")
    return None


def has_node_type(plan: Dict[str, Any], node_type: str) -> bool:
    return any(n.get("Node Type") == node_type for n in _walk(_root(plan)))


def max_actual_rows(plan: Dict[str, Any]) -> int:
    """Largest per-node actual row count — how much data any operator handled."""
    return max((int(n.get("Actual Rows", 0)) for n in _walk(_root(plan))), default=0)


def index_only_heap_fetches(plan: Dict[str, Any]) -> int:
    """Sum of Heap Fetches on Index Only Scan nodes (0 == truly index-only)."""
    return sum(int(n.get("Heap Fetches", 0))
               for n in _walk(_root(plan)) if n.get("Node Type") == "Index Only Scan")


# ---------------------------------------------------------------------------
# The assertion
# ---------------------------------------------------------------------------

async def assert_plan(
    conn,
    sql: str,
    *params,
    must_use_index: Optional[str] = None,
    no_seq_scan_on: Sequence[str] = (),
    max_shared_buffers: Optional[int] = None,
    no_spill: bool = True,
    index_only: bool = False,
    max_actual_rows_bound: Optional[int] = None,
) -> Dict[str, Any]:
    """Assert the plan's *shape and work* — the size-independent scaling gate.

    - ``must_use_index``: an index (name) must appear in the plan (None = any index ok if given).
    - ``no_seq_scan_on``: none of these relations may get a Seq Scan.
    - ``max_shared_buffers``: total buffers touched must be under this bound
      (proves O(page) rather than O(N) — the key check).
    - ``no_spill``: no sort/hash may spill to temp files.
    - ``index_only``: the driving scan must be Index Only with 0 heap fetches.
    - ``max_actual_rows_bound``: no operator may handle more than this many rows
      (e.g. a paged query must not materialize the whole table).

    Returns the plan (for further ad-hoc checks / logging).
    """
    plan = await explain_json(conn, sql, *params, analyze=True)

    if must_use_index is not None:
        assert uses_index(plan, must_use_index), (
            f"expected index {must_use_index!r} in plan; node types={node_types(plan)}")

    if no_seq_scan_on:
        hit = has_seq_scan_on(plan, no_seq_scan_on)
        assert hit is None, f"unexpected Seq Scan on {hit!r}; node types={node_types(plan)}"

    if max_shared_buffers is not None:
        got = total_shared_buffers(plan)
        assert got <= max_shared_buffers, (
            f"shared buffers {got} exceeds bound {max_shared_buffers} "
            f"(O(N) creep?); node types={node_types(plan)}")

    if no_spill:
        spilled = temp_written_blocks(plan)
        assert spilled == 0, f"query spilled {spilled} temp blocks (unbounded sort/hash)"

    if index_only:
        assert has_node_type(plan, "Index Only Scan"), (
            f"expected an Index Only Scan; node types={node_types(plan)}")
        hf = index_only_heap_fetches(plan)
        assert hf == 0, f"Index Only Scan did {hf} heap fetches (not covering)"

    if max_actual_rows_bound is not None:
        got = max_actual_rows(plan)
        assert got <= max_actual_rows_bound, (
            f"an operator handled {got} rows (> {max_actual_rows_bound}); "
            f"paged query materializing too much? node types={node_types(plan)}")

    return plan


# ---------------------------------------------------------------------------
# Growth-curve / complexity-class check
# ---------------------------------------------------------------------------

def classify_growth(points: Dict[int, float]) -> str:
    """Classify how a metric grows with size N from a few (N, metric) points.

    Returns one of: "flat", "log", "linear", "superlinear". Used by growth_curve
    tests to assert an operation kept its complexity class as data grew.
    """
    items = sorted(points.items())
    if len(items) < 2:
        return "flat"
    (n0, m0), (n1, m1) = items[0], items[-1]
    if m0 <= 0:
        m0 = 1.0
    size_ratio = n1 / n0
    metric_ratio = m1 / m0
    if size_ratio <= 1:
        return "flat"
    # exponent p in metric ~ N^p  →  p = log(metric_ratio)/log(size_ratio)
    p = math.log(max(metric_ratio, 1e-9)) / math.log(size_ratio)
    if p < 0.15:
        return "flat"
    if p < 0.5:
        return "log"
    if p <= 1.2:
        return "linear"
    return "superlinear"


def assert_growth_class(points: Dict[int, float], allowed: Sequence[str]) -> str:
    cls = classify_growth(points)
    assert cls in allowed, (
        f"growth class {cls!r} not in allowed {list(allowed)}; points={points}")
    return cls


# ---------------------------------------------------------------------------
# Cold-cache measurement
# ---------------------------------------------------------------------------

async def measure_cold_vs_warm(conn, sql: str, *params) -> Tuple[int, int]:
    """Return (cold_read_blocks, warm_read_blocks) for `sql`.

    Best-effort locally: `DISCARD ALL` resets session state but NOT the shared
    buffer pool, so a truly cold pool needs a PG restart or eviction. What this
    reliably shows is the *first vs repeated* read pattern; for a real cold-pool
    measurement use the ephemeral vg-test container (clean DB each run) or an
    L3 run. See scaling_test_strategy.md §3.4.
    """
    await conn.execute("DISCARD ALL")
    p1 = await explain_json(conn, sql, *params, analyze=True)
    p2 = await explain_json(conn, sql, *params, analyze=True)
    return shared_read_blocks(p1), shared_read_blocks(p2)

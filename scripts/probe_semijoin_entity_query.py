"""Does the semi-join gate fire on the high-cardinality slot-value entity query?

`issues/040` shipped `semijoin.py`, whose gate was measured only on the
synthetic lead fixtures. `planning/planning_performance/high_cardinality_slot_value_query_plan.md`
is about a different, much larger shape: an entity query whose frame criteria go
through the edge-table rewrite, on a 22.4M-quad space. The gate should pass it —
the criterion matches ~96% of candidates — but nothing tested that, and the way
it fails is silent (it declines and falls back to the slow set-based plan).

Everything tenant-specific is read from the environment so it stays out of the
source. Run via scripts/probe_semijoin_entity_query.sh, which derives them from
the database.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DSN = os.environ["PROBE_DSN"]
SPACE = os.environ["PROBE_SPACE"]
GRAPH = os.environ["PROBE_GRAPH"]
ENTITY_TYPE = os.environ["PROBE_ENTITY_TYPE"]
FRAME_TYPE = os.environ["PROBE_FRAME_TYPE"]
SLOT_TYPE = os.environ["PROBE_SLOT_TYPE"]
SLOT_VALUE = os.environ["PROBE_SLOT_VALUE"]
# Optional outer frame. The lead-fixture criteria nest two frame levels; the
# production query has one. That difference is what this probe isolates.
PARENT_FRAME = os.environ.get("PROBE_PARENT_FRAME_TYPE") or None
SLOT_CLASS = os.environ.get("PROBE_SLOT_CLASS") or None
COMPARATOR = os.environ.get("PROBE_COMPARATOR", "eq")
SIDECAR = os.environ.get("PROBE_SIDECAR", "http://localhost:7070")
PAGE_SIZE = int(os.environ.get("PROBE_PAGE_SIZE", "50"))

KGURI_SLOT = "http://vital.ai/ontology/haley-ai-kg#KGURISlot"


class Capture(logging.Handler):
    """Collect the gate's own decision lines rather than inferring them."""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


async def main() -> int:
    import asyncpg
    from vitalgraph.sparql.kg_query_builder import (
        KGQueryCriteriaBuilder, EntityQueryCriteria, FrameCriteria, SlotCriteria)
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.sparql_sql.generator import generate_sql

    cap = Capture()
    for name in ("vitalgraph.db.sparql_sql.semijoin",
                 "vitalgraph.db.sparql_sql.emit_slice"):
        lg = logging.getLogger(name)
        lg.setLevel(logging.DEBUG)
        lg.addHandler(cap)

    # Dump the tree the marking pass actually receives. Inferring the plan shape
    # from the emitted SQL is guesswork; this shows whether there is a JOIN node
    # to mark at all.
    # Optional: disable the edge-table rewrite, to measure what collapsing
    # 3 quads into 1 edge row is actually worth on this query.
    if os.environ.get("PROBE_NO_EDGE_REWRITE"):
        import vitalgraph.db.sparql_sql.rewrite_edge_table as RET
        RET.rewrite_edge_table = lambda plan, a, s: plan
        import vitalgraph.db.sparql_sql.generator as _g
        _g.rewrite_edge_table = getattr(_g, "rewrite_edge_table", None)

    from vitalgraph.db.sparql_sql import semijoin as sj_mod
    seen_tree = []

    def _dump(node, depth=0):
        if node is None or depth > 12:
            return
        extra = ""
        if getattr(node, "tables", None):
            extra = f"  tables={len(node.tables)}"
        seen_tree.append("  " * depth + f"{node.kind}{extra}")
        for c in (node.children or []):
            _dump(c, depth + 1)

    # generator.py imports the symbol inside the function, so patch it at its
    # source module rather than on the generator.
    _real_mark = sj_mod.mark_semijoins

    def _wrapped(plan, aliases=None):
        _dump(plan)
        return _real_mark(plan, aliases)

    sj_mod.mark_semijoins = _wrapped

    value = SLOT_VALUE
    if COMPARATOR in ("gte", "gt", "lte", "lt"):
        value = float(SLOT_VALUE)
    inner = FrameCriteria(
        frame_type=FRAME_TYPE,
        negate=False,
        slot_criteria=[SlotCriteria(
            slot_type=SLOT_TYPE,
            slot_class_uri=SLOT_CLASS or KGURI_SLOT,
            value=value,
            comparator=COMPARATOR)])
    top = (FrameCriteria(frame_type=PARENT_FRAME, frame_criteria=[inner])
           if PARENT_FRAME else inner)

    criteria = EntityQueryCriteria(
        entity_type=ENTITY_TYPE,
        entity_uris=None,
        frame_criteria=[top],
        use_edge_pattern=True)

    builder = KGQueryCriteriaBuilder()
    count_mode = os.environ.get("PROBE_COUNT")
    if count_mode:
        # "cap" mirrors include_total_count=yes (TOTAL_COUNT_CAP), "exact"
        # mirrors include_total_count=exact.
        count_cap = None if count_mode == "exact" else 1000
        sparql = builder.build_entity_count_query_sparql(criteria, GRAPH, count_cap)
    else:
        sparql = builder.build_entity_query_sparql(criteria, GRAPH, PAGE_SIZE, 0)

    client = AsyncSidecarClient(SIDECAR)
    try:
        raw = await client.compile(sparql)
    finally:
        close = getattr(client, "aclose", None) or getattr(client, "close", None)
        if close:
            res = close()
            if hasattr(res, "__await__"):
                await res

    cr = map_compile_response(raw)
    if not cr.ok:
        print("COMPILE FAILED:", cr.error)
        print(sparql)
        return 2

    conn = await asyncpg.connect(DSN, command_timeout=300)
    try:
        t0 = time.time()
        gen = await generate_sql(cr, SPACE, conn=conn)
        gen_ms = (time.time() - t0) * 1000
        sql = gen.sql

        fired = "EXISTS" in sql.upper()
        print(f"generation: {gen_ms:.0f} ms")
        print(f"semijoin emitted: {fired}")
        print("plan tree as mark_semijoins saw it:")
        for line in seen_tree:
            print("   ", line)
        print("gate log:")
        for line in cap.lines:
            print("   ", line)

        print("\n--- SQL ---")
        print(sql)

        if os.environ.get("PROBE_PLAN"):
            # Plain EXPLAIN — no ANALYZE, so it returns instantly even when the
            # query would take minutes. This is how to find the cliff without
            # paying for it.
            for r in await conn.fetch("EXPLAIN " + sql):
                print(r[0])
            return 0

        if os.environ.get("PROBE_EXPLAIN"):
            rows = await conn.fetch(
                "EXPLAIN (ANALYZE, BUFFERS, SETTINGS) " + sql)
            for r in rows:
                print(r[0])
            return 0

        if os.environ.get("PROBE_VERIFY"):
            # Set equality, not just counts: the earlier two-phase bug returned
            # the right NUMBER of rows from the wrong set, and only comparing
            # membership caught it.
            import hashlib
            t0 = time.time()
            rows = await conn.fetch(sql)
            ms = (time.time() - t0) * 1000
            cols = list(rows[0].keys()) if rows else []
            key = next((c for c in ("v0__uuid", "entity__uuid", "v0", "entity")
                        if c in cols), cols[0] if cols else None)
            print(f"VERIFY: columns = {cols}")
            if key is None:
                print("VERIFY: no rows")
                return 0
            uuids = sorted(str(r[key]) for r in rows)
            digest = hashlib.md5("\n".join(uuids).encode()).hexdigest()
            print(f"\nVERIFY: {len(rows)} rows in {ms:.0f} ms")
            print(f"VERIFY: distinct entities = {len(set(uuids))}")
            print(f"VERIFY: keyed on {key}")
            dedup = hashlib.md5(
                "\n".join(sorted(set(uuids))).encode()).hexdigest()
            print(f"VERIFY: row-list md5 = {digest}")
            print(f"VERIFY: DEDUPED SET md5 = {dedup}")
            from collections import Counter
            dupes = [(u, n) for u, n in Counter(uuids).items() if n > 1]
            print(f"VERIFY: duplicated keys = {len(dupes)}, "
                  f"extra rows from duplication = {sum(n - 1 for _, n in dupes)}")
            for u, n in dupes[:3]:
                print(f"    {u} x{n}")
            return 0

        if os.environ.get("PROBE_SKIP_TIMING"):
            return 0
        print(f"needs_ordered_scan flag: {gen.needs_ordered_scan}")
        print("\n--- timing the page ---")
        for i in range(3):
            t0 = time.time()
            try:
                if gen.needs_ordered_scan and not os.environ.get("PROBE_NO_FENCE"):
                    async with conn.transaction():
                        await conn.execute("SET LOCAL enable_sort = off")
                        rows = await conn.fetch(sql)
                else:
                    rows = await conn.fetch(sql)
                val = (f" value={list(rows[0].values())[0]}"
                       if rows and os.environ.get("PROBE_COUNT") else "")
                print(f"  run {i+1}: {(time.time()-t0)*1000:.0f} ms, "
                      f"{len(rows)} rows{val}")
            except Exception as exc:
                print(f"  run {i+1}: FAILED after "
                      f"{(time.time()-t0)*1000:.0f} ms: {type(exc).__name__} {exc}")
                break
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

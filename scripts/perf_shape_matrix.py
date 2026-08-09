"""Sweep the KGQuery shape space and report where the engine misbehaves.

Why this exists
---------------
Five defects were found in one week, and every one was a dimension the benchmark
held constant:

    issues/045  rewrite never fired      entity type (always KGEntity)
    issues/046  duplicate rows           data multiplicity (no duplicate quads)
    issues/047  plan cliff               page size (always 25)
    range gate miss                      comparator (gate built on eq)
    10k vs 100k on different indexes     index configuration

That is not bad luck, it is the method: the suite measures one point in a large
space, so it can only certify that point. Meanwhile 2 of 15 comparators are
exercised anywhere in the tests, nesting depth is always exactly 2, and negate,
sort, vector, geo and FTS have no performance coverage at all.

This sweeps one factor at a time from a base shape, which finds *which*
dimensions matter for linear cost rather than the combinatorial explosion of
crossing them all. Dimensions shown to interact can then be crossed deliberately.

Two things are measured per cell, and the second is the one that matters
-----------------------------------------------------------------------
**Cost class**, from plain EXPLAIN. Never ANALYZE: past the issues/047 cliff a
query takes minutes, and the entire point is to detect that without paying for
it. Classification is by plan shape:

    ordered-probe   Unique/Limit directly over an ordered index scan — O(page)
    blocking        a Sort or HashAggregate between them — O(matches)
    set-based       no semi-join at all — O(matches) by construction
    no-plan         generation or planning failed

**Correctness**, differentially. Each cell runs twice — once normally, once with
the semi-join rewrite forced off — and the two result sets must be identical.
This needs no per-cell ground truth, which is what makes it possible to check
comparators nobody has manifest counts for. It is also the check that would have
caught issues/046: a rewrite returning the right *set* with the wrong row
multiplicity differs from the baseline, while any subset check passes.

Usage
-----
    python scripts/perf_shape_matrix.py --space sp_lead_synth_10k \\
        --graph urn:lead_synth_10k --out /tmp/matrix.md

    # plan classification only, no execution (fast, safe on any size)
    python scripts/perf_shape_matrix.py --space sp_lead_synth_100k \\
        --graph urn:lead_synth_100k --no-execute
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

NS = "urn:acme:kg"
KGENTITY = "http://vital.ai/ontology/haley-ai-kg#KGEntity"
SPECIFIC_ENTITY = f"{NS}:entity:Lead"
H = "http://vital.ai/ontology/haley-ai-kg#"

TEXT, DOUBLE, BOOL, INT, DATETIME, CHOICE = (
    H + "KGTextSlot", H + "KGDoubleSlot", H + "KGBooleanSlot",
    H + "KGIntegerSlot", H + "KGDateTimeSlot", H + "KGChoiceSlot")

# One representative slot per class: (slot name, value, parent frame, child frame).
#
# The frame path MATTERS and is not interchangeable. An earlier revision put
# every slot under CompanyFrame -> CompanyAddressFrame, where only the text slot
# actually lives; the other five matched nothing, so their plan classes described
# empty queries and the differential check compared empty sets to empty sets. A
# sweep that reports "0 mismatches" over vacuous cells is worse than no sweep.
# Paths below are read off the fixture's own slot URIs, which encode containment.
SLOTS = {
    TEXT:     ("CompanyStateCode", "CA",   "CompanyFrame",    "CompanyAddressFrame"),
    DOUBLE:   ("MQLRating",        65.0,   "LeadStatusFrame", "LeadStatusQualificationFrame"),
    BOOL:     ("MQLv2",            True,   "LeadStatusFrame", "LeadStatusQualificationFrame"),
    INT:      ("MQLRatingPoints",  50,     "LeadStatusFrame", "LeadStatusQualificationFrame"),
    DATETIME: ("CreatedDate", "2020-01-01T04:24:00",
                                           "LeadStatusFrame", "LeadStatusTimestampsFrame"),
    # Choice slots hold enum URIs, not bare labels — "Working" matched nothing.
    CHOICE:   ("LeadStatus", "urn:acme:kg:enum:LeadStatus:Working",
                                           "LeadStatusFrame", "LeadStatusCurrentFrame"),
}

# Which comparators are meaningful for which slot class. A comparator applied to
# a class it cannot serve is not a defect, so it is not swept there.
COMPARATORS = {
    "eq": [TEXT, DOUBLE, BOOL, INT, DATETIME, CHOICE],
    "ne": [TEXT, DOUBLE, BOOL, INT, CHOICE],
    "gt": [DOUBLE, INT, DATETIME],
    "gte": [DOUBLE, INT, DATETIME],
    "lt": [DOUBLE, INT, DATETIME],
    "lte": [DOUBLE, INT, DATETIME],
    "contains": [TEXT],
    "exists": [TEXT, DOUBLE],
    "not_exists": [TEXT, DOUBLE],
    "is_empty": [TEXT],
    "has": [TEXT, CHOICE],
    "has_any": [TEXT, CHOICE],
    "has_all": [TEXT, CHOICE],
    "not_has": [TEXT, CHOICE],
    "not_has_any": [TEXT, CHOICE],
}

# Page size for the differential check: large enough that both paths return the
# whole match set, so the comparison is of results rather than of pagination.
FULL_SET_LIMIT = 1_000_000

# Per-cell execution budget for the differential check.
CELL_TIMEOUT_S = 90

PARENT_FRAME = f"{NS}:frame:CompanyFrame"
CHILD_FRAME = f"{NS}:frame:CompanyAddressFrame"


@dataclass
class Cell:
    dimension: str
    value: str
    plan_class: str = "?"
    ordered_flag: bool = False
    cost: float = 0.0
    rows_ok: str = ""
    note: str = ""
    detail: dict = field(default_factory=dict)


def _slot(slot_class, comparator):
    name, value, parent, child = SLOTS[slot_class]
    if comparator in ("has_any", "has_all", "not_has_any"):
        value = [value]
    if comparator in ("exists", "not_exists", "is_empty"):
        value = None
    return name, value, parent, child


def build_criteria(comparator="eq", slot_class=TEXT, depth=2, negate=False):
    """Frame criteria for one cell, at the requested nesting depth."""
    from vitalgraph.model.kgentities_model import SlotCriteria, FrameCriteria

    name, value, parent, child = _slot(slot_class, comparator)
    slot = SlotCriteria(slot_type=f"{NS}:slot:{name}", slot_class_uri=slot_class,
                        value=value, comparator=comparator)
    inner = FrameCriteria(frame_type=f"{NS}:frame:{child}", slot_criteria=[slot],
                          negate=negate)
    if depth <= 1:
        # Depth 1 addresses the child frame directly. Production is 98% depth 1,
        # so this is the common shape, not an edge case.
        return [inner]
    return [FrameCriteria(frame_type=f"{NS}:frame:{parent}",
                          frame_criteria=[inner])]


def classify(plan_text: str) -> str:
    """Cost class from a plan. See the module docstring for the categories."""
    if "EXISTS" not in plan_text and "SubPlan" not in plan_text:
        return "set-based"
    for line in plan_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("->  Sort") or stripped.startswith("->  HashAggregate"):
            return "blocking"
    return "ordered-probe"


async def sql_for(conn, criteria, space, graph, entity_type, page_size, sidecar):
    from tests.performance.test_kgquery_generated_sql_plans import _to_builder_frame
    from vitalgraph.sparql.kg_query_builder import (
        KGQueryCriteriaBuilder, EntityQueryCriteria)
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.sparql_sql.generator import generate_sql

    ec = EntityQueryCriteria(
        entity_type=entity_type, entity_uris=None,
        frame_criteria=[_to_builder_frame(f) for f in criteria],
        use_edge_pattern=True)
    sparql = KGQueryCriteriaBuilder().build_entity_query_sparql(
        ec, graph, page_size, 0)

    client = AsyncSidecarClient(sidecar)
    try:
        raw = await client.compile(sparql)
    finally:
        close = getattr(client, "aclose", None) or getattr(client, "close", None)
        if close:
            r = close()
            if hasattr(r, "__await__"):
                await r
    cr = map_compile_response(raw)
    if not cr.ok:
        raise RuntimeError(f"compile failed: {cr.error}")
    gen = await generate_sql(cr, space, conn=conn)
    if not gen.ok:
        raise RuntimeError(f"generate failed: {gen.error}")
    return gen


async def run_cell(conn, cell: Cell, criteria, space, graph, entity_type,
                   page_size, sidecar, execute: bool) -> Cell:
    try:
        gen = await sql_for(conn, criteria, space, graph, entity_type,
                            page_size, sidecar)
    except Exception as exc:
        cell.plan_class, cell.note = "no-plan", f"{type(exc).__name__}: {exc}"[:110]
        return cell

    cell.ordered_flag = bool(gen.needs_ordered_scan)
    try:
        # EXPLAIN under the same fence the executor applies, or this classifies
        # a plan that never runs. Six cells were reported "blocking" on the
        # first pass purely because the sweep explained them unfenced.
        if gen.needs_ordered_scan:
            async with conn.transaction():
                await conn.execute("SET LOCAL enable_sort = off")
                plan = "\n".join(r[0] for r in await conn.fetch("EXPLAIN " + gen.sql))
        else:
            plan = "\n".join(r[0] for r in await conn.fetch("EXPLAIN " + gen.sql))
    except Exception as exc:
        cell.plan_class, cell.note = "no-plan", f"EXPLAIN: {exc}"[:110]
        return cell
    cell.plan_class = classify(plan)
    first = plan.splitlines()[0] if plan else ""
    if "cost=" in first:
        try:
            cell.cost = float(first.split("cost=")[1].split("..")[1].split()[0])
        except Exception:
            pass

    if not execute or cell.plan_class == "blocking":
        cell.rows_ok = "skipped" if cell.plan_class == "blocking" else "-"
        return cell

    # Differential correctness compares FULL result sets, not pages. The two
    # paths order differently — the rewrite pages by subject_uuid, the set-based
    # path by the entity's text — so their first N rows legitimately differ and
    # comparing pages reports a mismatch on every correct query. Comparing
    # everything, as sorted lists, catches both a wrong set and a wrong row
    # multiplicity (issues/046), which is the pair that matters.
    # Bounded per cell: one pathological shape should cost the sweep 90s, not
    # stall it. A cell that cannot finish is itself a finding.
    try:
        full_gen = await sql_for(conn, criteria, space, graph, entity_type,
                                 FULL_SET_LIMIT, sidecar)
        rows = await asyncio.wait_for(_fetch(conn, full_gen), CELL_TIMEOUT_S)
        import vitalgraph.db.sparql_sql.semijoin as sj
        saved = sj.MIN_SELECTIVITY
        sj.MIN_SELECTIVITY = 99.0          # gate can never pass -> baseline path
        try:
            base_gen = await sql_for(conn, criteria, space, graph, entity_type,
                                     FULL_SET_LIMIT, sidecar)
            base = await asyncio.wait_for(_fetch(conn, base_gen), CELL_TIMEOUT_S)
        finally:
            sj.MIN_SELECTIVITY = saved
        cell.detail = {"rows": len(rows), "baseline_rows": len(base)}
        # "OK" must mean "agreed on something". A cell where both sides return
        # nothing agrees trivially and proves nothing — that is how five of six
        # slot classes went unnoticed while the sweep reported no mismatches.
        # Vacuity is a distinct verdict, not a pass.
        if rows != base:
            cell.rows_ok = "MISMATCH"
        elif not rows:
            cell.rows_ok = "VACUOUS"
        else:
            cell.rows_ok = "OK"
        if rows != base:
            cell.note = (f"{len(rows)} rows vs {len(base)} baseline; "
                         f"distinct {len(set(rows))} vs {len(set(base))}")
    except asyncio.TimeoutError:
        cell.rows_ok = "TIMEOUT"
        cell.note = f"exceeded {CELL_TIMEOUT_S}s on a 10k-entity fixture"
    except Exception as exc:
        cell.rows_ok, cell.note = "ERROR", f"{type(exc).__name__}: {exc}"[:110]
    return cell


async def _fetch(conn, gen):
    """Run a generated query, fencing it exactly as the executor does."""
    if gen.needs_ordered_scan:
        async with conn.transaction():
            await conn.execute("SET LOCAL enable_sort = off")
            rows = await conn.fetch(gen.sql)
    else:
        rows = await conn.fetch(gen.sql)
    key = next((c for c in ("entity__uuid", "v0__uuid") if rows and c in rows[0].keys()), None)
    if key is None:
        return []
    return sorted(str(r[key]) for r in rows)


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--space", required=True)
    ap.add_argument("--graph", required=True)
    ap.add_argument("--dsn", default="postgresql://hadfield@localhost:5432/sparql_sql_graph")
    ap.add_argument("--sidecar", default=os.environ.get("VG_TEST_SIDECAR_URL",
                                                        "http://localhost:7070"))
    ap.add_argument("--out", default="/tmp/shape_matrix.md")
    ap.add_argument("--no-execute", action="store_true",
                    help="classify plans only; skip the differential check")
    ap.add_argument("--only", default=None, help="run one dimension by name")
    a = ap.parse_args()

    import asyncpg
    conn = await asyncpg.connect(a.dsn, command_timeout=600)
    execute = not a.no_execute
    cells: list[Cell] = []
    t0 = time.time()

    async def sweep(dim, value, **kw):
        if a.only and a.only != dim:
            return
        crit = build_criteria(**{k: v for k, v in kw.items()
                                 if k in ("comparator", "slot_class", "depth", "negate")})
        cell = Cell(dimension=dim, value=value)
        cell = await run_cell(conn, cell, crit, a.space, a.graph,
                              kw.get("entity_type", KGENTITY),
                              kw.get("page_size", 25), a.sidecar, execute)
        cells.append(cell)
        print(f"  {dim:14s} {value:34s} {cell.plan_class:14s} "
              f"{cell.rows_ok:9s} {cell.note}", flush=True)

    print("comparator x slot class")
    for comp, classes in COMPARATORS.items():
        for sc in classes:
            await sweep("comparator", f"{comp} / {sc.split('#')[1]}",
                        comparator=comp, slot_class=sc)

    print("entity type anchor")
    for label, et in (("generic KGEntity", KGENTITY), ("specific Lead", SPECIFIC_ENTITY)):
        await sweep("entity_type", label, entity_type=et)

    print("page size")
    for ps in (25, 50, 100, 250, 1000):
        await sweep("page_size", str(ps), page_size=ps)
        await sweep("page_size", f"{ps} (specific anchor)", page_size=ps,
                    entity_type=SPECIFIC_ENTITY)

    print("nesting depth")
    for d in (1, 2, 3):
        await sweep("depth", str(d), depth=d)

    print("negate")
    for n in (False, True):
        await sweep("negate", str(n), negate=n)

    await conn.close()

    lines = [f"# KGQuery shape matrix — {a.space}", "",
             f"{len(cells)} cells in {time.time()-t0:.0f}s. "
             f"Differential correctness {'ON' if execute else 'OFF'}.", "",
             "| dimension | value | plan class | fenced | correctness | note |",
             "|---|---|---|---|---|---|"]
    for c in cells:
        lines.append(f"| {c.dimension} | {c.value} | {c.plan_class} | "
                     f"{'yes' if c.ordered_flag else ''} | {c.rows_ok} | {c.note} |")
    counts: dict = {}
    for c in cells:
        counts[c.plan_class] = counts.get(c.plan_class, 0) + 1
    lines += ["", "## Summary", ""]
    for k, v in sorted(counts.items()):
        lines.append(f"- `{k}`: {v}")
    bad = [c for c in cells if c.rows_ok == "MISMATCH"]
    vac = [c for c in cells if c.rows_ok == "VACUOUS"]
    lines.append(f"- correctness mismatches: **{len(bad)}**")
    lines.append(f"- vacuous cells (both sides empty — proved nothing): "
                 f"**{len(vac)}**")
    if vac:
        lines += ["", "Vacuous cells are not passes. Either the test value "
                      "matches no data, or the comparator genuinely selects "
                      "nothing on this fixture:", ""]
        lines += [f"  - {c.dimension} / {c.value}" for c in vac]
    open(a.out, "w").write("\n".join(lines) + "\n")
    open(a.out.replace(".md", ".json"), "w").write(
        json.dumps([c.__dict__ for c in cells], indent=1, default=str))
    print(f"\nreport: {a.out}")
    print("summary:", counts, f"mismatches={len(bad)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

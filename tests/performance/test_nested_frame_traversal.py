"""Nested frames — `traversal_chain_plan.md` GAP 4, the shape nothing had seen.

Frames nest via `Edge_hasKGFrame` (frame -> frame), which is how the product
models a compound fact: a LeadStatusFrame carrying a LeadStatusQualificationFrame
beneath it. So a criterion routinely lives one level BELOW the frame that
connects two entities, and arbitrary depth is served by SPARQL property paths
through a recursive CTE capped at `emit_path.MAX_PATH_DEPTH = 5`.

Before this, none of it had been tested: zero `Edge_hasKGFrame` terms in any
loaded space, and `test_frame_nesting_hops.py` seeds raw edge-table rows with no
quads and no SPARQL, so it guards the index and nothing above it.

WHAT IS ASSERTED, AND WHY IT IS COUNTS RATHER THAN TIMINGS

The failure mode here is a WRONG ANSWER, not a slow one. A walk that truncates
at the cap returns strictly fewer rows and reads as success; a rewrite that
declines the nested hop returns a subset and reads as success. Neither is
visible without ground truth, so every assertion below is against the manifest.

A NOTE ON THE GROUND TRUTH, because getting it wrong here is easy and quiet.

`NESTED_CRITERIA` descends exactly ONE `Edge_hasKGFrame` hop. The manifest's
matching set must therefore be direct children only. The first version of this
fixture computed it at ANY depth — 11,536 frames against a query matching
9,065 — and a CORRECT engine returned 3 entities where the manifest said 4, on
one case in twelve. That reads as "the traversal silently drops rows", the most
alarming thing this suite can report, and it was entirely the fixture's. If a
case here fails, check that the manifest key and the query template ask the same
question before believing the engine is wrong.
"""

from __future__ import annotations

import pytest

from .conftest import skip_no_pg, space_exists
from .graph_fixtures import (NESTED_CRITERIA, SMALL, chain_query,
                             entity_indexes, nested_path_query)

pytestmark = [pytest.mark.performance, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]

# emit_path.py's cap. Named here so a change there fails this rather than
# silently shortening every path walk.
MAX_PATH_DEPTH = 5


async def _require(conn):
    if not SMALL.available:
        pytest.skip(f"{SMALL.manifest_path} not generated")
    if not await space_exists(conn, SMALL.space):
        pytest.skip(f"space {SMALL.space} not loaded")
    try:
        SMALL.nesting()
    except KeyError as exc:
        pytest.skip(str(exc))


async def _run(conn, sparql):
    """Generate SQL the way the server does and return the rows."""
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.sparql_sql.generator import generate_sql
    from .test_kgquery_growth_curve import SIDECAR_URL

    client = AsyncSidecarClient(SIDECAR_URL)
    try:
        raw = await client.compile(sparql)
    finally:
        close = getattr(client, "aclose", None) or getattr(client, "close", None)
        if close:
            res = close()
            if hasattr(res, "__await__"):
                await res
    cr = map_compile_response(raw)
    assert cr.ok, f"SPARQL failed to compile: {cr.error}\n{sparql}"
    gen = await generate_sql(cr, SMALL.space, conn=conn)
    assert gen.ok, f"SQL generation failed: {gen.error}\n{sparql}"
    return await conn.fetch(gen.sql), gen


async def test_the_fixture_actually_contains_nesting(perf_conn):
    """A suite that skips its own subject passes by asking nothing."""
    await _require(perf_conn)
    n = SMALL.nesting()
    assert n["n_nested_frames"] > 0
    deep = SMALL.deep_roots()
    assert deep, "no chain runs past MAX_PATH_DEPTH — the cap cannot be tested"
    reached = max(int(d) for v in deep.values() for d in v)
    assert reached > MAX_PATH_DEPTH, (
        f"deepest chain is {reached}, at or under the cap of {MAX_PATH_DEPTH}; "
        f"a truncating path walk would be indistinguishable from a correct one")


@pytest.mark.parametrize("depth", list(range(1, 9)))
async def test_explicit_hops_descend_past_the_path_cap(perf_conn, depth):
    """Written-out hops are not bounded by MAX_PATH_DEPTH, and must not be.

    Depths 6-8 are the ones that matter: they are past the cap, so if the
    recursive-CTE bound ever leaked into ordinary BGP emission this is where it
    would show, as a silently short answer.
    """
    await _require(perf_conn)
    deep = SMALL.deep_roots()
    checked = 0
    for root in sorted(deep, key=int)[:3]:
        expected = deep[root].get(str(depth), [])
        rows, _gen = await _run(perf_conn, nested_path_query(SMALL, int(root), depth))
        assert len(rows) == len(expected), (
            f"frame {root} at nesting depth {depth}: got {len(rows)}, "
            f"manifest says {len(expected)}")
        checked += 1
    assert checked, "no deep roots exercised"


@pytest.mark.parametrize("criterion", sorted(NESTED_CRITERIA))
@pytest.mark.parametrize("depth", [1, 2, 3])
async def test_traversal_with_the_criterion_one_level_down(perf_conn, criterion,
                                                           depth):
    """entity -> frame -> [child frame satisfying X] -> entity, at N hops.

    Structurally different from every criterion in `CRITERIA`: the value sits
    one Edge_hasKGFrame below the traversal edge, so a rewrite that quietly
    declines the nested hop still satisfies all of those and fails here.
    """
    await _require(perf_conn)
    template, manifest_key = NESTED_CRITERIA[criterion]
    for start in SMALL.sample_starts()[:4]:
        expected = SMALL.expected(manifest_key, start, depth)
        rows, _gen = await _run(
            perf_conn, chain_query(SMALL, start, depth, criterion=template))
        got = entity_indexes(rows)
        assert got == expected, (
            f"{criterion} from {start} at depth {depth}: "
            f"unexpected {sorted(got - expected)[:5]}, "
            f"missing {sorted(expected - got)[:5]}")


@pytest.mark.xfail(reason="the recursive CTE is not seeded from the pinned "
                          "start — see the docstring", strict=True)
async def test_a_pinned_property_path_seeds_the_recursion_from_the_pin(perf_conn):
    """A `+` path from a CONSTANT frame must not close over the whole graph.

    MEASURED 2026-08-15 and it is a real defect, though not the one GAP 4
    predicted. The prediction was that `MAX_PATH_DEPTH = 5` would silently
    TRUNCATE a deeper chain. It does not truncate — the query never completes:
    `(^hasEdgeSource/hasEdgeDestination)+` from one frame with 8 descendants did
    not finish in 60 s on the 10k fixture.

    The generated SQL says why. The recursive CTE's non-recursive term selects
    EVERY edge pair in the space (EXPLAIN: a parallel Gather over 46,911 rows,
    estimated 49,661 for the Recursive Union), and the pin lands in the OUTER
    WHERE — literally 3,185 characters after the CTE closes:

        WHERE p0.start_uuid = (SELECT term_uuid FROM ..._term
                               WHERE term_text = 'urn:graphsyn:frame:0' ...)

    So the transitive closure of all 144,598 edges is computed and then filtered
    down to one root. That is the same pathology the whole traversal-chain effort
    exists to remove — the pinned constant should DRIVE — in `emit_path.py`,
    which that work never touched.

    Asserted structurally rather than by running it: a timing assertion here
    costs 60 s per run to tell us something a string already proves, and the fix
    is exactly "put the pin in the base case".
    """
    await _require(perf_conn)
    from .graph_fixtures import EDGE_DEST, EDGE_SOURCE

    root = sorted(SMALL.deep_roots(), key=int)[0]
    uri = SMALL.frame_uri(int(root))
    sparql = f"""
    SELECT DISTINCT ?child WHERE {{ GRAPH <{SMALL.graph}> {{
        <{uri}> (^<{EDGE_SOURCE}>/<{EDGE_DEST}>)+ ?child .
    }} }}"""
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.sparql_sql.generator import generate_sql
    from .test_kgquery_growth_curve import SIDECAR_URL

    client = AsyncSidecarClient(SIDECAR_URL)
    try:
        raw = await client.compile(sparql)
    finally:
        close = getattr(client, "aclose", None) or getattr(client, "close", None)
        if close:
            res = close()
            if hasattr(res, "__await__"):
                await res
    cr = map_compile_response(raw)
    assert cr.ok, cr.error
    gen = await generate_sql(cr, SMALL.space, conn=perf_conn)
    assert gen.ok, gen.error

    body = _recursive_cte_body(gen.sql)
    assert body is not None, "no WITH RECURSIVE in a property-path query"
    assert uri in body, (
        "the recursive CTE does not reference the pinned start, so it closes "
        "over every edge in the space before filtering to one root")


def _recursive_cte_body(sql: str) -> str | None:
    """The text between `WITH RECURSIVE x(...) AS (` and its matching paren."""
    import re
    m = re.search(r"WITH RECURSIVE \w+\([^)]*\) AS \(", sql)
    if not m:
        return None
    depth, i = 0, m.end() - 1
    while i < len(sql):
        if sql[i] == "(":
            depth += 1
        elif sql[i] == ")":
            depth -= 1
            if depth == 0:
                return sql[m.start():i]
        i += 1
    return None


@pytest.mark.parametrize("criterion", sorted(NESTED_CRITERIA))
async def test_the_nested_criterion_is_not_vacuous(perf_conn, criterion):
    """The negative-space check: a criterion matching NOTHING must return nothing.

    Result equality cannot see a dropped conjunct — if the nested criterion were
    ignored entirely, every case above would still pass wherever the unfiltered
    answer happens to coincide. Constraining on a value no nested frame carries
    makes that visible: the only correct answer is zero rows.
    """
    await _require(perf_conn)
    template, _key = NESTED_CRITERIA[criterion]
    bogus = template.replace('"alpha", "beta"', '"no-such-category"') \
                    .replace("?nsc{n} >= 50", "?nsc{n} >= 100000")
    if bogus == template:
        pytest.skip(f"{criterion} carries no value to falsify")
    start = SMALL.sample_starts()[0]
    rows, _gen = await _run(
        perf_conn, chain_query(SMALL, start, 2, criterion=bogus))
    assert not rows, (
        f"{criterion} with an unsatisfiable value returned {len(rows)} rows — "
        f"the nested criterion is not being applied")

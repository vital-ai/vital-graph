"""Nested frames — `traversal_chain_plan.md` GAP 4, the shape nothing had seen.

Frames nest via `Edge_hasKGFrame` (frame -> frame), which is how the product
models a compound fact: a LeadStatusFrame carrying a LeadStatusQualificationFrame
beneath it. So a criterion routinely lives one level BELOW the frame that
connects two entities, and arbitrary depth is served by SPARQL property paths
through a recursive CTE (`emit_path.MAX_PATH_DEPTH`, which is 100).

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
from .graph_fixtures import (NESTED_CRITERIA, NESTED_EDGE_TYPE, SMALL,
                             chain_query, entity_indexes, nested_path_query)

pytestmark = [pytest.mark.performance, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]

# How deep the fixture's forced chains run. Not emit_path's cap (that is 100)
# — this is the depth the fixture must exceed for a truncating walk to be
# distinguishable from a correct one at all.
DEEP_CHAIN_MIN = 5


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


async def test_the_space_holds_the_nesting_the_manifest_describes(perf_conn):
    """The guard that failed to guard (issues/099).

    `test_the_fixture_actually_contains_nesting` below reads the MANIFEST, which
    describes what the generator produced — not what the database under test
    holds. When the two disagreed, it passed and eighteen row-count assertions
    failed instead, looking exactly like a traversal regression.

    They disagreed because the fixture LOADER and this suite default to
    different PostgreSQL clusters (`VG_TEST_PG_PORT` 5433 vs 5432), so the
    fixture was seeded into one and read from the other, which happened to hold
    a stale space of the same name.

    This asks the space directly, and names the likely cause when it is wrong —
    because "0 nested edges" is not self-explanatory and cost a long
    investigation once.
    """
    await _require(perf_conn)
    expected = SMALL.nesting()["n_nested_frames"]
    actual = await perf_conn.fetchval(f"""
        SELECT count(*) FROM {SMALL.space}_rdf_quad q
        JOIN {SMALL.space}_term p ON q.predicate_uuid = p.term_uuid
        JOIN {SMALL.space}_term o ON q.object_uuid = o.term_uuid
        WHERE p.term_text = 'http://vital.ai/ontology/vital-core#vitaltype'
          AND o.term_text = '{NESTED_EDGE_TYPE}'
    """)
    assert actual == expected, (
        f"{SMALL.space} holds {actual} nested-frame edges, manifest says "
        f"{expected}. The space and the manifest describe different data — "
        f"most likely the fixture was loaded into a different cluster from the "
        f"one these tests read (VG_TEST_PG_PORT defaults to 5433 in the loaders "
        f"and 5432 here). Reload it into this one; see issues/099.")


async def test_the_fixture_actually_contains_nesting(perf_conn):
    """A suite that skips its own subject passes by asking nothing."""
    await _require(perf_conn)
    n = SMALL.nesting()
    assert n["n_nested_frames"] > 0
    deep = SMALL.deep_roots()
    assert deep, "no chain runs deep enough to expose truncation"
    reached = max(int(d) for v in deep.values() for d in v)
    assert reached > DEEP_CHAIN_MIN, (
        f"deepest chain is {reached}, at or under {DEEP_CHAIN_MIN}; "
        f"a truncating path walk would be indistinguishable from a correct one")


@pytest.mark.parametrize("depth", list(range(1, 9)))
async def test_explicit_hops_descend_past_the_path_cap(perf_conn, depth):
    """Written-out hops are not bounded by any recursive-CTE cap, and must not be.

    Depths 6-8 are the ones that matter: if a recursive-CTE bound ever leaked
    into ordinary BGP emission this is where it would show, as a silently short
    answer.
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


async def test_a_pinned_property_path_seeds_the_recursion_from_the_pin(perf_conn):
    """A `+` path from a CONSTANT frame must not close over the whole graph.

    FOUND AND FIXED 2026-08-15, and it was not the defect GAP 4 predicted. The
    prediction was that the recursive CTE's depth cap would silently TRUNCATE a
    deeper chain. It did not truncate — the query never completed:
    `(^hasEdgeSource/hasEdgeDestination)+` from one frame with 8 nested
    descendants did not finish in 60 s on the 10k fixture. (`MAX_PATH_DEPTH` is
    100, not 5 as the plan doc had it, which is why nothing was ever truncated.)

    The generated SQL said why. The recursive CTE's non-recursive term selected
    EVERY edge pair in the space — EXPLAIN showed a parallel Gather over 46,911
    rows — and the pin landed in the OUTER WHERE, 3,185 characters after the CTE
    closed. So the transitive closure of all 144,598 edges was computed and then
    filtered to one root: the same pathology the whole traversal-chain effort
    exists to remove, in `emit_path.py`, which that work never touched.

    `emit_path` now hands a pinned subject down to `_path_to_sql`, which anchors
    the base term. **60,000 ms -> 3-7 ms.**

    Asserted structurally as well as behaviourally: the structural check names
    the actual fix, so a refactor that keeps it fast for the wrong reason still
    has to keep the pin in the base case.
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

    # The seed goes on the BASE term only. If it were also applied to the
    # recursive term's `step` relation the walk would stop at the pin's direct
    # neighbours — fast, and wrong in the direction that looks like success.
    # The chain is 8 deep, so its deepest member is the proof it did not.
    depths = SMALL.deep_roots()[root]
    deepest_idx = max(depths, key=int)
    assert int(deepest_idx) > 1, "this root has no chain to walk"
    tail = SMALL.nested_frame_uri(depths[deepest_idx][0])
    rows = await perf_conn.fetch(gen.sql)
    reached = {v for r in rows for v in r.values() if isinstance(v, str)}
    assert tail in reached, (
        f"the walk did not reach depth {deepest_idx} ({tail}) — the recursion "
        f"is anchored but truncated, which returns a subset and reads as "
        f"success")


@pytest.mark.parametrize("quant", ["+", "*"])
async def test_a_tail_pinned_path_walks_backward_from_the_pin(perf_conn, quant):
    """`?x path+ <C>` — the ancestors of C, not the whole graph.

    The sibling of the pinned-subject case and NOT the same fix. Seeding the
    forward recursion by `end_uuid` anchors the last edge and then extends PAST
    the pin, so the answer contains paths that pass THROUGH C rather than
    ending at it — more rows, and no error. The recursion has to run the other
    way: base is the edges arriving at C, and each step prepends one.

    `*` needs the same reversal for a subtler reason. Its identity row is
    correctly (C, C) once pinned, but extending FORWARD from there returns C's
    DESCENDANTS — the opposite question, with a plausible row count.

    Checked against a hand-written anchored closure rather than against the
    unseeded plan, because a reversed walk can be fast and wrong in a way
    result-equality with a timeout cannot see. Measured 8-28 ms against a
    75 s timeout unseeded.
    """
    await _require(perf_conn)
    from .graph_fixtures import EDGE_DEST, EDGE_SOURCE

    deep = SMALL.deep_roots()
    root = sorted(deep, key=int)[0]
    depths = deep[root]
    tail = depths[max(depths, key=int)][0]
    uri = SMALL.nested_frame_uri(tail)

    truth = await perf_conn.fetchval(f"""
        WITH RECURSIVE
         src AS (SELECT term_uuid FROM {SMALL.space}_term WHERE term_text=$1),
         dst AS (SELECT term_uuid FROM {SMALL.space}_term WHERE term_text=$2),
         tgt AS (SELECT term_uuid FROM {SMALL.space}_term WHERE term_text=$3),
         step AS (SELECT a.object_uuid AS frm, b.object_uuid AS too
                  FROM {SMALL.space}_rdf_quad a
                  JOIN {SMALL.space}_rdf_quad b
                    ON b.subject_uuid = a.subject_uuid
                  WHERE a.predicate_uuid=(SELECT * FROM src)
                    AND b.predicate_uuid=(SELECT * FROM dst)),
         walk(n) AS (SELECT frm FROM step WHERE too=(SELECT * FROM tgt)
                     UNION SELECT s.frm FROM walk w JOIN step s ON s.too=w.n)
        SELECT count(*) FROM walk""", EDGE_SOURCE, EDGE_DEST, uri)
    assert truth > 1, "this pin has no ancestors, so the test proves nothing"

    sparql = f"""
    SELECT DISTINCT ?x WHERE {{ GRAPH <{SMALL.graph}> {{
        ?x (^<{EDGE_SOURCE}>/<{EDGE_DEST}>){quant} <{uri}> .
    }} }}"""
    rows, gen = await _run(perf_conn, sparql)
    expected = truth + (1 if quant == "*" else 0)   # `*` includes C itself
    assert len(rows) == expected, (
        f"tail-pinned {quant} returned {len(rows)}, closure says {expected}")

    body = _recursive_cte_body(gen.sql)
    assert body is not None and uri in body, (
        "the recursion is not anchored at the pinned object, so it closes over "
        "the whole graph before filtering")


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

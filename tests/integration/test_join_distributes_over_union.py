"""A join must not drop bindings, and distributing it must not drop rows.

TWO MECHANISMS, ONE INVARIANT
-----------------------------
The CORRECTNESS fix is in `emit_join`: a shared variable that one side may
leave unbound is projected with `COALESCE`, because SPARQL merges compatible
solutions so the BOUND value wins. That is what ships, and it is
shape-independent.

`rewrite_distribute_union` is a separate, currently UNWIRED optimisation. It is
worth 6.1x on a full result set and costs exactly 2.0000x on
`ORDER BY ... LIMIT`, which is the shape the reference query uses, so it is not
enabled by default. The tests here still exercise it directly, because its row
loss was subtle and worth keeping pinned.

`rewrite_distribute_union` rewrites `Join(Union(A,B), C)` into
`Union(Join(A,C), Join(B,C))` so each arm joins on the variables that arm
actually binds. The gain is that the arm's condition becomes a plain equality
instead of `(v IS NULL OR v = x)`, which is unindexable and therefore stops a
small driving set from reaching the other side (`issues/180`, `issues/183`).

WHY THIS FILE EXISTS
--------------------
The first working version of that rewrite silently dropped HALF the answer —
425 rows became 213 — and every unit test stayed green. The cause was renaming
the cloned subtree's aliases: they appear in `var_slots`, in the constraint
strings, in `leaf_terms`, in `range_leaves` AND in the parent join node, and
missing any one leaves part of an arm pointing at the other arm's tables. The
arm then matches nothing and contributes no rows.

Nothing about that is visible in a plan-shape assertion. It is only visible if
something COUNTS THE ROWS, which is what these do — by running the same query
with the rewrite on and off and comparing the results rather than the SQL.
"""

from __future__ import annotations

import pytest

from .conftest import skip_no_infra
from .test_frame_entity_collapse import (  # noqa: F401  (fixtures)
    collapse_space, seeded, EX, HALEY, VITAL, SRC_ROLE, DST_ROLE,
)

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]


def _union_query(graph: str) -> str:
    """A UNION whose branches bind DIFFERENT variables, joined to a shared BGP.

    This is the shape that produces a null-tolerant join: neither branch binds
    what the other does, and the BGP below binds both.
    """
    return f"""
    SELECT ?entity ?frame ?srcE ?dstE WHERE {{ GRAPH <{graph}> {{
      {{ ?srcE <{VITAL}vitaltype> <{HALEY}KGEntity> . BIND(?srcE AS ?entity) }}
      UNION
      {{ ?dstE <{VITAL}vitaltype> <{HALEY}KGEntity> . BIND(?dstE AS ?entity) }}
      ?se <{VITAL}hasEdgeSource> ?frame . ?se <{VITAL}hasEdgeDestination> ?ss .
      ?ss <{HALEY}hasKGSlotType> <{SRC_ROLE}> .
      ?ss <{HALEY}hasEntitySlotValue> ?srcE .
      ?de <{VITAL}hasEdgeSource> ?frame . ?de <{VITAL}hasEdgeDestination> ?ds .
      ?ds <{HALEY}hasKGSlotType> <{DST_ROLE}> .
      ?ds <{HALEY}hasEntitySlotValue> ?dstE .
    }} }}"""


async def _rows(pg_conn, space_id, sparql, distribute):
    """Result rows keyed by SPARQL VARIABLE, not by SQL column.

    The two forms assign different internal column names (`v4` here, `v15`
    there), so comparing raw rows compares the naming and not the answer. The
    first version of this test did exactly that and failed on identical
    results.
    """
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.sparql_sql.generator import generate_sql
    from vitalgraph.db.sparql_sql import rewrite_distribute_union as rdu
    from .conftest import SIDECAR_URL

    saved = rdu.distribute_join_over_union
    if not distribute:
        rdu.distribute_join_over_union = lambda plan, aliases: plan
    try:
        c = AsyncSidecarClient(base_url=SIDECAR_URL)
        cr = map_compile_response(await c.compile(sparql))
        await c.close()
        gen = await generate_sql(cr, space_id, conn=pg_conn)
        assert gen.ok, gen.error
        rows = await pg_conn.fetch(gen.sql)
    finally:
        rdu.distribute_join_over_union = saved

    by_name = {}
    for vid, name in (gen.var_map or {}).items():
        by_name.setdefault(name, []).append(vid)

    def val(r, name):
        for vid in by_name.get(name, []):
            if vid in r.keys() and r[vid] is not None:
                return str(r[vid])
        return None

    names = sorted(gen.sparql_vars or by_name)
    return {tuple(val(r, n) for n in names) for r in rows}, names


async def test_distribution_preserves_the_row_count(seeded, pg_conn):
    """Same rows, and every variable BOUND.

    Not "identical results": the undistributed form is the buggy one. It leaves
    a variable NULL on rows where the other UNION branch bound it — the join
    merges compatible solutions in its CONDITION but not in its PROJECTION
    (`issues/180`) — so distribution legitimately changes those values from
    NULL to the value the query bound.

    What must NOT change is HOW MANY rows there are. That is the assertion the
    425 -> 213 regression needed: it shipped with every unit test green because
    nothing counted rows.
    """
    space_id, graph = seeded
    q = _union_query(graph)

    on, names = await _rows(pg_conn, space_id, q, distribute=True)
    off, _ = await _rows(pg_conn, space_id, q, distribute=False)

    assert off, "the fixture produced no rows, so this proves nothing"
    assert len(on) == len(off), (
        f"distribution changed the row count: {len(on)} with it, {len(off)} "
        f"without. An arm that matches nothing looks exactly like this.")

    # And the reason it is allowed to differ at all: the distributed form binds
    # what the other form drops.
    nulls_on = sum(1 for r in on for v in r if v is None)
    nulls_off = sum(1 for r in off for v in r if v is None)
    assert nulls_on <= nulls_off, (
        f"distribution introduced unbound values: {nulls_on} NULLs with it "
        f"against {nulls_off} without")


async def test_distribution_binds_what_the_null_tolerant_join_drops(seeded, pg_conn):
    """The correctness half of `issues/180`, pinned.

    Every projected variable is bound by the query, so none should come back
    NULL. Before distribution they did, on the rows the other branch supplied.
    """
    space_id, graph = seeded
    on, names = await _rows(pg_conn, space_id, _union_query(graph),
                            distribute=True)
    unbound = {names[i] for r in on for i, v in enumerate(r) if v is None}
    assert not unbound, (
        f"these variables came back NULL although the query binds them: "
        f"{sorted(unbound)}")


async def test_every_branch_contributes(seeded, pg_conn):
    """Both arms must produce rows.

    Equality of result sets would still pass if BOTH forms lost the same arm.
    This pins the thing that broke: one arm silently matching nothing.
    """
    space_id, graph = seeded
    rows, names = await _rows(pg_conn, space_id, _union_query(graph),
                              distribute=True)
    ie, isrc, idst = names.index("entity"), names.index("srcE"), names.index("dstE")
    from_src = {r for r in rows if r[ie] == r[isrc] and r[ie] != r[idst]}
    from_dst = {r for r in rows if r[ie] == r[idst] and r[ie] != r[isrc]}
    assert from_src, "no rows came from the first UNION arm"
    assert from_dst, "no rows came from the second UNION arm"


async def test_shipped_path_binds_every_variable(seeded, pg_conn):
    """The CORRECTNESS fix, on the path that actually ships.

    No distribution: the null-tolerant ON clause is still there and is correct.
    What must not happen is the PROJECTION taking the unbound side — which is
    what produced 212 and 213 NULLs on the reference CONSTRUCT before
    `emit_join` learned to COALESCE a maybe-bound shared variable.
    """
    space_id, graph = seeded
    rows, names = await _rows(pg_conn, space_id, _union_query(graph),
                              distribute=False)
    assert rows, "the fixture produced no rows, so this proves nothing"
    unbound = {names[i] for r in rows for i, v in enumerate(r) if v is None}
    assert not unbound, (
        f"the shipped join path returned NULL for variables the query binds: "
        f"{sorted(unbound)}. SPARQL merges compatible solutions so the BOUND "
        f"value wins; the projection must COALESCE, not pass through.")

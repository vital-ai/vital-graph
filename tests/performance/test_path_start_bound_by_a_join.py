"""A property path started from a bound variable must cost what the walk costs.

`issues/124`. A recursive path seeds its base term only when the start is a URI
written literally in the query (`emit_path.py:143`,
`isinstance(subject, URINode)`). Reached through a preceding triple the start is
a `VarNode`, nothing seeds, and the recursion closes over the whole graph before
filtering — which is precisely what the comment at `emit_path.py:134` says
seeding exists to avoid.

Measured on `sp_lead_synth_100k` (50.5M quads) BEFORE the fix:

    same walk, start PINNED as a constant     34 rows      4.2 ms
    same walk, start BOUND by a join          did not finish in 120 s

and in raw SQL over the identical reachable set, 67,122 ms against 25.9 ms for
the same 53 results. It was not a slow query, it was an unusable one, and
nothing in the suite covered the shape — which is why it shipped.

AFTER (`emit_join` hands the left's output down as a seed):

    start PINNED     34 rows   3.7 ms     723 buffers
    start BOUND      53 rows   4.2 ms   1,345 buffers

Two starts, roughly twice one start's cost. That is the property below.

WHY THIS ASSERTS A RATIO AND NOT A TIME. Wall-clock is context here, not the
gate (`performance_regression_tracking_plan.md`). The property is that a walk
from N starts costs about N walks — cost scales with the STARTS, not with the
size of the graph. Both sides are measured in the same run on the same data, so
the number carries no absolute and needs no threshold anyone has to maintain.
The slack is deliberately loose: this catches "closes over the graph", not a
regression of a few percent.
"""

from __future__ import annotations

import pytest

from .conftest import skip_no_pg
from .lead_fixtures import SYNTH, require_usable
from .test_kgquery_growth_curve import SIDECAR_URL

pytestmark = [pytest.mark.performance, pytest.mark.slow, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]

VC = "http://vital.ai/ontology/vital-core#"
# One frame-nesting hop, as this data models it: an edge NODE carrying
# hasEdgeSource and hasEdgeDestination, so frame -> frame is inverse-then-forward.
HOP = f"(^<{VC}hasEdgeSource>/<{VC}hasEdgeDestination>)"
PROBE_TIMEOUT_MS = 60_000
# A bound start does more work than a pinned one — it walks from every frame the
# entity has, not one. Slack over that is generous on purpose; the failure this
# guards against is unbounded, not marginal.
SLACK = 8.0


async def _buffers(conn, sql):
    """Buffers for this plan, or None if it could not finish."""
    from .harness import explain_json, total_shared_buffers
    try:
        async with conn.transaction():
            await conn.execute(f"SET LOCAL statement_timeout = {PROBE_TIMEOUT_MS}")
            return total_shared_buffers(await explain_json(conn, sql))
    except Exception:
        return None


async def _gen(conn, space, sparql):
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.sparql_sql.generator import generate_sql

    client = AsyncSidecarClient(SIDECAR_URL)
    try:
        cr = map_compile_response(await client.compile(sparql))
        if not cr.ok:
            pytest.fail(f"SPARQL failed to compile: {cr.error}\n\n{sparql}")
        return await generate_sql(cr, space, conn=conn)
    finally:
        close = getattr(client, "aclose", None) or getattr(client, "close", None)
        if close:
            res = close()
            if hasattr(res, "__await__"):
                await res


async def test_a_path_started_from_a_bound_variable_costs_what_the_walk_costs(perf_conn):
    fx = [f for f in SYNTH if f.label == "100k"][0]
    reason = await require_usable(perf_conn, fx)
    if reason:
        pytest.skip(reason)

    # A real entity, and one of its frames, taken from the fixture rather than
    # hardcoded — the fixture is regenerated and URIs must not be assumed.
    row = await perf_conn.fetchrow(f"""
        SELECT te.term_text AS entity, tf.term_text AS frame
        FROM {fx.space}_edge e
        JOIN {fx.space}_term et ON et.term_uuid = e.edge_type_uuid
             AND et.term_text = 'http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame'
        JOIN {fx.space}_term te ON te.term_uuid = e.source_node_uuid
        JOIN {fx.space}_term tf ON tf.term_uuid = e.dest_node_uuid
        LIMIT 1""")
    if row is None:
        pytest.skip(f"{fx.space} has no entity->frame edges")
    entity, frame = row["entity"], row["frame"]

    # How many frames does that entity have? The bound walk starts from all of
    # them, so this is the factor the two sides legitimately differ by.
    n_starts = await perf_conn.fetchval(f"""
        SELECT count(*) FROM {fx.space}_edge e
        JOIN {fx.space}_term et ON et.term_uuid = e.edge_type_uuid
             AND et.term_text = 'http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame'
        JOIN {fx.space}_term te ON te.term_uuid = e.source_node_uuid
        WHERE te.term_text = $1""", entity) or 1

    pinned_sparql = (f'SELECT ?sub WHERE {{ GRAPH <{fx.graph}> {{ '
                     f'<{frame}> {HOP}* ?sub }} }}')
    bound_sparql = (f'SELECT ?sub WHERE {{ GRAPH <{fx.graph}> {{ '
                    f'?e <{VC}hasEdgeSource> <{entity}> . '
                    f'?e <{VC}hasEdgeDestination> ?f . '
                    f'?f {HOP}* ?sub }} }}')

    pinned = await _gen(perf_conn, fx.space, pinned_sparql)
    bound = await _gen(perf_conn, fx.space, bound_sparql)
    for label, gen in (("pinned", pinned), ("bound", bound)):
        if not gen.ok:
            pytest.skip(f"generation refused for the {label} form: "
                        f"{str(gen.error)[:120]}")

    pinned_buf = await _buffers(perf_conn, pinned.sql)
    if pinned_buf is None:
        pytest.skip("the PINNED walk did not finish, so there is no baseline "
                    "to compare against — a different problem from this one")

    bound_buf = await _buffers(perf_conn, bound.sql)

    assert bound_buf is not None, (
        f"the walk from a BOUND start did not finish in {PROBE_TIMEOUT_MS}ms, "
        f"while the same walk from a PINNED start cost {pinned_buf:,} buffers. "
        f"Not finishing is the failure this test exists for: the recursion is "
        f"closing over the graph instead of walking from the {n_starts} "
        f"start(s) it was given (issues/124).")

    budget = pinned_buf * n_starts * SLACK
    assert bound_buf <= budget, (
        f"a walk from {n_starts} bound start(s) cost {bound_buf:,} buffers "
        f"against {pinned_buf:,} for one pinned start — {bound_buf / pinned_buf:.0f}x "
        f"where at most {n_starts * SLACK:.0f}x is expected. Cost is scaling "
        f"with the GRAPH rather than with the starts (issues/124).")

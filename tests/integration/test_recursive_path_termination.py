"""A `*` path must terminate on cyclic data, and must not truncate deep ones.

`issues/123`. The recursive CTEs carry a `depth` column whose only consumer is
`WHERE r.depth < MAX_PATH_DEPTH` (`emit_path.py`). `UNION` deduplicates, which
is what normally terminates a transitive closure over a cycle — but because
`depth` is IN the tuple, `(s,e,1)` and `(s,e,2)` are different rows, the dedup
never fires, and the cap is what stops the recursion. Demonstrated in raw SQL
on a three-node cycle: 300 rows with the depth column, 9 without.

The cap then doubles as a hard limit on path LENGTH, which is `issues/122`: a
chain of 200 links reports 101 of them, silently.

These two tests pin both halves so the cap can be removed safely:

  * termination over a cycle — passes TODAY via the cap, and must keep passing
    when the cap goes, via dedup instead. It is a safety net for that change,
    not a failing test, and it has never existed before.
  * a chain longer than the cap — fails today, and is the reason to make the
    change.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from rdflib import URIRef

from .conftest import skip_no_infra, TEST_SPACE_PREFIX

pytestmark = [pytest.mark.integration, skip_no_infra,
              pytest.mark.asyncio(loop_scope="session")]

NEXT = "urn:rec:next"
GRAPH = "urn:rec:g"
SIDECAR = "http://localhost:7071"
STAR = f'SELECT ?n WHERE {{ GRAPH <{GRAPH}> {{ <urn:rec:START> <{NEXT}>* ?n }} }}'


async def _run(space_impl, space, sparql):
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.sparql_sql.generator import generate_sql

    client = AsyncSidecarClient(SIDECAR)
    try:
        cr = map_compile_response(await client.compile(sparql))
        assert cr.ok, f"compile failed: {cr.error}"
        async with space_impl.db_impl.connection_pool.acquire() as conn:
            gen = await generate_sql(cr, space, conn=conn)
            assert gen.ok, f"generation refused: {gen.error}"
            async with conn.transaction():
                await conn.execute("SET LOCAL statement_timeout = 60000")
                return await conn.fetch(gen.sql)
    finally:
        close = getattr(client, "aclose", None) or getattr(client, "close", None)
        if close:
            res = close()
            if hasattr(res, "__await__"):
                await res


@pytest_asyncio.fixture(loop_scope="session")
async def cycle_space(make_space):
    return await make_space(f"{TEST_SPACE_PREFIX}cyc_{uuid.uuid4().hex[:8]}")


@pytest_asyncio.fixture(loop_scope="session")
async def chain_space(make_space):
    return await make_space(f"{TEST_SPACE_PREFIX}chn_{uuid.uuid4().hex[:8]}")


async def test_a_star_path_terminates_over_a_cycle(space_impl, cycle_space):
    """A cycle must not hang, and each reachable node appears once."""
    g, p = URIRef(GRAPH), URIRef(NEXT)
    S = URIRef("urn:rec:START")
    b, c = URIRef("urn:rec:b"), URIRef("urn:rec:c")
    await space_impl.add_rdf_quads_batch_bulk(cycle_space, [
        (S, p, b, g), (b, p, c, g), (c, p, S, g)])           # START -> b -> c -> START

    rows = await _run(space_impl, cycle_space, STAR)
    got = {str(list(dict(r).values())[0]) for r in rows}

    # `*` is reflexive, so the start itself is included along with the cycle.
    assert got == {str(S), str(b), str(c)}, got
    assert len(rows) == len(got), (
        f"a cycle produced {len(rows)} rows for {len(got)} distinct nodes — the "
        f"recursion is revisiting nodes instead of deduplicating (issues/123)")


async def test_a_chain_longer_than_the_path_cap_is_not_truncated(space_impl, chain_space):
    """101 links must report 101 nodes, not stop at the cap.

    `MAX_PATH_DEPTH = 100` was chosen as a backstop for frame nesting, where a
    depth of 100 is beyond anything real. For a LINEAR structure — an
    `rdf:rest` chain, a linked list, any `next*` — the depth IS the length, so
    the cap becomes a silent size limit (`issues/122`).
    """
    g, p = URIRef(GRAPH), URIRef(NEXT)
    N = 150
    S = URIRef("urn:rec:START")
    quads = [(S, p, URIRef("urn:rec:n1"), g)]
    for i in range(1, N):
        quads.append((URIRef(f"urn:rec:n{i}"), p, URIRef(f"urn:rec:n{i+1}"), g))
    await space_impl.add_rdf_quads_batch_bulk(chain_space, quads)

    rows = await _run(space_impl, chain_space, STAR)
    got = {str(list(dict(r).values())[0]) for r in rows}

    # START plus n1..nN, reflexively.
    assert len(got) == N + 1, (
        f"a chain of {N} links reported {len(got)} nodes, not {N + 1}. The "
        f"recursion stopped at the depth cap and said nothing (issues/122, "
        f"issues/123).")

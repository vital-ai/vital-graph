"""A property-path alternation is a MULTISET union, and a closure still ends.

`issues/205`. `emit_path` emitted a deduplicating `UNION` for `PathAlt`, where
SPARQL 1.1 translates `X p1|p2 Y` to `Union(BGP(X p1 Y), BGP(X p2 Y))` and
SPARQL's Union preserves duplicates. Measured on a 7.4M-quad fixture,
`?s p|p ?o` returned 120,000 solutions where 240,000 is correct — solutions
dropped silently, with no error and a plausible count.

The fix is `UNION ALL`, and it is NOT safe everywhere, which is why these two
tests exist together. The header of `emit_path.py` records that the recursive
CTEs rely on dedup to TERMINATE a transitive closure over cyclic data —
"revisiting a pair adds no new row" — and documents a runaway from the one time
that property was accidentally defeated: "300 rows with the depth column, 9
without, and 9 is the correct answer."

So: duplicates preserved for a bare alternation, dedup kept beneath `+` and `*`.
The second test is the one nothing asserted before, and it is the one that would
catch a fix applied too broadly.
"""
from __future__ import annotations

import pytest
from rdflib import URIRef

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

EX = "http://ex.org/"
P = URIRef(f"{EX}p")
Q = URIRef(f"{EX}q")
N = [URIRef(f"{EX}n{i}") for i in range(3)]


async def _seed_cycle(space_impl, sid, graph):
    """A three-node cycle n0 -> n1 -> n2 -> n0, plus one q edge for alternation."""
    quads = [(N[i], P, N[(i + 1) % 3], graph) for i in range(3)]
    quads.append((N[0], Q, N[1], graph))
    await space_impl.add_rdf_quads_batch(sid, quads)


async def _rows(sparql_execute, sparql, sid):
    return await sparql_execute(sparql, sid)


@pytest.mark.asyncio(loop_scope="session")
async def test_bare_alternation_preserves_duplicates(make_space, space_impl,
                                                     sparql_execute):
    """`p|p` yields every solution TWICE — once per alternative branch."""
    sid = await make_space()
    graph = URIRef(f"urn:{sid}:g")
    await _seed_cycle(space_impl, sid, graph)

    single = await _rows(sparql_execute,
        f"SELECT * WHERE {{ GRAPH <{graph}> {{ ?s <{P}> ?o }} }}", sid)
    doubled = await _rows(sparql_execute,
        f"SELECT * WHERE {{ GRAPH <{graph}> {{ ?s <{P}>|<{P}> ?o }} }}", sid)

    assert len(single) == 3, f"expected the 3 cycle edges, got {len(single)}"
    assert len(doubled) == 2 * len(single), (
        f"`p|p` returned {len(doubled)} solutions against {len(single)} for `p`. "
        f"SPARQL's Union is a MULTISET union, so an alternation of the same "
        f"path yields each solution once per branch; deduplicating here drops "
        f"solutions silently (issues/205)")


@pytest.mark.asyncio(loop_scope="session")
async def test_closure_over_a_cycle_terminates_and_is_exact(make_space,
                                                            space_impl,
                                                            sparql_execute):
    """`p+` over a 3-cycle is 9 pairs, and `(p|p)+` is still 9.

    Nine because every node reaches every node including itself. The second
    query is the one that matters here: if the alternation beneath `+` stopped
    deduplicating, the closure would still terminate — the recursion has its own
    dedup — but this pins the COUNT, which is what a broken dedup changes first.
    """
    sid = await make_space()
    graph = URIRef(f"urn:{sid}:g")
    await _seed_cycle(space_impl, sid, graph)

    plus = await _rows(sparql_execute,
        f"SELECT * WHERE {{ GRAPH <{graph}> {{ ?s <{P}>+ ?o }} }}", sid)
    alt_plus = await _rows(sparql_execute,
        f"SELECT * WHERE {{ GRAPH <{graph}> {{ ?s (<{P}>|<{P}>)+ ?o }} }}", sid)

    assert len(plus) == 9, (
        f"`p+` over a three-node cycle should reach 9 pairs, got {len(plus)} — "
        f"the closure is either not terminating on the cycle or not complete")
    assert len(alt_plus) == 9, (
        f"`(p|p)+` returned {len(alt_plus)} against 9 for `p+`. An alternation "
        f"beneath a recursive operator must keep deduplicating, or the closure "
        f"multiplies rows per branch — the runaway emit_path.py's header records")

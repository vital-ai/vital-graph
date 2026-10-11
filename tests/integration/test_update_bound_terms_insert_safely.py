"""Integration: terms minted by a SPARQL UPDATE's bindings insert safely — issue 152.

`emit_update` inserts every NEW term the WHERE bindings produce in one
`INSERT ... SELECT FROM _upd_bindings`, guarded by `NOT EXISTS` rather than
`ON CONFLICT`. Two consequences the single-term path (`ON CONFLICT DO NOTHING`,
issues 003/019) was written to avoid:

* two binding rows that produce the SAME new term collide inside the one
  statement — `NOT EXISTS` is evaluated against the table as it was before the
  statement, so both rows pass it and the second violates the primary key;
* two concurrent updates can both pass `NOT EXISTS` for the same term, and the
  rows are inserted in whatever order the SELECT yields, which is the deadlock
  `issues/152` recorded and left open.
"""

from __future__ import annotations

import asyncio

import pytest
from rdflib import Literal, URIRef

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

G = "urn:test:t152:g"
P = "urn:test:t152:p"
Q = "urn:test:t152:q"


async def _seed(space_impl, space, n, tag):
    # Each test seeds under its OWN predicate, so its WHERE matches only its rows.
    quads = [(URIRef(f"urn:test:t152:{tag}:s{i}"), URIRef(f"{P}:{tag}"), Literal(f"{tag}-v{i}"), URIRef(G))
             for i in range(n)]
    await space_impl.add_rdf_quads_batch(space, quads)


async def test_one_new_term_bound_on_many_rows_inserts_once(test_space, space_impl, pg_conn):
    await _seed(space_impl, test_space, 5, "same")
    token = "minted-once-t152"
    ok = await space_impl.execute_sparql_update(test_space, f"""
        INSERT {{ GRAPH <{G}> {{ ?s <{Q}> ?n }} }}
        WHERE  {{ GRAPH <{G}> {{ ?s <{P}:same> ?o }} BIND("{token}" AS ?n) }}""")
    assert ok, "an update binding one new literal on five rows failed (duplicate term key)"
    terms = await pg_conn.fetchval(
        f"SELECT count(*) FROM {test_space}_term WHERE term_text = $1", token)
    quads = await pg_conn.fetchval(
        f"SELECT count(*) FROM {test_space}_rdf_quad q JOIN {test_space}_term t "
        f"ON t.term_uuid = q.object_uuid WHERE t.term_text = $1", token)
    assert terms == 1 and quads == 5


async def test_concurrent_updates_minting_the_same_terms_both_succeed(
        test_space, space_impl, pg_conn):
    await _seed(space_impl, test_space, 20, "conc")
    upd = f"""
        INSERT {{ GRAPH <{G}> {{ ?s <{Q}> ?n }} }}
        WHERE  {{ GRAPH <{G}> {{ ?s <{P}:conc> ?o }} BIND(CONCAT("conc-t152-", STR(?o)) AS ?n) }}"""
    # Several identical updates at once: each mints the same 20 terms, so
    # every pair races on every term.
    results = await asyncio.gather(
        *[space_impl.execute_sparql_update(test_space, upd) for _ in range(4)],
        return_exceptions=True)
    assert all(r is True for r in results), results
    n = await pg_conn.fetchval(
        f"SELECT count(*) FROM {test_space}_term WHERE term_text LIKE 'conc-t152-%'")
    assert n == 20

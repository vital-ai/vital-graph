"""An RDF graph is a set: re-asserting a quad must not add a second row.

SPARQL 1.1 Update: a triple "MAY be considered to be processed with no action if
that triple already exists in the graph". So (subject, predicate, object,
context) is unique by the data model, and the store has to enforce it.

It did not. `rdf_quad`'s primary key included `quad_uuid`, which defaults to
`gen_random_uuid()`, so an identical quad got a fresh key and never conflicted —
every `ON CONFLICT DO NOTHING` on that table was a no-op. Re-inserting an
existing quad returned `INSERT 0 1` and took its row count from 1 to 2.

Nothing failed loudly. The write path's own comment asserted the opposite
("ON CONFLICT DO NOTHING means a duplicate quad inserts no row, and counting it
would inflate rdf_stats") and built its stats-sync list on that belief, so the
duplicates were faithfully counted into rdf_stats as well — consistent, and
consistently wrong. 1,323 duplicate quads across 6 spaces, one of them in a
5.1M-quad space.

The fix is the key, not the insert: enforcing (s,p,o,c) makes the existing
`ON CONFLICT DO NOTHING` mean what it says, with no race and no read-before-write.
"""

from __future__ import annotations

import pytest
from rdflib import Literal, URIRef

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

GRAPH = URIRef("urn:test:setsem_graph")
S = URIRef("urn:test:setsem:subject")
P = URIRef("urn:test:setsem:pred")
O = URIRef("urn:test:setsem:object")


async def _count(conn, space_id, s, p, o, g) -> int:
    return await conn.fetchval(
        f"""
        SELECT count(*) FROM {space_id}_rdf_quad q
        JOIN {space_id}_term ts ON ts.term_uuid = q.subject_uuid   AND ts.term_text = $1
        JOIN {space_id}_term tp ON tp.term_uuid = q.predicate_uuid AND tp.term_text = $2
        JOIN {space_id}_term to_ ON to_.term_uuid = q.object_uuid  AND to_.term_text = $3
        JOIN {space_id}_term tg ON tg.term_uuid = q.context_uuid   AND tg.term_text = $4
        """, str(s), str(p), str(o), str(g))


class TestQuadSetSemantics:

    async def test_the_primary_key_is_the_quad_not_the_row(
        self, test_space, space_impl, pg_conn
    ):
        """(s,p,o,c) must be the key. quad_uuid in it defeats every dedup."""
        pk = await pg_conn.fetch("""
            SELECT a.attname
            FROM pg_constraint c
            JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
            WHERE c.conrelid = $1::regclass AND c.contype = 'p'
            ORDER BY array_position(c.conkey, a.attnum)
        """, f"{test_space}_rdf_quad")
        cols = [r["attname"] for r in pk]
        assert cols == ["subject_uuid", "predicate_uuid", "object_uuid",
                        "context_uuid"], (
            f"rdf_quad primary key is {cols}. With quad_uuid in the key an "
            f"identical quad gets a fresh key and never conflicts, so every "
            f"ON CONFLICT DO NOTHING on this table silently does nothing.")

    async def test_reinserting_the_same_quad_adds_no_row(
        self, test_space, space_impl, pg_conn
    ):
        quad = (S, P, O, GRAPH)
        await space_impl.add_rdf_quads_batch(test_space, [quad])
        first = await _count(pg_conn, test_space, *quad)
        assert first == 1, "the quad was not written at all"

        await space_impl.add_rdf_quads_batch(test_space, [quad])
        assert await _count(pg_conn, test_space, *quad) == 1, (
            "re-asserting an existing quad added a second row; an RDF graph is "
            "a set and INSERT DATA of a present triple is a no-op")

    async def test_a_duplicate_within_one_batch_collapses(
        self, test_space, space_impl, pg_conn
    ):
        """The same quad twice in ONE call is the likelier real-world shape.

        A caller assembling a batch from overlapping sources repeats a quad
        without ever calling twice, so the batch itself has to collapse.
        """
        s = URIRef("urn:test:setsem:batch_subject")
        quad = (s, P, O, GRAPH)
        await space_impl.add_rdf_quads_batch(test_space, [quad, quad, quad])
        assert await _count(pg_conn, test_space, *quad) == 1, (
            "three copies of one quad in a single batch produced more than one row")

    async def test_distinct_objects_are_still_distinct_quads(
        self, test_space, space_impl, pg_conn
    ):
        """Guard the guard: dedup must key on the whole quad, not part of it.

        A key that collapsed (s,p,c) would make this pass while destroying data,
        and multi-valued properties are ordinary in this model.
        """
        s = URIRef("urn:test:setsem:multi")
        await space_impl.add_rdf_quads_batch(test_space, [
            (s, P, Literal("one"), GRAPH),
            (s, P, Literal("two"), GRAPH),
        ])
        for val in ("one", "two"):
            assert await _count(pg_conn, test_space, s, P, Literal(val), GRAPH) == 1, (
                f"the {val!r} value was lost — dedup is keying on less than the "
                f"full quad and is destroying multi-valued properties")

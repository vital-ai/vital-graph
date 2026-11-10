"""`edge.edge_type_uuid` is kept equal to the edge's vitaltype (`issues/293`).

A query reads an edge's vitaltype off the column only in a space MARKED as
maintaining it (`sync_edge_table`). These pin the two rules that keep the mark
honest: the write path updates the type of an edge row that already exists, and
a SPARQL update that may change an edge's vitaltype (its edge sync runs after
it) unmarks the space.
"""

from __future__ import annotations

from vitalgraph.db.jena_sparql.jena_types import (
    QuadPattern, URINode, UpdateClear, UpdateDataDelete, UpdateDataInsert,
    UpdateModify, VarNode)
from vitalgraph.db.sparql_sql import sync_edge_table as se
from vitalgraph.db.sparql_sql.sparql_sql_space_impl import _may_change_an_edge_vitaltype

VT = URINode("http://vital.ai/ontology/vital-core#vitaltype")
NAME = URINode("http://vital.ai/ontology/vital-core#hasName")
S, O, G = URINode("urn:s"), URINode("urn:o"), URINode("urn:g")


def q(p, s=S):
    return QuadPattern(graph=G, subject=s, predicate=p, object=O)


class TestWhichUpdatesUnmarkTheSpace:

    def test_a_vitaltype_quad_does(self):
        assert _may_change_an_edge_vitaltype([UpdateDataInsert(quads=[q(VT)])])
        assert _may_change_an_edge_vitaltype([UpdateDataDelete(quads=[q(VT)])])
        assert _may_change_an_edge_vitaltype([UpdateModify(insert_quads=[q(VT)])])

    def test_a_variable_predicate_does_since_it_may_bind_vitaltype(self):
        assert _may_change_an_edge_vitaltype(
            [UpdateModify(delete_quads=[q(VarNode(name="p"))])])

    def test_an_operation_it_does_not_know_does(self):
        """CLEAR's edge cleanup also runs after the update: conservative."""
        assert _may_change_an_edge_vitaltype([UpdateClear(target="ALL")])

    def test_other_constant_predicates_do_not(self):
        """INSERT DATA / DELETE DATA of ordinary properties, the common case."""
        assert not _may_change_an_edge_vitaltype([UpdateDataInsert(quads=[q(NAME)])])
        assert not _may_change_an_edge_vitaltype(
            [UpdateModify(delete_quads=[q(NAME, VarNode(name="s"))],
                          insert_quads=[q(NAME, VarNode(name="s"))])])


class TestTheWritePathKeepsTheTypeInStep:

    def test_an_existing_edge_row_takes_the_current_type(self):
        """`DO NOTHING` kept a NULL for an edge typed in a later write, and the
        old type after an update changed it."""
        sql = se.EDGE_TYPE_ON_CONFLICT.format(t_edge="s_edge")
        assert sql.startswith("ON CONFLICT (edge_uuid, context_uuid) DO UPDATE")
        assert "edge_type_uuid = EXCLUDED.edge_type_uuid" in sql
        assert "source_node_uuid" not in sql, "the endpoints are left as they were"

    def test_both_inserting_paths_use_it_with_one_row_per_edge(self):
        """`DO UPDATE` may not touch one row twice in a statement, so the SELECT
        keeps one row per (edge, graph)."""
        import inspect
        for fn in (se.sync_edge_table_after_insert, se.backfill_edge_table):
            src = inspect.getsource(fn)
            assert "EDGE_TYPE_ON_CONFLICT" in src, fn.__name__
            assert "DISTINCT ON (src.subject_uuid, src.context_uuid)" in src, fn.__name__

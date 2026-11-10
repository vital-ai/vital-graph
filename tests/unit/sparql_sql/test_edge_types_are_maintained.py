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
    """The update keeps the edge table for its CONCRETE subjects and named
    CLEAR/DROP graphs inside its own transaction; only what that cannot reach
    unmarks the space."""

    V = VarNode(name="e")

    def test_a_where_bound_vitaltype_change_does(self):
        assert _may_change_an_edge_vitaltype(
            [UpdateModify(delete_quads=[q(VT, self.V)], insert_quads=[q(VT, self.V)])])
        assert _may_change_an_edge_vitaltype(
            [UpdateModify(delete_quads=[q(VarNode(name="p"), self.V)])])

    def test_unscoped_clear_and_unknown_operations_do(self):
        assert _may_change_an_edge_vitaltype([UpdateClear(target="ALL")])
        assert _may_change_an_edge_vitaltype([UpdateClear(target="DEFAULT")])

    def test_concrete_subjects_do_not_since_the_transaction_keeps_them(self):
        """INSERT DATA / DELETE DATA, the common SPARQL write: no contention on
        the marker row."""
        assert not _may_change_an_edge_vitaltype([UpdateDataInsert(quads=[q(VT)])])
        assert not _may_change_an_edge_vitaltype([UpdateDataDelete(quads=[q(VT)])])
        assert not _may_change_an_edge_vitaltype(
            [UpdateModify(delete_quads=[q(VarNode(name="p"))], insert_quads=[q(VT)])])

    def test_a_named_clear_does_not(self):
        assert not _may_change_an_edge_vitaltype([UpdateClear(graph="urn:g")])

    def test_other_predicates_on_variable_subjects_do_not(self):
        assert not _may_change_an_edge_vitaltype(
            [UpdateModify(delete_quads=[q(NAME, self.V)], insert_quads=[q(NAME, self.V)])])


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



class TestReconcileIsBatchedUnderRepeatableRead:

    def test_batches_in_repeatable_read_and_retries_a_conflict(self):
        """Under READ COMMITTED a row retyped concurrently was set back to the
        snapshot's type, then marked."""
        import inspect
        src = inspect.getsource(se.reconcile_edge_types)
        assert 'isolation="repeatable_read"' in src
        assert "SerializationError" in src
        assert se.RECONCILE_BATCH_ROWS <= 100_000

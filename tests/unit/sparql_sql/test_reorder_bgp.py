"""Unit tests for vitalgraph.db.sparql_sql.reorder_bgp — join reordering."""

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql.ir import TableRef
from vitalgraph.db.sparql_sql.reorder_bgp import reorder_joins


def _quad(alias: str) -> TableRef:
    return TableRef(ref_id=alias, kind="quad", table_name="rdf_quad", alias=alias)


class TestReorderJoins:

    def test_empty_tables(self):
        tables, on_map, first_conds = reorder_joins([], [])
        assert tables == []
        assert on_map == {}
        assert first_conds == []

    def test_single_table(self):
        tables = [_quad("q0")]
        constraints = [("q0", "q0.predicate_uuid = 'abc'::uuid")]
        ordered, on_map, first_conds = reorder_joins(tables, constraints)
        assert ordered == tables
        assert on_map == {}
        assert first_conds == ["q0.predicate_uuid = 'abc'::uuid"]

    def test_two_tables_connected(self):
        """q0 and q1 share a subject → no cartesian product."""
        tables = [_quad("q0"), _quad("q1")]
        constraints = [
            ("q0", "q0.predicate_uuid = '11111111-1111-1111-1111-111111111111'::uuid"),
            ("q1", "q1.predicate_uuid = '22222222-2222-2222-2222-222222222222'::uuid"),
            ("q1", "q1.subject_uuid = q0.subject_uuid"),
        ]
        ordered, on_map, first_conds = reorder_joins(tables, constraints)

        # Both tables should be in the result
        assert len(ordered) == 2
        aliases = [t.alias for t in ordered]
        assert "q0" in aliases
        assert "q1" in aliases

        # The join constraint should be on the later table
        all_on_conds = []
        for conds in on_map.values():
            all_on_conds.extend(conds)
        assert any("subject_uuid = q0.subject_uuid" in c for c in all_on_conds + first_conds)

    def test_text_filter_anchor(self):
        """Table with LIKE/ILIKE filter should become the chain root."""
        tables = [_quad("q0"), _quad("q1")]
        constraints = [
            ("q0", "q0.predicate_uuid = '11111111-1111-1111-1111-111111111111'::uuid"),
            ("q1", "q1.object_uuid IN (SELECT term_uuid FROM term WHERE term_text ILIKE '%hello%')"),
            ("q1", "q1.subject_uuid = q0.subject_uuid"),
        ]
        ordered, _, _ = reorder_joins(tables, constraints)

        # q1 should be first (text filter anchor)
        assert ordered[0].alias == "q1"

    def test_cardinality_tiebreaker(self):
        """When connectivity is tied, lower cardinality wins."""
        tables = [_quad("q0"), _quad("q1"), _quad("q2")]
        # q1 and q2 both connect to q0 equally
        constraints = [
            ("q0", "q0.predicate_uuid = '11111111-1111-1111-1111-111111111111'::uuid"),
            ("q1", "q1.predicate_uuid = '22222222-2222-2222-2222-222222222222'::uuid"),
            ("q1", "q1.subject_uuid = q0.subject_uuid"),
            ("q2", "q2.predicate_uuid = '33333333-3333-3333-3333-333333333333'::uuid"),
            ("q2", "q2.subject_uuid = q0.subject_uuid"),
        ]
        pred_stats = {
            "22222222-2222-2222-2222-222222222222": 1000,  # q1 high card
            "33333333-3333-3333-3333-333333333333": 10,    # q2 low card
        }
        ordered, _, _ = reorder_joins(tables, constraints, pred_stats=pred_stats)

        # q0 first (chain root), then q2 (lower cardinality) before q1
        aliases = [t.alias for t in ordered]
        assert aliases[0] == "q0"
        assert aliases.index("q2") < aliases.index("q1")

    def test_disconnected_tables_still_placed(self):
        """Tables with no cross-references are still placed (as cartesian product)."""
        tables = [_quad("q0"), _quad("q1")]
        constraints = [
            ("q0", "q0.predicate_uuid = '11111111-1111-1111-1111-111111111111'::uuid"),
            ("q1", "q1.predicate_uuid = '22222222-2222-2222-2222-222222222222'::uuid"),
        ]
        ordered, on_map, first_conds = reorder_joins(tables, constraints)
        assert len(ordered) == 2

    def test_three_table_chain(self):
        """q0 → q1 → q2: should order to minimize cartesian joins."""
        tables = [_quad("q0"), _quad("q1"), _quad("q2")]
        constraints = [
            ("q0", "q0.predicate_uuid = '11111111-1111-1111-1111-111111111111'::uuid"),
            ("q1", "q1.subject_uuid = q0.object_uuid"),
            ("q1", "q1.predicate_uuid = '22222222-2222-2222-2222-222222222222'::uuid"),
            ("q2", "q2.subject_uuid = q1.object_uuid"),
            ("q2", "q2.predicate_uuid = '33333333-3333-3333-3333-333333333333'::uuid"),
        ]
        ordered, on_map, first_conds = reorder_joins(tables, constraints)

        aliases = [t.alias for t in ordered]
        # q1 must come after q0, q2 must come after q1
        assert aliases.index("q0") < aliases.index("q1")
        assert aliases.index("q1") < aliases.index("q2")

    def test_constraint_assigned_to_latest_alias(self):
        """Constraints go on the ON clause of the last-placed alias they reference."""
        tables = [_quad("q0"), _quad("q1")]
        constraints = [
            ("q0", "q0.predicate_uuid = '11111111-1111-1111-1111-111111111111'::uuid"),
            ("q1", "q1.predicate_uuid = '22222222-2222-2222-2222-222222222222'::uuid"),
            ("q1", "q1.subject_uuid = q0.subject_uuid"),
        ]
        ordered, on_map, first_conds = reorder_joins(tables, constraints)

        # The cross-reference constraint should be on whichever is placed later
        # Since q0 is first by default, q1 gets the join constraint
        if ordered[0].alias == "q0":
            assert "q1" in on_map
            assert any("q0.subject_uuid" in c for c in on_map["q1"])

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

        # The ROOT is now the cheapest leaf, not the first one listed.
        #
        # This assertion used to read `aliases[0] == "q0"`, encoding the old
        # policy: root at quad_tables[0] and only use cardinality for placement
        # afterwards. That is what made the same KGQuery 8x slower depending on
        # the order the caller wrote its criteria in (issues/061) — same 20-table
        # join order both ways, different end of the chain to start from.
        #
        # q2 is 10 rows; q0's predicate has no entry in pred_stats, so it is
        # unknown and ranks last. Starting from 10 rows and joining outward is
        # the point of having the statistic at all.
        aliases = [t.alias for t in ordered]
        assert aliases[0] == "q2"
        assert aliases.index("q2") < aliases.index("q1")

    def test_text_filter_anchor_outranks_a_cheaper_leaf(self):
        """The text anchor wins even when another leaf reports fewer rows.

        The original rule was hardcoded and unconditional, and it stays that way.
        A LIKE/regex leaf rides the GIN trigram index but has no constant object,
        so it is absent from quad_stats entirely — ranking by cardinality would
        score it UNKNOWN and place it last, which is backwards for the one leaf
        known to be cheap to enter.

        The pre-existing test for this had no competing cardinality, so it would
        not have caught the two branches being swapped.
        """
        tables = [_quad("q0"), _quad("q1")]
        constraints = [
            ("q0", "q0.predicate_uuid = '11111111-1111-1111-1111-111111111111'::uuid"),
            ("q1", "q1.term_text ILIKE '%needle%'"),
        ]
        # q0 is reported as tiny; the text anchor must still root the chain.
        ordered, _, _ = reorder_joins(tables, constraints,
                                      leaf_cardinality={"q0": 1, "q1": 900000})
        assert ordered[0].alias == "q1"

    def test_root_is_the_cheapest_leaf(self):
        """Root selection is by row count, and ties keep list order."""
        tables = [_quad("q0"), _quad("q1"), _quad("q2")]
        constraints = [
            ("q0", "q0.predicate_uuid = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'::uuid"),
            ("q1", "q1.predicate_uuid = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'::uuid"),
            ("q1", "q1.subject_uuid = q0.subject_uuid"),
            ("q2", "q2.predicate_uuid = 'cccccccc-cccc-cccc-cccc-cccccccccccc'::uuid"),
            ("q2", "q2.subject_uuid = q0.subject_uuid"),
        ]
        cheap = reorder_joins(tables, constraints, pred_stats={
            "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa": 5000,
            "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb": 7,
            "cccccccc-cccc-cccc-cccc-cccccccccccc": 900,
        })[0]
        assert cheap[0].alias == "q1"

        # No statistics at all: unchanged from before, so a plan that cannot be
        # ranked is emitted byte-identically to how it always was.
        blind = reorder_joins(tables, constraints)[0]
        assert blind[0].alias == "q0"

    def test_structural_cardinality_beats_the_parsed_kind(self):
        """`leaf_cardinality` overrides what the constraint text would imply.

        The caller reads it from `plan.leaf_terms`, recorded at collect time. The
        SQL-parsing fallback cannot see a KGQuery's object constants at all —
        they arrive in a constraint that also references the joined alias, which
        its object branch skips — so every leaf reads as unknown and the root
        falls through to list position.
        """
        tables = [_quad("q0"), _quad("q1")]
        constraints = [
            ("q0", "q0.predicate_uuid = '11111111-1111-1111-1111-111111111111'::uuid"),
            ("q1", "q1.subject_uuid = q0.subject_uuid AND "
                   "q1.predicate_uuid = '22222222-2222-2222-2222-222222222222'::uuid AND "
                   "q1.object_uuid = '33333333-3333-3333-3333-333333333333'::uuid"),
        ]
        # Parsed: q1's object sits beside a join reference, so it is skipped.
        assert reorder_joins(tables, constraints)[0][0].alias == "q0"
        # Structural: q1 is 3 rows and roots the chain.
        ordered = reorder_joins(tables, constraints,
                                leaf_cardinality={"q0": 90000, "q1": 3})[0]
        assert ordered[0].alias == "q1"

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

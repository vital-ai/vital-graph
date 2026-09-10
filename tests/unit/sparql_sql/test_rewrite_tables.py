"""Unit tests for rewrite_edge_table.py and rewrite_frame_entity_table.py.

Tests the materialized-view (MV) rewrite passes that collapse multi-quad
patterns into single optimized table lookups (edge table, frame_entity table).
"""

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql.ir import (
    PlanV2, TableRef, VarSlot, AliasGenerator,
    KIND_BGP, KIND_PROJECT, KIND_FILTER,
)
from vitalgraph.db.sparql_sql.rewrite_edge_table import (
    rewrite_edge_table,
    EDGE_SOURCE_URI, EDGE_DEST_URI,
    _remap_col_ref, _remap_constraint_sql,
)
from vitalgraph.db.sparql_sql.rewrite_frame_entity_table import (
    rewrite_frame_entity_table,
    SLOT_TYPE_URI, SLOT_VALUE_URI,
)

# SAMPLE role values, defined here rather than imported. They are
# `hasKGSlotType` OBJECT values — data a query supplies — and the rewrite no
# longer names any (`issues/183`). Any two distinct URIs exercise the same code
# path; these two are used because the reference queries happen to.
SOURCE_ENTITY_URI = "urn:hasSourceEntity"
DEST_ENTITY_URI = "urn:hasDestinationEntity"

SPACE = "test_space"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bgp_plan(tables, var_slots, tagged_constraints, constraints=None):
    """Build a minimal KIND_BGP PlanV2 with the given tables and constraints."""
    plan = PlanV2(kind=KIND_BGP)
    plan.tables = tables
    plan.var_slots = var_slots
    plan.tagged_constraints = tagged_constraints
    plan.constraints = constraints or [sql for _, sql in tagged_constraints]
    return plan


def _aliases_with_constants(const_map: dict) -> AliasGenerator:
    """Build an AliasGenerator with pre-loaded constants.

    const_map: {const_alias: (text, ttype)}
    """
    aliases = AliasGenerator()
    for alias, (text, ttype) in const_map.items():
        aliases.constants[(text, ttype, None, None)] = alias
    return aliases


# ===========================================================================
# rewrite_edge_table tests
# ===========================================================================

class TestRewriteEdgeTableDetection:
    """Tests for edge pair detection logic."""

    def test_no_bgp_passthrough(self):
        """Non-BGP plans pass through unchanged."""
        plan = PlanV2(kind=KIND_PROJECT)
        aliases = AliasGenerator()
        result = rewrite_edge_table(plan, aliases, SPACE)
        assert result.kind == KIND_PROJECT

    def test_empty_tables_passthrough(self):
        """BGP with no tables passes through."""
        plan = _make_bgp_plan([], {}, [])
        aliases = AliasGenerator()
        result = rewrite_edge_table(plan, aliases, SPACE)
        assert result.tables == []

    def test_no_edge_predicates_passthrough(self):
        """BGP without edge source/dest predicates passes through."""
        aliases = _aliases_with_constants({
            "c_0": ("http://example.org/someProperty", "U"),
        })
        tables = [
            TableRef(ref_id="q0", kind="quad", table_name=f"{SPACE}_rdf_quad", alias="q0"),
        ]
        tagged = [("q0", "q0.predicate_uuid = __CONST_c_0__")]
        plan = _make_bgp_plan(tables, {}, tagged)
        result = rewrite_edge_table(plan, aliases, SPACE)
        assert len(result.tables) == 1
        assert result.tables[0].kind == "quad"

    def test_detects_edge_pair_via_coref(self):
        """Detects edge pair when src/dst share subject_uuid via explicit constraint."""
        aliases = _aliases_with_constants({
            "c_0": (EDGE_SOURCE_URI, "U"),
            "c_1": (EDGE_DEST_URI, "U"),
        })
        tables = [
            TableRef(ref_id="q0", kind="quad", table_name=f"{SPACE}_rdf_quad", alias="q0"),
            TableRef(ref_id="q1", kind="quad", table_name=f"{SPACE}_rdf_quad", alias="q1"),
        ]
        tagged = [
            ("q0", "q0.predicate_uuid = __CONST_c_0__"),
            ("q1", "q1.predicate_uuid = __CONST_c_1__"),
            ("q0", "q0.subject_uuid = q1.subject_uuid"),
        ]
        var_slots = {
            "edge": VarSlot(name="edge", positions=[("q0", "subject_uuid"), ("q1", "subject_uuid")]),
            "src": VarSlot(name="src", positions=[("q0", "object_uuid")]),
            "dst": VarSlot(name="dst", positions=[("q1", "object_uuid")]),
        }
        plan = _make_bgp_plan(tables, var_slots, tagged)
        result = rewrite_edge_table(plan, aliases, SPACE)

        # Should replace 2 quads with 1 edge table
        edge_tables = [t for t in result.tables if t.kind == "edge"]
        quad_tables = [t for t in result.tables if t.kind == "quad"]
        assert len(edge_tables) == 1
        assert len(quad_tables) == 0
        assert edge_tables[0].table_name == f"{SPACE}_edge"

    def test_detects_edge_pair_via_var_slots(self):
        """Detects edge pair via var_slots transitive co-reference."""
        aliases = _aliases_with_constants({
            "c_0": (EDGE_SOURCE_URI, "U"),
            "c_1": (EDGE_DEST_URI, "U"),
        })
        tables = [
            TableRef(ref_id="q0", kind="quad", table_name=f"{SPACE}_rdf_quad", alias="q0"),
            TableRef(ref_id="q1", kind="quad", table_name=f"{SPACE}_rdf_quad", alias="q1"),
        ]
        tagged = [
            ("q0", "q0.predicate_uuid = __CONST_c_0__"),
            ("q1", "q1.predicate_uuid = __CONST_c_1__"),
            # No explicit co-reference constraint, but shared var_slot
        ]
        var_slots = {
            "edge": VarSlot(name="edge", positions=[("q0", "subject_uuid"), ("q1", "subject_uuid")]),
            "src": VarSlot(name="src", positions=[("q0", "object_uuid")]),
            "dst": VarSlot(name="dst", positions=[("q1", "object_uuid")]),
        }
        plan = _make_bgp_plan(tables, var_slots, tagged)
        result = rewrite_edge_table(plan, aliases, SPACE)

        edge_tables = [t for t in result.tables if t.kind == "edge"]
        assert len(edge_tables) == 1

    def test_no_pair_if_only_source(self):
        """Only hasEdgeSource without matching hasEdgeDestination → no rewrite."""
        aliases = _aliases_with_constants({
            "c_0": (EDGE_SOURCE_URI, "U"),
        })
        tables = [
            TableRef(ref_id="q0", kind="quad", table_name=f"{SPACE}_rdf_quad", alias="q0"),
        ]
        tagged = [("q0", "q0.predicate_uuid = __CONST_c_0__")]
        plan = _make_bgp_plan(tables, {}, tagged)
        result = rewrite_edge_table(plan, aliases, SPACE)
        assert all(t.kind == "quad" for t in result.tables)


class TestRewriteEdgeTableVarSlots:
    """Tests for variable position rewriting after edge rewrite."""

    def _do_rewrite(self):
        aliases = _aliases_with_constants({
            "c_0": (EDGE_SOURCE_URI, "U"),
            "c_1": (EDGE_DEST_URI, "U"),
        })
        tables = [
            TableRef(ref_id="q0", kind="quad", table_name=f"{SPACE}_rdf_quad", alias="q0"),
            TableRef(ref_id="q1", kind="quad", table_name=f"{SPACE}_rdf_quad", alias="q1"),
        ]
        tagged = [
            ("q0", "q0.predicate_uuid = __CONST_c_0__"),
            ("q1", "q1.predicate_uuid = __CONST_c_1__"),
            ("q0", "q0.subject_uuid = q1.subject_uuid"),
        ]
        var_slots = {
            "edge": VarSlot(name="edge", positions=[("q0", "subject_uuid"), ("q1", "subject_uuid")]),
            "src": VarSlot(name="src", positions=[("q0", "object_uuid")]),
            "dst": VarSlot(name="dst", positions=[("q1", "object_uuid")]),
        }
        plan = _make_bgp_plan(tables, var_slots, tagged)
        return rewrite_edge_table(plan, aliases, SPACE)

    def test_edge_var_remapped(self):
        result = self._do_rewrite()
        edge_slot = result.var_slots.get("edge")
        assert edge_slot is not None
        # Should point to edge table's edge_uuid
        assert any("edge_uuid" in col for _, col in edge_slot.positions)

    def test_src_var_remapped(self):
        result = self._do_rewrite()
        src_slot = result.var_slots.get("src")
        assert src_slot is not None
        assert any("source_node_uuid" in col for _, col in src_slot.positions)

    def test_dst_var_remapped(self):
        result = self._do_rewrite()
        dst_slot = result.var_slots.get("dst")
        assert dst_slot is not None
        assert any("dest_node_uuid" in col for _, col in dst_slot.positions)


class TestRewriteEdgeTableConstraints:
    """Tests for constraint rewriting after edge rewrite."""

    def _do_rewrite(self):
        aliases = _aliases_with_constants({
            "c_0": (EDGE_SOURCE_URI, "U"),
            "c_1": (EDGE_DEST_URI, "U"),
            "c_2": ("http://example.org/ctx", "U"),
        })
        tables = [
            TableRef(ref_id="q0", kind="quad", table_name=f"{SPACE}_rdf_quad", alias="q0"),
            TableRef(ref_id="q1", kind="quad", table_name=f"{SPACE}_rdf_quad", alias="q1"),
        ]
        tagged = [
            ("q0", "q0.predicate_uuid = __CONST_c_0__"),
            ("q1", "q1.predicate_uuid = __CONST_c_1__"),
            ("q0", "q0.subject_uuid = q1.subject_uuid"),
            ("q0", "q0.context_uuid = __CONST_c_2__"),
            ("q1", "q1.context_uuid = __CONST_c_2__"),
        ]
        var_slots = {
            "edge": VarSlot(name="edge", positions=[("q0", "subject_uuid"), ("q1", "subject_uuid")]),
        }
        plan = _make_bgp_plan(tables, var_slots, tagged)
        return rewrite_edge_table(plan, aliases, SPACE)

    def test_predicate_constraints_removed(self):
        result = self._do_rewrite()
        for _, sql in result.tagged_constraints:
            assert "predicate_uuid" not in sql

    def test_coref_constraint_removed(self):
        result = self._do_rewrite()
        for _, sql in result.tagged_constraints:
            assert "subject_uuid = " not in sql or "edge_uuid" in sql

    def test_context_constraints_deduplicated(self):
        result = self._do_rewrite()
        ctx_constraints = [sql for _, sql in result.tagged_constraints
                          if "context_uuid" in sql]
        # Two context constraints on same edge should dedup to one
        assert len(ctx_constraints) == 1


class TestRewriteEdgeTableRecursive:
    """Edge rewrite recurses into non-BGP children."""

    def test_recurses_into_children(self):
        aliases = _aliases_with_constants({
            "c_0": (EDGE_SOURCE_URI, "U"),
            "c_1": (EDGE_DEST_URI, "U"),
        })
        # Inner BGP with edge pair
        inner_tables = [
            TableRef(ref_id="q0", kind="quad", table_name=f"{SPACE}_rdf_quad", alias="q0"),
            TableRef(ref_id="q1", kind="quad", table_name=f"{SPACE}_rdf_quad", alias="q1"),
        ]
        inner_tagged = [
            ("q0", "q0.predicate_uuid = __CONST_c_0__"),
            ("q1", "q1.predicate_uuid = __CONST_c_1__"),
            ("q0", "q0.subject_uuid = q1.subject_uuid"),
        ]
        inner_var_slots = {
            "edge": VarSlot(name="edge", positions=[("q0", "subject_uuid"), ("q1", "subject_uuid")]),
        }
        inner_plan = _make_bgp_plan(inner_tables, inner_var_slots, inner_tagged)

        # Wrap in FILTER
        outer = PlanV2(kind=KIND_FILTER, children=[inner_plan])
        result = rewrite_edge_table(outer, aliases, SPACE)

        # The child BGP should have been rewritten
        child = result.children[0]
        edge_tables = [t for t in child.tables if t.kind == "edge"]
        assert len(edge_tables) == 1


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------

class TestRemapColRef:

    def test_known_alias(self):
        alias_map = {"q0": ("mv0", {"subject_uuid": "edge_uuid", "object_uuid": "source_node_uuid"})}
        assert _remap_col_ref("q0.subject_uuid", alias_map) == "mv0.edge_uuid"
        assert _remap_col_ref("q0.object_uuid", alias_map) == "mv0.source_node_uuid"

    def test_unknown_alias(self):
        alias_map = {"q0": ("mv0", {"subject_uuid": "edge_uuid"})}
        assert _remap_col_ref("q5.subject_uuid", alias_map) == "q5.subject_uuid"

    def test_null_mapping(self):
        alias_map = {"q0": ("mv0", {"predicate_uuid": None})}
        assert _remap_col_ref("q0.predicate_uuid", alias_map) == "q0.predicate_uuid"

    def test_no_dot(self):
        alias_map = {"q0": ("mv0", {"x": "y"})}
        assert _remap_col_ref("nodot", alias_map) == "nodot"


class TestRemapConstraintSql:

    def test_replaces_all_refs(self):
        alias_map = {
            "q0": ("mv0", {"subject_uuid": "edge_uuid", "object_uuid": "source_node_uuid"}),
        }
        sql = "q0.subject_uuid = q0.object_uuid"
        result = _remap_constraint_sql(sql, alias_map)
        assert result == "mv0.edge_uuid = mv0.source_node_uuid"

    def test_skips_none_mapping(self):
        alias_map = {"q0": ("mv0", {"predicate_uuid": None, "subject_uuid": "edge_uuid"})}
        sql = "q0.predicate_uuid = __CONST_c_0__"
        result = _remap_constraint_sql(sql, alias_map)
        # predicate_uuid mapping is None → not replaced
        assert "q0.predicate_uuid" in result


# ===========================================================================
# rewrite_frame_entity_table tests
# ===========================================================================

def _build_frame_pattern():
    """Build a full frame-entity pattern (6 tables: 2 edge + 2 slot_type + 2 slot_value).

    Returns (plan, aliases) ready for rewrite.
    """
    # Constant aliases must match regex c_\\d+ used in the rewrite module
    aliases = _aliases_with_constants({
        "c_10": (SLOT_TYPE_URI, "U"),
        "c_11": (SLOT_VALUE_URI, "U"),
        "c_12": (SOURCE_ENTITY_URI, "U"),
        "c_13": (DEST_ENTITY_URI, "U"),
    })

    # 2 edge tables (from prior edge rewrite)
    # edge0: frame → srcSlot
    # edge1: frame → dstSlot
    tables = [
        TableRef(ref_id="mv0", kind="edge", table_name=f"{SPACE}_edge", alias="mv0"),
        TableRef(ref_id="mv1", kind="edge", table_name=f"{SPACE}_edge", alias="mv1"),
        # slot_type quads
        TableRef(ref_id="q2", kind="quad", table_name=f"{SPACE}_rdf_quad", alias="q2"),
        TableRef(ref_id="q3", kind="quad", table_name=f"{SPACE}_rdf_quad", alias="q3"),
        # slot_value quads
        TableRef(ref_id="q4", kind="quad", table_name=f"{SPACE}_rdf_quad", alias="q4"),
        TableRef(ref_id="q5", kind="quad", table_name=f"{SPACE}_rdf_quad", alias="q5"),
    ]

    var_slots = {
        "frame": VarSlot(name="frame", positions=[
            ("mv0", "source_node_uuid"), ("mv1", "source_node_uuid"),
        ]),
        "srcSlot": VarSlot(name="srcSlot", positions=[
            ("mv0", "dest_node_uuid"), ("q2", "subject_uuid"), ("q4", "subject_uuid"),
        ]),
        "dstSlot": VarSlot(name="dstSlot", positions=[
            ("mv1", "dest_node_uuid"), ("q3", "subject_uuid"), ("q5", "subject_uuid"),
        ]),
        "srcEntity": VarSlot(name="srcEntity", positions=[("q4", "object_uuid")]),
        "dstEntity": VarSlot(name="dstEntity", positions=[("q5", "object_uuid")]),
    }

    tagged = [
        # slot_type predicates
        ("q2", "q2.predicate_uuid = __CONST_c_10__"),
        ("q3", "q3.predicate_uuid = __CONST_c_10__"),
        # slot_type objects (source vs dest)
        ("q2", "q2.object_uuid = __CONST_c_12__"),
        ("q3", "q3.object_uuid = __CONST_c_13__"),
        # slot_value predicates
        ("q4", "q4.predicate_uuid = __CONST_c_11__"),
        ("q5", "q5.predicate_uuid = __CONST_c_11__"),
    ]

    plan = _make_bgp_plan(tables, var_slots, tagged)
    return plan, aliases


class TestRewriteFrameEntityDetection:

    def test_non_bgp_passthrough(self):
        plan = PlanV2(kind=KIND_PROJECT)
        aliases = AliasGenerator()
        result = rewrite_frame_entity_table(plan, aliases, SPACE)
        assert result.kind == KIND_PROJECT

    def test_no_edge_tables_passthrough(self):
        """BGP without edge tables → no frame-entity rewrite possible."""
        aliases = _aliases_with_constants({
            "c_st": (SLOT_TYPE_URI, "U"),
        })
        tables = [
            TableRef(ref_id="q0", kind="quad", table_name=f"{SPACE}_rdf_quad", alias="q0"),
        ]
        tagged = [("q0", "q0.predicate_uuid = __CONST_c_st__")]
        plan = _make_bgp_plan(tables, {}, tagged)
        result = rewrite_frame_entity_table(plan, aliases, SPACE)
        assert all(t.kind == "quad" for t in result.tables)

    def test_detects_full_frame_pattern(self):
        """Full 6-table frame pattern is detected and collapsed."""
        plan, aliases = _build_frame_pattern()
        result = rewrite_frame_entity_table(plan, aliases, SPACE)

        fs_tables = [t for t in result.tables if t.kind == "frame_slot"]
        # One join per ARM — two here, because this fixture has two slots.
        assert len(fs_tables) == 2
        assert all(t.table_name == f"{SPACE}_frame_slot" for t in fs_tables)

    def test_removes_all_six_tables(self):
        """All 6 original tables are removed."""
        plan, aliases = _build_frame_pattern()
        original_count = len(plan.tables)
        assert original_count == 6

        result = rewrite_frame_entity_table(plan, aliases, SPACE)
        # 6 removed, one frame_slot join per arm added = 2 total
        assert len(result.tables) == 2

    def test_incomplete_pattern_no_rewrite(self):
        """Missing slot_value quad → no rewrite."""
        aliases = _aliases_with_constants({
            "c_20": (SLOT_TYPE_URI, "U"),
            "c_21": (SOURCE_ENTITY_URI, "U"),
            "c_22": (DEST_ENTITY_URI, "U"),
        })
        tables = [
            TableRef(ref_id="mv0", kind="edge", table_name=f"{SPACE}_edge", alias="mv0"),
            TableRef(ref_id="q2", kind="quad", table_name=f"{SPACE}_rdf_quad", alias="q2"),
        ]
        var_slots = {
            "frame": VarSlot(name="frame", positions=[("mv0", "source_node_uuid")]),
            "srcSlot": VarSlot(name="srcSlot", positions=[
                ("mv0", "dest_node_uuid"), ("q2", "subject_uuid"),
            ]),
        }
        tagged = [
            ("q2", "q2.predicate_uuid = __CONST_c_20__"),
            ("q2", "q2.object_uuid = __CONST_c_21__"),
        ]
        plan = _make_bgp_plan(tables, var_slots, tagged)
        result = rewrite_frame_entity_table(plan, aliases, SPACE)
        # No frame_entity table should be introduced
        assert not any(t.kind == "frame_slot" for t in result.tables)


class TestRewriteFrameEntityVarSlots:

    def test_frame_var_remapped(self):
        plan, aliases = _build_frame_pattern()
        result = rewrite_frame_entity_table(plan, aliases, SPACE)

        frame_slot = result.var_slots.get("frame")
        assert frame_slot is not None
        assert any(col == "frame_uuid" for _, col in frame_slot.positions)

    def test_entity_vars_remapped(self):
        plan, aliases = _build_frame_pattern()
        result = rewrite_frame_entity_table(plan, aliases, SPACE)

        src_slot = result.var_slots.get("srcEntity")
        assert src_slot is not None
        assert any(col == "entity_uuid" for _, col in src_slot.positions)

        dst_slot = result.var_slots.get("dstEntity")
        assert dst_slot is not None
        assert any(col == "entity_uuid" for _, col in dst_slot.positions)

    def test_slot_vars_removed(self):
        """Intermediate slot variables should lose their positions."""
        plan, aliases = _build_frame_pattern()
        result = rewrite_frame_entity_table(plan, aliases, SPACE)

        # srcSlot and dstSlot had positions on removed tables
        # After rewrite, their positions in removed tables are gone
        # They may or may not remain depending on whether any positions survive
        for slot_name in ("srcSlot", "dstSlot"):
            slot = result.var_slots.get(slot_name)
            if slot is not None:
                # Any remaining positions should NOT reference removed tables
                for ref_id, _ in slot.positions:
                    assert ref_id not in ("mv0", "mv1", "q2", "q3", "q4", "q5")


class TestRewriteFrameEntityRecursive:

    def test_recurses_into_children(self):
        plan, aliases = _build_frame_pattern()
        outer = PlanV2(kind=KIND_FILTER, children=[plan])
        result = rewrite_frame_entity_table(outer, aliases, SPACE)

        child = result.children[0]
        fs_tables = [t for t in child.tables if t.kind == "frame_slot"]
        assert len(fs_tables) == 2      # one per arm; the fixture has two slots


class TestRewriteFrameEntityProjectionGuard:
    """issues/178 — the collapse must not empty a variable the query reads.

    Since `issues/182` the SLOT variables survive the collapse: `frame_entity`
    carries `source_slot_uuid`/`dest_slot_uuid`, so `?srcSlot` is remapped
    rather than emptied and the guard has nothing to decline for. What can
    still be emptied is a variable bound only to a position the table has no
    column for — `edge.edge_uuid` is the live example, i.e. `?srcEdge`.

    These pin the DISCRIMINATION, not just the decline. A guard that always
    declined would pass the decline cases and destroy the optimisation, so the
    "still collapses" cases are what keep it honest.
    """

    @staticmethod
    def _under_project(project_vars, with_edge_var=False):
        plan, aliases = _build_frame_pattern()
        if with_edge_var:
            # `?srcEdge` — bound ONLY to a position frame_entity cannot express.
            plan.var_slots["srcEdge"] = VarSlot(
                name="srcEdge", positions=[("mv0", "edge_uuid")])
        root = PlanV2(kind=KIND_PROJECT)
        root.children = [plan]
        root.project_vars = project_vars
        return root, aliases

    def test_declines_when_an_emptied_var_is_projected(self):
        root, aliases = self._under_project(
            ["frame", "srcEntity", "srcEdge"], with_edge_var=True)
        result = rewrite_frame_entity_table(root, aliases, SPACE)

        bgp = result.children[0]
        assert not any(t.kind == "frame_slot" for t in bgp.tables), \
            "collapsed away a projected variable it has no column for"
        assert bgp.var_slots["srcEdge"].positions

    def test_declines_for_select_star(self):
        """project_vars=None means every variable is read."""
        root, aliases = self._under_project(None, with_edge_var=True)
        result = rewrite_frame_entity_table(root, aliases, SPACE)

        bgp = result.children[0]
        assert not any(t.kind == "frame_slot" for t in bgp.tables)

    def test_slot_vars_now_survive_the_collapse(self):
        """issues/182: projecting a slot no longer costs the collapse.

        Before the slot columns existed this DECLINED, trading the traversal
        table for correct output. Now it does both.
        """
        root, aliases = self._under_project(["frame", "srcEntity", "srcSlot"])
        result = rewrite_frame_entity_table(root, aliases, SPACE)

        bgp = result.children[0]
        assert any(t.kind == "frame_slot" for t in bgp.tables), \
            "declined even though frame_entity can now bind the slot"
        cols = [c for _, c in bgp.var_slots["srcSlot"].positions]
        assert "slot_uuid" in cols, f"slot bound to the wrong column: {cols}"

    def test_dst_slot_maps_to_its_own_arm(self):
        """Two slots must land on two different frame_slot joins."""
        root, aliases = self._under_project(["frame", "srcSlot", "dstSlot"])
        result = rewrite_frame_entity_table(root, aliases, SPACE)

        bgp = result.children[0]
        assert any(t.kind == "frame_slot" for t in bgp.tables)
        # Distinct ARMS, so distinct aliases — the role separates them now,
        # not two differently-named columns.
        src_al = {a for a, c in bgp.var_slots["srcSlot"].positions if c == "slot_uuid"}
        dst_al = {a for a, c in bgp.var_slots["dstSlot"].positions if c == "slot_uuid"}
        assert src_al and dst_al and src_al != dst_al, (src_al, dst_al)

    def test_still_collapses_when_slots_are_not_read(self):
        """The common shape — FRAME_UNION / RELATIONSHIPS, 25x per issues/051."""
        root, aliases = self._under_project(["frame", "srcEntity", "dstEntity"])
        result = rewrite_frame_entity_table(root, aliases, SPACE)

        bgp = result.children[0]
        assert any(t.kind == "frame_slot" for t in bgp.tables), \
            "declined a collapse that reads nothing the table cannot bind"

    def test_emptied_but_unread_var_is_still_dropped(self):
        """Only READ variables block the collapse, not every emptied one."""
        root, aliases = self._under_project(["frame"], with_edge_var=True)
        result = rewrite_frame_entity_table(root, aliases, SPACE)

        bgp = result.children[0]
        assert any(t.kind == "frame_slot" for t in bgp.tables)
        assert "srcEdge" not in bgp.var_slots

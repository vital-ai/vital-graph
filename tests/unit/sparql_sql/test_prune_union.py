"""Unit tests for vitalgraph.db.sparql_sql.prune_union — dead UNION branch pruning."""

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql.ir import (
    AliasGenerator, PlanV2, TableRef, VarSlot,
    KIND_BGP, KIND_UNION, KIND_JOIN, KIND_PROJECT,
)
from vitalgraph.db.sparql_sql.prune_union import prune_dead_union_branches


def _aliases_with_constants(resolved: dict, unresolved_cols: list) -> AliasGenerator:
    """Create an AliasGenerator with some resolved and unresolved constants."""
    gen = AliasGenerator()
    for col, uuid in resolved.items():
        # Register a constant and resolve it
        gen.constants[("resolved_text", "uri")] = col
        gen.resolved_constants[col] = uuid
    for col in unresolved_cols:
        gen.constants[(f"unresolved_{col}", "uri")] = col
        # Not adding to resolved_constants → marks as unresolved
    return gen


def _bgp_with_constraint(constraint: str, alias: str = "q0") -> PlanV2:
    """Create a BGP with a constraint string."""
    return PlanV2(
        kind=KIND_BGP,
        tables=[TableRef(ref_id=alias, kind="quad", table_name="rdf_quad", alias=alias)],
        constraints=[constraint],
    )


class TestPruneDeadUnionBranches:

    def test_no_unresolved_noop(self):
        """If all constants are resolved, no pruning occurs."""
        gen = AliasGenerator()
        gen.constants[("http://example.org", "uri")] = "c_0"
        gen.resolved_constants["c_0"] = "some-uuid"

        left = _bgp_with_constraint("q0.predicate_uuid = __CONST_c_0__")
        right = _bgp_with_constraint("q1.predicate_uuid = __CONST_c_0__", alias="q1")
        plan = PlanV2(kind=KIND_UNION, children=[left, right])

        result = prune_dead_union_branches(plan, gen)
        assert result.kind == KIND_UNION
        assert len(result.children) == 2

    def test_left_dead_right_survives(self):
        """Left branch has unresolved constant → replaced by right."""
        gen = _aliases_with_constants({"c_0": "uuid-0"}, ["c_1"])

        left = _bgp_with_constraint("q0.predicate_uuid = __CONST_c_1__")
        right = _bgp_with_constraint("q1.predicate_uuid = __CONST_c_0__", alias="q1")
        plan = PlanV2(kind=KIND_UNION, children=[left, right])

        result = prune_dead_union_branches(plan, gen)
        # UNION replaced in-place with surviving right child
        assert result.kind == KIND_BGP
        assert result.constraints == ["q1.predicate_uuid = __CONST_c_0__"]

    def test_right_dead_left_survives(self):
        """Right branch has unresolved constant → replaced by left."""
        gen = _aliases_with_constants({"c_0": "uuid-0"}, ["c_1"])

        left = _bgp_with_constraint("q0.predicate_uuid = __CONST_c_0__")
        right = _bgp_with_constraint("q1.predicate_uuid = __CONST_c_1__", alias="q1")
        plan = PlanV2(kind=KIND_UNION, children=[left, right])

        result = prune_dead_union_branches(plan, gen)
        assert result.kind == KIND_BGP
        assert result.constraints == ["q0.predicate_uuid = __CONST_c_0__"]

    def test_both_dead_unchanged(self):
        """Both branches dead → leave unchanged as safety measure."""
        gen = _aliases_with_constants({}, ["c_1", "c_2"])

        left = _bgp_with_constraint("q0.predicate_uuid = __CONST_c_1__")
        right = _bgp_with_constraint("q1.predicate_uuid = __CONST_c_2__", alias="q1")
        plan = PlanV2(kind=KIND_UNION, children=[left, right])

        result = prune_dead_union_branches(plan, gen)
        assert result.kind == KIND_UNION
        assert len(result.children) == 2

    def test_nested_union_pruning(self):
        """UNION(UNION(dead, alive), alive) → inner UNION pruned first."""
        gen = _aliases_with_constants({"c_0": "uuid-0"}, ["c_1"])

        inner_left = _bgp_with_constraint("q0.predicate_uuid = __CONST_c_1__")
        inner_right = _bgp_with_constraint("q1.predicate_uuid = __CONST_c_0__", alias="q1")
        inner_union = PlanV2(kind=KIND_UNION, children=[inner_left, inner_right])

        outer_right = _bgp_with_constraint("q2.predicate_uuid = __CONST_c_0__", alias="q2")
        outer_union = PlanV2(kind=KIND_UNION, children=[inner_union, outer_right])

        result = prune_dead_union_branches(outer_union, gen)
        # Inner UNION should have been pruned to inner_right (BGP)
        # Outer UNION still has 2 live branches
        assert result.kind == KIND_UNION
        assert result.children[0].kind == KIND_BGP  # was inner_union, now inner_right
        assert result.children[1].kind == KIND_BGP

    def test_tagged_constraints_checked(self):
        """Unresolved constant in tagged_constraints should also trigger pruning."""
        gen = _aliases_with_constants({}, ["c_1"])

        left = PlanV2(
            kind=KIND_BGP,
            tables=[TableRef(ref_id="q0", kind="quad", table_name="rdf_quad", alias="q0")],
            constraints=[],
            tagged_constraints=[("q0", "q0.predicate_uuid = __CONST_c_1__")],
        )
        right = _bgp_with_constraint("something_alive")
        plan = PlanV2(kind=KIND_UNION, children=[left, right])

        result = prune_dead_union_branches(plan, gen)
        assert result.kind == KIND_BGP
        assert result.constraints == ["something_alive"]

    def test_no_constants_noop(self):
        """No constants registered at all → no pruning."""
        gen = AliasGenerator()
        left = _bgp_with_constraint("q0.x = 1")
        right = _bgp_with_constraint("q1.x = 2", alias="q1")
        plan = PlanV2(kind=KIND_UNION, children=[left, right])

        result = prune_dead_union_branches(plan, gen)
        assert result.kind == KIND_UNION

    def test_non_union_not_affected(self):
        """JOIN nodes should not be pruned even if they have dead branches."""
        gen = _aliases_with_constants({}, ["c_1"])

        left = _bgp_with_constraint("q0.predicate_uuid = __CONST_c_1__")
        right = _bgp_with_constraint("q1.x = 1", alias="q1")
        plan = PlanV2(kind=KIND_JOIN, children=[left, right])

        result = prune_dead_union_branches(plan, gen)
        assert result.kind == KIND_JOIN
        assert len(result.children) == 2

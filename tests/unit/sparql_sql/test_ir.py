"""Unit tests for vitalgraph.db.sparql_sql.ir — IR data structures."""

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql.ir import (
    AliasGenerator,
    PlanV2,
    TableRef,
    VarSlot,
    KIND_BGP,
    KIND_JOIN,
    KIND_LEFT_JOIN,
    KIND_UNION,
    KIND_MINUS,
    KIND_TABLE,
    KIND_NULL,
    KIND_PATH,
    KIND_PROJECT,
    KIND_DISTINCT,
    KIND_REDUCED,
    KIND_SLICE,
    KIND_ORDER,
    KIND_FILTER,
    KIND_EXTEND,
    KIND_GROUP,
    RELATION_KINDS,
    MODIFIER_KINDS,
    ALL_KINDS,
)


# ---------------------------------------------------------------------------
# AliasGenerator
# ---------------------------------------------------------------------------

class TestAliasGenerator:

    def test_sequential_aliases(self):
        gen = AliasGenerator()
        assert gen.next("q") == "q0"
        assert gen.next("q") == "q1"
        assert gen.next("q") == "q2"

    def test_independent_prefixes(self):
        gen = AliasGenerator()
        assert gen.next("q") == "q0"
        assert gen.next("t") == "t0"
        assert gen.next("q") == "q1"
        assert gen.next("t") == "t1"

    def test_alias_prefix(self):
        gen = AliasGenerator(alias_prefix="sub_")
        assert gen.next("q") == "sub_q0"
        assert gen.next("t") == "sub_t0"

    def test_next_var(self):
        gen = AliasGenerator()
        sql0 = gen.next_var("x")
        sql1 = gen.next_var("name")
        assert sql0 == "v0"
        assert sql1 == "v1"
        assert gen.var_map == {"v0": "x", "v1": "name"}

    def test_next_var_with_prefix(self):
        gen = AliasGenerator(alias_prefix="inner_")
        sql0 = gen.next_var("x")
        assert sql0 == "inner_v0"

    def test_register_constant_dedup(self):
        gen = AliasGenerator()
        c1 = gen.register_constant("hello", "string")
        c2 = gen.register_constant("hello", "string")
        c3 = gen.register_constant("world", "string")
        assert c1 == c2  # same key → same alias
        assert c1 != c3  # different key → different alias
        assert c1 == "c_0"
        assert c3 == "c_1"


# ---------------------------------------------------------------------------
# Kind constants
# ---------------------------------------------------------------------------

class TestKindConstants:

    def test_relation_kinds_complete(self):
        expected = {
            KIND_BGP, KIND_JOIN, KIND_LEFT_JOIN, KIND_UNION,
            KIND_MINUS, KIND_TABLE, KIND_NULL, KIND_PATH,
        }
        assert RELATION_KINDS == expected

    def test_modifier_kinds_complete(self):
        expected = {
            KIND_PROJECT, KIND_DISTINCT, KIND_REDUCED, KIND_SLICE,
            KIND_ORDER, KIND_FILTER, KIND_EXTEND, KIND_GROUP,
        }
        assert MODIFIER_KINDS == expected

    def test_all_kinds_is_union(self):
        assert ALL_KINDS == RELATION_KINDS | MODIFIER_KINDS

    def test_no_overlap(self):
        assert RELATION_KINDS & MODIFIER_KINDS == set()


# ---------------------------------------------------------------------------
# PlanV2 structure
# ---------------------------------------------------------------------------

class TestPlanV2:

    def test_leaf_bgp(self):
        plan = PlanV2(kind=KIND_BGP, var_slots={"x": VarSlot(name="x"), "y": VarSlot(name="y")})
        assert plan.is_relation
        assert not plan.is_modifier
        assert plan.depth() == 1

    def test_modifier_child_property(self):
        inner = PlanV2(kind=KIND_BGP)
        outer = PlanV2(kind=KIND_PROJECT, children=[inner], project_vars=["x"])
        assert outer.child is inner

    def test_child_assertion_on_binary(self):
        left = PlanV2(kind=KIND_BGP)
        right = PlanV2(kind=KIND_BGP)
        join = PlanV2(kind=KIND_JOIN, children=[left, right])
        with pytest.raises(AssertionError):
            _ = join.child  # JOIN has 2 children, not 1

    def test_walk_preorder(self):
        leaf1 = PlanV2(kind=KIND_BGP)
        leaf2 = PlanV2(kind=KIND_BGP)
        join = PlanV2(kind=KIND_JOIN, children=[leaf1, leaf2])
        proj = PlanV2(kind=KIND_PROJECT, children=[join], project_vars=["x"])
        nodes = list(proj.walk())
        assert nodes == [proj, join, leaf1, leaf2]

    def test_depth_nested(self):
        leaf = PlanV2(kind=KIND_BGP)
        filt = PlanV2(kind=KIND_FILTER, children=[leaf])
        proj = PlanV2(kind=KIND_PROJECT, children=[filt], project_vars=["x"])
        assert proj.depth() == 3

    def test_summary_includes_kind(self):
        plan = PlanV2(kind=KIND_SLICE, children=[PlanV2(kind=KIND_BGP)], limit=10, offset=5)
        s = plan.summary()
        assert "slice" in s
        assert "limit=10" in s
        assert "offset=5" in s
        assert "bgp" in s

    def test_is_modifier_vs_relation(self):
        for kind in RELATION_KINDS:
            assert PlanV2(kind=kind).is_relation
            assert not PlanV2(kind=kind).is_modifier
        for kind in MODIFIER_KINDS:
            assert PlanV2(kind=kind).is_modifier
            assert not PlanV2(kind=kind).is_relation


# ---------------------------------------------------------------------------
# TableRef / VarSlot
# ---------------------------------------------------------------------------

class TestTableRef:

    def test_creation(self):
        t = TableRef(ref_id="q0", kind="quad", table_name="my_rdf_quad")
        assert t.ref_id == "q0"
        assert t.kind == "quad"
        assert t.alias == ""

    def test_alias(self):
        t = TableRef(ref_id="t1", kind="term", table_name="my_rdf_term", join_col="subject_uuid", alias="t1_alias")
        assert t.alias == "t1_alias"
        assert t.join_col == "subject_uuid"


class TestVarSlot:

    def test_creation(self):
        vs = VarSlot(name="x", positions=[("q0", "subject_uuid")])
        assert vs.name == "x"
        assert len(vs.positions) == 1
        assert vs.partial is False

    def test_defaults(self):
        vs = VarSlot(name="y")
        assert vs.positions == []
        assert vs.term_ref_id is None
        assert vs.uuid_col is None
        assert vs.text_col is None
        assert vs.type_col is None

"""Unit tests for collect.py — v2 collect pass (Op tree → PlanV2 IR)."""
# pyright: reportOperatorIssue=false, reportArgumentType=false

from __future__ import annotations

import pytest

from vitalgraph.db.jena_sparql.jena_types import (
    VarNode, URINode, LiteralNode, BNodeNode,
    ExprVar, ExprValue, ExprFunction, ExprAggregator,
    SortCondition, GroupVar,
    OpBGP, OpJoin, OpLeftJoin, OpUnion, OpFilter,
    OpProject, OpSlice, OpDistinct, OpReduced, OpOrder,
    OpGroup, OpExtend, OpTable, OpMinus, OpGraph,
    OpSequence, OpNull, OpPath,
    PathLink,
    TriplePattern,
)
from vitalgraph.db.sparql_sql.ir import (
    AliasGenerator, PlanV2,
    KIND_BGP, KIND_JOIN, KIND_LEFT_JOIN, KIND_UNION, KIND_MINUS,
    KIND_TABLE, KIND_NULL, KIND_PATH,
    KIND_PROJECT, KIND_DISTINCT, KIND_REDUCED, KIND_SLICE,
    KIND_ORDER, KIND_FILTER, KIND_EXTEND, KIND_GROUP,
)
from vitalgraph.db.sparql_sql.collect import collect, GRAPH_VAR_SCOPE, _esc


SPACE = "test_space"


def _aliases(**kwargs) -> AliasGenerator:
    return AliasGenerator(**kwargs)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestEsc:
    def test_none_returns_empty(self):
        assert _esc(None) == ""

    def test_escapes_quotes(self):
        assert _esc("it's") == "it''s"

    def test_no_change(self):
        assert _esc("hello") == "hello"


# ---------------------------------------------------------------------------
# OpBGP
# ---------------------------------------------------------------------------


class TestCollectBGP:

    def test_empty_bgp(self):
        """Empty BGP → plan with no tables."""
        op = OpBGP(triples=[])
        plan = collect(op, SPACE, _aliases())
        assert plan.kind == KIND_BGP
        assert len(plan.tables) == 0

    def test_single_triple_vars(self):
        """Single triple with all variable nodes."""
        op = OpBGP(triples=[TriplePattern(
            subject=VarNode(name="s"),
            predicate=VarNode(name="p"),
            object=VarNode(name="o"),
        )])
        plan = collect(op, SPACE, _aliases())
        assert plan.kind == KIND_BGP
        assert len(plan.tables) >= 1
        assert "s" in plan.var_slots
        assert "p" in plan.var_slots
        assert "o" in plan.var_slots

    def test_uri_predicate_constraint(self):
        """URI predicate → constraint with const token."""
        op = OpBGP(triples=[TriplePattern(
            subject=VarNode(name="s"),
            predicate=URINode(value="http://ex.org/knows"),
            object=VarNode(name="o"),
        )])
        plan = collect(op, SPACE, _aliases())
        assert any("predicate_uuid" in c for c in plan.constraints)
        assert any("__CONST_" in c for c in plan.constraints)

    def test_literal_object_with_lang(self):
        """Literal with lang → inline subquery constraint."""
        op = OpBGP(triples=[TriplePattern(
            subject=VarNode(name="s"),
            predicate=URINode(value="http://ex.org/label"),
            object=LiteralNode(value="hello", lang="en"),
        )])
        plan = collect(op, SPACE, _aliases())
        assert any("lang = 'en'" in c for c in plan.constraints)
        assert any("term_text = 'hello'" in c for c in plan.constraints)

    def test_literal_object_no_lang(self):
        """Literal without lang → const subquery."""
        op = OpBGP(triples=[TriplePattern(
            subject=VarNode(name="s"),
            predicate=URINode(value="http://ex.org/val"),
            object=LiteralNode(value="42"),
        )])
        plan = collect(op, SPACE, _aliases())
        assert any("__CONST_" in c for c in plan.constraints)

    def test_coref_same_variable(self):
        """Same variable in subject and object → co-reference constraint."""
        op = OpBGP(triples=[TriplePattern(
            subject=VarNode(name="x"),
            predicate=URINode(value="http://ex.org/self"),
            object=VarNode(name="x"),
        )])
        plan = collect(op, SPACE, _aliases())
        assert "x" in plan.var_slots
        # Should have a co-ref constraint
        assert any("subject_uuid" in c and "object_uuid" in c
                   for c in plan.constraints)

    def test_graph_lock_uri(self):
        """graph_lock_uri → context_uuid constraint prepended."""
        aliases = _aliases()
        aliases.graph_lock_uri = "http://ex.org/locked"
        op = OpBGP(triples=[TriplePattern(
            subject=VarNode(name="s"),
            predicate=VarNode(name="p"),
            object=VarNode(name="o"),
        )])
        plan = collect(op, SPACE, aliases)
        assert any("context_uuid" in c and "__CONST_" in c
                   for c in plan.constraints)

    def test_default_graph_no_graph_clause(self):
        """default_graph + no GRAPH clause → context_uuid constraint."""
        aliases = _aliases()
        aliases.default_graph = "http://ex.org/default"
        op = OpBGP(triples=[TriplePattern(
            subject=VarNode(name="s"),
            predicate=VarNode(name="p"),
            object=VarNode(name="o"),
        )])
        plan = collect(op, SPACE, aliases)
        assert any("context_uuid" in c for c in plan.constraints)

    def test_default_graph_inside_graph_clause(self):
        """default_graph + inside GRAPH <uri> → no default graph constraint."""
        aliases = _aliases()
        aliases.default_graph = "http://ex.org/default"
        op = OpBGP(triples=[TriplePattern(
            subject=VarNode(name="s"),
            predicate=VarNode(name="p"),
            object=VarNode(name="o"),
        )])
        plan = collect(op, SPACE, aliases, graph_uri="http://ex.org/named")
        # Should have context_uuid from the graph_uri, not default
        ctx_constraints = [c for c in plan.constraints if "context_uuid" in c]
        # graph_uri constraint should use the named graph, not default
        assert any("__CONST_" in c for c in ctx_constraints)

    def test_graph_var_scope_excludes_default(self):
        """GRAPH ?g → IS DISTINCT FROM default graph."""
        aliases = _aliases()
        aliases.default_graph = "http://ex.org/default"
        op = OpBGP(triples=[TriplePattern(
            subject=VarNode(name="s"),
            predicate=VarNode(name="p"),
            object=VarNode(name="o"),
        )])
        plan = collect(op, SPACE, aliases, graph_uri=GRAPH_VAR_SCOPE)
        assert any("IS DISTINCT FROM" in c for c in plan.constraints)

    def test_graph_uri_constraint(self):
        """GRAPH <uri> → context_uuid = const."""
        aliases = _aliases()
        op = OpBGP(triples=[TriplePattern(
            subject=VarNode(name="s"),
            predicate=VarNode(name="p"),
            object=VarNode(name="o"),
        )])
        plan = collect(op, SPACE, aliases, graph_uri="http://ex.org/mygraph")
        assert any("context_uuid" in c and "__CONST_" in c
                   for c in plan.constraints)


# ---------------------------------------------------------------------------
# Binary operators
# ---------------------------------------------------------------------------


class TestCollectBinary:

    def test_join(self):
        op = OpJoin(
            left=OpBGP(triples=[]),
            right=OpBGP(triples=[]),
        )
        plan = collect(op, SPACE, _aliases())
        assert plan.kind == KIND_JOIN
        assert len(plan.children) == 2

    def test_left_join(self):
        op = OpLeftJoin(
            left=OpBGP(triples=[]),
            right=OpBGP(triples=[]),
            exprs=[],
        )
        plan = collect(op, SPACE, _aliases())
        assert plan.kind == KIND_LEFT_JOIN

    def test_left_join_with_exprs(self):
        expr = ExprVar(var="x")
        op = OpLeftJoin(
            left=OpBGP(triples=[]),
            right=OpBGP(triples=[]),
            exprs=[expr],
        )
        plan = collect(op, SPACE, _aliases())
        assert plan.left_join_exprs == [expr]

    def test_union(self):
        op = OpUnion(
            left=OpBGP(triples=[]),
            right=OpBGP(triples=[]),
        )
        plan = collect(op, SPACE, _aliases())
        assert plan.kind == KIND_UNION

    def test_minus(self):
        op = OpMinus(
            left=OpBGP(triples=[]),
            right=OpBGP(triples=[]),
        )
        plan = collect(op, SPACE, _aliases())
        assert plan.kind == KIND_MINUS


# ---------------------------------------------------------------------------
# Leaf operators
# ---------------------------------------------------------------------------


class TestCollectLeaf:

    def test_table(self):
        op = OpTable(vars=["x", "y"], rows=[{"x": URINode(value="http://a")}])
        plan = collect(op, SPACE, _aliases())
        assert plan.kind == KIND_TABLE
        assert plan.values_vars == ["x", "y"]
        assert len(plan.values_rows) == 1

    def test_table_no_rows(self):
        op = OpTable(vars=["x"], rows=None)
        plan = collect(op, SPACE, _aliases())
        assert plan.values_rows == []

    def test_null(self):
        op = OpNull()
        plan = collect(op, SPACE, _aliases())
        assert plan.kind == KIND_NULL

    def test_sequence_single(self):
        """Single-element sequence → unwrapped."""
        op = OpSequence(elements=[OpBGP(triples=[])])
        plan = collect(op, SPACE, _aliases())
        assert plan.kind == KIND_BGP

    def test_sequence_multi(self):
        """Multi-element sequence → nested JOINs."""
        op = OpSequence(elements=[
            OpBGP(triples=[]),
            OpBGP(triples=[]),
            OpBGP(triples=[]),
        ])
        plan = collect(op, SPACE, _aliases())
        assert plan.kind == KIND_JOIN
        # Should be left-nested: (bgp1 JOIN bgp2) JOIN bgp3
        assert plan.children[0].kind == KIND_JOIN
        assert plan.children[1].kind == KIND_BGP


# ---------------------------------------------------------------------------
# OpPath
# ---------------------------------------------------------------------------


class TestCollectPath:

    def test_path_basic(self):
        op = OpPath(
            subject=VarNode(name="s"),
            path=PathLink(uri="http://ex.org/p"),
            object=VarNode(name="o"),
        )
        plan = collect(op, SPACE, _aliases())
        assert plan.kind == KIND_PATH
        assert plan.path_meta is not None
        assert plan.path_meta["quad_table"] == "test_space_rdf_quad"
        assert "s" in plan.var_slots
        assert "o" in plan.var_slots

    def test_path_same_var_dedup(self):
        """Same var in subject and object → only one VarSlot."""
        op = OpPath(
            subject=VarNode(name="x"),
            path=PathLink(uri="http://ex.org/p"),
            object=VarNode(name="x"),
        )
        plan = collect(op, SPACE, _aliases())
        assert "x" in plan.var_slots


# ---------------------------------------------------------------------------
# OpGraph
# ---------------------------------------------------------------------------


class TestCollectGraph:

    def test_graph_uri(self):
        """GRAPH <uri> → pass graph_uri to child."""
        inner = OpBGP(triples=[TriplePattern(
            subject=VarNode(name="s"),
            predicate=VarNode(name="p"),
            object=VarNode(name="o"),
        )])
        op = OpGraph(graph_node=URINode(value="http://ex.org/g1"), sub_op=inner)
        plan = collect(op, SPACE, _aliases())
        assert plan.kind == KIND_BGP
        assert any("context_uuid" in c for c in plan.constraints)

    def test_graph_var(self):
        """GRAPH ?g → bind graph var to context_uuid."""
        inner = OpBGP(triples=[TriplePattern(
            subject=VarNode(name="s"),
            predicate=VarNode(name="p"),
            object=VarNode(name="o"),
        )])
        op = OpGraph(graph_node=VarNode(name="g"), sub_op=inner)
        plan = collect(op, SPACE, _aliases())
        assert "g" in plan.var_slots

    def test_graph_var_coref(self):
        """GRAPH ?g with multiple quad tables → co-reference constraints."""
        bgp = OpBGP(triples=[
            TriplePattern(subject=VarNode(name="s"), predicate=VarNode(name="p"),
                   object=VarNode(name="o")),
            TriplePattern(subject=VarNode(name="a"), predicate=VarNode(name="b"),
                   object=VarNode(name="c")),
        ])
        op = OpGraph(graph_node=VarNode(name="g"), sub_op=bgp)
        plan = collect(op, SPACE, _aliases())
        assert "g" in plan.var_slots
        # Multiple quad tables: should have co-ref on context_uuid
        ctx_constraints = [c for c in plan.constraints if "context_uuid" in c]
        assert len(ctx_constraints) >= 1

    def test_graph_fallback(self):
        """Non-URI/non-Var graph_node → GRAPH_VAR_SCOPE."""
        inner = OpBGP(triples=[])
        op = OpGraph(graph_node=LiteralNode(value="bad"), sub_op=inner)
        plan = collect(op, SPACE, _aliases())
        assert plan.kind == KIND_BGP


# ---------------------------------------------------------------------------
# Modifier operators
# ---------------------------------------------------------------------------


class TestCollectModifiers:

    def test_filter(self):
        expr = ExprFunction(name="bound", args=[ExprVar(var="x")])
        op = OpFilter(
            exprs=[expr],
            sub_op=OpBGP(triples=[]),
        )
        plan = collect(op, SPACE, _aliases())
        assert plan.kind == KIND_FILTER
        assert plan.filter_exprs == [expr]

    def test_project(self):
        op = OpProject(
            vars=["s", "o"],
            sub_op=OpBGP(triples=[]),
        )
        plan = collect(op, SPACE, _aliases())
        assert plan.kind == KIND_PROJECT
        assert plan.project_vars == ["s", "o"]

    def test_slice(self):
        op = OpSlice(
            sub_op=OpBGP(triples=[]),
            start=5,
            length=10,
        )
        plan = collect(op, SPACE, _aliases())
        assert plan.kind == KIND_SLICE
        assert plan.limit == 10
        assert plan.offset == 5

    def test_slice_no_limit(self):
        op = OpSlice(
            sub_op=OpBGP(triples=[]),
            start=0,
            length=-1,
        )
        plan = collect(op, SPACE, _aliases())
        assert plan.limit == -1
        assert plan.offset == 0

    def test_distinct(self):
        op = OpDistinct(sub_op=OpBGP(triples=[]))
        plan = collect(op, SPACE, _aliases())
        assert plan.kind == KIND_DISTINCT

    def test_reduced(self):
        op = OpReduced(sub_op=OpBGP(triples=[]))
        plan = collect(op, SPACE, _aliases())
        assert plan.kind == KIND_REDUCED

    def test_order_var(self):
        op = OpOrder(
            sub_op=OpBGP(triples=[]),
            conditions=[
                SortCondition(expr=ExprVar(var="s"), direction="ASC"),
                SortCondition(expr=ExprVar(var="o"), direction="DESC"),
            ],
        )
        plan = collect(op, SPACE, _aliases())
        assert plan.kind == KIND_ORDER
        assert plan.order_conditions[0] == ("s", "ASC")
        assert plan.order_conditions[1] == ("o", "DESC")

    def test_order_expr(self):
        """Non-variable sort expression → stored as expression."""
        expr = ExprFunction(name="strlen", args=[ExprVar(var="s")])
        op = OpOrder(
            sub_op=OpBGP(triples=[]),
            conditions=[SortCondition(expr=expr, direction="ASC")],
        )
        plan = collect(op, SPACE, _aliases())
        assert plan.order_conditions[0] == (expr, "ASC")

    def test_extend(self):
        op = OpExtend(
            sub_op=OpBGP(triples=[]),
            var="x",
            expr=ExprVar(var="s"),
        )
        plan = collect(op, SPACE, _aliases())
        assert plan.kind == KIND_EXTEND
        assert plan.extend_var == "x"

    def test_group(self):
        op = OpGroup(
            sub_op=OpBGP(triples=[]),
            group_vars=[GroupVar(var="type")],
            aggregators=[{
                "var": "c",
                "aggregator": {"name": "COUNT", "distinct": False, "expr": None},
            }],
        )
        plan = collect(op, SPACE, _aliases())
        assert plan.kind == KIND_GROUP
        assert plan.aggregates is not None  # type: ignore[union-attr]
        assert "c" in plan.aggregates
        assert plan.aggregates["c"].name == "COUNT"

    def test_group_no_aggregators(self):
        op = OpGroup(
            sub_op=OpBGP(triples=[]),
            group_vars=[GroupVar(var="type")],
            aggregators=None,
        )
        plan = collect(op, SPACE, _aliases())
        assert plan.aggregates is None

    def test_group_drops_unmapped_expr(self):
        """Aggregator with a dict expr (unmapped) → expr becomes None."""
        op = OpGroup(
            sub_op=OpBGP(triples=[]),
            group_vars=[],
            aggregators=[{
                "var": "c",
                "aggregator": {
                    "name": "COUNT",
                    "distinct": False,
                    "expr": {"some_raw": "dict"},  # not mapped to AST
                },
            }],
        )
        plan = collect(op, SPACE, _aliases())
        assert plan.aggregates is not None
        assert plan.aggregates["c"].expr is None


# ---------------------------------------------------------------------------
# Dispatch error
# ---------------------------------------------------------------------------


class TestCollectDispatch:

    def test_unknown_op_raises(self):
        """Unregistered Op type → NotImplementedError."""

        class FakeOp:
            pass

        with pytest.raises(NotImplementedError, match="FakeOp"):
            collect(FakeOp(), SPACE, _aliases())

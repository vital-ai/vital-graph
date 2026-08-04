"""Unit tests for variable references inside EXISTS patterns — issue 027.

Two things had to be true for a correlated EXISTS to work, and neither was:

  1. `vars_in_expr` had no `ExprExists` case, so a variable referenced only
     inside the EXISTS pattern was invisible to `compute_text_needed_vars`. The
     outer BGP then emitted `NULL` for that variable's text column and the
     correlation compared against NULL.
  2. `_exists_to_sql` correlated only on scope-visible variables, so a
     filter-only outer variable was never bound to the outer row at all.

This module covers (1); the end-to-end behaviour of both is in
`tests/integration/test_minus_and_exists_correlation.py`.
"""
# pyright: reportOperatorIssue=false, reportArgumentType=false

from __future__ import annotations

from vitalgraph.db.sparql_sql.var_scope import vars_in_expr
from vitalgraph.db.jena_sparql.jena_types import (
    ExprExists, ExprFunction, ExprVar, OpBGP, OpFilter, OpGraph, OpJoin,
    TriplePattern, URINode, VarNode,
)


def _bgp(*triples):
    return OpBGP(triples=[
        TriplePattern(subject=s, predicate=p, object=o) for s, p, o in triples
    ])


class TestVarsInExprBasics:
    """Existing behaviour must be unchanged."""

    def test_plain_var(self):
        assert vars_in_expr(ExprVar(var="s")) == {"s"}

    def test_function_args(self):
        expr = ExprFunction(name="=", args=[ExprVar(var="a"), ExprVar(var="b")])
        assert vars_in_expr(expr) == {"a", "b"}

    def test_nested_functions(self):
        inner = ExprFunction(name="str", args=[ExprVar(var="x")])
        expr = ExprFunction(name="=", args=[inner, ExprVar(var="y")])
        assert vars_in_expr(expr) == {"x", "y"}


class TestVarsInsideExists:
    """A variable used only inside the EXISTS pattern must still be found."""

    def test_var_in_inner_filter(self):
        """The exact issue 027 shape: ?s appears only in the inner FILTER."""
        inner = OpFilter(
            exprs=[ExprFunction(name="=", args=[
                ExprVar(var="s"), ExprVar(var="s2"),
            ])],
            sub_op=_bgp((VarNode(name="s2"), URINode("urn:name"), VarNode(name="n"))),
        )
        found = vars_in_expr(ExprExists(graph_pattern=inner, negated=True))
        assert "s" in found, (
            "outer variable referenced only inside EXISTS was not collected — "
            "the outer BGP will emit NULL for its text column"
        )

    def test_vars_in_inner_bgp(self):
        inner = _bgp((VarNode(name="a"), URINode("urn:p"), VarNode(name="b")))
        assert vars_in_expr(ExprExists(graph_pattern=inner)) == {"a", "b"}

    def test_recurses_through_graph_and_join(self):
        inner = OpGraph(
            graph_node=VarNode(name="g"),
            sub_op=OpJoin(
                left=_bgp((VarNode(name="a"), URINode("urn:p"), VarNode(name="b"))),
                right=_bgp((VarNode(name="c"), URINode("urn:q"), VarNode(name="d"))),
            ),
        )
        assert vars_in_expr(ExprExists(graph_pattern=inner)) == {
            "g", "a", "b", "c", "d"}

    def test_nested_exists(self):
        deep = OpFilter(
            exprs=[ExprExists(graph_pattern=_bgp(
                (VarNode(name="deepvar"), URINode("urn:p"), VarNode(name="z"))
            ))],
            sub_op=_bgp((VarNode(name="mid"), URINode("urn:p"), VarNode(name="y"))),
        )
        found = vars_in_expr(ExprExists(graph_pattern=deep))
        assert {"deepvar", "mid", "y", "z"} <= found

    def test_constants_are_not_variables(self):
        inner = _bgp((VarNode(name="a"), URINode("urn:p"), URINode("urn:o")))
        assert vars_in_expr(ExprExists(graph_pattern=inner)) == {"a"}

    def test_empty_pattern(self):
        assert vars_in_expr(ExprExists(graph_pattern=OpBGP(triples=[]))) == set()

    def test_none_pattern(self):
        assert vars_in_expr(ExprExists(graph_pattern=None)) == set()

    def test_exists_nested_in_a_function(self):
        """EXISTS reached through a surrounding expression, e.g. `!EXISTS{...}`."""
        ex = ExprExists(graph_pattern=_bgp(
            (VarNode(name="inner_only"), URINode("urn:p"), VarNode(name="v"))
        ))
        assert "inner_only" in vars_in_expr(ExprFunction(name="!", args=[ex]))

"""`GRAPH ?g { P }` is evaluated per graph only when P sees ?g — issues/280.

The cheap compile (bind ?g to every quad's context) stays for P made of triple
patterns. P that filters on ?g, binds ?g itself, or holds a MINUS is rewritten
so ?g is unbound inside P and joined afterwards, as SPARQL 1.1 §18.6 says.
"""

from __future__ import annotations

from vitalgraph.db.jena_sparql.jena_types import (
    ExprFunction, ExprVar, OpBGP, OpExtend, OpFilter, OpJoin, OpLeftJoin, OpMinus,
    OpProject, OpTable, TriplePattern, URINode, VarNode,
)
from vitalgraph.db.sparql_sql import graph_scope_rewrite as G


def _tp(s, p, o):
    n = lambda x: VarNode(name=x[1:]) if x.startswith("?") else URINode(value=x)  # noqa: E731
    return TriplePattern(subject=n(s), predicate=n(p), object=n(o))


def _bgp(*tps):
    return OpBGP(triples=[_tp(*t) for t in tps])


def test_plain_triples_keep_the_cheap_compile():
    assert not G.needs_scoped_graph(_bgp(("?s", "?p", "?o")), "g")


def test_a_filter_on_the_graph_variable_is_rewritten():
    p = OpFilter(exprs=[ExprFunction(name="bound", args=[ExprVar(var="g")])],
                 sub_op=OpTable(vars=[], rows=[{}]))
    assert G.needs_scoped_graph(p, "g")


def test_an_inner_binding_of_the_graph_variable_is_rewritten():
    p = OpLeftJoin(left=_bgp(("?s", "?p", "?o")), right=_bgp(("?s", "?p", "?g")))
    assert G.needs_scoped_graph(p, "g")


def test_a_minus_is_rewritten_even_without_the_variable():
    p = OpMinus(left=_bgp(("?a", "http://e/p", "http://e/o")),
                right=_bgp(("?b", "http://e/p", "http://e/o")))
    assert G.needs_scoped_graph(p, "g")


def test_the_rewrites_own_graph_is_never_rewritten_again():
    p = OpMinus(left=_bgp(("?a", "?p", "?o")), right=_bgp(("?b", "?p", "?o")))
    assert not G.needs_scoped_graph(p, G.GRAPH_CTX_PREFIX + "x")


def test_a_subselect_not_projecting_the_variable_is_a_different_variable():
    p = OpProject(vars=["x"], sub_op=_bgp(("?x", "?p", "?g")))
    assert not G.needs_scoped_graph(p, "g")
    assert G._rename(p, "g", "h") is p


def test_rename_reaches_triples_expressions_extend_and_values():
    p = OpExtend(var="g", expr=ExprVar(var="g"), sub_op=OpJoin(
        left=_bgp(("?s", "?p", "?g")),
        right=OpTable(vars=["g", "t"], rows=[{"g": URINode(value="http://e/x")}])))
    r = G._rename(p, "g", "h")
    assert r.var == "h" and r.expr.var == "h"
    assert r.sub_op.left.triples[0].object.name == "h"
    assert r.sub_op.right.vars == ["h", "t"] and "h" in r.sub_op.right.rows[0]
    assert not G._mentions(r, "g")


def test_the_rewrite_binds_the_graph_variable_from_the_context():
    p = OpLeftJoin(left=_bgp(("?s", "?p", "?o")), right=_bgp(("?s", "?p", "?g")))
    out = G.rewrite_scoped_graph(p, "g", "1")
    assert isinstance(out, OpExtend) and out.var == "g"
    assert out.expr.var.startswith(G.GRAPH_CTX_PREFIX)
    assert not G._mentions(out.sub_op, "g"), "inside, ?g must be the renamed variable"


def test_a_pattern_with_no_triples_is_joined_with_the_graph_enumeration():
    p = OpFilter(exprs=[ExprFunction(name="bound", args=[ExprVar(var="g")])],
                 sub_op=OpTable(vars=[], rows=[{}]))
    out = G.rewrite_scoped_graph(p, "g", "1")
    assert isinstance(out, OpFilter) and isinstance(out.sub_op, OpJoin)
    assert out.sub_op.left.graph_node.name == "g"

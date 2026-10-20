"""`GRAPH ?g { P }` with P evaluated in each named graph, as SPARQL 1.1 says — issues/280.

SPARQL 1.1 §18.6: eval(D, Graph(?g, P)) is, over the named graphs G, the union
of Join(eval(D(G), P), {?g -> G}). P is evaluated with ?g UNBOUND, and only
then joined with the graph name.

The compiler's usual shortcut binds ?g to the context column of every quad in
P (`collect._bind_graph_var`). For a P made of triple patterns that is the same
thing, and it is kept for them. It differs whenever P sees ?g itself, which is
what this module rewrites:

* a FILTER on ?g: `GRAPH ?g { FILTER(BOUND(?g)) }` must be empty
  (`graph-variable-scope`), because inside P ?g is unbound;
* P binding ?g: `GRAPH ?g { ?s ?p ?o OPTIONAL { ?s ?p ?g } }` must drop a row
  whose OPTIONAL bound ?g to anything but the graph (`graph-optional`);
* MINUS in P: the graph is not a variable the two sides share, so
  `?a :p :o MINUS { ?b :p :o }` keeps its rows (`outer GRAPH operator does not
  affect MINUS disjointness`).

The rewrite, in algebra the compiler already handles:

    Extend(?g := ?.gctx,
      Filter(!bound(?.gp) || sameTerm(?.gp, ?.gctx),
        Graph(?.gctx, P[?g -> ?.gp])))       # P, per graph

P's quads range over the named graphs and bind ?.gctx. A P with no triple
pattern (FILTERs over `{}`, VALUES) does not depend on the graph, so it is
joined with the plain enumeration `Graph(?g, {})` instead, and the same
compatibility filter compares the renamed ?g with ?g.

Both hidden variables are anonymous (a leading `.`), so `SELECT *` does not
show them. `emit_minus` treats a `.gctx` variable as the same-graph correlation
it is: compared for equality, but not counted toward MINUS's
shared-domain rule.

NOT changed: named graphs are enumerated by their CONTENTS
(`named_graph_semantics` §4.4), so an empty named graph is still absent. The
two DAWG cases that count one (`VALUES inside GRAPH binding the same variable
as the graph name`, `COUNT: no GROUP BY inside of GRAPH`) are recorded as known
differences for that reason.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from ..jena_sparql.jena_types import (
    ExprFunction, ExprVar, OpExtend, OpFilter, OpGraph, OpJoin, OpMinus,
    OpProject, OpTable, VarNode,
)

GRAPH_CTX_PREFIX = ".gctx"
GRAPH_INNER_PREFIX = ".gp"


def is_graph_ctx_var(name: str) -> bool:
    return name.startswith(GRAPH_CTX_PREFIX)


def _rename(node: Any, old: str, new: str) -> Any:
    """A copy of an algebra or expression tree with variable `old` renamed.

    Stops at a sub-SELECT that does not project `old`: inside it, `old` is a
    different variable.
    """
    if isinstance(node, VarNode):
        return VarNode(name=new) if node.name == old else node
    if isinstance(node, ExprVar):
        return ExprVar(var=new) if node.var == old else node
    if isinstance(node, list):
        return [_rename(x, old, new) for x in node]
    if isinstance(node, tuple):
        return tuple(_rename(x, old, new) for x in node)
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            k2 = new if k == old else k
            if k in ("var", "name") and v == old:
                out[k2] = new
            else:
                out[k2] = _rename(v, old, new)
        return out
    if isinstance(node, OpProject) and old not in (node.vars or []):
        return node
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        changes = {}
        for f in dataclasses.fields(node):
            v = getattr(node, f.name)
            if f.name == "var" and isinstance(v, str):
                changes[f.name] = new if v == old else v
            elif f.name == "vars" and isinstance(v, list) and all(isinstance(x, str) for x in v):
                changes[f.name] = [new if x == old else x for x in v]
            else:
                changes[f.name] = _rename(v, old, new)
        return dataclasses.replace(node, **changes)
    return node


def _mentions(node: Any, name: str) -> bool:
    if isinstance(node, VarNode):
        return node.name == name
    if isinstance(node, ExprVar):
        return node.var == name
    if isinstance(node, (list, tuple)):
        return any(_mentions(x, name) for x in node)
    if isinstance(node, dict):
        return any(k == name or v == name or _mentions(v, name) for k, v in node.items())
    if isinstance(node, OpProject) and name not in (node.vars or []):
        return False
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        for f in dataclasses.fields(node):
            v = getattr(node, f.name)
            if f.name == "var" and v == name:
                return True
            if f.name == "vars" and isinstance(v, list) and name in v:
                return True
            if _mentions(v, name):
                return True
    return False


def _contains_minus(node: Any) -> bool:
    if isinstance(node, OpMinus):
        return True
    if isinstance(node, (list, tuple)):
        return any(_contains_minus(x) for x in node)
    if isinstance(node, OpProject):
        return False
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        return any(_contains_minus(getattr(node, f.name)) for f in dataclasses.fields(node))
    return False


def needs_scoped_graph(sub_op: Any, graph_var: str) -> bool:
    """Whether `GRAPH ?graph_var { sub_op }` must be evaluated per graph:
    P mentions the graph variable itself, or contains MINUS."""
    if is_graph_ctx_var(graph_var):
        return False                    # already the rewrite's own inner GRAPH
    return _mentions(sub_op, graph_var) or _contains_minus(sub_op)


def rewrite_scoped_graph(sub_op: Any, graph_var: str, uid: str) -> Any:
    """The algebra for `GRAPH ?graph_var { sub_op }` with SPARQL 1.1 scoping."""
    ctx_var = f"{GRAPH_CTX_PREFIX}{uid}"
    inner_var = f"{GRAPH_INNER_PREFIX}{uid}"
    body = _rename(sub_op, graph_var, inner_var)
    compatible_with = lambda g: ExprFunction(name="or", args=[  # noqa: E731
        ExprFunction(name="not", args=[ExprFunction(name="bound", args=[ExprVar(var=inner_var)])]),
        ExprFunction(name="sameterm", args=[ExprVar(var=inner_var), ExprVar(var=g)]),
    ])
    if not _has_triples(body):
        # No triple pattern (FILTERs over `{}`, VALUES): P does not depend on
        # the graph, so it is joined with the enumeration of the named graphs,
        # bound straight to ?g. `GRAPH ?g { FILTER(BOUND(?g)) }` is then empty
        # (`graph-variable-scope`), and a VALUES row binding ?g keeps only its
        # own graph.
        return OpFilter(exprs=[compatible_with(graph_var)], sub_op=OpJoin(
            left=OpGraph(graph_node=VarNode(name=graph_var), sub_op=OpTable(vars=[], rows=[{}])),
            right=body))
    # P's own quads range over the named graphs and bind the context.
    per_graph = OpGraph(graph_node=VarNode(name=ctx_var), sub_op=body)
    return OpExtend(
        var=graph_var, expr=ExprVar(var=ctx_var),
        sub_op=OpFilter(exprs=[compatible_with(ctx_var)], sub_op=per_graph))



def _has_triples(node: Any) -> bool:
    """Whether a pattern contains a triple or path pattern (outside sub-SELECTs)."""
    from ..jena_sparql.jena_types import OpBGP, OpPath
    if isinstance(node, OpBGP):
        return bool(node.triples)
    if isinstance(node, OpPath):
        return True
    if isinstance(node, (list, tuple)):
        return any(_has_triples(x) for x in node)
    if isinstance(node, OpProject):
        return False
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        return any(_has_triples(getattr(node, f.name)) for f in dataclasses.fields(node))
    return False

"""VALUES -> FILTER ... IN, and the cases where that is not the same question.

`VALUES` is the standard SPARQL idiom for "restrict this variable to a set", and
it was by far the slowest way to say it: `emit_table` renders the rows fine, but
the resulting table is a JOIN operand and nothing carries its constants into the
BGP's quad scan, so the pattern is evaluated unrestricted and filtered
afterwards. Measured on a 5.1M-quad space, ten URIs against a two-branch
entity-graph pattern: 19,747ms against 98ms once rewritten, same 9,378 rows.

The rewrite is only sound under conditions this file pins down. Each test below
is a way the two forms give DIFFERENT answers, so a rewrite that fired anyway
would be silently wrong rather than slow — which is the worse failure, and the
reason every guard declines toward today's behaviour.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.jena_sparql.jena_types import LiteralNode, URINode
from vitalgraph.db.sparql_sql.ir import (
    KIND_BGP, KIND_FILTER, KIND_JOIN, KIND_TABLE, PlanV2)
from vitalgraph.db.sparql_sql.rewrite_values_filter import rewrite_values_filter


def _values(vars_, rows) -> PlanV2:
    return PlanV2(kind=KIND_TABLE, values_vars=list(vars_), values_rows=list(rows))


def _bgp(var: str) -> PlanV2:
    """A BGP binding `var`, enough for compute_scope to see it."""
    from vitalgraph.db.sparql_sql.ir import VarSlot
    return PlanV2(kind=KIND_BGP,
                  var_slots={var: VarSlot(name=var, positions=[("q0", "subject_uuid")])})


def _join(a: PlanV2, b: PlanV2) -> PlanV2:
    return PlanV2(kind=KIND_JOIN, children=[a, b])


def _uri(u):
    return URINode(value=u)


def test_single_variable_uri_values_becomes_an_in_filter():
    plan = _join(_values(["s"], [{"s": _uri("urn:a")}, {"s": _uri("urn:b")}]), _bgp("s"))
    out = rewrite_values_filter(plan)
    assert out.kind == KIND_FILTER, "the VALUES join was not rewritten"
    expr = out.filter_exprs[0]
    assert (expr.name or "").lower() == "in"
    assert len(expr.args) == 3               # ?s + two constants


def test_multi_variable_values_is_declined():
    """`VALUES (?a ?b) {(1 2) (3 4)}` constrains the PAIR.

    Two independent INs would admit (1 4), which the VALUES excludes. There is
    no single-variable IN that expresses a correlated tuple set.
    """
    plan = _join(
        _values(["a", "b"], [{"a": _uri("urn:1"), "b": _uri("urn:2")},
                             {"a": _uri("urn:3"), "b": _uri("urn:4")}]),
        _bgp("a"))
    assert rewrite_values_filter(plan).kind == KIND_JOIN


def test_undef_is_declined():
    """UNDEF means "leave unbound", which is not a value.

    A row of UNDEF matches everything, where `IN` over the remaining constants
    matches only those — so rewriting would drop rows.
    """
    plan = _join(_values(["s"], [{"s": _uri("urn:a")}, {"s": None}]), _bgp("s"))
    assert rewrite_values_filter(plan).kind == KIND_JOIN


def test_duplicate_rows_are_declined():
    """VALUES is a MULTISET: a repeated row duplicates each match.

    A FILTER cannot duplicate, so the rewrite would change cardinality — visible
    to COUNT and to any caller not applying DISTINCT.
    """
    plan = _join(_values(["s"], [{"s": _uri("urn:a")}, {"s": _uri("urn:a")}]), _bgp("s"))
    assert rewrite_values_filter(plan).kind == KIND_JOIN


def test_variable_not_bound_by_the_other_side_is_declined():
    """Opposite answers, not merely different plans.

    If the pattern does not bind ?s, the join ASSIGNS it — a cross product that
    yields rows. A FILTER on an unbound variable eliminates every row instead.
    """
    plan = _join(_values(["s"], [{"s": _uri("urn:a")}]), _bgp("other"))
    assert rewrite_values_filter(plan).kind == KIND_JOIN


def test_typed_numeric_literal_is_declined():
    """`5`, `5.0` and `05` are three terms and one value.

    The IN pushdown compares terms, so a typed numeric would match fewer rows
    than VALUES does. Mirrors filter_pushdown's own rule.
    """
    num = LiteralNode(value="5",
                      datatype="http://www.w3.org/2001/XMLSchema#integer")
    plan = _join(_values(["s"], [{"s": num}]), _bgp("s"))
    assert rewrite_values_filter(plan).kind == KIND_JOIN


def test_plain_string_literal_is_accepted():
    """A plain literal's lexical form IS its value, so the two coincide."""
    plan = _join(_values(["s"], [{"s": LiteralNode(value="alice")}]), _bgp("s"))
    assert rewrite_values_filter(plan).kind == KIND_FILTER


def test_empty_values_is_declined():
    """No rows means "match nothing", which an empty IN does not express."""
    plan = _join(_values(["s"], []), _bgp("s"))
    assert rewrite_values_filter(plan).kind == KIND_JOIN


def test_rewrite_recurses_into_children():
    """A VALUES join nested under other operators must still be reached."""
    inner = _join(_values(["s"], [{"s": _uri("urn:a")}]), _bgp("s"))
    outer = PlanV2(kind=KIND_FILTER, children=[inner], filter_exprs=[])
    out = rewrite_values_filter(outer)
    assert out.children[0].kind == KIND_FILTER, "nested VALUES join was not rewritten"


def test_values_on_either_side_of_the_join():
    """Join operand order is not guaranteed, so both positions must be handled."""
    for plan in (_join(_values(["s"], [{"s": _uri("urn:a")}]), _bgp("s")),
                 _join(_bgp("s"), _values(["s"], [{"s": _uri("urn:a")}]))):
        assert rewrite_values_filter(plan).kind == KIND_FILTER

"""Unit tests for DELETE template variable binding — issue 023, second half.

`_delete_from_bindings` used to omit the SQL condition for any delete-template
variable the WHERE clause did not bind:

    if _var_is_bound(dq.subject.name):
        conditions.append(...)
    # else: unbound variable → omit condition (wildcard match)

An omitted condition is not a narrower match, it is *no* match constraint — so
that triple position becomes a wildcard and the delete hits every row.  This is
a fail-open independent of the mapper bug: even with `VALUES` parsed correctly,
any future path that drops a variable from `var_map` would silently widen a
delete.

The correct behaviour is a **no-op**: SPARQL 1.1 §3.1.3 says an unbound
template variable yields no triple, so the quad is skipped. An earlier pass at
issue 023 raised instead — also safe, but not spec-legal. It failed four W3C
update conformance tests once that suite was actually wired into pytest
(`tests/conformance/test_dawg_update_sql_v2.py`).
"""
# pyright: reportOperatorIssue=false, reportArgumentType=false

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql.emit_update import (
    UnboundDeleteTemplateVar,
    _delete_from_bindings,
)
from vitalgraph.db.jena_sparql.jena_types import (
    LiteralNode,
    QuadPattern,
    URINode,
    VarNode,
)

SPACE = "testspace"

# var_map maps sql_col → sparql_var_name, as returned by generate_sql
ALL_BOUND = {"s": "s", "p": "p", "o": "o"}


def _quad(subject, predicate, obj, graph=None) -> QuadPattern:
    return QuadPattern(subject=subject, predicate=predicate,
                       object=obj, graph=graph)


def _spo_quad(graph=None) -> QuadPattern:
    return _quad(VarNode(name="s"), VarNode(name="p"), VarNode(name="o"),
                 graph=graph)


def _is_noop(sql: str) -> bool:
    """A template quad that yields no triple emits a statement that deletes
    nothing."""
    return "DELETE" not in sql.upper()


class TestUnboundVariablesYieldNoTriple:
    """SPARQL 1.1 §3.1.3: a template quad with a variable the WHERE clause does
    not bind produces NO triple — the instantiation is skipped.

    Not an error, and emphatically not a wildcard. The W3C update suite checks
    this directly ("Simple DELETE 7", whose stated purpose is "to test that
    unbound variables in the DELETE clause do not act as wildcards"), so
    rejecting the update instead — which an earlier pass at issue 023 did —
    fails conformance.
    """

    @pytest.mark.parametrize("missing,var_map", [
        ("s", {"p": "p", "o": "o"}),
        ("p", {"s": "s", "o": "o"}),
        ("o", {"s": "s", "p": "p"}),
    ])
    def test_unbound_position_is_a_noop(self, missing, var_map):
        sql = _delete_from_bindings(_spo_quad(), SPACE, "urn:g", var_map=var_map)
        assert _is_noop(sql), (
            f"?{missing} is unbound, so this template yields no triple; "
            f"emitted:\n{sql}"
        )

    def test_no_bindings_at_all_is_a_noop(self):
        """The catastrophic case: WHERE bound nothing, template is all vars."""
        sql = _delete_from_bindings(_spo_quad(), SPACE, "urn:g", var_map={})
        assert _is_noop(sql)

    def test_unbound_graph_var_is_a_noop(self):
        quad = _quad(VarNode(name="s"), VarNode(name="p"), VarNode(name="o"),
                     graph=VarNode(name="g"))
        sql = _delete_from_bindings(quad, SPACE, "urn:g", var_map=ALL_BOUND)
        assert _is_noop(sql)

    def test_never_emits_an_unconstrained_delete(self):
        """The safety property, stated independently of the mechanism.

        Whatever an unbound variable compiles to, it must never be a DELETE
        whose only constraint is the graph — that is a whole-graph delete.
        """
        for var_map in ({}, {"s": "s"}, {"p": "p", "o": "o"}):
            sql = _delete_from_bindings(_spo_quad(), SPACE, "urn:g",
                                        var_map=var_map)
            if "DELETE" in sql.upper():
                assert "q.subject_uuid =" in sql and "q.predicate_uuid =" in sql \
                    and "q.object_uuid =" in sql, (
                    f"emitted a DELETE with a wildcard position "
                    f"(var_map={var_map}):\n{sql}"
                )

    def test_partial_binding_does_not_delete_partially(self):
        """?s bound but ?p/?o not: the whole quad is skipped, not narrowed to
        'every triple of ?s'."""
        sql = _delete_from_bindings(_spo_quad(), SPACE, "urn:g",
                                    var_map={"s": "s"})
        assert _is_noop(sql)


class TestBoundVariablesStillWork:
    """The shapes the issue recorded as correct must stay correct."""

    def test_all_bound_emits_conditions_for_each_position(self):
        sql = _delete_from_bindings(_spo_quad(), SPACE, "urn:g",
                                    var_map=ALL_BOUND)
        assert "q.subject_uuid =" in sql
        assert "q.predicate_uuid =" in sql
        assert "q.object_uuid =" in sql
        assert "USING _upd_bindings b" in sql

    def test_bound_graph_var_emits_context_condition(self):
        quad = _quad(VarNode(name="s"), VarNode(name="p"), VarNode(name="o"),
                     graph=VarNode(name="g"))
        var_map = dict(ALL_BOUND, g="g")
        sql = _delete_from_bindings(quad, SPACE, "urn:g", var_map=var_map)
        assert "q.context_uuid =" in sql

    def test_bound_subject_constant_template(self):
        """DELETE { <uri> ?p ?o } — the current mitigation's shape."""
        quad = _quad(URINode(value="urn:probe:doc0"),
                     VarNode(name="p"), VarNode(name="o"))
        sql = _delete_from_bindings(quad, SPACE, "urn:g",
                                    var_map={"p": "p", "o": "o"})
        assert "q.subject_uuid =" in sql
        assert "USING _upd_bindings b" in sql

    def test_all_constant_template_needs_no_bindings(self):
        quad = _quad(URINode(value="urn:s"), URINode(value="urn:p"),
                     LiteralNode(value="v"))
        sql = _delete_from_bindings(quad, SPACE, "urn:g", var_map={})
        assert "USING _upd_bindings" not in sql
        assert sql.startswith("DELETE FROM")

    def test_graph_defaults_to_target_graph(self):
        sql = _delete_from_bindings(_spo_quad(), SPACE, "urn:g",
                                    var_map=ALL_BOUND)
        assert "q.context_uuid =" in sql

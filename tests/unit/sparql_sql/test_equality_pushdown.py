"""`FILTER(?var = <uri>)` must reach the leaf as a UUID equality.

Without it the comparison stays at the OUTERMOST level and runs against the
variable's resolved TEXT, so the query is computed in full and then filtered. On
a 3-hop traversal pinned by `FILTER(?e0 = <entity>)` the generated SQL contained
the entity's uuid ZERO times and its URI once, in a trailing
`WHERE (v1 = 'urn:graphsyn:entity:1256')` — every entity in the graph walked
three hops, every uuid resolved to text, then all but one starting point thrown
away. Pushing it down measured 524.5 ms -> 0.8 ms on one criterion and
673.6 ms -> 22.3 ms on another (`issues/090`).

The first implementation of the handler silently never fired: it matched on the
operator name `"="` where the mapper emits `"eq"`. Everything passed, because a
push-down that declines is always CORRECT — just slow. That is why these tests
assert the constraint is produced rather than only that results are right; a
correctness-only test cannot tell "pushed" from "not pushed".
"""

from __future__ import annotations

import pytest

from vitalgraph.db.jena_sparql.jena_types import (
    ExprFunction, ExprValue, ExprVar, URINode, LiteralNode)
from vitalgraph.db.sparql_sql.filter_pushdown import (
    _equality_operands, _equality_var, _try_equality_filter)
from vitalgraph.db.sparql_sql.ir import PlanV2, TableRef, VarSlot, KIND_BGP

pytestmark = pytest.mark.unit

URI = "urn:graphsyn:entity:1256"


def _eq(left, right):
    return ExprFunction(name="eq", args=[left, right])


def _var(name):
    return ExprVar(var=name)


def _uri(value=URI):
    return ExprValue(node=URINode(value=value))


class _Aliases:
    """Minimal AliasGenerator: records the constants the push-down registers."""

    def __init__(self):
        self.registered = []

    def register_constant(self, text, ttype):
        self.registered.append((text, ttype))
        return f"c_{len(self.registered)}"


class _Ctx:
    def __init__(self):
        self.aliases = _Aliases()


def _bgp(var_name="e0", alias="q0", col="subject_uuid"):
    return PlanV2(
        kind=KIND_BGP,
        tables=[TableRef(ref_id=alias, kind="quad",
                         table_name="rdf_quad", alias=alias)],
        var_slots={var_name: VarSlot(name=var_name, positions=[(alias, col)])},
    )


class TestRecognition:

    def test_matches_the_mapper_s_operator_name(self):
        """The mapper emits `eq`. Matching on `=` is why the handler shipped
        inert the first time."""
        assert _equality_var(_eq(_var("e0"), _uri())) == "e0"

    def test_matches_with_the_operands_reversed(self):
        assert _equality_var(_eq(_uri(), _var("e0"))) == "e0"

    def test_ignores_other_operators(self):
        for name in ("ne", "ge", "lt", "contains"):
            assert _equality_var(ExprFunction(
                name=name, args=[_var("e0"), _uri()])) is None

    def test_ignores_variable_to_variable(self):
        """Nothing to push: there is no constant to pin the leaf to."""
        assert _equality_operands(_eq(_var("a"), _var("b"))) is None


class TestPushing:

    def test_emits_a_uuid_equality_on_the_leaf(self):
        ctx = _Ctx()
        bgp = _bgp()
        got = _try_equality_filter(_eq(_var("e0"), _uri()), bgp,
                                   "sp_term", {"q0"}, ctx)
        assert got is not None, "the filter was not pushed"
        alias, sql = got
        assert alias == "q0"
        assert sql.startswith("q0.subject_uuid = ")
        assert "__CONST_" in sql, (
            "the constant must be registered for the second materialization "
            "pass, not inlined as text — comparing text is the defect")

    def test_registers_the_uri_as_a_term_constant(self):
        ctx = _Ctx()
        _try_equality_filter(_eq(_var("e0"), _uri()), _bgp(), "sp_term",
                            {"q0"}, ctx)
        assert ctx.aliases.registered == [(URI, "U")]

    def test_declines_when_the_variable_is_not_bound_by_this_bgp(self):
        ctx = _Ctx()
        got = _try_equality_filter(_eq(_var("other"), _uri()), _bgp(),
                                   "sp_term", {"q0"}, ctx)
        assert got is None

    def test_declines_when_the_alias_is_not_a_quad_table(self):
        """A constraint on a non-quad alias would name a column that is not
        there."""
        ctx = _Ctx()
        got = _try_equality_filter(_eq(_var("e0"), _uri()), _bgp(),
                                   "sp_term", set(), ctx)
        assert got is None


class TestWhatMustNotBePushed:

    def test_a_typed_numeric_is_not_one_term(self):
        """`5`, `5.0` and `05` are three terms and one value, so term equality
        is not value equality. `_try_numeric_filter` owns this case; pushing it
        here would silently drop rows."""
        ctx = _Ctx()
        num = ExprValue(node=LiteralNode(
            value="5", datatype="http://www.w3.org/2001/XMLSchema#integer"))
        assert _try_equality_filter(_eq(_var("e0"), num), _bgp(),
                                    "sp_term", {"q0"}, ctx) is None

    def test_a_plain_string_literal_is_one_term(self):
        """RDF 1.1: a plain literal and an xsd:string literal are the same
        term, so this one IS safe."""
        ctx = _Ctx()
        lit = ExprValue(node=LiteralNode(value="alpha", datatype=None))
        got = _try_equality_filter(_eq(_var("e0"), lit), _bgp(),
                                   "sp_term", {"q0"}, ctx)
        assert got is not None
        assert ctx.aliases.registered == [("alpha", "L")]

    def test_a_language_tagged_literal_is_not(self):
        """`"x"@en` and `"x"` are different terms; equality on one must not
        match the other."""
        ctx = _Ctx()
        lit = ExprValue(node=LiteralNode(value="alpha", datatype=None, lang="en"))
        assert _try_equality_filter(_eq(_var("e0"), lit), _bgp(),
                                    "sp_term", {"q0"}, ctx) is None

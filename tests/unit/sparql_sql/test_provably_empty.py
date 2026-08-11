"""`query_is_provably_empty` — a required absent constant makes a query empty.

An equality against a term that was never stored matches nothing. Knowing that
BEFORE running turns the worst case into the cheapest: without it the constant
compiles to a scalar subquery over an empty `_const` CTE, the comparison is NULL
for every row, the planner cannot see it is constant-false, and under the
ordered-scan fence it walks the whole ordering index proving it. Measured on
eq/DateTime at 100k, 40 s+ to return nothing against ~1 ms with this.

These tests are mostly about where it must NOT fire. Each of OPTIONAL, MINUS,
UNION and aggregation breaks the inference in a different way, and getting any
of them wrong turns a performance win into wrong answers.
"""

from __future__ import annotations

from vitalgraph.db.sparql_sql.ir import (
    AliasGenerator, PlanV2, TableRef,
    KIND_BGP, KIND_JOIN, KIND_LEFT_JOIN, KIND_UNION, KIND_MINUS, KIND_GROUP,
    KIND_FILTER, KIND_PROJECT, KIND_SLICE,
)
from vitalgraph.db.sparql_sql.prune_union import query_is_provably_empty

SPACE = "test_space"


def _aliases(resolve: bool):
    """One registered constant, resolved or not."""
    a = AliasGenerator()
    col = a.register_constant("urn:absent", "U")
    if resolve:
        a.resolved_constants[col] = "0000-uuid"
    return a, f"__CONST_{col}__"


def _bgp(constraint: str = "") -> PlanV2:
    p = PlanV2(kind=KIND_BGP,
               tables=[TableRef(ref_id="q0", kind="quad",
                                table_name=f"{SPACE}_rdf_quad", alias="q0")])
    if constraint:
        p.constraints.append(constraint)
    return p


class TestFiresWhenRequired:

    def test_bare_bgp_with_dead_constant(self):
        a, tok = _aliases(resolve=False)
        assert query_is_provably_empty(_bgp(f"q0.object_uuid = {tok}"), a) is True

    def test_resolved_constant_does_not_fire(self):
        a, tok = _aliases(resolve=True)
        assert query_is_provably_empty(_bgp(f"q0.object_uuid = {tok}"), a) is False

    def test_no_constants_at_all(self):
        assert query_is_provably_empty(_bgp(), AliasGenerator()) is False

    def test_through_inner_join(self):
        a, tok = _aliases(resolve=False)
        plan = PlanV2(kind=KIND_JOIN,
                      children=[_bgp(), _bgp(f"q0.object_uuid = {tok}")])
        assert query_is_provably_empty(plan, a) is True

    def test_through_modifiers(self):
        a, tok = _aliases(resolve=False)
        plan = PlanV2(kind=KIND_SLICE, children=[
            PlanV2(kind=KIND_PROJECT, children=[
                PlanV2(kind=KIND_FILTER, children=[
                    _bgp(f"q0.object_uuid = {tok}")])])])
        assert query_is_provably_empty(plan, a) is True

    def test_left_side_of_an_optional_is_required(self):
        a, tok = _aliases(resolve=False)
        plan = PlanV2(kind=KIND_LEFT_JOIN,
                      children=[_bgp(f"q0.object_uuid = {tok}"), _bgp()])
        assert query_is_provably_empty(plan, a) is True


class TestMustNotFire:
    """Each of these would be a WRONG ANSWER, not a slow query."""

    def test_optional_body(self):
        """OPTIONAL { ?s p <absent> } still yields the outer row, unbound."""
        a, tok = _aliases(resolve=False)
        plan = PlanV2(kind=KIND_LEFT_JOIN,
                      children=[_bgp(), _bgp(f"q0.object_uuid = {tok}")])
        assert query_is_provably_empty(plan, a) is False

    def test_minus_body(self):
        """MINUS { ... <absent> } subtracts nothing — the left side survives."""
        a, tok = _aliases(resolve=False)
        plan = PlanV2(kind=KIND_MINUS,
                      children=[_bgp(), _bgp(f"q0.object_uuid = {tok}")])
        assert query_is_provably_empty(plan, a) is False

    def test_union_branch(self):
        """A sibling branch may still match."""
        a, tok = _aliases(resolve=False)
        plan = PlanV2(kind=KIND_UNION,
                      children=[_bgp(f"q0.object_uuid = {tok}"), _bgp()])
        assert query_is_provably_empty(plan, a) is False

    def test_aggregate_over_empty_input_still_returns_a_row(self):
        """SELECT (COUNT(*) AS ?n) over nothing is 0, not empty."""
        a, tok = _aliases(resolve=False)
        plan = PlanV2(kind=KIND_PROJECT, children=[
            PlanV2(kind=KIND_GROUP, children=[
                _bgp(f"q0.object_uuid = {tok}")])])
        assert query_is_provably_empty(plan, a) is False

    def test_dead_constant_only_inside_an_optional_under_a_join(self):
        a, tok = _aliases(resolve=False)
        plan = PlanV2(kind=KIND_JOIN, children=[
            _bgp(),
            PlanV2(kind=KIND_LEFT_JOIN,
                   children=[_bgp(), _bgp(f"q0.object_uuid = {tok}")]),
        ])
        assert query_is_provably_empty(plan, a) is False


class TestTaggedConstraintsAreAlsoChecked:

    def test_tagged_constraint_counts(self):
        a, tok = _aliases(resolve=False)
        p = _bgp()
        p.tagged_constraints.append(("q0", f"q0.object_uuid = {tok}"))
        assert query_is_provably_empty(p, a) is True

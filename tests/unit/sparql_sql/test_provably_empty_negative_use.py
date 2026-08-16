"""A missing term used only to EXCLUDE does not make a query empty (issues/093).

`query_is_provably_empty` short-circuits a query to `LIMIT 0` when it requires a
constant that is not in the term table. That is a large win — an equality
against a never-stored term matched nothing, and proving it by scanning cost
40 s+ on one measured shape.

But "requires" was decided by looking for the constant's token ANYWHERE in a
constraint string, with no regard for the operator. So:

    col = <missing>                  can never hold   -> empty. Correct.
    col IS DISTINCT FROM <missing>   ALWAYS holds     -> empty. Wrong.

`collect.py` emits the second for every `GRAPH ?g`, because SPARQL's `GRAPH ?g`
ranges over the named graphs and the default graph must be excluded — and it
picks `IS DISTINCT FROM` over `!=` precisely so that a missing default-graph
term reads as "no exclusion" rather than filtering every row. The emptiness
check then read that same absence as proof of emptiness.

Consequence: any query with a `GRAPH ?g` and a `default_graph` whose URI has no
term returned ZERO ROWS. An empty default graph is enough to trigger it. Silent
— `LIMIT 0` is not an error, and zero rows is a legitimate answer to a query
matching nothing.

These are unit tests over the predicate itself, so they run without a database.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql.prune_union import (
    _dead_constant_is_required,
    _node_owns_dead_constant,
)

TOK = "__CONST_c_3__"


class TestOperatorDecidesWhetherAbsenceIsFatal:

    @pytest.mark.parametrize("constraint", [
        f"q0.context_uuid = {TOK}",
        f"q0.subject_uuid = {TOK}",
        f"q0.object_uuid={TOK}",
        f"q0.predicate_uuid IN ({TOK}, x)",
    ])
    def test_positive_use_is_required(self, constraint):
        """The optimisation must keep firing where it was right."""
        assert _dead_constant_is_required(constraint, TOK) is True

    @pytest.mark.parametrize("constraint", [
        f"q0.context_uuid IS DISTINCT FROM {TOK}",
        f"q0.context_uuid is distinct from {TOK}",
        f"q0.context_uuid IS DISTINCT FROM ({TOK})",
    ])
    def test_exclusion_is_not_required(self, constraint):
        """Everything is DISTINCT FROM a term that does not exist."""
        assert _dead_constant_is_required(constraint, TOK) is False

    def test_mixed_constraint_is_required(self):
        """One positive use is enough, wherever it sits.

        A constraint that excludes on the dead term AND pins on it still cannot
        hold, so the conservative answer is the correct one here.
        """
        c = f"q0.context_uuid IS DISTINCT FROM {TOK} AND q0.subject_uuid = {TOK}"
        assert _dead_constant_is_required(c, TOK) is True

    def test_absent_token_is_not_required(self):
        assert _dead_constant_is_required("q0.subject_uuid = __CONST_c_9__", TOK) is False


class TestNodeLevelBehaviour:

    class _Plan:
        """Minimal stand-in: the predicate reads only these two attributes."""
        def __init__(self, constraints=None, tagged=None):
            self.constraints = constraints or []
            self.tagged_constraints = tagged or []

    def test_graph_var_exclusion_does_not_kill_the_node(self):
        """The exact constraint collect.py emits for `GRAPH ?g`."""
        plan = self._Plan(constraints=[
            f"q0.context_uuid IS DISTINCT FROM {TOK}",
        ])
        assert _node_owns_dead_constant(plan, {TOK}) is False

    def test_default_graph_pin_still_kills_the_node(self):
        """The constraint collect.py emits OUTSIDE a GRAPH clause.

        Same constant, same absence, opposite meaning — pinned to a graph with
        no terms, nothing can match, and short-circuiting is right.
        """
        plan = self._Plan(constraints=[f"q0.context_uuid = {TOK}"])
        assert _node_owns_dead_constant(plan, {TOK}) is True

    def test_tagged_constraints_are_checked_too(self):
        plan = self._Plan(tagged=[("q0", f"q0.subject_uuid = {TOK}")])
        assert _node_owns_dead_constant(plan, {TOK}) is True

    def test_tagged_exclusion_is_also_spared(self):
        plan = self._Plan(tagged=[("q0", f"q0.context_uuid IS DISTINCT FROM {TOK}")])
        assert _node_owns_dead_constant(plan, {TOK}) is False

    def test_no_dead_constants_at_all(self):
        plan = self._Plan(constraints=["q0.subject_uuid = q1.object_uuid"])
        assert _node_owns_dead_constant(plan, {TOK}) is False

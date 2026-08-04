"""Unit tests for unresolved-variable classification — issue 028.

An expression referencing a variable the emitter cannot resolve compiles to
`NULL`. Whether that is correct depends entirely on one question: **was the
variable in scope here?**

- *Out of scope* — bound nowhere, or bound only in a sibling scope SPARQL
  evaluates independently. `NULL` is the specified result. `FILTER(?x = ?o)`
  errors and excludes the row, `COALESCE` depends on it, `BIND(?nova AS ?z)`
  leaves `?z` unbound.
- *In scope* — the translator should have resolved it and did not. There is no
  data for which NULL is right; the enclosing constraint is silently weakened.
  Issues 023 and 027 were both this, and both produced whole-graph deletes.

The two were indistinguishable until scope was threaded through emission, which
is why 028 sat mitigated rather than fixed. These tests cover the mechanism;
`tests/integration/test_minus_and_exists_correlation.py` covers the behaviour.
"""
# pyright: reportOperatorIssue=false, reportArgumentType=false

from __future__ import annotations

import pytest

from vitalgraph.db.jena_sparql.jena_types import ExprVar
from vitalgraph.db.sparql_sql.emit_expressions import (
    UNRESOLVED_VAR_SQL, UnresolvedVariableError, _var_to_sql,
)
from vitalgraph.db.sparql_sql.emit_context import EmitContext
from vitalgraph.db.sparql_sql.generator import _check_unresolved_vars
from vitalgraph.db.sparql_sql.ir import AliasGenerator
from vitalgraph.db.sparql_sql.sql_type_generation import ColumnInfo, TypeRegistry


def _ctx(all_vars=("missing",)):
    aliases = AliasGenerator()
    ctx = EmitContext(space_id="s", aliases=aliases,
                      types=TypeRegistry(aliases=aliases))
    ctx.query_all_vars = frozenset(all_vars)
    return ctx


class TestClassification:

    def test_out_of_scope_is_recorded_as_legitimate(self):
        ctx = _ctx()
        with ctx.expression_scope({"other"}):
            _var_to_sql(ExprVar(var="missing"), ctx)
        assert ctx.unresolved_vars == [("missing", 0, False, "unresolvable")]

    def test_in_scope_is_recorded_as_a_gap(self):
        """In scope and unresolvable — the translator should have wired it."""
        ctx = _ctx()
        with ctx.expression_scope({"missing"}):
            _var_to_sql(ExprVar(var="missing"), ctx)
        assert ctx.unresolved_vars == [("missing", 0, True, "unresolvable")]

    def test_undeclared_scope_is_treated_as_out_of_scope(self):
        """An emitter that has not declared a scope must not manufacture false
        positives — fail safe toward the permissive reading."""
        ctx = _ctx()
        assert ctx.expr_scope is None
        _var_to_sql(ExprVar(var="missing"), ctx)
        assert ctx.unresolved_vars == [("missing", 0, False, "unresolvable")]

    def test_emitted_sql_is_unchanged_either_way(self):
        """Classification decides whether to raise, not what to emit."""
        for scope in ({"missing"}, {"other"}, None):
            ctx = _ctx()
            with ctx.expression_scope(scope):
                sql = _var_to_sql(ExprVar(var="missing"), ctx)
            assert sql.startswith(UNRESOLVED_VAR_SQL)

    def test_resolvable_var_is_never_recorded(self):
        ctx = _ctx()
        ctx.types.register(ColumnInfo.simple_output("s", "v0"))
        with ctx.expression_scope({"s"}):
            assert _var_to_sql(ExprVar(var="s"), ctx) == "v0"
        assert ctx.unresolved_vars == []


class TestScopeIsPositional:
    """SPARQL scoping depends on *where* the expression sits, so the scope
    cannot be computed once per query."""

    def test_scope_is_restored_after_the_block(self):
        ctx = _ctx()
        with ctx.expression_scope({"a"}):
            assert ctx.expr_scope == frozenset({"a"})
        assert ctx.expr_scope is None

    def test_nested_scopes_do_not_leak_outward(self):
        """An EXISTS body inside a FILTER must not overwrite the FILTER's
        scope — otherwise a later reference is judged against the wrong set."""
        ctx = _ctx()
        with ctx.expression_scope({"outer"}):
            with ctx.expression_scope({"inner"}):
                assert ctx.expr_scope == frozenset({"inner"})
            assert ctx.expr_scope == frozenset({"outer"})

    def test_scope_restored_even_on_exception(self):
        ctx = _ctx()
        with pytest.raises(RuntimeError):
            with ctx.expression_scope({"a"}):
                raise RuntimeError("boom")
        assert ctx.expr_scope is None

    def test_child_contexts_inherit_the_scope(self):
        ctx = _ctx()
        with ctx.expression_scope({"a"}):
            assert ctx.child().expr_scope == frozenset({"a"})

    def test_correlated_scope_survives_a_handler_replacing_expr_scope(self):
        """The EXISTS case: a nested FILTER declares its own pattern's scope,
        which must not hide the correlated outer variables (§8.1.1)."""
        ctx = _ctx(all_vars=("outer",))
        ctx.correlated_scope = frozenset({"outer"})
        with ctx.expression_scope({"inner_only"}):
            _var_to_sql(ExprVar(var="outer"), ctx)
        assert ctx.unresolved_vars == [("outer", 0, True, "unresolvable")]


class TestExistsContextSharesTheRecord:
    """`_exists_to_sql` builds its context directly, not via `ctx.child()`.

    A mark recorded on a context nobody reads is the same as no mark at all —
    and that is precisely how issue 027 stayed invisible. Testing only the
    `child()` path missed this once already.
    """

    def test_inner_context_writes_into_the_parents_record(self):
        import inspect
        from vitalgraph.db.sparql_sql import emit_expressions

        src = inspect.getsource(emit_expressions._exists_to_sql)
        assert "inner_ctx._unresolved_vars = ctx._unresolved_vars" in src, (
            "the EXISTS inner context must share the parent's unresolved "
            "record, or a gap inside the body is recorded and dropped"
        )

    def test_inner_context_carries_the_outer_variables_as_correlated(self):
        import inspect
        from vitalgraph.db.sparql_sql import emit_expressions

        src = inspect.getsource(emit_expressions._exists_to_sql)
        assert "inner_ctx.correlated_scope" in src, (
            "outer variables are in scope inside EXISTS per §8.1.1; without "
            "declaring that, a genuine gap there reads as legitimately unbound"
        )


class TestPolicy:
    """generate_sql decides after emission, with the whole query in view."""

    def test_gap_raises(self):
        with pytest.raises(UnresolvedVariableError, match=r"\?missing"):
            _check_unresolved_vars([("missing", 0, True, "unresolvable")])

    def test_out_of_scope_never_raises(self):
        """Raising here would reject conformant queries — COALESCE, BIND of an
        unbound expression, and cross-scope references all rely on NULL."""
        _check_unresolved_vars([("missing", 0, False, "unresolvable")])

    def test_mixed_raises_only_for_the_gap(self):
        with pytest.raises(UnresolvedVariableError) as exc:
            _check_unresolved_vars([("fine", 0, False, "unresolvable"),
                                    ("broken", 1, True, "unresolvable")])
        assert "?broken" in str(exc.value)
        assert "?fine" not in str(exc.value)

    def test_empty_is_a_noop(self):
        _check_unresolved_vars([])

    def test_message_says_it_is_a_translation_gap(self):
        """The reader must not be tempted to 'fix' this by relaxing a check —
        in scope and unresolvable is always a wiring bug."""
        with pytest.raises(UnresolvedVariableError) as exc:
            _check_unresolved_vars([("x", 0, True, "unresolvable")])
        msg = str(exc.value)
        assert "translation gap" in msg
        assert "in scope" in msg

    def test_raises_without_any_opt_in(self):
        """Production too, not only under test — the fail-open this closes
        produced two whole-graph deletes."""
        import inspect
        from vitalgraph.db.sparql_sql import generator
        assert "_STRICT_UNRESOLVED_VARS" not in inspect.getsource(generator), (
            "the opt-in toggle should be gone; gaps raise unconditionally"
        )


class TestTextNotMaterialised:
    """The other way a variable loses its value — issue 027's *second* half.

    Here the variable resolves: it has a ColumnInfo and a column reference.
    Only its text column is NULL at runtime, because the term JOIN was deferred
    on the belief that nothing referenced it. Scope analysis cannot see this —
    nothing is unresolved — so it needs its own check, keyed on the invariant
    `compute_text_needed_vars` states: a variable may only be deferred if it is
    "NOT referenced by any expression".
    """

    def _ctx_with(self, materialized):
        ctx = _ctx(all_vars=("s",))
        ctx.types.register(
            ColumnInfo.simple_output("s", "v0", from_triple=True,
                                     text_materialized=materialized))
        return ctx

    def test_deferred_text_is_recorded_as_a_gap(self):
        ctx = self._ctx_with(False)
        assert _var_to_sql(ExprVar(var="s"), ctx) == "v0"
        assert ctx.unresolved_vars == [("s", 0, True, "text-not-materialised")]

    def test_materialised_text_is_not_recorded(self):
        ctx = self._ctx_with(True)
        assert _var_to_sql(ExprVar(var="s"), ctx) == "v0"
        assert ctx.unresolved_vars == []

    def test_it_does_not_depend_on_declared_scope(self):
        """Unlike the unresolvable case, this is a broken invariant regardless
        of where the expression sits — an expression referencing the variable
        is itself the proof the deferral was wrong."""
        ctx = self._ctx_with(False)
        with ctx.expression_scope(set()):
            _var_to_sql(ExprVar(var="s"), ctx)
        assert ctx.unresolved_vars[0][2] is True

    def test_still_returns_the_column(self):
        """Marking must not change what is emitted."""
        ctx = self._ctx_with(False)
        assert _var_to_sql(ExprVar(var="s"), ctx) == "v0"

    def test_message_names_the_actual_cause(self):
        """'unresolvable' would be wrong here and would send the reader to the
        wrong fix — the variable resolved fine."""
        with pytest.raises(UnresolvedVariableError) as exc:
            _check_unresolved_vars([("s", 0, True, "text-not-materialised")])
        msg = str(exc.value)
        assert "text-not-materialised" in msg
        assert "DID resolve" in msg
        assert "reference collector" in msg

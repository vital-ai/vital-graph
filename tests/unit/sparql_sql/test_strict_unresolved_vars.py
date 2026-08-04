"""Unit tests for unresolved-variable marking and the strict ratchet — issue 028.

An expression referencing a variable the emitter cannot resolve compiles to
`NULL`. That is correct for a *legitimately* unbound variable (bound nowhere,
or bound only in a scope SPARQL evaluates independently) and wrong for a
*translation gap* — a variable that should have resolved and did not. Issues
023 and 027 were both the latter, and both silently widened a DELETE.

The two are indistinguishable at the point of emission, so the emitter does not
decide: it **marks** (`ctx.add_unresolved_var`), following the same convention
as `_is_null_placeholder` in `emit_group` and the deferred-UUID / vector /
fuzzy request lists on `EmitContext`. `generator.generate_sql` reads the marks
after emission and applies policy there.

Production is permissive; the test suite runs strict with the known legitimate
occurrences allowlisted in `tests/conftest.py`.
"""
# pyright: reportOperatorIssue=false, reportArgumentType=false

from __future__ import annotations

import logging

import pytest

from vitalgraph.db.jena_sparql.jena_types import ExprVar
from vitalgraph.db.sparql_sql import generator
from vitalgraph.db.sparql_sql.emit_expressions import (
    UNRESOLVED_VAR_SQL,
    UnresolvedVariableError,
    _var_to_sql,
)
from vitalgraph.db.sparql_sql.emit_context import EmitContext
from vitalgraph.db.sparql_sql.generator import (
    _check_unresolved_vars,
    set_strict_unresolved_vars,
)
from vitalgraph.db.sparql_sql.ir import AliasGenerator
from vitalgraph.db.sparql_sql.sql_type_generation import ColumnInfo, TypeRegistry


def _ctx(all_vars=("missing",)):
    aliases = AliasGenerator()
    ctx = EmitContext(space_id="s", aliases=aliases,
                      types=TypeRegistry(aliases=aliases))
    ctx.query_all_vars = frozenset(all_vars)
    return ctx


@pytest.fixture
def strict():
    prev = set_strict_unresolved_vars(True)
    yield
    set_strict_unresolved_vars(prev)


@pytest.fixture
def permissive():
    prev = set_strict_unresolved_vars(False)
    yield
    set_strict_unresolved_vars(prev)


class TestMarking:
    """The emitter marks; it does not decide. Marking is unconditional — it
    must not depend on strict mode, or production would lose the trace."""

    def test_unresolvable_var_is_recorded(self, permissive):
        ctx = _ctx()
        _var_to_sql(ExprVar(var="missing"), ctx)
        assert [v for v, _ in ctx.unresolved_vars] == ["missing"]

    def test_emitted_value_is_still_null(self, permissive):
        """The VALUE must stay NULL — it is the SPARQL-specified result when
        the variable is legitimately unbound (§10.5), and the emitter cannot
        tell that case from a translation gap. Only the annotation is new."""
        sql = _var_to_sql(ExprVar(var="missing"), _ctx())
        assert sql.startswith("NULL")
        assert UNRESOLVED_VAR_SQL == "NULL"
        # everything after the value is an inert SQL comment
        assert sql.removeprefix("NULL").strip().startswith("/*")
        assert sql.rstrip().endswith("*/")

    def test_emitted_sql_names_the_variable(self, permissive):
        """Generated SQL is logged, so it outlives the EmitContext. Someone
        debugging from a log has the SQL and nothing else — a bare NULL there
        is indistinguishable from the many legitimate NULL companions."""
        sql = _var_to_sql(ExprVar(var="missing"), _ctx())
        assert "?missing" in sql
        assert "vg:unresolved-var" in sql

    def test_marker_is_greppable_and_namespaced(self, permissive):
        """A generic word would collide with ordinary SQL text in a log grep."""
        sql = _var_to_sql(ExprVar(var="missing"), _ctx())
        assert "vg:" in sql

    def test_records_depth(self, permissive):
        ctx = _ctx()
        _var_to_sql(ExprVar(var="missing"), ctx)
        assert ctx.unresolved_vars[0][1] == ctx.depth

    def test_resolvable_var_is_not_recorded(self, permissive):
        ctx = _ctx()
        ctx.types.register(ColumnInfo.simple_output("s", "v0"))
        assert _var_to_sql(ExprVar(var="s"), ctx) == "v0"
        assert ctx.unresolved_vars == []

    def test_var_not_named_in_query_is_not_recorded(self, permissive):
        """Gated on query_all_vars: a variable that is not part of the query at
        all is not evidence of a translation gap."""
        ctx = _ctx(all_vars=())
        assert _var_to_sql(ExprVar(var="stranger"), ctx) == "NULL"
        assert ctx.unresolved_vars == []

    def test_marks_survive_from_child_contexts(self, permissive):
        """EXISTS bodies and UNION branches emit into child contexts. Their
        marks must reach the parent, or the post-generation check sees nothing
        — which is exactly how issue 027 stayed invisible.
        """
        parent = _ctx()
        child = parent.child()
        _var_to_sql(ExprVar(var="missing"), child)
        assert [v for v, _ in parent.unresolved_vars] == ["missing"]

    def test_marking_happens_in_strict_mode_too(self, strict):
        ctx = _ctx()
        _var_to_sql(ExprVar(var="missing"), ctx)
        assert ctx.unresolved_vars


class TestPolicy:
    """generate_sql decides, after the whole query has been emitted."""

    def test_strict_raises(self, strict):
        with pytest.raises(UnresolvedVariableError, match=r"\?missing"):
            _check_unresolved_vars([("missing", 0)])

    def test_permissive_does_not_raise(self, permissive):
        _check_unresolved_vars([("missing", 0)])  # no exception

    def test_no_marks_never_raises(self, strict):
        _check_unresolved_vars([])  # no exception

    def test_message_is_actionable(self, strict):
        """Whoever hits this needs to know which of the two cases it is and
        what to do — an opaque error would just get allowlisted blindly."""
        with pytest.raises(UnresolvedVariableError) as exc:
            _check_unresolved_vars([("missing", 2)])
        msg = str(exc.value)
        assert "allowlist" in msg          # the legitimate path
        assert "translation gap" in msg    # the bug path
        assert "conftest" in msg           # where to do it

    def test_message_lists_every_variable(self, strict):
        with pytest.raises(UnresolvedVariableError) as exc:
            _check_unresolved_vars([("a", 0), ("b", 1)])
        assert "?a" in str(exc.value) and "?b" in str(exc.value)


class TestToggle:

    def test_default_is_permissive(self):
        """Production must not inherit the test suite's strictness.

        The ratchet is opt-in precisely because raising on a legitimately
        unbound variable would break four passing W3C conformance tests.
        """
        import inspect
        src = inspect.getsource(generator)
        assert "_STRICT_UNRESOLVED_VARS = False" in src

    def test_set_returns_previous_value(self):
        prev = set_strict_unresolved_vars(True)
        try:
            assert set_strict_unresolved_vars(False) is True
        finally:
            set_strict_unresolved_vars(prev)


class TestWarningStillEmitted:

    def test_warns_regardless_of_mode(self, permissive, caplog):
        with caplog.at_level(logging.WARNING,
                             logger="vitalgraph.db.sparql_sql.emit_expressions"):
            _var_to_sql(ExprVar(var="missing"), _ctx())
        assert any("not resolvable" in r.getMessage() for r in caplog.records)

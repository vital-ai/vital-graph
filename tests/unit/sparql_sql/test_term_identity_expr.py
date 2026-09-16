"""Unit tests for term_identity_expr and its use in MINUS — issue 026.

`emit_minus` used to compare shared variables on the raw `__uuid` companion.
Producers that synthesize a value (BIND, VALUES, aggregates) emit a literal
`NULL::uuid` there, so a bound value read as unbound, the domain-intersection
test could never be satisfied, and the MINUS silently became a no-op.

These run without a database — they assert on the generated SQL, which is where
the defect lived.
"""
# pyright: reportOperatorIssue=false, reportArgumentType=false

from __future__ import annotations

import re

import pytest

from vitalgraph.db.sparql_sql.sql_type_generation import term_identity_expr

SPACE = "testspace"


class TestTermIdentityExpr:

    def test_prefers_the_stored_uuid(self):
        sql = term_identity_expr("ml0", "v0", SPACE)
        assert sql.startswith("COALESCE(ml0.v0__uuid,")

    def test_derives_from_companions_when_uuid_is_null(self):
        sql = term_identity_expr("ml0", "v0", SPACE)
        assert "vitalgraph_term_uuid(" in sql
        # text, type, lang and datatype all participate — a derived UUID that
        # ignored lang/datatype would not equal the term table's UUID
        assert "CAST(ml0.v0 AS text)" in sql
        assert "CAST(ml0.v0__type AS char(1))" in sql
        assert "ml0.v0__lang" in sql
        assert "ml0.v0__datatype" in sql

    def test_resolves_datatype_id_from_the_space_datatype_table(self):
        sql = term_identity_expr("ml0", "v0", SPACE)
        assert f"FROM {SPACE}_datatype dt" in sql
        assert "dt.datatype_uri = ml0.v0__datatype" in sql

    def test_unbound_stays_null(self):
        """The derived branch is guarded on the text column being non-NULL, so
        a genuinely unbound variable keeps NULL identity and the SPARQL §10.5
        'NULL means unbound' reading still holds."""
        sql = term_identity_expr("ml0", "v0", SPACE)
        assert "CASE WHEN ml0.v0 IS NOT NULL THEN" in sql

    def test_no_alias(self):
        sql = term_identity_expr(None, "v0", SPACE)
        assert "COALESCE(v0__uuid," in sql
        assert "CAST(v0 AS text)" in sql
        assert ".v0" not in sql

    @pytest.mark.parametrize("alias,name", [("mr0", "v7"), ("ml3", "ex_v2")])
    def test_alias_and_name_are_threaded_through(self, alias, name):
        sql = term_identity_expr(alias, name, SPACE)
        assert f"COALESCE({alias}.{name}__uuid," in sql
        assert f"CAST({alias}.{name} AS text)" in sql


class TestEmitMinusUsesIt:
    """The MINUS correlation must not reduce to a bare __uuid comparison."""

    def _minus_sql(self):
        """MINUS whose shared variable ?s is bound by VALUES on both sides —
        the shape whose __uuid columns are literal NULLs."""
        from vitalgraph.db.sparql_sql.ir import PlanV2, KIND_MINUS, KIND_TABLE
        from vitalgraph.db.jena_sparql.jena_types import URINode
        from .emit_helpers import _make_ctx

        def _values(uri):
            return PlanV2(
                kind=KIND_TABLE,
                values_vars=["s"],
                values_rows=[{"s": URINode(value=uri)}],
            )

        ctx = _make_ctx({})
        plan = PlanV2(kind=KIND_MINUS,
                      children=[_values("urn:a"), _values("urn:x")])
        from vitalgraph.db.sparql_sql.emit_minus import emit_minus
        return emit_minus(plan, ctx)

    def test_correlation_is_not_a_bare_uuid_comparison(self):
        sql = self._minus_sql()
        # A VALUES row has NULL::uuid in its __uuid column; comparing that
        # column directly is exactly the bug.
        bare = re.search(r"\(m[lr]\d+\.\w+__uuid IS NOT NULL AND m[lr]\d+\.\w+__uuid IS NOT NULL\)", sql)
        assert bare is None, (
            f"MINUS still correlates on raw __uuid columns — a VALUES/BIND-bound "
            f"shared variable will read as unbound:\n{bare.group(0) if bare else ''}"
        )

    def test_correlation_uses_derived_identity(self):
        sql = self._minus_sql()
        assert "vitalgraph_term_uuid(" in sql
        assert "COALESCE(" in sql

    def test_still_emits_both_compatibility_and_domain_clauses(self):
        """SPARQL §18.5 needs both halves; the fix must not drop one.

        BOTH HALVES ARE STILL THERE, constant-folded. A VALUES row binds its
        variable in every solution, so `compute_scope` puts it in `defined` on
        both sides, the NULL arms of the compatibility test are dead, and the
        domain intersection is satisfied by construction (`issues/205`):

            compatibility   `l IS NULL OR r IS NULL OR l = r`  ->  `l = r`
            domain          `l IS NOT NULL AND r IS NOT NULL`  ->  `TRUE`

        That folding is the point rather than a side effect: PostgreSQL cannot
        hash or index the three-part disjunction, so the correlated NOT EXISTS
        re-scans the right side per outer row and a LIMIT never stops it —
        661,626 buffers to return 25 rows on a 7.4M-quad fixture.

        The unfolded form is still required where a variable is NOT provably
        bound, and `test_optional_side_keeps_the_null_arms` covers that.
        """
        sql = self._minus_sql()
        assert "NOT EXISTS" in sql
        # The identity comparison survives in some form.
        assert re.search(r"=\s*COALESCE|COALESCE[^=]*=", sql) or "= m" in sql, (
            f"the compatibility test disappeared entirely:\n{sql}")

    def test_optional_side_keeps_the_null_arms(self):
        """A variable the right side only MAYBE binds keeps the full test.

        This is the guard on the folding above. `compute_scope` puts an
        OPTIONAL's right-hand variables in `maybe`, not `defined`, so the
        unbound arms are live: a right-hand solution that does not bind ?s is
        COMPATIBLE with a left-hand one that does, and must not remove it.
        Folding to `l = r` there would delete rows SPARQL keeps.
        """
        from vitalgraph.db.sparql_sql.ir import (
            PlanV2, KIND_MINUS, KIND_TABLE, KIND_LEFT_JOIN)
        from vitalgraph.db.jena_sparql.jena_types import URINode
        from .emit_helpers import _make_ctx

        def _values(var, uri):
            return PlanV2(kind=KIND_TABLE, values_vars=[var],
                          values_rows=[{var: URINode(value=uri)}])

        # right = { ?anchor ... } OPTIONAL { ?s ... }, so ?s is only MAYBE bound.
        right = PlanV2(kind=KIND_LEFT_JOIN,
                       children=[_values("anchor", "urn:anchor"),
                                 _values("s", "urn:x")])
        plan = PlanV2(kind=KIND_MINUS,
                      children=[_values("s", "urn:a"), right])
        from vitalgraph.db.sparql_sql.emit_minus import emit_minus
        sql = emit_minus(plan, _make_ctx({}))

        assert "IS NULL OR" in sql, (
            "?s is only MAYBE bound on the right (it comes from an OPTIONAL), "
            "so the compatibility test must keep its unbound arms — folding to "
            "an equality would remove left rows that SPARQL keeps")

    def test_a_provably_bound_variable_folds_to_equality(self):
        """VALUES binds its variable, so the NULL arms are dead code."""
        sql = self._minus_sql()
        assert "IS NULL OR" not in sql, (
            "a variable bound in every solution on both sides does not need the "
            "unbound arms, and keeping them costs the anti-join its index "
            "(issues/205)")

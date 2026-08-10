"""Unit tests for generator.prepend_ctes — CTE clauses must MERGE, not stack.

Emitted SQL sometimes already opens with its own `WITH`: the candidate-driven
negation path builds one (emit_backward.emit_candidate_ctes). Concatenating a
second `WITH` in front of it yields `WITH a AS (...) WITH b AS (...)`, which is
a syntax error rather than a slow query.

The emit-pipeline suite parses generated SQL with a real PostgreSQL parser, but
it validated the query BODY without the WITH prefix, so it could not see this;
that is fixed too. These pin the merge directly and need no optional dependency.
"""

from __future__ import annotations

from vitalgraph.db.sparql_sql.ir import AliasGenerator
from vitalgraph.db.sparql_sql.generator import prepend_ctes

TERM = "test_space_term"


def _aliases_with_unresolved_constant() -> AliasGenerator:
    """An AliasGenerator that will produce a _const CTE.

    build_constants_cte emits only for constants that were NOT resolved during
    materialization, so registering one and resolving nothing is what makes the
    prefix appear.
    """
    a = AliasGenerator()
    a.register_constant("CA", "L")
    return a


class TestPrependCtes:

    def test_no_ctes_returns_sql_unchanged(self):
        sql = "SELECT 1"
        assert prepend_ctes(sql, AliasGenerator(), TERM) == sql

    def test_resolved_constants_need_no_prefix(self):
        a = AliasGenerator()
        col = a.register_constant("CA", "L")
        a.resolved_constants[col] = "0000-uuid"
        assert prepend_ctes("SELECT 1", a, TERM) == "SELECT 1"

    def test_unresolved_constant_gets_a_with_clause(self):
        a = _aliases_with_unresolved_constant()
        out = prepend_ctes("SELECT 1", a, TERM)
        assert out.startswith("WITH _const AS (")
        assert out.rstrip().endswith("SELECT 1")

    def test_merges_with_an_existing_with_clause(self):
        """The whole point: one WITH, not two."""
        a = _aliases_with_unresolved_constant()
        out = prepend_ctes("WITH excl AS (SELECT 1) SELECT * FROM excl", a, TERM)

        assert out.startswith("WITH _const AS (")
        # the query's own CTE survives, and its WITH keyword does not
        assert "excl AS (SELECT 1)" in out
        assert "WITH excl" not in out
        # exactly one WITH keyword in the whole statement
        assert len([t for t in out.split() if t.upper() == "WITH"]) == 1

    def test_merge_is_comma_separated(self):
        a = _aliases_with_unresolved_constant()
        out = prepend_ctes("WITH excl AS (SELECT 1) SELECT 1", a, TERM)
        assert "),\nexcl AS" in out

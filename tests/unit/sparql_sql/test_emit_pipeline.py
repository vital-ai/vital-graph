"""End-to-end emit pipeline tests — collect → emit → valid SQL.

Uses real sidecar fixtures to reconstruct PlanV2 trees, runs the full
emit pipeline (no DB), and validates the generated SQL is syntactically
valid using pglast (libpg_query wrapper).

This catches:
- Emit handlers crashing on real query shapes
- Malformed SQL (unclosed parens, bad syntax, missing aliases)
- TypeRegistry / companion column issues with real variable sets
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

try:
    import pglast
    HAS_PGLAST = True
except ImportError:
    HAS_PGLAST = False

from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
from vitalgraph.db.sparql_sql.collect import collect
from vitalgraph.db.sparql_sql.ir import AliasGenerator, PlanV2, KIND_PROJECT
from vitalgraph.db.sparql_sql.var_scope import compute_scope, compute_text_needed_vars
from vitalgraph.db.sparql_sql.emit_context import EmitContext, ProcessingTrace
from vitalgraph.db.sparql_sql.emit import emit
from vitalgraph.db.sparql_sql.filter_pushdown import push_text_filters
from vitalgraph.db.sparql_sql.ir import KIND_FILTER


FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "plan_trees" / "json"
SPACE_ID = "test_space"


def _load_fixtures():
    if not FIXTURE_DIR.exists():
        return []
    fixtures = []
    for path in sorted(FIXTURE_DIR.glob("*.json")):
        data = json.loads(path.read_text())
        fixtures.append((data["name"], data))
    return fixtures


def _generate_sql_from_fixture(fixture: dict) -> str:
    """Run the pure (no-DB) pipeline: collect → optimize → emit → SQL."""
    compile_result = map_compile_response(fixture["sidecar_response"])
    aliases = AliasGenerator()
    plan = collect(compile_result.algebra, SPACE_ID, aliases)

    # Apply filter pushdown (pure, no DB)
    for node in list(plan.walk()):
        if node.kind == KIND_FILTER:
            push_text_filters(node, SPACE_ID)

    # Compute text-needed vars
    text_needed = compute_text_needed_vars(plan)

    # Build EmitContext
    trace = ProcessingTrace(sparql_query=fixture.get("sparql", ""))
    ctx = EmitContext(
        space_id=SPACE_ID,
        aliases=aliases,
        trace=trace,
        text_needed_vars=text_needed,
    )

    # Emit SQL
    sql = emit(plan, ctx)
    return sql


FIXTURES = _load_fixtures()

pytestmark = pytest.mark.skipif(
    len(FIXTURES) == 0,
    reason="No plan tree fixtures found. Run generate_fixtures.py first.",
)


# ---------------------------------------------------------------------------
# Emit produces non-empty SQL
# ---------------------------------------------------------------------------

class TestEmitProducesSQL:

    @pytest.mark.parametrize("name,fixture", FIXTURES, ids=[f[0] for f in FIXTURES])
    def test_emit_produces_nonempty_sql(self, name, fixture):
        """The emit pipeline should produce a non-empty SQL string."""
        sql = _generate_sql_from_fixture(fixture)
        assert sql is not None
        assert len(sql.strip()) > 0, f"Empty SQL for query: {name}"

    @pytest.mark.parametrize("name,fixture", FIXTURES, ids=[f[0] for f in FIXTURES])
    def test_sql_contains_select(self, name, fixture):
        """Generated SQL should contain SELECT (all fixtures are SELECT queries)."""
        sql = _generate_sql_from_fixture(fixture)
        assert "SELECT" in sql.upper(), f"No SELECT in SQL for: {name}"

    @pytest.mark.parametrize("name,fixture", FIXTURES, ids=[f[0] for f in FIXTURES])
    def test_sql_references_space_tables(self, name, fixture):
        """Generated SQL should reference the space's quad or term tables."""
        sql = _generate_sql_from_fixture(fixture)
        # DESCRIBE <uri> without WHERE produces degenerate fallback SQL
        if "FALSE" in sql and len(sql.strip()) < 30:
            pytest.skip("Degenerate SQL for pattern-less DESCRIBE")
        assert SPACE_ID in sql, (
            f"SQL doesn't reference space '{SPACE_ID}' tables for: {name}"
        )


# ---------------------------------------------------------------------------
# SQL syntax validation via pglast
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not HAS_PGLAST, reason="pglast not installed")
class TestSQLSyntaxValid:

    @pytest.mark.parametrize("name,fixture", FIXTURES, ids=[f[0] for f in FIXTURES])
    def test_sql_parses_as_valid_postgresql(self, name, fixture):
        """Generated SQL must be syntactically valid PostgreSQL."""
        sql = _generate_sql_from_fixture(fixture)

        # pglast.parse_sql raises ParseError for invalid SQL
        try:
            pglast.parse_sql(sql)
        except pglast.parser.ParseError as e:
            # Show the SQL in the failure message for debugging
            pytest.fail(
                f"Invalid SQL for '{name}':\n"
                f"Error: {e}\n"
                f"SQL (first 500 chars):\n{sql[:500]}"
            )


# ---------------------------------------------------------------------------
# Trace structure tests
# ---------------------------------------------------------------------------

class TestTraceStructure:

    @pytest.mark.parametrize("name,fixture", FIXTURES, ids=[f[0] for f in FIXTURES])
    def test_trace_has_steps(self, name, fixture):
        """The processing trace should record steps."""
        compile_result = map_compile_response(fixture["sidecar_response"])
        aliases = AliasGenerator()
        plan = collect(compile_result.algebra, SPACE_ID, aliases)
        text_needed = compute_text_needed_vars(plan)
        trace = ProcessingTrace(sparql_query=fixture.get("sparql", ""))
        ctx = EmitContext(
            space_id=SPACE_ID, aliases=aliases,
            trace=trace, text_needed_vars=text_needed,
        )
        emit(plan, ctx)

        assert len(trace.steps) > 0, f"No trace steps for: {name}"
        assert trace.max_depth() >= 0

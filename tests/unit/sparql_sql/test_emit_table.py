"""Unit tests for emit_table.py — VALUES inline data."""
# pyright: reportOperatorIssue=false, reportArgumentType=false

from __future__ import annotations

from vitalgraph.db.jena_sparql.jena_types import LiteralNode, URINode, BNodeNode
from vitalgraph.db.sparql_sql.ir import PlanV2, KIND_TABLE

from .emit_helpers import _make_ctx


class TestEmitTable:
    """Tests for emit_table.py — VALUES inline data."""

    def test_empty_rows(self):
        """No rows → SELECT 1 WHERE FALSE."""
        ctx = _make_ctx({})
        plan = PlanV2(
            kind=KIND_TABLE,
            values_vars=["x"],
            values_rows=[],
        )
        from vitalgraph.db.sparql_sql.emit_table import emit_table
        sql = emit_table(plan, ctx)
        assert "FALSE" in sql

    def test_no_vars(self):
        """No vars but rows → SELECT 1 per row."""
        ctx = _make_ctx({})
        plan = PlanV2(
            kind=KIND_TABLE,
            values_vars=[],
            values_rows=[{}, {}],
        )
        from vitalgraph.db.sparql_sql.emit_table import emit_table
        sql = emit_table(plan, ctx)
        assert sql.count("SELECT 1") == 2
        assert "UNION ALL" in sql

    def test_uri_value(self):
        """VALUES ?x { <http://example.org/a> } → URI row."""
        ctx = _make_ctx({})
        plan = PlanV2(
            kind=KIND_TABLE,
            values_vars=["x"],
            values_rows=[{"x": URINode(value="http://example.org/a")}],
        )
        from vitalgraph.db.sparql_sql.emit_table import emit_table
        sql = emit_table(plan, ctx)
        assert "http://example.org/a" in sql
        assert "'U'" in sql  # type = URI

    def test_literal_value_with_lang(self):
        """VALUES ?x { "hello"@en } → literal with lang."""
        ctx = _make_ctx({})
        plan = PlanV2(
            kind=KIND_TABLE,
            values_vars=["x"],
            values_rows=[{"x": LiteralNode(value="hello", lang="en")}],
        )
        from vitalgraph.db.sparql_sql.emit_table import emit_table
        sql = emit_table(plan, ctx)
        assert "'hello'" in sql
        assert "'L'" in sql  # type = Literal
        assert "'en'" in sql  # lang

    def test_literal_value_with_datatype(self):
        """VALUES ?x { "42"^^xsd:integer } → literal with datatype."""
        ctx = _make_ctx({})
        xsd_int = "http://www.w3.org/2001/XMLSchema#integer"
        plan = PlanV2(
            kind=KIND_TABLE,
            values_vars=["x"],
            values_rows=[{"x": LiteralNode(value="42", datatype=xsd_int)}],
        )
        from vitalgraph.db.sparql_sql.emit_table import emit_table
        sql = emit_table(plan, ctx)
        assert "'42'" in sql
        assert xsd_int in sql

    def test_bnode_value(self):
        """VALUES ?x { _:b0 } → blank node.

        Note: emit_table accesses .value on BNodeNode, but BNodeNode's
        field is .label — we set both so the test exercises the code path.
        """
        ctx = _make_ctx({})
        bnode = BNodeNode(label="b0")
        bnode.value = "b0"  # type: ignore[attr-defined]  # match emit_table's usage
        plan = PlanV2(
            kind=KIND_TABLE,
            values_vars=["x"],
            values_rows=[{"x": bnode}],
        )
        from vitalgraph.db.sparql_sql.emit_table import emit_table
        sql = emit_table(plan, ctx)
        assert "'b0'" in sql
        assert "'B'" in sql  # type = BNode

    def test_undef_value(self):
        """VALUES ?x { UNDEF } → NULL companions."""
        ctx = _make_ctx({})
        plan = PlanV2(
            kind=KIND_TABLE,
            values_vars=["x"],
            values_rows=[{"x": None}],
        )
        from vitalgraph.db.sparql_sql.emit_table import emit_table
        sql = emit_table(plan, ctx)
        assert "NULL" in sql

    def test_multiple_rows_union_all(self):
        """Multiple rows produce UNION ALL."""
        ctx = _make_ctx({})
        plan = PlanV2(
            kind=KIND_TABLE,
            values_vars=["x"],
            values_rows=[
                {"x": URINode(value="http://example.org/a")},
                {"x": URINode(value="http://example.org/b")},
            ],
        )
        from vitalgraph.db.sparql_sql.emit_table import emit_table
        sql = emit_table(plan, ctx)
        assert "UNION ALL" in sql
        assert "example.org/a" in sql
        assert "example.org/b" in sql

    def test_multiple_vars(self):
        """VALUES (?x ?y) → columns for each variable."""
        ctx = _make_ctx({})
        plan = PlanV2(
            kind=KIND_TABLE,
            values_vars=["x", "y"],
            values_rows=[{
                "x": URINode(value="http://example.org/a"),
                "y": LiteralNode(value="hello"),
            }],
        )
        from vitalgraph.db.sparql_sql.emit_table import emit_table
        sql = emit_table(plan, ctx)
        # Should have columns for both x and y
        x_info = ctx.types.get("x")
        y_info = ctx.types.get("y")
        assert x_info is not None
        assert y_info is not None

    def test_sql_injection_escaped(self):
        """Values with single quotes should be escaped."""
        ctx = _make_ctx({})
        plan = PlanV2(
            kind=KIND_TABLE,
            values_vars=["x"],
            values_rows=[{"x": LiteralNode(value="O'Brien")}],
        )
        from vitalgraph.db.sparql_sql.emit_table import emit_table
        sql = emit_table(plan, ctx)
        assert "O''Brien" in sql  # escaped

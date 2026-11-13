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
        """VALUES ?x { _:b0 } emits SQL for a plain BNodeNode.

        NO ATTRIBUTE PATCHING. The previous version of this test set `.value`
        onto the node before calling, because that is what emit_table read —
        and BNodeNode has no `value` field, so every real VALUES clause
        containing a blank node raised AttributeError while this test passed
        (issues/066). A test that patches the object into the shape the
        implementation expects describes the implementation, not the contract,
        and cannot fail when the implementation is wrong.

        Built from the type as the AST mapper produces it, so the test breaks
        if the field is renamed or the branch reverts.
        """
        ctx = _make_ctx({})
        plan = PlanV2(
            kind=KIND_TABLE,
            values_vars=["x"],
            values_rows=[{"x": BNodeNode(label="b0")}],
        )
        from vitalgraph.db.sparql_sql.emit_table import emit_table
        sql = emit_table(plan, ctx)
        assert "'b0'" in sql, "the label was not emitted"
        assert "'B'" in sql, "the term type was not marked as a blank node"
        # The bare label, matching storage: term_text holds the label and the
        # serializers re-add `_:`. Emitting the prefix here would double it.
        assert "'_:b0'" not in sql, (
            "emitted the `_:` prefix into the VALUES row; term_text holds the "
            "bare label and serializers add the prefix on the way out")

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


class TestValuesLiteralLanes:
    """A VALUES literal fills `__num`/`__bool`/`__dt` as a stored term does.

    They were always NULL, so `VALUES ?a { 1 2 } FILTER(?a > 1)` dropped every
    row and `BIND(?a + 1 AS ?y)` was unbound (issues/340).
    """

    XSD = "http://www.w3.org/2001/XMLSchema#"

    def _sql(self, node):
        from vitalgraph.db.sparql_sql.emit_table import emit_table
        plan = PlanV2(kind=KIND_TABLE, values_vars=["x"], values_rows=[{"x": node}])
        return emit_table(plan, _make_ctx({}))

    def test_a_number_is_on_the_numeric_lane(self):
        for dt, text in [("integer", "1"), ("decimal", "2.5"), ("double", "1e3")]:
            sql = self._sql(LiteralNode(value=text, datatype=f"{self.XSD}{dt}"))
            num = [p for p in sql.split(", ") if "__num" in p][0]
            assert f"CAST('{text}' AS NUMERIC)" in num, num

    def test_a_malformed_number_stays_off_the_lane_without_a_cast(self):
        """PostgreSQL coerces a quoted constant while parsing, so even a CASE
        branch never taken fails the statement: no CAST may be emitted."""
        for text in ("xyz", "1\n", "1.2.3", ""):
            sql = self._sql(LiteralNode(value=text, datatype=f"{self.XSD}integer"))
            assert "CAST(" not in sql, sql
            assert [p for p in sql.split(", ") if "__num" in p][0].startswith("NULL::")
        sql = self._sql(LiteralNode(value="2024-13-45", datatype=f"{self.XSD}dateTime"))
        assert "CAST(" not in sql, sql

    def test_a_boolean_and_a_datetime_are_on_their_lanes(self):
        sql = self._sql(LiteralNode(value="true", datatype=f"{self.XSD}boolean"))
        assert [p for p in sql.split(", ") if "__bool" in p][0].startswith("TRUE")
        sql = self._sql(LiteralNode(value="2024-01-02T00:00:00", datatype=f"{self.XSD}dateTime"))
        assert "CAST('2024-01-02T00:00:00' AS TIMESTAMP)" in sql

    def test_a_string_stays_off_every_lane(self):
        sql = self._sql(LiteralNode(value="12"))
        for suffix in ("__num", "__bool", "__dt"):
            assert [p for p in sql.split(", ") if suffix in p][0].startswith("NULL::")

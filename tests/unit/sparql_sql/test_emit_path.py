"""Unit tests for emit_path.py — property path emission via WITH RECURSIVE CTEs."""
# pyright: reportOperatorIssue=false, reportArgumentType=false

from __future__ import annotations

import pytest

from vitalgraph.db.jena_sparql.jena_types import (
    URINode,
    PathLink, PathInverse, PathSeq, PathAlt,
    PathOneOrMore, PathZeroOrMore, PathZeroOrOne, PathNegPropSet,
)
from vitalgraph.db.sparql_sql.ir import PlanV2, KIND_PATH

from .emit_helpers import _make_ctx


class TestEmitPath:
    """Tests for emit_path.py — property path emission via WITH RECURSIVE CTEs."""

    QUAD_TABLE = "test_space_rdf_quad"
    TERM_TABLE = "test_space_term"

    def _path_plan(self, path_expr, subject=None, obj=None,
                   graph_uri=None, graph_var=None) -> PlanV2:
        from vitalgraph.db.jena_sparql.jena_types import VarNode
        return PlanV2(
            kind=KIND_PATH,
            path_meta={
                "path": path_expr,
                "subject": subject or VarNode(name="s"),
                "object": obj or VarNode(name="o"),
                "quad_table": self.QUAD_TABLE,
                "term_table": self.TERM_TABLE,
                "graph_uri": graph_uri,
                "cte_alias": "pp",
                "graph_var": graph_var,
            },
        )

    # --- PathLink ---

    def test_path_link(self):
        """Simple PathLink → single quad scan."""
        from vitalgraph.db.sparql_sql.emit_path import emit_path
        ctx = _make_ctx({})
        plan = self._path_plan(PathLink(uri="http://example.org/knows"))
        sql = emit_path(plan, ctx)
        assert "predicate_uuid" in sql
        assert "example.org/knows" in sql
        assert "start_uuid" in sql
        assert "end_uuid" in sql

    # --- PathInverse ---

    def test_path_inverse(self):
        """PathInverse → swap start/end."""
        from vitalgraph.db.sparql_sql.emit_path import emit_path
        ctx = _make_ctx({})
        plan = self._path_plan(PathInverse(sub=PathLink(uri="http://ex.org/p")))
        sql = emit_path(plan, ctx)
        assert "inv.end_uuid AS start_uuid" in sql
        assert "inv.start_uuid AS end_uuid" in sql

    # --- PathAlt ---

    def test_path_alt(self):
        """PathAlt → UNION of two branches."""
        from vitalgraph.db.sparql_sql.emit_path import emit_path
        ctx = _make_ctx({})
        plan = self._path_plan(PathAlt(
            left=PathLink(uri="http://ex.org/a"),
            right=PathLink(uri="http://ex.org/b"),
        ))
        sql = emit_path(plan, ctx)
        assert "UNION" in sql
        assert "ex.org/a" in sql
        assert "ex.org/b" in sql

    # --- PathSeq ---

    def test_path_seq(self):
        """PathSeq → JOIN on end→start."""
        from vitalgraph.db.sparql_sql.emit_path import emit_path
        ctx = _make_ctx({})
        plan = self._path_plan(PathSeq(
            left=PathLink(uri="http://ex.org/a"),
            right=PathLink(uri="http://ex.org/b"),
        ))
        sql = emit_path(plan, ctx)
        assert "JOIN" in sql
        assert "lp.end_uuid = rp.start_uuid" in sql

    def test_path_seq_same_graph(self):
        """PathSeq inside GRAPH → ctx_uuid constraint."""
        from vitalgraph.db.sparql_sql.emit_path import emit_path
        ctx = _make_ctx({})
        plan = self._path_plan(
            PathSeq(
                left=PathLink(uri="http://ex.org/a"),
                right=PathLink(uri="http://ex.org/b"),
            ),
            graph_uri="http://ex.org/graph1",
        )
        sql = emit_path(plan, ctx)
        assert "lp.ctx_uuid = rp.ctx_uuid" in sql

    # --- PathOneOrMore ---

    def test_path_one_or_more(self):
        """PathOneOrMore → WITH RECURSIVE CTE."""
        from vitalgraph.db.sparql_sql.emit_path import emit_path
        ctx = _make_ctx({})
        plan = self._path_plan(PathOneOrMore(sub=PathLink(uri="http://ex.org/p")))
        sql = emit_path(plan, ctx)
        assert "WITH RECURSIVE" in sql
        assert "depth" in sql
        assert str(100) in sql  # MAX_PATH_DEPTH

    # --- PathZeroOrMore ---

    def test_path_zero_or_more(self):
        """PathZeroOrMore → WITH RECURSIVE + identity base."""
        from vitalgraph.db.sparql_sql.emit_path import emit_path
        ctx = _make_ctx({})
        plan = self._path_plan(PathZeroOrMore(sub=PathLink(uri="http://ex.org/p")))
        sql = emit_path(plan, ctx)
        assert "WITH RECURSIVE" in sql
        # Identity: node → itself
        assert "subject_uuid AS start_uuid, q.subject_uuid AS end_uuid" in sql

    # --- PathZeroOrOne ---

    def test_path_zero_or_one(self):
        """PathZeroOrOne → identity UNION one step."""
        from vitalgraph.db.sparql_sql.emit_path import emit_path
        ctx = _make_ctx({})
        plan = self._path_plan(PathZeroOrOne(sub=PathLink(uri="http://ex.org/p")))
        sql = emit_path(plan, ctx)
        assert "UNION" in sql
        # Identity part
        assert "subject_uuid AS start_uuid, q.subject_uuid AS end_uuid" in sql

    # --- PathNegPropSet ---

    def test_path_neg_prop_set_forward(self):
        """PathNegPropSet with forward URIs → exclude predicates."""
        from vitalgraph.db.sparql_sql.emit_path import emit_path
        ctx = _make_ctx({})
        plan = self._path_plan(PathNegPropSet(uris=["http://ex.org/exclude"]))
        sql = emit_path(plan, ctx)
        assert "!=" in sql or "IS DISTINCT" in sql
        assert "ex.org/exclude" in sql

    def test_path_neg_prop_set_inverse(self):
        """PathNegPropSet with ^uri → inverse exclusion."""
        from vitalgraph.db.sparql_sql.emit_path import emit_path
        ctx = _make_ctx({})
        plan = self._path_plan(PathNegPropSet(uris=["^http://ex.org/inv"]))
        sql = emit_path(plan, ctx)
        assert "object_uuid AS start_uuid" in sql
        assert "ex.org/inv" in sql

    def test_path_neg_prop_set_mixed(self):
        """PathNegPropSet with both forward and inverse → UNION."""
        from vitalgraph.db.sparql_sql.emit_path import emit_path
        ctx = _make_ctx({})
        plan = self._path_plan(PathNegPropSet(
            uris=["http://ex.org/fwd", "^http://ex.org/inv"]
        ))
        sql = emit_path(plan, ctx)
        assert "UNION" in sql

    def test_path_neg_prop_set_empty(self):
        """PathNegPropSet with no URIs → all predicates (no exclusion)."""
        from vitalgraph.db.sparql_sql.emit_path import emit_path
        ctx = _make_ctx({})
        plan = self._path_plan(PathNegPropSet(uris=[]))
        sql = emit_path(plan, ctx)
        assert self.QUAD_TABLE in sql

    # --- URI subject/object constraints ---

    def test_subject_uri_constraint(self):
        """URI subject → WHERE filter on start_uuid."""
        from vitalgraph.db.sparql_sql.emit_path import emit_path
        ctx = _make_ctx({})
        plan = self._path_plan(
            PathLink(uri="http://ex.org/p"),
            subject=URINode(value="http://ex.org/alice"),
        )
        sql = emit_path(plan, ctx)
        assert "start_uuid" in sql
        assert "ex.org/alice" in sql

    def test_object_uri_constraint(self):
        """URI object → WHERE filter on end_uuid."""
        from vitalgraph.db.sparql_sql.emit_path import emit_path
        ctx = _make_ctx({})
        plan = self._path_plan(
            PathLink(uri="http://ex.org/p"),
            obj=URINode(value="http://ex.org/bob"),
        )
        sql = emit_path(plan, ctx)
        assert "end_uuid" in sql
        assert "ex.org/bob" in sql

    # --- Graph clauses ---

    def test_graph_lock_uri(self):
        """graph_lock_uri → context_uuid constraint."""
        from vitalgraph.db.sparql_sql.emit_path import emit_path
        ctx = _make_ctx({})
        ctx.aliases.graph_lock_uri = "http://ex.org/locked"
        plan = self._path_plan(PathLink(uri="http://ex.org/p"))
        sql = emit_path(plan, ctx)
        assert "context_uuid" in sql
        assert "ex.org/locked" in sql

    def test_graph_uri_constraint(self):
        """GRAPH <uri> → context_uuid constraint."""
        from vitalgraph.db.sparql_sql.emit_path import emit_path
        ctx = _make_ctx({})
        plan = self._path_plan(
            PathLink(uri="http://ex.org/p"),
            graph_uri="http://ex.org/mygraph",
        )
        sql = emit_path(plan, ctx)
        assert "context_uuid" in sql
        assert "ex.org/mygraph" in sql

    def test_default_graph_constraint(self):
        """default_graph → context_uuid constraint when no GRAPH clause."""
        from vitalgraph.db.sparql_sql.emit_path import emit_path
        ctx = _make_ctx({})
        ctx.aliases.default_graph = "http://ex.org/default"
        plan = self._path_plan(PathLink(uri="http://ex.org/p"))
        sql = emit_path(plan, ctx)
        assert "context_uuid" in sql
        assert "ex.org/default" in sql

    def test_graph_var_scope_excludes_default(self):
        """GRAPH ?g → IS DISTINCT FROM default graph."""
        from vitalgraph.db.sparql_sql.collect import GRAPH_VAR_SCOPE
        from vitalgraph.db.sparql_sql.emit_path import emit_path
        ctx = _make_ctx({})
        ctx.aliases.default_graph = "http://ex.org/default"
        plan = self._path_plan(
            PathLink(uri="http://ex.org/p"),
            graph_uri=GRAPH_VAR_SCOPE,
            graph_var="g",
        )
        sql = emit_path(plan, ctx)
        assert "IS DISTINCT FROM" in sql

    # --- Graph variable binding ---

    def test_graph_var_binding(self):
        """GRAPH ?g → ctx_uuid bound as variable g."""
        from vitalgraph.db.sparql_sql.collect import GRAPH_VAR_SCOPE
        from vitalgraph.db.sparql_sql.emit_path import emit_path
        ctx = _make_ctx({})
        plan = self._path_plan(
            PathLink(uri="http://ex.org/p"),
            graph_uri=GRAPH_VAR_SCOPE,
            graph_var="g",
        )
        sql = emit_path(plan, ctx)
        # Graph var should be bound via term-table JOIN
        g_info = ctx.types.get("g")
        assert g_info is not None
        assert "ctx_uuid" in sql

    # --- _merge_ctes ---

    def test_merge_ctes_empty(self):
        """Empty inner CTE → wraps with WITH RECURSIVE."""
        from vitalgraph.db.sparql_sql.emit_path import _merge_ctes
        result = _merge_ctes("", "foo AS (SELECT 1)")
        assert result == "WITH RECURSIVE foo AS (SELECT 1)"

    def test_merge_ctes_existing(self):
        """Existing CTE → combines both."""
        from vitalgraph.db.sparql_sql.emit_path import _merge_ctes
        result = _merge_ctes(
            "WITH RECURSIVE a AS (SELECT 1)",
            "b AS (SELECT 2)",
        )
        assert "WITH RECURSIVE a AS (SELECT 1)" in result
        assert "b AS (SELECT 2)" in result
        # Should have only one WITH RECURSIVE
        assert result.count("WITH RECURSIVE") == 1

    # --- No path_meta error ---

    def test_no_path_meta_raises(self):
        """Missing path_meta → ValueError."""
        from vitalgraph.db.sparql_sql.emit_path import emit_path
        ctx = _make_ctx({})
        plan = PlanV2(kind=KIND_PATH)
        with pytest.raises(ValueError, match="path_meta"):
            emit_path(plan, ctx)

    # --- Fallback for unsupported path type ---

    def test_unsupported_path_fallback(self):
        """Unknown path type → fallback empty SELECT."""
        from vitalgraph.db.sparql_sql.emit_path import _path_to_sql

        class FakePath:
            pass

        cte, sql = _path_to_sql(
            FakePath(), self.QUAD_TABLE, self.TERM_TABLE, "", "pp"
        )
        assert "FALSE" in sql
        assert cte == ""

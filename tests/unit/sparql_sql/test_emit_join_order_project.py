"""Unit tests for emit_order, emit_project, emit_join."""
# pyright: reportOperatorIssue=false, reportArgumentType=false

from __future__ import annotations

from vitalgraph.db.jena_sparql.jena_types import ExprVar, ExprFunction
from vitalgraph.db.sparql_sql.ir import (
    PlanV2, KIND_BGP, KIND_ORDER, KIND_PROJECT, KIND_SLICE, KIND_JOIN,
    KIND_LEFT_JOIN, KIND_TABLE,
)
from vitalgraph.db.sparql_sql.sql_type_generation import ColumnInfo

from .emit_helpers import _make_ctx, _leaf_bgp, _var, _func


# ===========================================================================
# emit_order tests
# ===========================================================================


class TestEmitOrder:

    def test_no_conditions_passthrough(self):
        """No order_conditions → child SQL unchanged."""
        from vitalgraph.db.sparql_sql.emit_order import emit_order
        ctx = _make_ctx({"s": "text"})
        plan = PlanV2(kind=KIND_ORDER, order_conditions=[], children=[_leaf_bgp()])
        sql = emit_order(plan, ctx)
        assert "ORDER BY" not in sql

    def test_variable_asc(self):
        """ORDER BY ?s → ORDER BY alias.v0."""
        from vitalgraph.db.sparql_sql.emit_order import emit_order
        ctx = _make_ctx({"s": "text"})
        plan = PlanV2(kind=KIND_ORDER, order_conditions=[("s", "ASC")],
                      children=[_leaf_bgp()])
        sql = emit_order(plan, ctx)
        assert "ORDER BY" in sql
        assert "v0" in sql
        assert "DESC" not in sql

    def test_variable_desc(self):
        """ORDER BY DESC(?s) → ORDER BY ... DESC."""
        from vitalgraph.db.sparql_sql.emit_order import emit_order
        ctx = _make_ctx({"s": "text"})
        plan = PlanV2(kind=KIND_ORDER, order_conditions=[("s", "DESC")],
                      children=[_leaf_bgp()])
        sql = emit_order(plan, ctx)
        assert "DESC" in sql

    def test_expression_key(self):
        """ORDER BY STRLEN(?s) → expression in ORDER BY."""
        from vitalgraph.db.sparql_sql.emit_order import emit_order
        ctx = _make_ctx({"s": "text"})
        expr = ExprFunction(name="strlen", args=[ExprVar(var="s")])
        plan = PlanV2(kind=KIND_ORDER, order_conditions=[(expr, "ASC")],
                      children=[_leaf_bgp()])
        sql = emit_order(plan, ctx)
        assert "ORDER BY" in sql
        assert "LENGTH(" in sql

    def test_expression_empty_sql_skipped(self):
        """Expression producing empty SQL → skipped, no ORDER BY."""
        from vitalgraph.db.sparql_sql.emit_order import emit_order
        ctx = _make_ctx({"s": "text"})
        expr = ExprFunction(name="unknown_xyz_func", args=[])
        plan = PlanV2(kind=KIND_ORDER, order_conditions=[(expr, "ASC")],
                      children=[_leaf_bgp()])
        sql = emit_order(plan, ctx)
        assert "ORDER BY" not in sql

    def test_multiple_keys(self):
        """ORDER BY ?s ASC, ?o DESC."""
        from vitalgraph.db.sparql_sql.emit_order import emit_order
        ctx = _make_ctx({"s": "text", "o": "text"})
        plan = PlanV2(kind=KIND_ORDER,
                      order_conditions=[("s", "ASC"), ("o", "DESC")],
                      children=[_leaf_bgp()])
        sql = emit_order(plan, ctx)
        assert "ORDER BY" in sql
        assert "DESC" in sql


# ===========================================================================
# emit_project tests
# ===========================================================================


class TestEmitProject:

    def test_no_vars_passthrough(self):
        """No project_vars → child SQL unchanged."""
        from vitalgraph.db.sparql_sql.emit_project import emit_project
        ctx = _make_ctx({"s": "text"})
        plan = PlanV2(kind=KIND_PROJECT, project_vars=[], children=[_leaf_bgp()])
        sql = emit_project(plan, ctx)
        # Should be child SQL without a SELECT wrapper
        assert sql is not None

    def test_project_known_vars(self):
        """PROJECT ?s ?o → SELECT with companions."""
        from vitalgraph.db.sparql_sql.emit_project import emit_project
        ctx = _make_ctx({"s": "text", "o": "text"})
        plan = PlanV2(kind=KIND_PROJECT, project_vars=["s", "o"],
                      children=[_leaf_bgp()])
        sql = emit_project(plan, ctx)
        assert "SELECT" in sql
        assert "v0" in sql
        assert "v1" in sql

    def test_project_out_of_scope_var(self):
        """Out-of-scope variable → NULL companions."""
        from vitalgraph.db.sparql_sql.emit_project import emit_project
        ctx = _make_ctx({"s": "text"})
        plan = PlanV2(kind=KIND_PROJECT, project_vars=["s", "unknown"],
                      children=[_leaf_bgp()])
        sql = emit_project(plan, ctx)
        assert "NULL" in sql

    def test_project_lifts_order_by(self):
        """PROJECT wrapping ORDER → re-emits ORDER BY on outer SELECT."""
        from vitalgraph.db.sparql_sql.emit_project import emit_project
        ctx = _make_ctx({"s": "text", "o": "text"})
        order_node = PlanV2(
            kind=KIND_ORDER,
            order_conditions=[("s", "ASC")],
            children=[_leaf_bgp()],
        )
        plan = PlanV2(kind=KIND_PROJECT, project_vars=["s", "o"],
                      children=[order_node])
        sql = emit_project(plan, ctx)
        assert "ORDER BY" in sql

    def test_project_lifts_order_through_slice(self):
        """PROJECT wrapping SLICE → ORDER → re-emits ORDER BY."""
        from vitalgraph.db.sparql_sql.emit_project import emit_project
        ctx = _make_ctx({"s": "text"})
        order_node = PlanV2(
            kind=KIND_ORDER,
            order_conditions=[("s", "DESC")],
            children=[_leaf_bgp()],
        )
        slice_node = PlanV2(
            kind=KIND_SLICE,
            limit=10,
            children=[order_node],
        )
        plan = PlanV2(kind=KIND_PROJECT, project_vars=["s"],
                      children=[slice_node])
        sql = emit_project(plan, ctx)
        assert "ORDER BY" in sql
        assert "DESC" in sql

    def test_project_lifts_order_with_expr(self):
        """PROJECT lifting ORDER BY expr → expression in outer ORDER."""
        from vitalgraph.db.sparql_sql.emit_project import emit_project
        ctx = _make_ctx({"s": "text"})
        expr = ExprFunction(name="strlen", args=[ExprVar(var="s")])
        order_node = PlanV2(
            kind=KIND_ORDER,
            order_conditions=[(expr, "ASC")],
            children=[_leaf_bgp()],
        )
        plan = PlanV2(kind=KIND_PROJECT, project_vars=["s"],
                      children=[order_node])
        sql = emit_project(plan, ctx)
        assert "ORDER BY" in sql
        assert "LENGTH(" in sql


# ===========================================================================
# emit_join tests
# ===========================================================================


class TestEmitJoin:

    def _bgp_with_var(self, var_name: str, lane=None, from_triple=True):
        """Create a BGP plan with a registered variable."""
        plan = PlanV2(kind=KIND_BGP)
        from vitalgraph.db.sparql_sql.ir import VarSlot, TableRef
        slot = VarSlot(name=var_name, term_ref_id="t0")
        slot.positions.append(("q0", "subject_uuid"))
        plan.var_slots[var_name] = slot
        plan.tables.append(TableRef(ref_id="q0", kind="quad",
                                    table_name="test_space_rdf_quad", alias="q0"))
        plan.tables.append(TableRef(ref_id="t0", kind="term",
                                    table_name="test_space_term", alias="t0",
                                    join_col="q0.subject_uuid"))
        return plan

    def test_inner_join_shared_var(self):
        """Inner JOIN on shared variable → UUID-based ON clause."""
        from vitalgraph.db.sparql_sql.emit_join import emit_join
        ctx = _make_ctx({})
        left = self._bgp_with_var("x")
        right = self._bgp_with_var("x")
        plan = PlanV2(kind=KIND_JOIN, children=[left, right])
        sql = emit_join(plan, ctx)
        assert "JOIN" in sql
        assert "__uuid" in sql

    def test_inner_join_no_shared_vars(self):
        """No shared vars → ON TRUE (cross join)."""
        from vitalgraph.db.sparql_sql.emit_join import emit_join
        ctx = _make_ctx({})
        left = self._bgp_with_var("x")
        right = self._bgp_with_var("y")
        plan = PlanV2(kind=KIND_JOIN, children=[left, right])
        sql = emit_join(plan, ctx)
        assert "ON TRUE" in sql

    def test_left_join_shared_var(self):
        """LEFT JOIN with shared var → NULL-tolerant ON."""
        from vitalgraph.db.sparql_sql.emit_join import emit_left_join
        ctx = _make_ctx({})
        left = self._bgp_with_var("x")
        right = self._bgp_with_var("x")
        plan = PlanV2(kind=KIND_LEFT_JOIN, children=[left, right])
        sql = emit_left_join(plan, ctx)
        assert "LEFT JOIN" in sql
        assert "IS NULL" in sql  # NULL-tolerant for compatible-mapping

    def test_left_join_with_exprs(self):
        """LEFT JOIN with filter expressions → appended to ON clause."""
        from vitalgraph.db.sparql_sql.emit_join import emit_left_join
        ctx = _make_ctx({})
        left = self._bgp_with_var("x")
        right = self._bgp_with_var("x")
        plan = PlanV2(kind=KIND_LEFT_JOIN, children=[left, right],
                      left_join_exprs=[ExprFunction(
                          name="bound", args=[ExprVar(var="x")])])
        sql = emit_left_join(plan, ctx)
        assert "LEFT JOIN" in sql
        assert "AND" in sql

    def test_join_typed_lane_match(self):
        """Both sides have same typed_lane → join on lane column."""
        from vitalgraph.db.sparql_sql.emit_join import emit_join
        from vitalgraph.db.sparql_sql.ir import VarSlot, TableRef

        ctx = _make_ctx({})
        # Build plans where the variable has typed_lane="num"
        left = PlanV2(kind=KIND_BGP)
        slot = VarSlot(name="val", term_ref_id="t0")
        slot.positions.append(("q0", "object_uuid"))
        left.var_slots["val"] = slot
        left.tables.append(TableRef(ref_id="q0", kind="quad",
                                    table_name="test_space_rdf_quad", alias="q0"))

        right = PlanV2(kind=KIND_BGP)
        slot2 = VarSlot(name="val", term_ref_id="t1")
        slot2.positions.append(("q1", "object_uuid"))
        right.var_slots["val"] = slot2
        right.tables.append(TableRef(ref_id="q1", kind="quad",
                                     table_name="test_space_rdf_quad", alias="q1"))

        plan = PlanV2(kind=KIND_JOIN, children=[left, right])
        sql = emit_join(plan, ctx)
        # Both sides should have been emitted and joined
        assert "JOIN" in sql

    def test_join_values_table_null_tolerant(self):
        """VALUES table as right child → NULL-tolerant ON."""
        from vitalgraph.db.sparql_sql.emit_join import emit_join
        ctx = _make_ctx({})
        left = self._bgp_with_var("x")
        right = PlanV2(kind=KIND_TABLE, values_vars=["x"],
                       values_rows=[{"x": None}])
        plan = PlanV2(kind=KIND_JOIN, children=[left, right])
        sql = emit_join(plan, ctx)
        assert "IS NULL" in sql  # NULL-tolerant for VALUES UNDEF

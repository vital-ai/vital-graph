"""Unit tests for ORDER BY emission on sequence-style sort keys.

Covers the SQL-generation half of the step-0 spike in
``planning/planning_sequence/frame_slot_sequence_sort_paging_plan.md``:

- Can an ORDER BY carry a COALESCE expression at all (missing-sequence-last)?
- Does ordering on an integer-valued variable emit a numeric comparison,
  or a lexical one ("10" < "9")?

These assert on the emitted SQL only — no database, no sidecar.  The
end-to-end counterpart lives in ``tests/integration/test_sequence_ordering.py``.
"""
# pyright: reportOperatorIssue=false, reportArgumentType=false

from __future__ import annotations

from vitalgraph.db.sparql_sql.ir import PlanV2, KIND_ORDER

from .emit_helpers import _make_ctx, _leaf_bgp, _var, _lit, _func

XSD_INT = "http://www.w3.org/2001/XMLSchema#integer"

# Sentinel used to push unbound sequences to the end of an ascending sort,
# mirroring the frontend's Infinity fallback in entityGraphBuilder.ts.
SEQ_SENTINEL = "2147483647"


def _order(conditions) -> PlanV2:
    return PlanV2(kind=KIND_ORDER, order_conditions=conditions,
                  children=[_leaf_bgp()])


class TestOrderByExpressionKey:
    """ORDER BY may carry an arbitrary expression, not just a variable."""

    def test_coalesce_expression_reaches_order_by(self):
        """ORDER BY COALESCE(?seq, sentinel) emits a COALESCE in ORDER BY.

        This is the missing-sequence-sorts-last construct.  emit_order
        dispatches non-str keys through expr_to_sql (emit_order.py:34).
        """
        ctx = _make_ctx({"frame": "text", "seq": "text"})
        plan = _order([
            (_func("coalesce", _var("seq"), _lit(SEQ_SENTINEL, datatype=XSD_INT)),
             "ASC"),
            ("frame", "ASC"),
        ])
        from vitalgraph.db.sparql_sql.emit_order import emit_order
        sql = emit_order(plan, ctx)

        order_clause = sql.split("ORDER BY", 1)[1]
        assert "COALESCE" in order_clause
        assert SEQ_SENTINEL in order_clause

    def test_coalesce_key_keeps_uri_tiebreaker(self):
        """The anchor tiebreaker survives alongside an expression key.

        Paging needs a total order; the sequence value alone is not unique.
        """
        ctx = _make_ctx({"frame": "text", "seq": "text"})
        plan = _order([
            (_func("coalesce", _var("seq"), _lit(SEQ_SENTINEL, datatype=XSD_INT)),
             "ASC"),
            ("frame", "ASC"),
        ])
        from vitalgraph.db.sparql_sql.emit_order import emit_order
        sql = emit_order(plan, ctx)

        order_clause = sql.split("ORDER BY", 1)[1]
        # two comma-separated sort terms
        assert order_clause.count(",") >= 1
        # the frame variable's column is the trailing term
        frame_col = ctx.types.get("frame").sql_name
        # The trailing term is the frame column, now carrying the pinned
        # collation (`... COLLATE "C"`). Asserting on the LAST TERM rather than
        # on the exact tail keeps the intent — frame sorts last — without
        # re-encoding the emitted spelling.
        last_term = order_clause.rstrip().rsplit(",", 1)[-1]
        assert frame_col in last_term

    def test_descending_expression_key(self):
        """sort_order=desc applies DESC to the expression term."""
        ctx = _make_ctx({"frame": "text", "seq": "text"})
        plan = _order([
            (_func("coalesce", _var("seq"), _lit(SEQ_SENTINEL, datatype=XSD_INT)),
             "DESC"),
            ("frame", "ASC"),
        ])
        from vitalgraph.db.sparql_sql.emit_order import emit_order
        sql = emit_order(plan, ctx)

        order_clause = sql.split("ORDER BY", 1)[1]
        # DESC attaches to the COALESCE term, ahead of the ASC tiebreaker.
        # (Can't split on "," — COALESCE's own argument list contains one.)
        frame_col = ctx.types.get("frame").sql_name
        assert "COALESCE" in order_clause
        assert "DESC" in order_clause
        assert order_clause.index("DESC") < order_clause.rindex(frame_col)

    def test_expression_key_survives_project_lift(self):
        """emit_project re-lifts a buried ORDER BY, including expression keys.

        Wrapping ORDER in a subquery would otherwise let PostgreSQL drop it
        (emit_project.py:52-75).
        """
        from vitalgraph.db.sparql_sql.ir import KIND_PROJECT
        ctx = _make_ctx({"frame": "text", "seq": "text"})
        order_node = _order([
            (_func("coalesce", _var("seq"), _lit(SEQ_SENTINEL, datatype=XSD_INT)),
             "ASC"),
            ("frame", "ASC"),
        ])
        plan = PlanV2(kind=KIND_PROJECT, project_vars=["frame"],
                      children=[order_node])
        from vitalgraph.db.sparql_sql.emit_project import emit_project
        sql = emit_project(plan, ctx)

        assert "ORDER BY" in sql
        assert "COALESCE" in sql.split("ORDER BY", 1)[1]


class TestSequenceKeyNumericLane:
    """Whether a sequence sort key compares numerically or lexically.

    A lexical comparison is silently correct for 0-9 and wrong from 10 up,
    which is exactly the failure mode the 1..12 fixture in the integration
    tests is designed to catch.
    """

    def test_plain_bgp_var_orders_on_text_column(self):
        """ORDER BY ?seq on a BGP variable sorts by the text lane.

        emit_order.py:30-32 resolves a str key to ``info.sql_name``, which is
        the lexical column — NOT ``num_col``.  Pinning this makes the risk
        explicit: any sequence sort expressed as a bare variable is a string
        sort unless the value column is numeric.
        """
        ctx = _make_ctx({"seq": "text"})
        plan = _order([("seq", "ASC")])
        from vitalgraph.db.sparql_sql.emit_order import emit_order
        sql = emit_order(plan, ctx)

        info = ctx.types.get("seq")
        order_clause = sql.split("ORDER BY", 1)[1]
        assert info.sql_name in order_clause
        assert info.num_col not in order_clause

    def test_numeric_lane_var_still_orders_on_text_column(self):
        """Even a typed_lane='num' variable orders on sql_name, not num_col.

        Confirms the str-key path in emit_order ignores the numeric lane
        entirely, so numeric ordering has to come from the value column's
        own SQL type rather than from sort-key selection.
        """
        ctx = _make_ctx({"seq": "numeric"})
        plan = _order([("seq", "ASC")])
        from vitalgraph.db.sparql_sql.emit_order import emit_order
        sql = emit_order(plan, ctx)

        info = ctx.types.get("seq")
        order_clause = sql.split("ORDER BY", 1)[1]
        assert info.sql_name in order_clause
        assert info.num_col not in order_clause

    def test_coalesce_mixing_text_var_and_numeric_literal_casts_to_text(self):
        """COALESCE(?text_var, 2147483647) degrades to a TEXT comparison.

        emit_expressions.py:694-702 casts every argument to TEXT when a text
        variable is mixed with a numeric literal.  So the obvious
        missing-sequence-last construct produces a LEXICAL sort — the
        sentinel approach needs a numeric-lane sequence variable, or an
        explicit cast, to sort correctly past 9.
        """
        ctx = _make_ctx({"seq": "text"})
        plan = _order([
            (_func("coalesce", _var("seq"), _lit(SEQ_SENTINEL, datatype=XSD_INT)),
             "ASC"),
        ])
        from vitalgraph.db.sparql_sql.emit_order import emit_order
        sql = emit_order(plan, ctx)

        order_clause = sql.split("ORDER BY", 1)[1]
        assert "CAST(" in order_clause and "AS TEXT" in order_clause

    def test_coalesce_over_numeric_lane_var_avoids_text_cast(self):
        """A numeric-lane sequence variable keeps COALESCE numeric.

        _is_numeric_expr (emit_expressions.py:174) trusts typed_lane='num',
        so no text cast is injected and the sort stays numeric.  This is the
        shape ``build_sequence_order_clause`` must produce.
        """
        ctx = _make_ctx({"seq": "numeric"})
        plan = _order([
            (_func("coalesce", _var("seq"), _lit(SEQ_SENTINEL, datatype=XSD_INT)),
             "ASC"),
        ])
        from vitalgraph.db.sparql_sql.emit_order import emit_order
        sql = emit_order(plan, ctx)

        order_clause = sql.split("ORDER BY", 1)[1]
        assert "COALESCE" in order_clause
        assert "AS TEXT" not in order_clause


class TestSequenceOrderWithSlice:
    """ORDER BY + LIMIT/OFFSET must stay attached — the paging-stability case."""

    def test_slice_reapplies_sequence_order(self):
        """SLICE over ORDER keeps both the ORDER BY and the LIMIT/OFFSET.

        Unstable paging (LIMIT with no ORDER BY) is the priority-one bug in
        _build_frames_with_slots_query; this pins that the emitter itself
        does not drop a supplied ordering.
        """
        from vitalgraph.db.sparql_sql.ir import KIND_SLICE
        ctx = _make_ctx({"frame": "text", "seq": "text"})
        order_node = _order([
            (_func("coalesce", _var("seq"), _lit(SEQ_SENTINEL, datatype=XSD_INT)),
             "ASC"),
            ("frame", "ASC"),
        ])
        plan = PlanV2(kind=KIND_SLICE, limit=10, offset=20,
                      children=[order_node])
        from vitalgraph.db.sparql_sql.emit_slice import emit_slice
        sql = emit_slice(plan, ctx)

        assert "ORDER BY" in sql
        assert "LIMIT 10" in sql
        assert "OFFSET 20" in sql

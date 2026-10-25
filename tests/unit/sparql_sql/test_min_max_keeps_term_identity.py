"""MIN / MAX keep the input's term identity, so a join on them compares terms (issue 307).

MIN/MAX return one term of the group (SPARQL §18.5.1). They used to emit its uuid
as a constant NULL, so the result had no term identity and every join on it fell
back to `CAST(a AS TEXT) = CAST(b AS TEXT)`, matching terms that differ only in
datatype or language. The identity is kept only under GROUP BY: an implicit group
over no rows yields one UNBOUND result that no structural check sees.
"""
# pyright: reportOperatorIssue=false, reportArgumentType=false

from __future__ import annotations

import re

from vitalgraph.db.jena_sparql.jena_types import ExprAggregator, GroupVar
from vitalgraph.db.sparql_sql.ir import KIND_EXTEND, KIND_GROUP, PlanV2

from .emit_helpers import _leaf_bgp, _make_ctx, _var


def _group(ctx, agg_name: str, group_vars):
    from vitalgraph.db.sparql_sql.emit_group import emit_group
    plan = PlanV2(
        kind=KIND_GROUP,
        group_vars=group_vars,
        aggregates={".0": ExprAggregator(name=agg_name, expr=_var("val"), distinct=False)},
        children=[_leaf_bgp()],
    )
    sql = emit_group(plan, ctx)
    return sql, ctx.types.get(".0")


def _uuid_column(sql: str, info) -> str:
    """The SELECT item that produces the aggregate's __uuid: the last one by that
    name (`_make_ctx` registers v0, v1 ... by hand, and the allocator, unaware of
    them, can hand the aggregate a name a group key's passthrough also uses)."""
    items = re.findall(r"(\(array_agg\([^\[]*\)\)\[1\]|NULL::uuid|g\d+\.\w+) AS "
                       + re.escape(f"{info.sql_name}__uuid") + r"\b", sql)
    assert items, sql
    return items[-1]


def test_grouped_min_max_picks_the_winning_terms_uuid():
    for agg_name in ("MIN", "MAX"):
        ctx = _make_ctx({"k": "full", "val": "full"})
        sql, info = _group(ctx, agg_name, [GroupVar(var="k")])
        col = _uuid_column(sql, info)
        # picked with the same ordering as the value itself
        assert col.startswith("(array_agg(") and "__uuid ORDER BY" in col, col
        order = col.split(" ORDER BY ", 1)[1]
        assert ("DESC" in order) == (agg_name == "MAX"), col
        assert info.has_term_identity()
        assert info.uuid_col == f"{info.sql_name}__uuid"


def test_ungrouped_min_max_has_no_term_identity():
    """An implicit group over no rows: one row, the result UNBOUND. Claiming
    identity would also claim it always bound to the join's boundness check."""
    for agg_name in ("MIN", "MAX"):
        ctx = _make_ctx({"val": "full"})
        sql, info = _group(ctx, agg_name, [])
        assert _uuid_column(sql, info) == "NULL::uuid"
        assert not info.has_term_identity()


def test_min_max_of_a_computed_value_has_no_term_identity():
    """No stored term behind the input: nothing to pick, today's text compare stays."""
    ctx = _make_ctx({"k": "full", "val": "full"})
    val = ctx.types.get("val")
    val.from_triple = False
    val.uuid_col = None
    sql, info = _group(ctx, "MAX", [GroupVar(var="k")])
    assert _uuid_column(sql, info) == "NULL::uuid"
    assert not info.has_term_identity()


def test_count_is_unchanged():
    ctx = _make_ctx({"k": "full", "val": "full"})
    from vitalgraph.db.sparql_sql.emit_group import emit_group
    plan = PlanV2(
        kind=KIND_GROUP,
        group_vars=[GroupVar(var="k")],
        aggregates={".0": ExprAggregator(name="COUNT", expr=_var("val"), distinct=False)},
        children=[_leaf_bgp()],
    )
    emit_group(plan, ctx)
    assert not ctx.types.get(".0").has_term_identity()


def _extend(ctx, src: str):
    from vitalgraph.db.sparql_sql.emit_extend import emit_extend
    plan = PlanV2(kind=KIND_EXTEND, extend_var="m", extend_expr=_var(src),
                  children=[_leaf_bgp()])
    sql = emit_extend(plan, ctx)
    return sql, ctx.types.get("m")


def test_a_variable_copy_keeps_the_sources_identity():
    """`(MAX(?v) AS ?m)` is an EXTEND copying the aggregate; so is BIND(?x AS ?y)."""
    ctx = _make_ctx({"x": "full"})
    src = ctx.types.get("x")
    src._sql_has_companions = True
    src.partial = True
    sql, info = _extend(ctx, "x")
    assert f"{src.sql_name}__uuid AS {info.sql_name}__uuid" in sql
    assert info.has_term_identity()
    assert info.uuid_col == f"{info.sql_name}__uuid"
    assert info.from_triple and info.partial          # boundness claims travel with it


def test_a_copy_of_the_grouped_max_keeps_its_identity():
    ctx = _make_ctx({"k": "full", "val": "full"})
    _sql, agg = _group(ctx, "MAX", [GroupVar(var="k")])
    _sql2, info = _extend(ctx, ".0")
    assert agg.has_term_identity() and info.has_term_identity()


def test_a_copy_of_a_computed_value_has_no_identity():
    ctx = _make_ctx({"x": "full"})
    src = ctx.types.get("x")
    src._sql_has_companions = True
    src.from_triple = False
    _sql, info = _extend(ctx, "x")
    assert not info.has_term_identity()

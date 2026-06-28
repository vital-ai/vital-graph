"""
Pass 1: COLLECT — Walk the Op tree and produce a RelationPlan IR tree.

No SQL is generated here. Just records tables, variables, constraints, and modifiers.
"""

from __future__ import annotations

from functools import singledispatch
from typing import Optional, List

from .jena_sparql.jena_types import (
    VarNode, URINode, LiteralNode, BNodeNode,
    ExprVar, ExprValue, ExprFunction, ExprAggregator, Expr,
    SortCondition, GroupVar,
    OpBGP, OpJoin, OpLeftJoin, OpUnion, OpFilter,
    OpProject, OpSlice, OpDistinct, OpReduced, OpOrder,
    OpGroup, OpExtend, OpTable, OpMinus, OpGraph,
    OpSequence, OpNull, OpPath,
    PathExpr, PathLink, PathInverse, PathSeq, PathAlt,
    PathOneOrMore, PathZeroOrMore, PathZeroOrOne, PathNegPropSet,
)
from .jena_sql_ir import AliasGenerator, TableRef, VarSlot, RelationPlan
from .jena_sql_helpers import _esc, _const_subquery, _vars_in_expr


@singledispatch
def collect(op, space_id: str, aliases: AliasGenerator, graph_uri: str = None) -> RelationPlan:
    """Dispatch an Op to its collect handler."""
    raise NotImplementedError(f"No collect handler for {type(op).__name__}")


# ---- OpBGP ----
@collect.register(OpBGP)
def _collect_bgp(op: OpBGP, space_id: str, aliases: AliasGenerator,
                  graph_uri: str = None) -> RelationPlan:
    plan = RelationPlan(kind="bgp")
    if not op.triples:
        return plan

    quad_table = f"{space_id}_rdf_quad"
    term_table = f"{space_id}_term"

    for triple in op.triples:
        q_id = aliases.next("q")
        plan.tables.append(TableRef(ref_id=q_id, kind="quad", table_name=quad_table, alias=q_id))

        for node, uuid_col_name in [
            (triple.subject, "subject_uuid"),
            (triple.predicate, "predicate_uuid"),
            (triple.object, "object_uuid"),
        ]:
            full_uuid = f"{q_id}.{uuid_col_name}"

            if isinstance(node, VarNode):
                if node.name in plan.var_slots:
                    # Co-reference: constrain this position = first position
                    first = plan.var_slots[node.name]
                    first_uuid = f"{first.positions[0][0]}.{first.positions[0][1]}"
                    constraint = f"{full_uuid} = {first_uuid}"
                    plan.constraints.append(constraint)
                    plan.tagged_constraints.append((q_id, constraint))
                    first.positions.append((q_id, uuid_col_name))
                else:
                    # Variable: record position, term JOIN added in emit for projection
                    t_id = aliases.next("t")
                    plan.tables.append(TableRef(
                        ref_id=t_id, kind="term", table_name=term_table,
                        join_col=full_uuid, alias=t_id,
                    ))
                    slot = VarSlot(name=node.name, term_ref_id=t_id)
                    slot.positions.append((q_id, uuid_col_name))
                    plan.var_slots[node.name] = slot

            elif isinstance(node, URINode):
                # Constant URI: register in CTE and reference it
                subq = _const_subquery(node.value, 'U', aliases)
                constraint = f"{full_uuid} = {subq}"
                plan.constraints.append(constraint)
                plan.tagged_constraints.append((q_id, constraint))

            elif isinstance(node, LiteralNode):
                # Constant literal: register in CTE and reference it
                # Note: literals with lang tags need direct lookup (CTE doesn't filter by lang)
                if node.lang:
                    constraint = (
                        f"{full_uuid} = (SELECT term_uuid FROM {term_table} "
                        f"WHERE term_text = '{_esc(node.value)}' AND term_type = 'L'"
                        f" AND lang = '{_esc(node.lang)}' LIMIT 1)"
                    )
                    plan.constraints.append(constraint)
                    plan.tagged_constraints.append((q_id, constraint))
                else:
                    subq = _const_subquery(node.value, 'L', aliases)
                    constraint = f"{full_uuid} = {subq}"
                    plan.constraints.append(constraint)
                    plan.tagged_constraints.append((q_id, constraint))

        # Graph lock: if aliases.graph_uri is set, always constrain first
        if aliases.graph_uri:
            subq = _const_subquery(aliases.graph_uri, 'U', aliases)
            constraint = f"{q_id}.context_uuid = {subq}"
            plan.constraints.insert(0, constraint)
            plan.tagged_constraints.insert(0, (q_id, constraint))

        # Graph scoping from SPARQL GRAPH clause (AND-ed with lock if both present)
        if graph_uri and graph_uri != aliases.graph_uri:
            subq = _const_subquery(graph_uri, 'U', aliases)
            constraint = f"{q_id}.context_uuid = {subq}"
            plan.constraints.append(constraint)
            plan.tagged_constraints.append((q_id, constraint))

    return plan


# ---- OpFilter ----
@collect.register(OpFilter)
def _collect_filter(op: OpFilter, space_id: str, aliases: AliasGenerator,
                     graph_uri: str = None) -> RelationPlan:
    inner = collect(op.sub_op, space_id, aliases, graph_uri)

    # Detect HAVING: if the inner plan has aggregates, filter expressions
    # referencing aggregate variables (e.g. ".0") become HAVING clauses.
    agg_vars = set(inner.aggregates.keys()) if inner.aggregates else set()

    for expr in op.exprs:
        if agg_vars and agg_vars & _vars_in_expr(expr):
            if inner.having_exprs is None:
                inner.having_exprs = []
            inner.having_exprs.append(expr)
        else:
            if inner.filter_exprs is None:
                inner.filter_exprs = []
            inner.filter_exprs.append(expr)

    return inner


# ---- OpJoin ----
@collect.register(OpJoin)
def _collect_join(op: OpJoin, space_id: str, aliases: AliasGenerator,
                   graph_uri: str = None) -> RelationPlan:
    left = collect(op.left, space_id, aliases, graph_uri)
    right = collect(op.right, space_id, aliases, graph_uri)
    return RelationPlan(kind="join", children=[left, right])


# ---- OpLeftJoin ----
@collect.register(OpLeftJoin)
def _collect_left_join(op: OpLeftJoin, space_id: str, aliases: AliasGenerator,
                        graph_uri: str = None) -> RelationPlan:
    left = collect(op.left, space_id, aliases, graph_uri)
    right = collect(op.right, space_id, aliases, graph_uri)
    plan = RelationPlan(kind="left_join", children=[left, right])
    if op.exprs:
        plan.left_join_exprs = list(op.exprs)
    return plan


# ---- OpUnion ----
@collect.register(OpUnion)
def _collect_union(op: OpUnion, space_id: str, aliases: AliasGenerator,
                    graph_uri: str = None) -> RelationPlan:
    left = collect(op.left, space_id, aliases, graph_uri)
    right = collect(op.right, space_id, aliases, graph_uri)
    return RelationPlan(kind="union", children=[left, right])


# ---- OpProject ----
@collect.register(OpProject)
def _collect_project(op: OpProject, space_id: str, aliases: AliasGenerator,
                      graph_uri: str = None) -> RelationPlan:
    inner = collect(op.sub_op, space_id, aliases, graph_uri)
    inner.select_vars = list(op.vars)
    return inner


# ---- OpSlice ----
@collect.register(OpSlice)
def _collect_slice(op: OpSlice, space_id: str, aliases: AliasGenerator,
                    graph_uri: str = None) -> RelationPlan:
    inner = collect(op.sub_op, space_id, aliases, graph_uri)
    if op.length >= 0:
        inner.limit = op.length
    if op.start > 0:
        inner.offset = op.start
    return inner


# ---- OpDistinct ----
@collect.register(OpDistinct)
def _collect_distinct(op: OpDistinct, space_id: str, aliases: AliasGenerator,
                       graph_uri: str = None) -> RelationPlan:
    inner = collect(op.sub_op, space_id, aliases, graph_uri)
    inner.distinct = True
    return inner


# ---- OpReduced ----
@collect.register(OpReduced)
def _collect_reduced(op: OpReduced, space_id: str, aliases: AliasGenerator,
                      graph_uri: str = None) -> RelationPlan:
    inner = collect(op.sub_op, space_id, aliases, graph_uri)
    inner.distinct = True
    return inner


# ---- OpOrder ----
@collect.register(OpOrder)
def _collect_order(op: OpOrder, space_id: str, aliases: AliasGenerator,
                    graph_uri: str = None) -> RelationPlan:
    inner = collect(op.sub_op, space_id, aliases, graph_uri)
    order = []
    for sc in op.conditions:
        direction = "ASC" if sc.direction != "DESC" else "DESC"
        if isinstance(sc.expr, ExprVar):
            order.append((sc.expr.var, direction))
        else:
            order.append((sc.expr, direction))
    inner.order_by = order
    return inner


def _map_agg_expr(raw) -> Optional[Expr]:
    """Convert a raw expression dict from an aggregator into an Expr object."""
    if raw is None:
        return None
    if isinstance(raw, (ExprVar, ExprValue, ExprFunction, ExprAggregator)):
        return raw  # already mapped
    if isinstance(raw, dict):
        t = raw.get('type', '')
        if t == 'ExprVar':
            return ExprVar(var=raw.get('var', raw.get('name', '')))
        if t == 'ExprValue':
            node_data = raw.get('node', {})
            nt = node_data.get('type', '')
            if nt == 'uri':
                return ExprValue(node=URINode(value=node_data.get('value', '')))
            return ExprValue(node=LiteralNode(value=node_data.get('value', '')))
    return None


# ---- OpGroup ----
@collect.register(OpGroup)
def _collect_group(op: OpGroup, space_id: str, aliases: AliasGenerator,
                    graph_uri: str = None) -> RelationPlan:
    inner = collect(op.sub_op, space_id, aliases, graph_uri)

    # Extract variable names and optional defining expressions from GroupVar objects
    var_names = []
    expr_map = {}
    for gv in op.group_vars:
        if isinstance(gv, GroupVar):
            var_names.append(gv.var)
            if gv.expr is not None:
                expr_map[gv.var] = gv.expr
        else:
            # Backward compat: plain string (shouldn't happen with new mapper)
            var_names.append(gv)
    inner.group_by = var_names
    if expr_map:
        inner.group_by_exprs = expr_map

    if op.aggregators:
        aggs = {}
        for a in op.aggregators:
            var = a.get('var')
            agg_dict = a.get('aggregator', {})
            if var and agg_dict:
                # Aggregator inner expressions are now pre-mapped by the AST mapper.
                # They arrive as Expr objects (or None), not raw dicts.
                agg_expr = agg_dict.get('expr')
                if agg_expr is not None and not isinstance(
                    agg_expr, (ExprVar, ExprValue, ExprFunction, ExprAggregator)
                ):
                    # Fallback: try the legacy _map_agg_expr for unmapped dicts
                    agg_expr = _map_agg_expr(agg_expr)
                aggs[var] = ExprAggregator(
                    name=agg_dict.get('name', 'COUNT'),
                    distinct=agg_dict.get('distinct', False),
                    expr=agg_expr,
                    separator=agg_dict.get('separator'),
                )
        inner.aggregates = aggs
    return inner


# ---- OpExtend ----
@collect.register(OpExtend)
def _collect_extend(op: OpExtend, space_id: str, aliases: AliasGenerator,
                     graph_uri: str = None) -> RelationPlan:
    inner = collect(op.sub_op, space_id, aliases, graph_uri)
    if inner.extend_exprs is None:
        inner.extend_exprs = {}
    inner.extend_exprs[op.var] = op.expr
    return inner


# ---- OpGraph ----
@collect.register(OpGraph)
def _collect_graph(op: OpGraph, space_id: str, aliases: AliasGenerator,
                    graph_uri: str = None) -> RelationPlan:
    if isinstance(op.graph_node, URINode):
        return collect(op.sub_op, space_id, aliases, graph_uri=op.graph_node.value)

    if isinstance(op.graph_node, VarNode):
        # GRAPH ?g { ... } — bind ?g to context_uuid on every quad table
        graph_var = op.graph_node.name
        inner = collect(op.sub_op, space_id, aliases, graph_uri=None)
        _bind_graph_var(inner, graph_var, space_id, aliases)
        return inner

    return collect(op.sub_op, space_id, aliases, graph_uri=None)


def _bind_graph_var(plan: RelationPlan, graph_var: str, space_id: str,
                     aliases: AliasGenerator) -> None:
    """Bind a GRAPH variable to the context_uuid column of all quad tables in a plan."""
    term_table = f"{space_id}_term"

    # Recursively bind in child plans (joins, unions, etc.)
    for child in plan.children:
        _bind_graph_var(child, graph_var, space_id, aliases)

    # Bind to quad tables in this plan
    quad_tables = [t for t in plan.tables if t.kind == "quad"]
    if not quad_tables:
        return

    for qt in quad_tables:
        full_uuid = f"{qt.alias}.context_uuid"
        if graph_var in plan.var_slots:
            # Co-reference: constrain to match the first binding
            first = plan.var_slots[graph_var]
            first_uuid = f"{first.positions[0][0]}.{first.positions[0][1]}"
            constraint = f"{full_uuid} = {first_uuid}"
            plan.constraints.append(constraint)
            plan.tagged_constraints.append((qt.alias, constraint))
            first.positions.append((qt.alias, "context_uuid"))
        else:
            # First occurrence: create VarSlot with term JOIN
            t_id = aliases.next("t")
            plan.tables.append(TableRef(
                ref_id=t_id, kind="term", table_name=term_table,
                join_col=full_uuid, alias=t_id,
            ))
            slot = VarSlot(name=graph_var, term_ref_id=t_id)
            slot.positions.append((qt.alias, "context_uuid"))
            plan.var_slots[graph_var] = slot


# ---- OpMinus ----
@collect.register(OpMinus)
def _collect_minus(op: OpMinus, space_id: str, aliases: AliasGenerator,
                    graph_uri: str = None) -> RelationPlan:
    left = collect(op.left, space_id, aliases, graph_uri)
    right = collect(op.right, space_id, aliases, graph_uri)
    return RelationPlan(kind="minus", children=[left, right])


# ---- OpTable (VALUES) ----
@collect.register(OpTable)
def _collect_table(op: OpTable, space_id: str, aliases: AliasGenerator,
                    graph_uri: str = None) -> RelationPlan:
    plan = RelationPlan(kind="table")
    plan.values_vars = list(op.vars)
    plan.values_rows = list(op.rows) if op.rows else []
    return plan


# ---- OpSequence ----
@collect.register(OpSequence)
def _collect_sequence(op: OpSequence, space_id: str, aliases: AliasGenerator,
                       graph_uri: str = None) -> RelationPlan:
    children = [collect(child, space_id, aliases, graph_uri) for child in op.elements]
    if len(children) == 1:
        return children[0]
    # Chain as nested joins
    result = children[0]
    for child in children[1:]:
        result = RelationPlan(kind="join", children=[result, child])
    return result


# ---- OpNull ----
@collect.register(OpNull)
def _collect_null(op: OpNull, space_id: str, aliases: AliasGenerator,
                   graph_uri: str = None) -> RelationPlan:
    return RelationPlan(kind="null")


# ---- OpPath (property paths) ----
@collect.register(OpPath)
def _collect_path(op: OpPath, space_id: str, aliases: AliasGenerator,
                   graph_uri: str = None) -> RelationPlan:
    """Collect a property path pattern into a RelationPlan.

    The plan stores the path expression, subject/object nodes, and
    creates var_slots for any variable endpoints. The actual CTE
    generation happens in the emit phase.
    """
    plan = RelationPlan(kind="path")
    term_table = f"{space_id}_term"
    quad_table = f"{space_id}_rdf_quad"

    # Store path metadata for emit
    plan._path_meta = {  # type: ignore[attr-defined]
        "path": op.path,
        "subject": op.subject,
        "object": op.object,
        "quad_table": quad_table,
        "term_table": term_table,
        "graph_uri": graph_uri,
        "cte_alias": aliases.next("p"),
    }

    # Create var_slots for variable endpoints
    for node, role in [(op.subject, "start"), (op.object, "end")]:
        if isinstance(node, VarNode):
            if node.name not in plan.var_slots:
                t_id = aliases.next("t")
                plan.tables.append(TableRef(
                    ref_id=t_id, kind="term", table_name=term_table,
                    join_col="", alias=t_id,
                ))
                slot = VarSlot(name=node.name, term_ref_id=t_id)
                plan.var_slots[node.name] = slot

    return plan

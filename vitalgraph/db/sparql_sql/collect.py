"""
v2 Collect Pass — Walk the Op tree and produce a nested PlanV2 IR tree.

Key difference from v1: each modifier (filter, extend, group, project, order,
slice, distinct, reduced) creates a **wrapper** PlanV2 node around its child,
preserving evaluation order. v1 flattened modifiers onto the inner plan, losing
ordering information.

No SQL is generated here — just IR construction.

Isolation: This module imports ONLY from:
  - The sidecar AST types (jena_types) — shared interface, not v1 pipeline code.
  - The local v2 IR (ir.py) — fully self-contained.
All helper functions are defined locally.
"""

from __future__ import annotations

from functools import singledispatch
from typing import Optional

from ..jena_sparql.jena_types import (
    VarNode, URINode, LiteralNode, BNodeNode,
    ExprVar, ExprValue, ExprFunction, ExprAggregator,
    SortCondition, GroupVar,
    OpBGP, OpJoin, OpLeftJoin, OpUnion, OpFilter,
    OpProject, OpSlice, OpDistinct, OpReduced, OpOrder,
    OpGroup, OpExtend, OpTable, OpMinus, OpGraph,
    OpSequence, OpNull, OpPath,
)

from .ir import (
    PlanV2, AliasGenerator, TableRef, VarSlot,
    KIND_BGP, KIND_JOIN, KIND_LEFT_JOIN, KIND_UNION, KIND_MINUS,
    KIND_TABLE, KIND_NULL, KIND_PATH,
    KIND_PROJECT, KIND_DISTINCT, KIND_REDUCED, KIND_SLICE,
    KIND_ORDER, KIND_FILTER, KIND_EXTEND, KIND_GROUP,
)

# Sentinel: "inside GRAPH ?var" — skip the default-graph lock,
# match all named graphs.  Distinct from None ("no GRAPH clause,
# apply lock if set") and from a URI string ("GRAPH <uri>").
GRAPH_VAR_SCOPE = "__graph_var_scope__"


# ---------------------------------------------------------------------------
# Helpers (copied from v1 to maintain isolation)
# ---------------------------------------------------------------------------

_CONST_PREFIX = "__CONST_"
_CONST_SUFFIX = "__"


def _esc(s: str) -> str:
    """Escape single quotes for SQL string literals."""
    if s is None:
        return ""
    return s.replace("'", "''")


def _like_escape(s: str) -> str:
    """Escape LIKE metacharacters (\\ % _) in a needle so it matches literally
    inside a ``LIKE '%'||needle||'%'`` pattern.

    Without this, SPARQL CONTAINS(?x, "50%") would emit LIKE '%50%%' and the
    literal % / _ act as wildcards (over-matching). Backslash is escaped first
    (it's the default LIKE escape char), so the result is safe to embed in a
    LIKE pattern with the default ESCAPE. pg_trgm honors the '\\' escape, so the
    escaped characters become literal trigram content and the GIN trigram index
    stays usable. Quote-escaping (_esc) is applied separately by the caller.
    """
    if s is None:
        return ""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _const_subquery(term_text: str, term_type: str, aliases: AliasGenerator,
                    lang: str = None, datatype: str = None) -> str:
    """Register a constant term and return a placeholder token.

    During collect, constants are embedded as placeholder tokens like
    ``__CONST_c_0__``.  After the materialize phase resolves UUIDs,
    these are replaced with ``'uuid'::uuid`` literals.

    `lang` and `datatype` are part of the term's identity. Dropping the
    datatype here made `{ ?x :p "a"^^t:type1 }` resolve to a `t:type2` term
    (`issues/129`).
    """
    col = aliases.register_constant(term_text, term_type, lang, datatype)
    return f"{_CONST_PREFIX}{col}{_CONST_SUFFIX}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@singledispatch
def collect(op, space_id: str, aliases: AliasGenerator,
            graph_uri: str = None) -> PlanV2:
    """Dispatch an Op to its collect handler."""
    raise NotImplementedError(f"No v2 collect handler for {type(op).__name__}")


# ---------------------------------------------------------------------------
# Relation kinds (leaf or binary)
# ---------------------------------------------------------------------------

@collect.register(OpBGP)
def _collect_bgp(op: OpBGP, space_id: str, aliases: AliasGenerator,
                 graph_uri: str = None) -> PlanV2:
    plan = PlanV2(kind=KIND_BGP)
    if not op.triples:
        return plan

    quad_table = f"{space_id}_rdf_quad"
    term_table = f"{space_id}_term"

    for triple in op.triples:
        q_id = aliases.next("q")
        plan.tables.append(TableRef(ref_id=q_id, kind="quad",
                                    table_name=quad_table, alias=q_id))

        for node, uuid_col_name in [
            (triple.subject, "subject_uuid"),
            (triple.predicate, "predicate_uuid"),
            (triple.object, "object_uuid"),
        ]:
            full_uuid = f"{q_id}.{uuid_col_name}"

            if isinstance(node, VarNode):
                if node.name in plan.var_slots:
                    first = plan.var_slots[node.name]
                    first_uuid = f"{first.positions[0][0]}.{first.positions[0][1]}"
                    constraint = f"{full_uuid} = {first_uuid}"
                    plan.constraints.append(constraint)
                    plan.tagged_constraints.append((q_id, constraint))
                    first.positions.append((q_id, uuid_col_name))
                else:
                    t_id = aliases.next("t")
                    plan.tables.append(TableRef(
                        ref_id=t_id, kind="term", table_name=term_table,
                        join_col=full_uuid, alias=t_id,
                    ))
                    slot = VarSlot(name=node.name, term_ref_id=t_id)
                    slot.positions.append((q_id, uuid_col_name))
                    plan.var_slots[node.name] = slot

            elif isinstance(node, URINode):
                subq = _const_subquery(node.value, 'U', aliases)
                constraint = f"{full_uuid} = {subq}"
                plan.constraints.append(constraint)
                plan.tagged_constraints.append((q_id, constraint))
                plan.leaf_terms[(q_id, uuid_col_name)] = (
                    node.value, 'U', None, None)

            elif isinstance(node, LiteralNode):
                if node.lang:
                    constraint = (
                        f"{full_uuid} = (SELECT term_uuid FROM {term_table} "
                        f"WHERE term_text = '{_esc(node.value)}' AND term_type = 'L'"
                        f" AND lang = '{_esc(node.lang)}' LIMIT 1)"
                    )
                    plan.constraints.append(constraint)
                    plan.tagged_constraints.append((q_id, constraint))
                else:
                    # Carry the DATATYPE. A graph pattern matches by TERM, so
                    # `"x"` and `"x"^^xsd:string` are different terms even
                    # though RDF 1.1 makes them one value — the opposite of the
                    # FILTER rule in `issues/121`.
                    subq = _const_subquery(node.value, 'L', aliases,
                                           datatype=node.datatype)
                    constraint = f"{full_uuid} = {subq}"
                    plan.constraints.append(constraint)
                    plan.tagged_constraints.append((q_id, constraint))
                    plan.leaf_terms[(q_id, uuid_col_name)] = (
                        node.value, 'L', None, node.datatype or None)

        # Graph lock — always applied (scoping / security)
        if aliases.graph_lock_uri:
            subq = _const_subquery(aliases.graph_lock_uri, 'U', aliases)
            constraint = f"{q_id}.context_uuid = {subq}"
            plan.constraints.insert(0, constraint)
            plan.tagged_constraints.insert(0, (q_id, constraint))

        # Default graph — only when NOT inside a GRAPH clause
        if aliases.default_graph and graph_uri is None:
            subq = _const_subquery(aliases.default_graph, 'U', aliases)
            constraint = f"{q_id}.context_uuid = {subq}"
            plan.constraints.append(constraint)
            plan.tagged_constraints.append((q_id, constraint))

        # Rule 3: IS DISTINCT FROM for negative comparisons (§10.5).
        # GRAPH ?g — exclude default graph (SPARQL: GRAPH ?g matches named graphs only).
        # Use IS DISTINCT FROM (not !=) so NULL from a missing default graph
        # term is treated as "no exclusion" rather than filtering all rows.
        if aliases.default_graph and graph_uri == GRAPH_VAR_SCOPE:
            subq = _const_subquery(aliases.default_graph, 'U', aliases)
            constraint = f"{q_id}.context_uuid IS DISTINCT FROM {subq}"
            plan.constraints.append(constraint)
            plan.tagged_constraints.append((q_id, constraint))

        # Graph scoping from SPARQL GRAPH <uri> clause
        if graph_uri and graph_uri != GRAPH_VAR_SCOPE and graph_uri != aliases.graph_lock_uri:
            subq = _const_subquery(graph_uri, 'U', aliases)
            constraint = f"{q_id}.context_uuid = {subq}"
            plan.constraints.append(constraint)
            plan.tagged_constraints.append((q_id, constraint))

    return plan


@collect.register(OpJoin)
def _collect_join(op: OpJoin, space_id: str, aliases: AliasGenerator,
                  graph_uri: str = None) -> PlanV2:
    left = collect(op.left, space_id, aliases, graph_uri)
    right = collect(op.right, space_id, aliases, graph_uri)
    return PlanV2(kind=KIND_JOIN, children=[left, right])


@collect.register(OpLeftJoin)
def _collect_left_join(op: OpLeftJoin, space_id: str, aliases: AliasGenerator,
                       graph_uri: str = None) -> PlanV2:
    left = collect(op.left, space_id, aliases, graph_uri)
    right = collect(op.right, space_id, aliases, graph_uri)
    plan = PlanV2(kind=KIND_LEFT_JOIN, children=[left, right])
    if op.exprs:
        plan.left_join_exprs = list(op.exprs)
    return plan


@collect.register(OpUnion)
def _collect_union(op: OpUnion, space_id: str, aliases: AliasGenerator,
                   graph_uri: str = None) -> PlanV2:
    left = collect(op.left, space_id, aliases, graph_uri)
    right = collect(op.right, space_id, aliases, graph_uri)
    return PlanV2(kind=KIND_UNION, children=[left, right])


@collect.register(OpMinus)
def _collect_minus(op: OpMinus, space_id: str, aliases: AliasGenerator,
                   graph_uri: str = None) -> PlanV2:
    left = collect(op.left, space_id, aliases, graph_uri)
    right = collect(op.right, space_id, aliases, graph_uri)
    return PlanV2(kind=KIND_MINUS, children=[left, right])


@collect.register(OpTable)
def _collect_table(op: OpTable, space_id: str, aliases: AliasGenerator,
                   graph_uri: str = None) -> PlanV2:
    # Register every constant the VALUES block names, so the FIRST
    # materialization pass resolves it to a term uuid. Registering here rather
    # than at emit time is what lets `emit_table` know whether each one
    # actually exists: a URI absent from the term table must match nothing, and
    # emitting a NULL uuid for it would make it match everything (`issues/087`).
    for row in (op.rows or []):
        for val in row.values():
            if isinstance(val, URINode):
                aliases.register_constant(val.value, "U")
            elif isinstance(val, LiteralNode):
                aliases.register_constant(val.value, "L",
                                          getattr(val, "lang", None),
                                          val.datatype)
    return PlanV2(
        kind=KIND_TABLE,
        values_vars=list(op.vars),
        values_rows=list(op.rows) if op.rows else [],
    )


@collect.register(OpNull)
def _collect_null(op: OpNull, space_id: str, aliases: AliasGenerator,
                  graph_uri: str = None) -> PlanV2:
    return PlanV2(kind=KIND_NULL)


@collect.register(OpSequence)
def _collect_sequence(op: OpSequence, space_id: str, aliases: AliasGenerator,
                      graph_uri: str = None) -> PlanV2:
    children = [collect(child, space_id, aliases, graph_uri)
                for child in op.elements]
    if len(children) == 1:
        return children[0]
    result = children[0]
    for child in children[1:]:
        result = PlanV2(kind=KIND_JOIN, children=[result, child])
    return result


@collect.register(OpPath)
def _collect_path(op: OpPath, space_id: str, aliases: AliasGenerator,
                  graph_uri: str = None) -> PlanV2:
    plan = PlanV2(kind=KIND_PATH)
    term_table = f"{space_id}_term"
    quad_table = f"{space_id}_rdf_quad"

    plan.path_meta = {
        "path": op.path,
        "subject": op.subject,
        "object": op.object,
        "quad_table": quad_table,
        "term_table": term_table,
        "graph_uri": graph_uri,
        "cte_alias": aliases.next("p"),
    }

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


@collect.register(OpGraph)
def _collect_graph(op: OpGraph, space_id: str, aliases: AliasGenerator,
                   graph_uri: str = None) -> PlanV2:
    if isinstance(op.graph_node, URINode):
        return collect(op.sub_op, space_id, aliases,
                       graph_uri=op.graph_node.value)

    if isinstance(op.graph_node, VarNode):
        graph_var = op.graph_node.name
        inner = collect(op.sub_op, space_id, aliases, graph_uri=GRAPH_VAR_SCOPE)
        _bind_graph_var(inner, graph_var, space_id, aliases)
        return inner

    return collect(op.sub_op, space_id, aliases, graph_uri=GRAPH_VAR_SCOPE)


def _bind_graph_var(plan: PlanV2, graph_var: str, space_id: str,
                     aliases: AliasGenerator) -> None:
    """Bind a GRAPH variable to context_uuid on all quad tables in a plan.

    Does NOT recurse into KIND_PROJECT children — a project creates a
    variable scope barrier (subquery boundary).
    """
    # If this plan IS a project, it's a scope barrier — don't bind inside.
    if plan.kind == KIND_PROJECT:
        return

    term_table = f"{space_id}_term"

    for child in plan.children:
        if child.kind == KIND_PROJECT:
            continue  # subquery scope barrier
        _bind_graph_var(child, graph_var, space_id, aliases)

    # Handle path plans: store graph_var in path_meta for the emitter
    if plan.kind == KIND_PATH and plan.path_meta is not None:
        plan.path_meta["graph_var"] = graph_var
        return

    quad_tables = [t for t in plan.tables if t.kind == "quad"]
    if not quad_tables:
        return

    for qt in quad_tables:
        full_uuid = f"{qt.alias}.context_uuid"
        if graph_var in plan.var_slots:
            first = plan.var_slots[graph_var]
            first_uuid = f"{first.positions[0][0]}.{first.positions[0][1]}"
            constraint = f"{full_uuid} = {first_uuid}"
            plan.constraints.append(constraint)
            plan.tagged_constraints.append((qt.alias, constraint))
            first.positions.append((qt.alias, "context_uuid"))
        else:
            t_id = aliases.next("t")
            plan.tables.append(TableRef(
                ref_id=t_id, kind="term", table_name=term_table,
                join_col=full_uuid, alias=t_id,
            ))
            slot = VarSlot(name=graph_var, term_ref_id=t_id)
            slot.positions.append((qt.alias, "context_uuid"))
            plan.var_slots[graph_var] = slot


# ---------------------------------------------------------------------------
# Modifier kinds (unary — each wraps its child, preserving eval order)
# ---------------------------------------------------------------------------

@collect.register(OpFilter)
def _collect_filter(op: OpFilter, space_id: str, aliases: AliasGenerator,
                    graph_uri: str = None) -> PlanV2:
    inner = collect(op.sub_op, space_id, aliases, graph_uri)
    # v2: HAVING detection is deferred to emit time.
    # The emitter checks if this filter's child is a group node and reclassifies
    # aggregate-referencing expressions as HAVING clauses.
    return PlanV2(kind=KIND_FILTER, filter_exprs=list(op.exprs),
                  children=[inner])


@collect.register(OpProject)
def _collect_project(op: OpProject, space_id: str, aliases: AliasGenerator,
                     graph_uri: str = None) -> PlanV2:
    inner = collect(op.sub_op, space_id, aliases, graph_uri)
    return PlanV2(kind=KIND_PROJECT, project_vars=list(op.vars),
                  children=[inner])


def _anchor_var_for_paging(node, depth: int = 0):
    """The single variable a paged result can be ordered by, or None.

    Only a single-variable projection qualifies. With more than one there is no
    obviously right key, and guessing one would be inventing an ordering the
    caller might notice.
    """
    if node is None or depth > 6:
        return None
    if node.kind == KIND_PROJECT and node.project_vars:
        vars_ = [v for v in node.project_vars if v != "*"]
        return vars_[0] if len(vars_) == 1 else None
    for c in (node.children or []):
        found = _anchor_var_for_paging(c, depth + 1)
        if found is not None:
            return found
    return None


def _has_order(node, depth: int = 0) -> bool:
    if node is None or depth > 6:
        return False
    if node.kind == KIND_ORDER and node.order_conditions:
        return True
    return any(_has_order(c, depth + 1) for c in (node.children or []))


@collect.register(OpSlice)
def _collect_slice(op: OpSlice, space_id: str, aliases: AliasGenerator,
                   graph_uri: str = None) -> PlanV2:
    inner = collect(op.sub_op, space_id, aliases, graph_uri)

    # A paged query with NO requested order needs one anyway: without an
    # ORDER BY, PostgreSQL guarantees nothing about the order between two
    # executions, so page 2 is not meaningfully "the next 25" of page 1. That
    # is unsafe regardless of which emitter runs.
    #
    # So one is imposed here, and MARKED as imposed. The mark is the point: a
    # synthesized order means "any stable order will do", which lets the paging
    # emitters use the entity uuid — index-backed, so the scan terminates early
    # (measured 117x cheaper than ordering on the requested key, `issues/075`).
    # A user's own ORDER BY carries no mark and must be answered as written.
    #
    # SPARQL permits this: with no ORDER BY the solution sequence is unordered,
    # so any order is a correct one. What is NOT permitted is substituting a
    # different order for one the caller asked for, which is what emitting a
    # default `ORDER BY ?entity` upstream had turned into (`issues/075`).
    if not _has_order(inner):
        anchor = _anchor_var_for_paging(inner)
        if anchor is not None:
            inner = PlanV2(kind=KIND_ORDER,
                           order_conditions=[(anchor, "ASC")],
                           hints={"stable_paging": True},
                           children=[inner])

    return PlanV2(
        kind=KIND_SLICE,
        limit=op.length if op.length >= 0 else -1,
        offset=op.start if op.start > 0 else 0,
        children=[inner],
    )


@collect.register(OpDistinct)
def _collect_distinct(op: OpDistinct, space_id: str, aliases: AliasGenerator,
                      graph_uri: str = None) -> PlanV2:
    inner = collect(op.sub_op, space_id, aliases, graph_uri)
    return PlanV2(kind=KIND_DISTINCT, children=[inner])


@collect.register(OpReduced)
def _collect_reduced(op: OpReduced, space_id: str, aliases: AliasGenerator,
                     graph_uri: str = None) -> PlanV2:
    inner = collect(op.sub_op, space_id, aliases, graph_uri)
    return PlanV2(kind=KIND_REDUCED, children=[inner])


@collect.register(OpOrder)
def _collect_order(op: OpOrder, space_id: str, aliases: AliasGenerator,
                   graph_uri: str = None) -> PlanV2:
    inner = collect(op.sub_op, space_id, aliases, graph_uri)
    conditions = []
    for sc in op.conditions:
        direction = "ASC" if sc.direction != "DESC" else "DESC"
        if isinstance(sc.expr, ExprVar):
            conditions.append((sc.expr.var, direction))
        else:
            conditions.append((sc.expr, direction))
    return PlanV2(kind=KIND_ORDER, order_conditions=conditions,
                  children=[inner])


@collect.register(OpExtend)
def _collect_extend(op: OpExtend, space_id: str, aliases: AliasGenerator,
                    graph_uri: str = None) -> PlanV2:
    inner = collect(op.sub_op, space_id, aliases, graph_uri)
    # v2: one extend node per binding (not flattened).
    return PlanV2(kind=KIND_EXTEND, extend_var=op.var, extend_expr=op.expr,
                  children=[inner])


@collect.register(OpGroup)
def _collect_group(op: OpGroup, space_id: str, aliases: AliasGenerator,
                   graph_uri: str = None) -> PlanV2:
    inner = collect(op.sub_op, space_id, aliases, graph_uri)

    # Build aggregates dict from pre-mapped aggregator dicts
    aggregates = None
    if op.aggregators:
        aggregates = {}
        for a in op.aggregators:
            var = a.get('var')
            agg_dict = a.get('aggregator', {})
            if var and agg_dict:
                agg_expr = agg_dict.get('expr')
                # Expressions are pre-mapped by AST mapper
                if agg_expr is not None and not isinstance(
                    agg_expr, (ExprVar, ExprValue, ExprFunction, ExprAggregator)
                ):
                    agg_expr = None  # Safety: drop unmapped dicts
                aggregates[var] = ExprAggregator(
                    name=agg_dict.get('name', 'COUNT'),
                    distinct=agg_dict.get('distinct', False),
                    expr=agg_expr,
                    separator=agg_dict.get('separator'),
                )

    return PlanV2(
        kind=KIND_GROUP,
        group_vars=list(op.group_vars),
        aggregates=aggregates,
        children=[inner],
    )

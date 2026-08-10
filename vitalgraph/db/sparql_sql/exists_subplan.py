"""Build and optimize the plans inside FILTER EXISTS / NOT EXISTS bodies.

`_exists_to_sql` used to call `collect()` on the inner graph pattern at *emit*
time. Emit is synchronous, and the passes that matter need database I/O, so the
body received none of the pipeline that had already been applied to the outer
plan:

    stage                     outer plan        EXISTS body
    materialize_constants     uuid literals     a subquery per URI, at runtime
    rewrite_edge_table        edge-table refs   raw quad joins
    text-needed pruning       applied           term JOINs for text nobody reads

Measured on a fully-indexed 100k fixture, one correlated probe cost 435ms and
40,403 buffer reads; a 25-row page needs 25 of them (issues/057). Every
comparator the KGQuery builder compiles to `FILTER NOT EXISTS` — `ne` on all
five slot classes, `not_exists`, `not_has`, `not_has_any` — paid it.

This module runs during `generate_sql`, where a connection is available, and
attaches the finished plan to the `ExprExists` node. Emit then uses it. When
preparation has not run the emit path still collects inline, so the fallback is
the old behaviour rather than a failure.

What is deliberately NOT run here:

  * `mark_semijoins` — it rewrites JOINs into EXISTS subqueries, and this is
    already inside one. The correlation rules at `_exists_to_sql` (SPARQL 1.1
    §8.1.1: a variable the body does not bind resolves to the OUTER row) are
    subtle enough that adding a pass which moves variables between scopes wants
    its own change and its own differential test.
  * `vg_optimize` — vector/geo hints, irrelevant to an existence test.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from .ir import PlanV2, AliasGenerator

logger = logging.getLogger(__name__)


def _iter_exists(expr, depth: int = 0):
    """Yield every ExprExists reachable from an expression tree."""
    from vitalgraph.db.jena_sparql.jena_types import (
        ExprExists, ExprFunction, ExprAggregator)

    if expr is None or depth > 12:
        return
    if isinstance(expr, ExprExists):
        yield expr
        return          # its body is an Op, not an Expr; recursed after collect
    if isinstance(expr, ExprFunction):
        for arg in (expr.args or []):
            yield from _iter_exists(arg, depth + 1)
    elif isinstance(expr, ExprAggregator):
        yield from _iter_exists(expr.expr, depth + 1)


def _plan_exists(plan: Optional[PlanV2], depth: int = 0) -> List[Any]:
    """Every ExprExists in a plan tree, from all expression-bearing fields.

    Missing one of these fields means that EXISTS silently keeps the slow path,
    so they are enumerated explicitly rather than by attribute sniffing.
    """
    found: List[Any] = []
    if plan is None or depth > 24:
        return found

    for expr in (plan.filter_exprs or []):
        found.extend(_iter_exists(expr))
    for expr in (plan.having_exprs or []):
        found.extend(_iter_exists(expr))
    for expr in (plan.left_join_exprs or []):
        found.extend(_iter_exists(expr))
    if plan.extend_expr is not None:
        found.extend(_iter_exists(plan.extend_expr))
    for cond in (plan.order_conditions or []):
        # [(Expr|str, "ASC"/"DESC")] — a bare string is a variable name.
        expr = cond[0] if isinstance(cond, (tuple, list)) else cond
        if not isinstance(expr, str):
            found.extend(_iter_exists(expr))

    for child in (plan.children or []):
        found.extend(_plan_exists(child, depth + 1))
    return found


async def prepare_exists_subplans(plan: PlanV2, space_id: str, *,
                                  conn=None, conn_params=None,
                                  graph_lock_uri: Optional[str] = None,
                                  edge_table_ready: bool = False,
                                  frame_entity_ready: bool = False,
                                  depth: int = 0) -> int:
    """Collect and optimize every EXISTS body in `plan`. Returns how many.

    Recurses into the bodies it prepares, so `FILTER NOT EXISTS { ... FILTER
    EXISTS { ... } }` is optimized all the way down.

    Each body gets its own AliasGenerator, because its constants are its own —
    materializing them into the outer generator would let an inner constant be
    emitted as an outer column reference.
    """
    from .collect import collect
    # Imported here, not at module scope: materialize_constants lives in
    # generator, which imports this module.
    from .generator import materialize_constants

    if depth > 4:
        # Deeper nesting than any real query; bail rather than recurse forever
        # on a malformed pattern.
        logger.warning("EXISTS nesting deeper than 4 — leaving inner bodies "
                       "unoptimized")
        return 0

    nodes = _plan_exists(plan)
    if not nodes:
        return 0

    term_table = f"{space_id}_term"
    prepared = 0

    for i, node in enumerate(nodes):
        if node.graph_pattern is None or node.prepared_plan is not None:
            continue
        try:
            # The "ex_" prefix is what keeps inner column names from colliding
            # with outer ones, which is what makes an unbound inner variable
            # resolve to the enclosing row instead of shadowing it. Preserved
            # exactly as the emit path had it.
            inner_aliases = AliasGenerator(alias_prefix="ex_")
            # graph_uri is NOT optional: the emit-time path passes
            # ctx.graph_lock_uri, and omitting it here would let the body match
            # quads in every graph while the outer query is locked to one —
            # a NOT EXISTS that finds a match in an unrelated graph excludes an
            # entity that should have been returned.
            inner_plan = collect(node.graph_pattern, space_id, inner_aliases,
                                 graph_uri=graph_lock_uri)

            if conn is not None or conn_params is not None:
                await materialize_constants(inner_aliases, term_table,
                                            conn_params=conn_params, conn=conn)

            from .prune_union import prune_dead_union_branches
            inner_plan = prune_dead_union_branches(inner_plan, inner_aliases)

            if edge_table_ready:
                from .rewrite_edge_table import rewrite_edge_table
                inner_plan = rewrite_edge_table(inner_plan, inner_aliases,
                                                space_id)
            if frame_entity_ready:
                from .rewrite_frame_entity_table import (
                    rewrite_frame_entity_table)
                inner_plan = rewrite_frame_entity_table(inner_plan,
                                                        inner_aliases, space_id)

            # Nested EXISTS inside this body.
            await prepare_exists_subplans(
                inner_plan, space_id, conn=conn, conn_params=conn_params,
                graph_lock_uri=graph_lock_uri,
                edge_table_ready=edge_table_ready,
                frame_entity_ready=frame_entity_ready, depth=depth + 1)

            node.prepared_plan = inner_plan
            node.prepared_aliases = inner_aliases
            prepared += 1
        except Exception as exc:
            # Never fail the query for this. An unprepared body emits the way
            # it always did — slowly, but correctly — and the alternative is
            # that a pass bug turns a working query into an error.
            logger.warning("EXISTS body %d not prepared (%s: %s); falling back "
                           "to inline collect", i, type(exc).__name__, exc)

    if prepared:
        logger.debug("Prepared %d EXISTS subplan(s) for %s", prepared, space_id)
    return prepared

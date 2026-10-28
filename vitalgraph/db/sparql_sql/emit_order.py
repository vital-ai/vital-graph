"""Handler for KIND_ORDER — ORDER BY emission."""

from __future__ import annotations

import logging

from .ir import PlanV2
from .emit_context import EmitContext

logger = logging.getLogger(__name__)


def emit_order(plan: PlanV2, ctx: EmitContext) -> str:
    """Emit SQL for an ORDER BY modifier.

    Recursively emits the child, then wraps with ORDER BY.
    """
    from .emit import emit
    from .emit_expressions import expr_to_sql

    child_sql = emit(plan.child, ctx)

    if not plan.order_conditions:
        return child_sql

    # An order this layer SYNTHESIZED for stable paging (`collect._collect_slice`,
    # `issues/075`) is ordered by the variable's UUID, not its text. Any stable
    # order satisfies it, and uuid is the one the paging emitters can produce
    # from an index without resolving text for the whole match set.
    #
    # This is what makes the paths agree. Ordering by text here while
    # `_emit_two_phase` ordered by uuid gave two total orders for one query, so
    # a pagination sequence crossing them skipped and repeated rows
    # (`issues/078`). A user's own ORDER BY has no such hint and is emitted on
    # the text column, as written.
    stable = bool((plan.hints or {}).get("stable_paging"))

    o_alias = ctx.aliases.next("o")
    ob_parts = []
    for key, direction in plan.order_conditions:
        if isinstance(key, str):
            if ctx.types.get(key) is None or getattr(ctx.types.get(key), "is_unbound", False):
                # a variable nothing binds: unbound on every row, so it orders
                # nothing; its columns do not exist (`ORDER BY ?nothing` failed)
                continue
            ob_parts.extend(variable_order_keys(o_alias, ctx.types.get(key), key,
                                                direction, stable=stable))
            continue
        col = _scoped_expr(key, plan, ctx)
        if not col:
            continue
        suffix = " DESC" if direction == "DESC" else ""
        ob_parts.append(f"{col}{suffix}")

    if not ob_parts:
        return child_sql

    ctx.log("order", f"ORDER BY: {', '.join(ob_parts)}")

    return (
        f"SELECT * FROM ({child_sql}) AS {o_alias}\n"
        f"ORDER BY {', '.join(ob_parts)}"
    )


def variable_order_keys(alias: str, info, var: str, direction: str,
                        stable: bool = False) -> list:
    """The ORDER BY terms for one variable, for BOTH emitters of a user's order.

    A literal from a triple pattern sorts on its VALUE: `__num`, then `__dt`,
    then the collated text (`issues/295`). Sorting on the text alone put
    "99.9" above "100.0" under DESC. SPARQL 1.1 15.1 orders literals with `<`:
    numerics by value, `xsd:dateTime` chronologically. A non-numeric term has
    NULL `__num`/`__dt`, so those keys tie and the text decides, as before.

    `emit_project` re-applies the order on its outer SELECT and must emit the
    same keys: it sorted on plain text, and that is the order the query
    actually returned.
    """
    from .collation import collate
    sn = info.sql_name if info else var
    suffix = " DESC" if direction == "DESC" else ""
    if stable:
        # Synthesized for stable paging: any total order, and uuid is the one
        # the paging emitters can produce from an index (issues/075, 078).
        return [f"{alias}.{sn}__uuid{suffix}"]
    from .ir import TiebreakVar
    if isinstance(var, TiebreakVar) and info is not None and info.has_term_identity():
        # A page's tiebreak (`collect._add_paging_tiebreak`, issues/312): the term's
        # identity, a total order over stored terms; a computed value keeps its
        # value keys below
        return [f"{alias}.{sn}__uuid{suffix}"]
    if info is not None and info.typed_lane:
        # A computed variable on the numeric or boolean lane — ORDER BY over a
        # COUNT, for instance. `sn` is not a text column there and PostgreSQL
        # raises "collations are not supported by type numeric" rather than
        # ignoring the clause. Caught by DAWG aggregates/COUNT 8b.
        return [f"{alias}.{sn}{suffix}"]
    keys = []
    if info is None or getattr(info, "_sql_has_companions", True):
        keys += [f"{alias}.{sn}__num{suffix}", f"{alias}.{sn}__dt{suffix}"]
    # Plain columns only (issues/324): a kind rank (SPARQL 15.1: blank node, IRI,
    # literal) or a text key confined to non-numeric values (10 and 1.0E1 tying to
    # the next key) is an EXPRESSION, and an expression key made the ordered queries
    # 10-59% slower: the outer ORDER BY no longer matched the inner one's sorted
    # output and sorted again. Both deviations are rare; the cost was not. An
    # unbound value sorts last ascending (PostgreSQL's NULLs), which the app's
    # sequence ordering relies on (test_sequence_ordering.py).
    # Pinned, not inherited: SPARQL orders strings by code point and PostgreSQL
    # orders by the cluster's collation. Only the text column takes it.
    keys.append(f"{collate(f'{alias}.{sn}')}{suffix}")
    return keys


def _scoped_expr(expr, plan, ctx):
    """Emit an expression with the child pattern's variables declared in scope.

    These expressions apply to whatever the child binds, so that is the scope
    an unresolvable reference should be judged against (issue 028).
    """
    from .emit_expressions import expr_to_sql
    from .var_scope import compute_scope

    child = plan.child if getattr(plan, "child", None) is not None else None
    in_scope = compute_scope(child).all_visible if child is not None else None
    with ctx.expression_scope(in_scope):
        return expr_to_sql(expr, ctx)

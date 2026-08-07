"""Mark inner JOINs that can be emitted as existence tests (issues/040).

A KGQuery frame criteria compiles to

    SLICE → DISTINCT → PROJECT[?entity] → ORDER → JOIN(A, B)

where A binds ?entity and B is the frame/slot chain: ten more tables binding
nothing the caller asked for. As a JOIN every matching combination crosses it
and `DISTINCT` collapses them afterwards, so a 25-row page costs proportional to
the whole match set. On a 100,000-entity space that is not slow, it is broken —
three of four ordinary lead queries exceed the 30s client timeout.

As `A WHERE EXISTS (B)` each row of A is tested once and kept or dropped.

This pass marks two things, and the second is as important as the first:

  hints['semijoin']          on the JOIN — emit the right side as an existence
                             test rather than a join
  hints['distinct_redundant'] on the DISTINCT above it — EXISTS yields at most
                             one row per outer row, so the DISTINCT no longer
                             removes anything, and the Unique/HashAggregate it
                             emits is a blocking node that stops LIMIT from
                             terminating the scan early. Leaving it in place
                             defeats the whole rewrite.

WHEN THE REWRITE IS VALID, and every clause matters:

1. **Inner join only.** For a LEFT JOIN the right side must contribute
   bindings, not merely existence.
2. **The right side adds no variable anyone needs above.** Otherwise its values
   are required in the output and existence is not enough.
3. **There is a DISTINCT above.** A join multiplies rows when the right side
   matches more than once; EXISTS does not. Without a DISTINCT collapsing them
   anyway the rewrite silently *changes the row count* — the query still runs
   and still looks reasonable. This is what makes the two forms equivalent
   rather than merely similar, and it is also what makes (2) above safe to
   remove.
4. **Shared variables exist.** With none the join is a cartesian product.
5. **Neither side is a VALUES table.** Those carry UNDEF and join under
   compatible-mapping rules that EXISTS does not reproduce.

The analysis is a live-variable pass: walk down carrying the variables some
ancestor still needs, and at each JOIN ask whether the right side's private
variables intersect it. It has to see the whole tree, which is why it is a pass
rather than a check inside `emit_join` — a JOIN cannot tell from its own subtree
whether a variable escapes upward through a sibling.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Set

from .ir import (
    PlanV2,
    KIND_JOIN, KIND_LEFT_JOIN, KIND_UNION, KIND_MINUS, KIND_TABLE,
    KIND_PROJECT, KIND_DISTINCT, KIND_REDUCED, KIND_SLICE, KIND_ORDER,
    KIND_FILTER, KIND_EXTEND, KIND_GROUP,
)
from .var_scope import compute_scope, vars_in_expr

logger = logging.getLogger(__name__)

# Probing costs O(page / selectivity): to fill a 25-row page it walks
# 25/selectivity candidates. Below this fraction the set-based join wins, and
# not by a little — measured on a 10k fixture, a criterion matching 9% of
# entities went to 0.77x the baseline while one matching 0.96% went to 889x.
# The gate is the difference between this rewrite being a win and being a
# catastrophe on exactly the queries that are cheap today.
MIN_SELECTIVITY = 0.05


def _term_uuid(aliases, text: str, ttype: str) -> Optional[str]:
    """Resolve a constant to its term uuid via the map the generator built.

    `materialize_constants` fills `resolved_constants[col_name]`, and
    `constants[(text, type)]` gives the col_name — so the uuid is available
    structurally. This replaces regex-parsing it out of the emitted SQL, which
    coupled the lookup to the SQL text and returned None silently whenever
    anything differed.
    """
    col = getattr(aliases, "constants", {}).get((text, ttype))
    if col is None:
        return None
    return getattr(aliases, "resolved_constants", {}).get(col)


def _leaf_rows(node, aliases) -> Optional[int]:
    """Smallest (predicate, object) row count among a subtree's constant leaves.

    Reads `plan.leaf_terms`, recorded at collect time, rather than parsing the
    generated SQL. The generator already loads these counts for `reorder_bgp`,
    so the selectivity signal costs nothing extra — and it does not depend on
    the planner, whose own estimate for these shapes is `rows=1` against
    thousands actual.
    """
    stats = getattr(aliases, "quad_stats", None)
    if not stats:
        return None
    best = None

    # Numeric ranges, matched by predicate. They cannot be found by walking
    # this subtree for FILTERs: the FILTER sits ABOVE the join, while the
    # predicate it constrains lives in the subtree below. Keying on the
    # predicate uuid is what associates the two — without it the range's count
    # is missed entirely and a 0.16%-selective range reads as 100%, which is
    # how a tight threshold came to be probed at 646x the cost.
    range_stats = getattr(aliases, "range_stats", {})
    if range_stats:
        preds = set()
        for bgp in _bgps(node):
            for (alias, col), term in (bgp.leaf_terms or {}).items():
                if col == "predicate_uuid":
                    u = _term_uuid(aliases, *term)
                    if u:
                        preds.add(u)
        for (p_uuid, _op, _lit), n in range_stats.items():
            if p_uuid in preds and n is not None and (best is None or n < best):
                best = n

    for bgp in _bgps(node):
        by_alias: dict = {}
        for (alias, col), (text, ttype) in (bgp.leaf_terms or {}).items():
            if col == "predicate_uuid":
                by_alias.setdefault(alias, {})["p"] = (text, ttype)
            elif col == "object_uuid":
                by_alias.setdefault(alias, {})["o"] = (text, ttype)
        for pair in by_alias.values():
            if "p" not in pair or "o" not in pair:
                continue
            p_uuid = _term_uuid(aliases, *pair["p"])
            o_uuid = _term_uuid(aliases, *pair["o"])
            if not p_uuid or not o_uuid:
                continue
            n = stats.get((p_uuid, o_uuid))
            if n is None:
                n = getattr(aliases, "extra_quad_stats", {}).get(
                    (p_uuid, o_uuid))
            if n is not None and (best is None or n < best):
                best = n
    return best


def needed_ranges(plan, aliases) -> set:
    """(predicate_uuid, operator, literal) for each numeric range in the plan.

    Read from the FILTER nodes directly, NOT from what `filter_pushdown`
    records: that runs during emission, long after this gate has decided. A
    range criterion also binds no constant object, so `needed_pairs` sees
    nothing for it — and left unestimated the gate declines to probe, which is
    the wrong answer for exactly the queries a range makes broad.
    """
    from .filter_pushdown import _NUMERIC_OPS, _numeric_literal, _FLIPPED
    from ..jena_sparql.jena_types import ExprVar, ExprFunction

    out = set()
    for filt in _filters(plan):
        for expr in (filt.filter_exprs or []):
            if not isinstance(expr, ExprFunction):
                continue
            op = _NUMERIC_OPS.get((expr.name or "").lower())
            if op is None or len(expr.args or []) != 2:
                continue
            left, right = expr.args
            if isinstance(left, ExprVar):
                var, lit = left.var, _numeric_literal(right)
            elif isinstance(right, ExprVar):
                var, lit = right.var, _numeric_literal(left)
                op = _FLIPPED[op]
            else:
                continue
            if lit is None:
                continue
            # The variable's leaf gives the predicate whose objects the range
            # constrains — that pair is what the count is over.
            for bgp in _bgps(plan):
                slot = bgp.var_slots.get(var)
                if not slot or not slot.positions:
                    continue
                alias, _col = slot.positions[0]
                pred = (bgp.leaf_terms or {}).get((alias, "predicate_uuid"))
                if not pred:
                    continue
                p_uuid = _term_uuid(aliases, *pred)
                if p_uuid:
                    out.add((p_uuid, op, lit))
                    break
    return out


def _filters(node, depth: int = 0):
    from .ir import KIND_FILTER
    if node is None or depth > 10:
        return
    if node.kind == KIND_FILTER:
        yield node
    for c in (node.children or []):
        yield from _filters(c, depth + 1)


def needed_pairs(plan, aliases) -> set:
    """Every constant (predicate, object) uuid pair the plan binds at a leaf.

    The generator resolves any of these that `quad_stats` lacks. That preload is
    deliberately capped at the 10,000 *least common* pairs
    (`ORDER BY row_count ASC LIMIT 10000`) because that is what join reordering
    needs — so a common pair such as (vitaltype, KGEntity) is simply absent, and
    absence is indistinguishable from "rare". The gate needs the anchor's real
    candidate count as its denominator, so it has to be fetched.
    """
    out = set()
    for bgp in _bgps(plan):
        by_alias: dict = {}
        for (alias, col), (text, ttype) in (bgp.leaf_terms or {}).items():
            if col == "predicate_uuid":
                by_alias.setdefault(alias, {})["p"] = (text, ttype)
            elif col == "object_uuid":
                by_alias.setdefault(alias, {})["o"] = (text, ttype)
        for pair in by_alias.values():
            if "p" in pair and "o" in pair:
                p_uuid = _term_uuid(aliases, *pair["p"])
                o_uuid = _term_uuid(aliases, *pair["o"])
                if p_uuid and o_uuid:
                    out.add((p_uuid, o_uuid))
    return out


def _bgps(node, depth: int = 0):
    from .ir import KIND_BGP
    if node is None or depth > 8:
        return
    if node.kind == KIND_BGP:
        yield node
    for c in (node.children or []):
        yield from _bgps(c, depth + 1)


def mark_semijoins(plan: PlanV2, aliases=None) -> PlanV2:
    """Annotate eligible JOINs, and the DISTINCT each one makes redundant."""
    marked: List[PlanV2] = []
    _walk(plan, needed=_root_needed(plan), distinct_node=None, marked=marked,
          aliases=aliases)
    if marked:
        logger.info("semijoin: marked %d join(s)", len(marked))
    return plan


def _root_needed(plan: PlanV2) -> Set[str]:
    try:
        return set(compute_scope(plan).all_visible)
    except Exception:
        return set()


def _expr_list_vars(exprs) -> Set[str]:
    out: Set[str] = set()
    for e in (exprs or []):
        try:
            out |= vars_in_expr(e)
        except Exception:
            pass
    return out


def _order_key_vars(plan: PlanV2) -> Set[str]:
    out: Set[str] = set()
    for key, _direction in (plan.order_conditions or []):
        if isinstance(key, str):
            out.add(key)
        else:
            try:
                out |= vars_in_expr(key)
            except Exception:
                pass
    return out


def _pushable_range_var(expr) -> Optional[str]:
    """Variable of a numeric range that `filter_pushdown` will consume, else None."""
    try:
        from .filter_pushdown import _NUMERIC_OPS, _numeric_literal
        from ..jena_sparql.jena_types import ExprVar, ExprFunction
    except Exception:
        return None
    if not isinstance(expr, ExprFunction):
        return None
    if (expr.name or "").lower() not in _NUMERIC_OPS or len(expr.args or []) != 2:
        return None
    left, right = expr.args
    if isinstance(left, ExprVar) and _numeric_literal(right) is not None:
        return left.var
    if isinstance(right, ExprVar) and _numeric_literal(left) is not None:
        return right.var
    return None


def _walk(node: Optional[PlanV2], needed: Set[str],
          distinct_node: Optional[PlanV2], marked: List[PlanV2],
          aliases=None, pushable_vars: Set[str] = frozenset()) -> None:
    """`distinct_node` is the nearest enclosing DISTINCT, or None.

    `pushable_vars` are variables referenced only by numeric-range FILTERs that
    will be pushed into the BGP, so they do not have to survive a semi-join.
    """
    if node is None:
        return

    kind = node.kind

    if kind in (KIND_DISTINCT, KIND_REDUCED):
        _walk(node.child, needed, node, marked, aliases, pushable_vars)
        return

    if kind == KIND_PROJECT:
        proj = set(node.project_vars or []) or needed
        _walk(node.child, proj, distinct_node, marked, aliases, pushable_vars)
        return

    if kind == KIND_SLICE:
        _walk(node.child, needed, distinct_node, marked, aliases, pushable_vars)
        return

    if kind == KIND_ORDER:
        _walk(node.child, needed | _order_key_vars(node), distinct_node,
              marked, aliases)
        return

    if kind == KIND_FILTER:
        # A numeric range is pushed into the probed BGP and evaluated there, so
        # its variable need not survive the join. That is only safe because the
        # emit side (emit_slice._emit_two_phase) pushes the filter and then
        # CHECKS it was consumed, falling back if not — without that check this
        # exclusion returns rows that do not satisfy the criterion.
        pushable, kept = set(), set()
        for expr in (node.filter_exprs or []):
            v = _pushable_range_var(expr)
            if v is not None:
                pushable.add(v)
            else:
                kept |= _expr_list_vars([expr])
        _walk(node.child, needed | kept, distinct_node, marked, aliases,
              pushable_vars | pushable)
        return

    if kind == KIND_EXTEND:
        extra = set()
        if node.extend_expr is not None:
            extra = _expr_list_vars([node.extend_expr])
        _walk(node.child, needed | extra, distinct_node, marked, aliases, pushable_vars)
        return

    if kind == KIND_GROUP:
        # Aggregates count rows, so collapsing duplicates below is never safe.
        for child in (node.children or []):
            _walk(child, _root_needed(node), None, marked, aliases)
        return

    if kind == KIND_JOIN and len(node.children or []) == 2:
        left, right = node.children[0], node.children[1]
        left_vars = compute_scope(left).all_visible
        right_vars = compute_scope(right).all_visible
        shared = left_vars & right_vars
        right_private = right_vars - left_vars

        if (distinct_node is not None
                and len(shared) == 1
                and not (right_private & (needed - pushable_vars))
                and left.kind != KIND_TABLE
                and right.kind != KIND_TABLE
                and not _contains_values(right)
                and _selective_enough(left, right, aliases)):
            node.hints['semijoin'] = True
            # EXISTS yields one row per outer row, so this DISTINCT no longer
            # removes anything — and as a Unique/HashAggregate it would block
            # the LIMIT from stopping the scan early.
            distinct_node.hints['distinct_redundant'] = True
            marked.append(node)
            logger.debug("semijoin: shared=%s right_private=%s",
                         sorted(shared), sorted(right_private))

        _walk(left, needed | shared, distinct_node, marked, aliases, pushable_vars)
        _walk(right, needed | shared, distinct_node, marked, aliases, pushable_vars)
        return

    for child in (node.children or []):
        sub_needed = needed
        sub_distinct = distinct_node
        if kind in (KIND_LEFT_JOIN, KIND_UNION, KIND_MINUS):
            sub_needed = needed | compute_scope(node).all_visible
            sub_distinct = None
        _walk(child, sub_needed, sub_distinct, marked, aliases, pushable_vars)


def _contains_values(node: Optional[PlanV2], depth: int = 0) -> bool:
    """True if the subtree contains a VALUES table (UNDEF semantics)."""
    if node is None or depth > 12:
        return False
    if node.kind == KIND_TABLE:
        return True
    return any(_contains_values(c, depth + 1) for c in (node.children or []))


def _selective_enough(left, right, aliases) -> bool:
    """Would probing beat the join for this criteria set?

    Compares the probed side's estimated match count against the anchor's
    candidate count. Unknown counts mean no — defaulting to the set-based plan,
    which is merely proportional to the match set rather than catastrophic.
    """
    if aliases is None:
        return False
    matches = _leaf_rows(right, aliases)
    candidates = _leaf_rows(left, aliases)
    if not matches or not candidates:
        return False
    sel = matches / candidates
    ok = sel >= MIN_SELECTIVITY
    logger.debug("semijoin selectivity: %d/%d = %.3f -> %s",
                 matches, candidates, sel, "probe" if ok else "join")
    return ok

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

This pass used to also mark hints['distinct_redundant'] on the DISTINCT above,
reasoning that EXISTS yields at most one row per outer row so the DISTINCT
removed nothing. That was wrong and is removed (issues/046). EXISTS does not
multiply the outer rows, but it does not deduplicate them either, and the outer
side is not one row per entity whenever the same (s,p,o,c) is stored more than
once — which rdf_quad permits, the rows differing by quad_uuid/dataset. On a
production copy 82 subjects carried the anchor quad twice or more and the result
came back with 34,659 rows for 34,423 entities: the right set, the wrong
multiplicity. Set-membership checks cannot see that, which is how it shipped.

The blocking-node problem the elision was meant to solve is real, and is now
solved where it belongs: emit_slice._emit_two_phase deduplicates on the ORDER BY
key itself, so PostgreSQL emits Unique over an already-ordered scan, which
streams rather than blocks.

WHEN THE REWRITE IS VALID, and every clause matters:

1. **Inner join only.** For a LEFT JOIN the right side must contribute
   bindings, not merely existence.
2. **The right side adds no variable anyone needs above.** Otherwise its values
   are required in the output and existence is not enough.
3. **There is a DISTINCT above.** A join multiplies rows when the right side
   matches more than once; EXISTS does not. Without a DISTINCT collapsing them
   anyway the rewrite silently *changes the row count* — the query still runs
   and still looks reasonable. This is what makes the two forms equivalent
   rather than merely similar. Note what it does NOT license: the DISTINCT is
   required for the rewrite to be sound, so it cannot then be removed as
   redundant (issues/046).
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
    KIND_BGP,
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


_QUAD_KINDS = ("quad", "edge", "frame_entity")


def _split_bgp(bgp: PlanV2, key: str) -> Optional[PlanV2]:
    """Partition one BGP into JOIN(anchor, rest) around `key`, or None.

    The anchor is every quad table binding `key` and nothing else; the rest is
    everything remaining. The cross-link constraint between them is dropped —
    the EXISTS correlation replaces it.

    Returns None whenever the shape is not clean, since the whole value here is
    an optimisation and a wrong split is a wrong answer.
    """
    from .ir import TableRef, VarSlot

    slot = bgp.var_slots.get(key)
    if not slot or len(slot.positions or []) < 2:
        return None

    bound: dict = {}
    for var, vs in bgp.var_slots.items():
        for alias, _col in (vs.positions or []):
            bound.setdefault(alias, set()).add(var)

    quad_aliases = {t.alias for t in bgp.tables if t.kind in _QUAD_KINDS}
    anchor_aliases = {a for a in quad_aliases if bound.get(a) == {key}}
    rest_aliases = quad_aliases - anchor_aliases
    if not anchor_aliases or not rest_aliases:
        return None
    # The probe correlates on `key`, so the rest must bind it somewhere.
    if not any(key in bound.get(a, set()) for a in rest_aliases):
        return None

    a_pos = [(al, c) for al, c in slot.positions if al in anchor_aliases]
    r_pos = [(al, c) for al, c in slot.positions if al in rest_aliases]
    if not a_pos or not r_pos:
        return None

    anchor = PlanV2(kind=KIND_BGP)
    rest = PlanV2(kind=KIND_BGP)
    for t in bgp.tables:
        if t.kind in _QUAD_KINDS:
            (anchor if t.alias in anchor_aliases else rest).tables.append(t)

    # The key's term table has to hang off a column the anchor actually has, so
    # repoint its join rather than reusing a join_col naming a rest alias.
    term_tr = next((t for t in bgp.tables if t.alias == slot.term_ref_id), None)
    if term_tr is not None:
        anchor.tables.append(TableRef(
            ref_id=term_tr.ref_id, kind="term", table_name=term_tr.table_name,
            join_col=f"{a_pos[0][0]}.{a_pos[0][1]}", alias=term_tr.alias))

    anchor.var_slots[key] = VarSlot(name=key, positions=a_pos,
                                    term_ref_id=slot.term_ref_id)
    rest.var_slots[key] = VarSlot(name=key, positions=r_pos)
    for var, vs in bgp.var_slots.items():
        if var == key:
            continue
        rest.var_slots[var] = vs
        tt = next((t for t in bgp.tables if t.alias == vs.term_ref_id), None)
        if tt is not None:
            rest.tables.append(tt)

    def _refs(sql: str, aliases_: Set[str]) -> bool:
        # Constraints are SQL strings in the IR, so alias membership is the only
        # test available. Aliases are generator-issued (q0, mv1, …), which makes
        # the prefix match unambiguous.
        return any(f"{a}." in sql for a in aliases_)

    for tag, c in (bgp.tagged_constraints or []):
        if tag in anchor_aliases and not _refs(c, rest_aliases):
            anchor.tagged_constraints.append((tag, c))
        elif tag in rest_aliases and not _refs(c, anchor_aliases):
            rest.tagged_constraints.append((tag, c))
    for c in (bgp.constraints or []):
        in_a, in_r = _refs(c, anchor_aliases), _refs(c, rest_aliases)
        if in_a and not in_r:
            anchor.constraints.append(c)
        elif in_r and not in_a:
            rest.constraints.append(c)

    for (al, col), v in (bgp.leaf_terms or {}).items():
        (anchor if al in anchor_aliases else rest).leaf_terms[(al, col)] = v
    for (al, col), v in (bgp.range_leaves or {}).items():
        (anchor if al in anchor_aliases else rest).range_leaves[(al, col)] = v

    logger.info("semijoin: split BGP on ?%s — anchor %s, probe %s",
                key, sorted(anchor_aliases), sorted(rest_aliases))
    return PlanV2(kind=KIND_JOIN, children=[anchor, rest])


def _split_anchors(node: Optional[PlanV2], distinct_seen: bool,
                   key: Optional[str], undo: List[tuple]) -> None:
    """Find `DISTINCT … BGP` chains and split the BGP into a JOIN.

    Whether a two-child JOIN exists at all turns out to depend on the caller's
    entity type: a generic vitaltype anchor is emitted as its own group and
    collects into a separate BGP, while a specific one folds into the same basic
    graph pattern as the rest of the criteria. The rewrite was therefore skipped
    entirely on the commoner shape — 24.5s versus 4ms on identical criteria
    (issues/045). Nothing about the rewrite requires two BGPs; it only requires
    being able to see the boundary, so put one there.
    """
    if node is None:
        return
    if node.kind in (KIND_DISTINCT, KIND_REDUCED):
        distinct_seen = True
    if node.kind == KIND_PROJECT and node.project_vars is not None:
        key = node.project_vars[0] if len(node.project_vars) == 1 else None

    for i, child in enumerate(list(node.children or [])):
        if child.kind == KIND_BGP and distinct_seen and key:
            split = _split_bgp(child, key)
            if split is not None:
                node.children[i] = split
                undo.append((node, i, child, split))
                continue
        _split_anchors(child, distinct_seen, key, undo)


def mark_semijoins(plan: PlanV2, aliases=None) -> PlanV2:
    """Annotate the JOINs that can be emitted as existence tests."""
    # Split first so the walk has a boundary to work with, then UNDO any split
    # the walk did not go on to mark.
    #
    # A split BGP is only equivalent to the original as a semi-join. The split
    # drops the cross-link constraint tying the two halves together, because
    # the EXISTS correlation replaces it — so if the gate then declines and the
    # node stays an ordinary JOIN, that constraint is simply gone. Measured: a
    # criterion at 1.0% selectivity fell below MIN_SELECTIVITY, kept the split
    # as a plain join, and returned 0 rows instead of 96. Reverting is what
    # makes the split safe to attempt speculatively.
    undo: List[tuple] = []
    _split_anchors(plan, False, None, undo)

    marked: List[PlanV2] = []
    _walk(plan, needed=_root_needed(plan), distinct_node=None, marked=marked,
          aliases=aliases)

    reverted = 0
    for parent, i, original, split in undo:
        if not split.hints.get('semijoin'):
            parent.children[i] = original
            reverted += 1

    if marked:
        logger.info("semijoin: marked %d join(s) (%d split BGP, %d reverted)",
                    len(marked), len(undo) - reverted, reverted)
    else:
        # Declining is worth a line. Every defect found in this pass so far has
        # been silent — a dropped leaf_terms field, an unseen range, an
        # unreachable BGP — and each cost 24s+ per query while looking healthy.
        logger.info("semijoin: no join rewritten (%d BGP split(s) reverted)",
                    reverted)
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
            if v is None:
                # `!=` is pushable too, as a NOT IN over the equality set. Both
                # ends have to recognise exactly the same expressions or the
                # gate marks a join whose filter then fails to push, which is
                # how `gt` became uniquely slow (issues/054) — so this defers to
                # filter_pushdown's own predicate rather than restating it.
                try:
                    from .filter_pushdown import _inequality_var
                    v = _inequality_var(expr)
                except Exception:
                    v = None
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

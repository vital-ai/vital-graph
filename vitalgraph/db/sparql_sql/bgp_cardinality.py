"""Cardinality of a flat BGP join, priced by the generator from statistics it owns.

`issues/293`, stage 2 of its general solution. PostgreSQL estimates a quad
self-join from per-column statistics, and in this store that is wrong in two
recurring ways: it cannot see a predicate's per-object FAN-OUT (a
`hasKGGraphURI` probe by object estimated at ~10 rows, ~1,000 actual), and it
underestimates MID-FREQUENCY `(predicate, object)` pairs (one slot type's 1,159
slots estimated at 3). Every issue in that class (161, 118, 045, 138, 048, 218,
293) is a plan chosen on one of those two numbers.

This prices the same join from what the generator knows exactly:

* a leaf SCANNED with a constant `(predicate, object)`: the pair's count
  (`rdf_stats`, or the on-demand count), as `_leaf_cardinality` has it;
* a leaf PROBED BY OBJECT, the object bound by an earlier leaf: the
  predicate's mean subjects per object, `row_count / object_count`
  (`rdf_pred_stats.object_count`, stage 1);
* a leaf PROBED BY SUBJECT: one value per subject (`row_count / subjects`
  with subjects taken as `row_count`: objects-per-subject is ~1 for nearly
  every predicate measured); with a constant object, CONTAINMENT, the smaller
  of the rows so far and the pair's count (the standard characteristic-set
  assumption; independence measured worse, see `step_factor`);
* BOTH ENDS bound (a cycle): a membership check, `1 / object_count`.

Independence across steps is still assumed, as Postgres assumes it. What
changes is that each step's factor is a measured property of the predicate
rather than a column-wide guess. Whether that is enough is a measurement, not
a claim: `test_scripts_internal/kg_uw_decision_reasons/model_vs_pg.py` compares
both estimates with actual counts, prefix by prefix (q-error).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set, Tuple

#: `step_factor`'s marker for a containment step (min, not a product).
_CONTAIN = object()


@dataclass(frozen=True)
class Leaf:
    alias: str
    pred: Optional[str]          # predicate uuid, when constant
    object_const: bool
    subject_const: bool
    scan_rows: Optional[float]   # rows when this leaf is scanned on its constants
    pred_rows: Optional[float]   # all rows of its predicate
    pred_objects: Optional[float]  # distinct objects of its predicate

    @property
    def restricted(self) -> bool:
        """Its own constants (a constant object, an IN list, a range, an FTS
        pin) keep it below its predicate's total."""
        return self.object_const or (
            self.scan_rows is not None and self.pred_rows is not None
            and self.scan_rows < self.pred_rows)


def leaves_from(plan, aliases, quad_tables, leaf_card: Dict[str, float],
                uuid_of) -> Dict[str, Leaf]:
    """One `Leaf` per quad alias of a flat BGP, from the IR and loaded stats."""
    leaf_terms = getattr(plan, "leaf_terms", None) or {}
    pred_stats = getattr(aliases, "pred_stats", None) or {}
    objects = getattr(aliases, "pred_object_counts", None) or {}
    quad_stats = getattr(aliases, "quad_stats", None) or {}
    extra = getattr(aliases, "extra_quad_stats", None) or {}
    resolved = getattr(aliases, "resolved_constants", None) or {}
    in_lists = _in_lists(getattr(plan, "tagged_constraints", None) or [], resolved)
    out: Dict[str, Leaf] = {}
    for t in quad_tables:
        a = t.alias
        p_term = leaf_terms.get((a, "predicate_uuid"))
        p = uuid_of(p_term) if p_term else None
        rows = pred_stats.get(p) if p else None
        objs = objects.get(p) if p else None
        if objs is None and p and rows:
            # Unmigrated space: mean pair size from rdf_stats, biased high.
            from .slot_group_cte import mean_fanout
            fan = mean_fanout(quad_stats, p)
            objs = (rows / fan) if fan else None
        scan = leaf_card.get(a)
        # An IN on the object (a VALUES pushed into the BGP): every value is a
        # constant pair, priced exactly by rdf_stats. Without this the leaf is
        # its whole predicate (1,150,000 for a state code filtered to two
        # states, 16,486 actual).
        if p and a in in_lists:
            counts = [quad_stats.get((p, o), extra.get((p, o))) for o in in_lists[a]]
            if counts and all(n is not None for n in counts):
                scan = min(scan, sum(counts)) if scan is not None else sum(counts)
        out[a] = Leaf(a, p, (a, "object_uuid") in leaf_terms,
                      (a, "subject_uuid") in leaf_terms, scan, rows, objs)
    return out


def _in_lists(tagged, resolved) -> Dict[str, List[str]]:
    """alias -> object uuids of an `alias.object_uuid IN (__CONST_x__, ...)`."""
    import re
    out: Dict[str, List[str]] = {}
    for owner, sql in tagged:
        m = re.fullmatch(rf"{re.escape(owner)}\.object_uuid IN \(([^)]*)\)", sql.strip())
        if not m:
            continue
        uuids = []
        for tok in (x.strip() for x in m.group(1).split(",")):
            c = re.fullmatch(r"__CONST_(\w+)__", tok)
            u = resolved.get(c.group(1)) if c else None
            if u is None:
                break
            uuids.append(u)
        else:
            out[owner] = uuids
    return out


def _positions(plan) -> Tuple[Dict[Tuple[str, str], str], Dict[str, Set[str]]]:
    var_at: Dict[Tuple[str, str], str] = {}
    holders: Dict[str, Set[str]] = {}
    for var, slot in plan.var_slots.items():
        for pos in slot.positions:
            var_at[pos] = var
            holders.setdefault(var, set()).add(pos[0])
    return var_at, holders


def step_factor(leaf: Leaf, subject_bound: bool, object_bound: bool) -> Optional[float]:
    """Rows this leaf contributes per row of what is already joined."""
    rows, objs = leaf.pred_rows, leaf.pred_objects
    if not subject_bound and not object_bound:
        return leaf.scan_rows                       # a cross product on constants
    if subject_bound and object_bound:
        return (1.0 / objs) if objs else None
    if subject_bound:
        if leaf.restricted:
            # CONTAINMENT, applied by the caller as min(rows so far, pair
            # count): see `estimate_order`. Independence (the pair's share of
            # its predicate) was measured first and is wrong in exactly the
            # cases that matter: frame type and slot type are correlated, so
            # "slots in this frame type that are NAICS slots" is 10%, not the
            # 0.1% NAICS is of all slots (483 actual, 10 independent).
            return None if leaf.scan_rows is None else _CONTAIN
        return 1.0                                  # one value per subject
    # object bound, subject free: the per-object fan-out
    return (rows / objs) if (rows and objs) else None


def estimate_order(plan, leaves: Dict[str, Leaf], order: Sequence[str]) -> List[Optional[float]]:
    """Estimated rows after joining each prefix of `order` (left-deep).

    Tracks DISTINCT VALUES per variable (`ndv`), because containment caps the
    distinct values of the joined variable, not the rows: a decision with six
    reason slots keeps six rows when the decision's type is joined last. A new
    variable's distinct count comes from what introduced it: the rows, for a
    fresh subject; at most the predicate's distinct objects, for an object.

    None from the first step that cannot be priced onward: an unpriced factor
    is reported as unknown, never guessed.
    """
    var_at, holders = _positions(plan)
    placed: Set[str] = set()
    ndv: Dict[str, float] = {}
    out: List[Optional[float]] = []
    est: Optional[float] = None
    for i, a in enumerate(order):
        leaf = leaves[a]
        s_var, o_var = var_at.get((a, "subject_uuid")), var_at.get((a, "object_uuid"))
        s_bound = bool(s_var and (holders.get(s_var, set()) & placed))
        o_bound = bool(o_var and (holders.get(o_var, set()) & placed))

        if i == 0:
            est = leaf.scan_rows
        elif est is not None:
            f = step_factor(leaf, s_bound, o_bound)
            if f is _CONTAIN:
                have = ndv.get(s_var) or est
                est = est * min(1.0, leaf.scan_rows / have) if have else 0.0
                ndv[s_var] = min(have, leaf.scan_rows)
            else:
                est = None if f is None else est * f
        if est is not None:
            if s_var and not s_bound:
                ndv[s_var] = est                       # a fresh subject per row
            if o_var and not o_bound:
                cap = leaf.pred_objects or est
                ndv[o_var] = min(est, cap)
            for v in list(ndv):
                ndv[v] = min(ndv[v], est)
        placed.add(a)
        out.append(est)
    return out


def choose_order(plan, leaves: Dict[str, Leaf],
                 aliases: Sequence[str]) -> Tuple[Optional[List[str]], Optional[float]]:
    """The left-deep order the model prices cheapest, and its cost.

    Cost is the sum of every prefix's estimated rows (C_out): what each step
    carries into the next. For each root the model can price, the order is
    extended greedily by the CONNECTED leaf (sharing a variable) whose step
    leaves the fewest rows; the cheapest root wins. Returns (None, None) when
    no complete order can be priced, so a caller keeps its own order rather
    than acting on a guess.
    """
    _var_at, holders = _positions(plan)
    vars_of: Dict[str, Set[str]] = {}
    for v, hs in holders.items():
        for a in hs:
            vars_of.setdefault(a, set()).add(v)

    def connected(a, placed):
        return any(holders[v] & placed for v in vars_of.get(a, ()))

    best: Tuple[Optional[List[str]], Optional[float]] = (None, None)
    for root in aliases:
        if leaves[root].scan_rows is None:
            continue
        order, cost, placed = [root], leaves[root].scan_rows, {root}
        ok = True
        while len(order) < len(aliases):
            cands = []
            for a in aliases:
                if a in placed or not connected(a, placed):
                    continue
                est = estimate_order(plan, leaves, order + [a])[-1]
                if est is not None:
                    cands.append((est, aliases.index(a), a))
            if not cands:
                ok = False
                break
            est, _, a = min(cands)
            order.append(a)
            placed.add(a)
            cost += est
        if ok and (best[1] is None or cost < best[1]):
            best = (order, cost)
    return best


#: Enforce the model's order only when it predicts at least this gain over the
#: default (`reorder_joins`). The model's error, measured against actual counts
#: on two workloads (`issues/293` stage 2), is 1.4-3.7x geometric mean with
#: non-zero worst cases near 6x; a smaller predicted gain is inside that band,
#: and enforcing it enforces the model's mistakes. Measured: category_page at a
#: predicted 4.5x went 3.1 s -> 9.1 s under an enforced order.
ENFORCE_MIN_GAIN = 10.0

NAME = "model_join_order"


def enforced_order(plan, aliases, quad_tables, leaf_card: Dict[str, float], uuid_of,
                   default_order: Sequence[str]) -> Optional[List[str]]:
    """The model's order, when it beats `default_order` by ENFORCE_MIN_GAIN.

    Records the verdict in `plan_decisions` either way. None keeps the default.
    """
    from .plan_decisions import recorder_for
    rec = recorder_for(aliases)
    aliases_list = [t.alias for t in quad_tables]
    if len(aliases_list) < 2:
        return None
    leaves = leaves_from(plan, aliases, quad_tables, leaf_card, uuid_of)
    order, cost = choose_order(plan, leaves, aliases_list)
    if not order:
        rec.declined(NAME, "the model cannot price a complete order", tables=len(aliases_list))
        return None
    est = estimate_order(plan, leaves, list(default_order))
    if any(e is None for e in est):
        rec.declined(NAME, "the model cannot price the default order", tables=len(aliases_list))
        return None
    default_cost = sum(est)
    gain = default_cost / cost if cost else float("inf")
    detail = dict(tables=len(aliases_list), gain=round(gain, 1),
                  default_root=default_order[0], model_root=order[0],
                  default_cost=round(default_cost), model_cost=round(cost))
    if gain < ENFORCE_MIN_GAIN:
        rec.declined(NAME, "predicted gain within the model's error band", **detail)
        return None
    rec.fired(NAME, "", **detail)
    return order

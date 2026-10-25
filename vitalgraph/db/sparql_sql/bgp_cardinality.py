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

import re
import uuid as _uuid
from dataclasses import dataclass, field
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
    # A DERIVED-TABLE leaf (edge, frame_slot): distinct values per column. A
    # step costs rows x prod(1 / ndv) over the columns already bound
    # (independence), and a fresh column carries at most its ndv. Quad leaves
    # leave this empty and keep the subject/object rules.
    cols: Dict[str, float] = field(default_factory=dict, compare=False, hash=False)

    @property
    def restricted(self) -> bool:
        """Its own constants (a constant object, an IN list, a range, an FTS
        pin) keep it below its predicate's total."""
        return self.object_const or (
            self.scan_rows is not None and self.pred_rows is not None
            and self.scan_rows < self.pred_rows)


_HK = "http://vital.ai/ontology/haley-ai-kg#"
_VC = "http://vital.ai/ontology/vital-core#"


def _iri_uuid(iri: str) -> str:
    """The term uuid of an IRI, as the term table keys it."""
    return str(_uuid.uuid5(_VITALGRAPH_NS(), f"{iri}\x00U"))


def _VITALGRAPH_NS():
    from .fast_slot_sort import _VITALGRAPH_NS as ns
    return ns


def _const_of(tagged, alias: str, col: str, resolved) -> Optional[str]:
    """uuid of `alias.col = __CONST_x__` in the tagged constraints, if resolved."""
    pat = re.compile(rf"{re.escape(alias)}\.{col} = __CONST_(\w+)__")
    for owner, sql in tagged:
        m = pat.fullmatch(sql.strip())
        if m:
            return resolved.get(m.group(1))
    return None


def _objects(p, rows, objects, quad_stats) -> Optional[float]:
    """Distinct objects of predicate `p`: `rdf_pred_stats.object_count` where
    the space has it, else rows over the mean pair size from rdf_stats (biased
    high, as `leaves_from` does for quad leaves)."""
    n = objects.get(p)
    if n is None and rows:
        from .slot_group_cte import mean_fanout
        fan = mean_fanout(quad_stats, p)
        n = (rows / fan) if fan else None
    return n


def _derived_leaf(t, tagged, pred_stats, objects, quad_stats, extra, resolved) -> Optional[Leaf]:
    """A Leaf for an edge or frame_slot table, priced from the quad statistics
    of the predicates it was derived from (`issues/293` stage 6). None when a
    number is missing: unpriced, never guessed."""
    a = t.alias
    if t.kind == "edge":
        src, dst = _iri_uuid(_VC + "hasEdgeSource"), _iri_uuid(_VC + "hasEdgeDestination")
        rows = pred_stats.get(src)
        n_src, n_dst = _objects(src, rows, objects, quad_stats), _objects(dst, rows, objects, quad_stats)
        if not (rows and n_src and n_dst):
            return None
        return Leaf(a, None, False, False, float(rows), float(rows), None,
                    cols={"edge_uuid": float(rows), "source_node_uuid": float(n_src),
                          "dest_node_uuid": float(n_dst)})
    if t.kind == "frame_slot":
        role = _const_of(tagged, a, "role_uuid", resolved)
        st = _iri_uuid(_HK + "hasKGSlotType")
        if role is None:
            return None
        rows = quad_stats.get((st, role), extra.get((st, role)))
        if not rows:
            return None
        # The frame's type, absorbed into the table by the rewrite
        # (`fsmvN.frame_type_uuid = <C>`): containment, at most the frames of
        # that type.
        ftype = _const_of(tagged, a, "frame_type_uuid", resolved)
        if ftype is not None:
            vt = _iri_uuid(_VC + "vitaltype")
            typed = quad_stats.get((vt, ftype), extra.get((vt, ftype)))
            if typed is None:
                return None
            rows = min(rows, typed)
        ev = _iri_uuid(_HK + "hasEntitySlotValue")
        ents = _objects(ev, pred_stats.get(ev), objects, quad_stats)
        # One slot of a role per frame; entities at most the predicate's.
        cols = {"slot_uuid": float(rows), "frame_uuid": float(rows),
                "entity_uuid": float(min(rows, ents)) if ents else float(rows)}
        return Leaf(a, None, False, False, float(rows), float(rows), None, cols=cols)
    return None


def leaves_from(plan, aliases, quad_tables, leaf_card: Dict[str, float],
                uuid_of) -> Dict[str, Leaf]:
    """One `Leaf` per alias of a flat BGP, from the IR and loaded stats. Edge
    and frame_slot tables get a column leaf (`_derived_leaf`) or are left out
    (the caller then cannot price an order through them)."""
    leaf_terms = getattr(plan, "leaf_terms", None) or {}
    pred_stats = getattr(aliases, "pred_stats", None) or {}
    objects = getattr(aliases, "pred_object_counts", None) or {}
    quad_stats = getattr(aliases, "quad_stats", None) or {}
    extra = getattr(aliases, "extra_quad_stats", None) or {}
    resolved = getattr(aliases, "resolved_constants", None) or {}
    in_lists = _in_lists(getattr(plan, "tagged_constraints", None) or [], resolved)
    out: Dict[str, Leaf] = {}
    tagged = getattr(plan, "tagged_constraints", None) or []
    for t in quad_tables:
        a = t.alias
        if t.kind in ("edge", "frame_slot"):
            leaf = _derived_leaf(t, tagged, pred_stats, objects, quad_stats, extra, resolved)
            if leaf is not None:
                out[a] = leaf
            continue
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


def estimate_order(plan, leaves: Dict[str, Leaf], order: Sequence[str],
                   bound_vars: Sequence[str] = ()) -> List[Optional[float]]:
    """Estimated rows after joining each prefix of `order` (left-deep).

    Tracks DISTINCT VALUES per variable (`ndv`), because containment caps the
    distinct values of the joined variable, not the rows: a decision with six
    reason slots keeps six rows when the decision's type is joined last. A new
    variable's distinct count comes from what introduced it: the rows, for a
    fresh subject; at most the predicate's distinct objects, for an object.

    `bound_vars`: variables bound BEFORE the join, one value each, as an
    EXISTS probe sees its correlated key. The estimate then starts at one row,
    and is the probe's work per outer row.

    None from the first step that cannot be priced onward: an unpriced factor
    is reported as unknown, never guessed.
    """
    var_at, holders = _positions(plan)
    placed: Set[str] = set()
    seeded = set(bound_vars)
    ndv: Dict[str, float] = {v: 1.0 for v in seeded}
    out: List[Optional[float]] = []
    est: Optional[float] = 1.0 if seeded else None
    for i, a in enumerate(order):
        leaf = leaves[a]
        if leaf.cols:
            est = _column_step(leaf, a, i, est, seeded, var_at, holders, placed, ndv)
            placed.add(a)
            out.append(est)
            continue
        s_var, o_var = var_at.get((a, "subject_uuid")), var_at.get((a, "object_uuid"))
        s_bound = bool(s_var and (s_var in seeded or holders.get(s_var, set()) & placed))
        o_bound = bool(o_var and (o_var in seeded or holders.get(o_var, set()) & placed))

        if i == 0 and not seeded:
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


def _column_step(leaf: Leaf, a: str, i: int, est, seeded, var_at, holders, placed,
                 ndv) -> Optional[float]:
    """One step of `estimate_order` for a column leaf (edge, frame_slot)."""
    cols = [(c, var_at.get((a, c))) for c in leaf.cols]
    bound = [c for c, v in cols if v and (v in seeded or holders.get(v, set()) & placed)]
    if i == 0 and not seeded:
        est = leaf.scan_rows
    elif est is not None:
        if not bound:
            est = None if leaf.scan_rows is None else est * leaf.scan_rows
        else:
            f = leaf.scan_rows
            for c in bound:
                f = f / leaf.cols[c] if leaf.cols[c] else None
                if f is None:
                    break
            est = None if f is None else est * f
    if est is not None:
        for c, v in cols:
            if v and c not in bound:
                ndv[v] = min(est, leaf.cols[c])
        for v in list(ndv):
            ndv[v] = min(ndv[v], est)
    return est


def choose_order(plan, leaves: Dict[str, Leaf], aliases: Sequence[str],
                 bound_vars: Sequence[str] = ()) -> Tuple[Optional[List[str]], Optional[float]]:
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

    seeded = set(bound_vars)

    def connected(a, placed):
        return any((v in seeded) or (holders[v] & placed) for v in vars_of.get(a, ()))

    best: Tuple[Optional[List[str]], Optional[float]] = (None, None)
    for root in aliases:
        if seeded:
            if not connected(root, set()):
                continue
            first = estimate_order(plan, leaves, [root], bound_vars)[-1]
        else:
            first = leaves[root].scan_rows
        if first is None:
            continue
        order, cost, placed = [root], first, {root}
        ok = True
        while len(order) < len(aliases):
            cands = []
            for a in aliases:
                if a in placed or not connected(a, placed):
                    continue
                est = estimate_order(plan, leaves, order + [a], bound_vars)[-1]
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


def _greedy_from(plan, leaves: Dict[str, Leaf], root: str, aliases: Sequence[str]):
    """`choose_order`'s greedy extension from a FIXED root: (order, rows after
    the last step), or (None, None) when a step cannot be priced or nothing
    connects."""
    _var_at, holders = _positions(plan)
    vars_of: Dict[str, Set[str]] = {}
    for v, hs in holders.items():
        for a in hs:
            vars_of.setdefault(a, set()).add(v)
    if leaves[root].scan_rows is None:
        return None, None
    order, placed, last = [root], {root}, leaves[root].scan_rows
    while len(order) < len(aliases):
        cands = []
        for a in aliases:
            if a in placed or not any(holders[v] & placed for v in vars_of.get(a, ())):
                continue
            est = estimate_order(plan, leaves, order + [a])[-1]
            if est is not None:
                cands.append((est, list(aliases).index(a), a))
        if not cands:
            return None, None
        last, _, a = min(cands)
        order.append(a)
        placed.add(a)
    return order, last


class _Slots:
    """A plan stand-in carrying only `var_slots`, which is all `estimate_order`
    and `choose_order` read of the plan."""
    def __init__(self, var_slots):
        self.var_slots = var_slots


class _Positions:
    def __init__(self, positions):
        self.positions = positions


def unit_model(plan, leaves: Dict[str, Leaf],
               units: Sequence[Tuple[str, Set[str], str]]):
    """The BGP as the model sees it after slot-group CTEs (`slot_group_cte`,
    `issues/310`): each unit `(name, member aliases, pin)` is ONE column leaf,
    the CTE, whose rows are its members joined from the pin and whose columns
    are the CTE's `alias__col` columns, the BGP's variable positions remapped
    onto them (one column per variable). Returns (plan stand-in, leaves) for
    `choose_order` / `estimate_order` over the remainder, or None when a unit
    cannot be priced."""
    owner = {a: name for name, members, _pin in units for a in members}
    unit_rows: Dict[str, float] = {}
    for name, members, pin in units:
        _order, rows = _greedy_from(plan, leaves, pin, sorted(members))
        if rows is None:
            return None
        unit_rows[name] = rows
    var_slots = {}
    cols: Dict[str, Dict[str, float]] = {name: {} for name in unit_rows}
    for var, slot in plan.var_slots.items():
        positions, seen_units = [], set()
        for a, col in slot.positions:
            name = owner.get(a)
            if name is None:
                positions.append((a, col))
                continue
            if name in seen_units:
                continue                     # one column per variable per unit
            seen_units.add(name)
            c = f"{a}__{col}"
            positions.append((name, c))
            rows = unit_rows[name]
            objs = leaves[a].pred_objects if a in leaves else None
            cols[name][c] = rows if col == "subject_uuid" or not objs else min(rows, objs)
        var_slots[var] = _Positions(positions)
    out = {a: l for a, l in leaves.items() if a not in owner}
    for name, rows in unit_rows.items():
        out[name] = Leaf(name, None, False, False, rows, rows, None, cols=cols[name])
    return _Slots(var_slots), out


REMAINDER_NAME = "slot_group_remainder_order"


#: Enforce the model's order only when it predicts at least this gain over the
#: default (`reorder_joins`). The model's error, measured against actual counts
#: on two workloads (`issues/293` stage 2), is 1.4-3.7x geometric mean with
#: non-zero worst cases near 6x; a smaller predicted gain is inside that band,
#: and enforcing it enforces the model's mistakes. Measured: category_page at a
#: predicted 4.5x went 3.1 s -> 9.1 s under an enforced order.
ENFORCE_MIN_GAIN = 10.0

NAME = "model_join_order"

#: Table kinds the model prices: quads, and the edge and frame_slot tables
#: priced from the quad statistics of the predicates they replace.
PRICED_KINDS = ("quad", "edge", "frame_slot")


def enforced_order(plan, aliases, quad_tables, leaf_card: Dict[str, float], uuid_of,
                   default_order: Sequence[str],
                   bound_vars: Sequence[str] = ()) -> Optional[List[str]]:
    """The model's order, when it beats `default_order` by ENFORCE_MIN_GAIN.

    `bound_vars`: variables bound per outer row, as an EXISTS body's correlated
    variables are. Both orders are then priced as the work of one probe.

    Records the verdict in `plan_decisions` either way. None keeps the default.
    """
    from .plan_decisions import recorder_for
    rec = recorder_for(aliases)
    aliases_list = [t.alias for t in quad_tables]
    if len(aliases_list) < 2:
        return None
    leaves = leaves_from(plan, aliases, quad_tables, leaf_card, uuid_of)
    if any(a not in leaves for a in aliases_list):
        rec.declined(NAME, "a leaf has no statistics (edge or frame_slot without object_count)",
                     tables=len(aliases_list))
        return None
    order, cost = choose_order(plan, leaves, aliases_list, bound_vars)
    if not order:
        rec.declined(NAME, "the model cannot price a complete order", tables=len(aliases_list))
        return None
    est = estimate_order(plan, leaves, list(default_order), bound_vars)
    if any(e is None for e in est):
        rec.declined(NAME, "the model cannot price the default order", tables=len(aliases_list))
        return None
    default_cost = sum(est)
    gain = default_cost / cost if cost else float("inf")
    detail = dict(tables=len(aliases_list), gain=round(gain, 1), bound=sorted(bound_vars),
                  default_root=default_order[0], model_root=order[0],
                  default_cost=round(default_cost), model_cost=round(cost))
    if gain < ENFORCE_MIN_GAIN:
        rec.declined(NAME, "predicted gain within the model's error band", **detail)
        return None
    rec.fired(NAME, "", **detail)
    return order


SEMIJOIN_NAME = "semijoin_model_gate"


def semijoin_is_cheaper(original, split, key: str, aliases) -> bool:
    """Whether the semi-join split of `original` is worth keeping (`issues/293` stage 6).

    The split anchors on the patterns that bind only `key`, which for an entity
    query is always the type triple (`issues/161`: "selectivity never enters
    the choice"), and probes the rest once per anchor row. Priced here:

        split   = anchor rows + anchor rows x (the probe's work per row)
        merged  = the merged BGP's cost in its cheapest order

    The split is reverted only when the merged form is predicted at least
    ENFORCE_MIN_GAIN cheaper, above the model's measured error. Anything the
    model cannot price keeps the split: it exists because it wins elsewhere
    (`issues/045`, 24 s -> 2 ms). Measured on KGQuery graph mode, the split's
    100,000 probes against the merged join: 55x, 15x and 1.5x slower.
    """
    from types import SimpleNamespace
    from .emit_bgp import _leaf_cardinality, _widen_term
    from .plan_decisions import recorder_for
    rec = recorder_for(aliases)
    tables = [t for t in original.tables if t.kind not in ("term",)]
    if any(t.kind not in PRICED_KINDS for t in tables):
        rec.declined(SEMIJOIN_NAME, "the BGP has tables the model does not price")
        return True
    consts = getattr(aliases, "constants", None) or {}
    resolved = getattr(aliases, "resolved_constants", None) or {}

    def uuid_of(term):
        col = consts.get(_widen_term(term))
        return resolved.get(col) if col else None

    card = _leaf_cardinality(original, SimpleNamespace(aliases=aliases))
    leaves = leaves_from(original, aliases, tables, card, uuid_of)
    if any(t.alias not in leaves for t in tables):
        rec.declined(SEMIJOIN_NAME, "a leaf has no statistics (edge or frame_slot without object_count)")
        return True
    anchor = [t.alias for t in split.children[0].tables if t.kind in PRICED_KINDS]
    rest = [t.alias for t in split.children[1].tables if t.kind in PRICED_KINDS]
    a_order, _ = choose_order(original, leaves, anchor)
    a_rows = estimate_order(original, leaves, a_order)[-1] if a_order else None
    _, probe = choose_order(original, leaves, rest, bound_vars=[key])
    _, merged = choose_order(original, leaves, [t.alias for t in tables])
    if a_rows is None or probe is None or merged is None:
        rec.declined(SEMIJOIN_NAME, "the model cannot price both forms",
                     anchor_rows=a_rows, probe=probe, merged=merged)
        return True
    split_cost = a_rows + a_rows * probe
    gain = split_cost / merged if merged else float("inf")
    detail = dict(anchor_rows=round(a_rows), probe_per_row=round(probe, 2),
                  split_cost=round(split_cost), merged_cost=round(merged), gain=round(gain, 1))
    if gain < ENFORCE_MIN_GAIN:
        rec.declined(SEMIJOIN_NAME, "merged join not predicted clearly cheaper; split kept", **detail)
        return True
    rec.fired(SEMIJOIN_NAME, "split reverted: merged join predicted cheaper", **detail)
    return False

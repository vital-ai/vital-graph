"""The annotated query tree: the planner's view of a query (planning_planner/09).

Built from the generator's `PlanV2` after its rewrites and statistics loading,
at the point emit starts. Every node carries the numbers the statistics tables
give for it, with the rule each number came from, so a plan chosen from the
tree can be traced back to the statistic that drove it, and a wrong estimate to
the rule that made it.

    Leaf     one quad / edge / frame_slot pattern
    Unit     the leaves sharing one subject (a star), driven from its anchor
    Link     a leaf whose object is another unit's subject (`?o graph ?d`)
    Block    a BGP's units, or a relation/modifier node above them

A number the statistics cannot give is None, never a default.

This module only BUILDS and ANNOTATES. Choosing a plan from it (cost, search)
and rendering one are separate steps. Nothing here runs with the planner
switch off.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .ir import (KIND_BGP, KIND_DISTINCT, KIND_FILTER, KIND_JOIN,
                 KIND_LEFT_JOIN, KIND_ORDER, KIND_PROJECT, KIND_SLICE, PlanV2)

DERIVED_KINDS = ("edge", "frame_slot")
LEAF_KINDS = ("quad",) + DERIVED_KINDS


@dataclass
class Est:
    """An estimated row count and the rule that produced it."""
    rows: Optional[float]
    rule: str

    def __str__(self) -> str:
        return f"{_n(self.rows)} [{self.rule}]"


def _n(v: Optional[float]) -> str:
    return "?" if v is None else f"{v:,.0f}"


@dataclass
class Leaf:
    alias: str
    kind: str                       # quad | edge | frame_slot
    pred: Optional[str]             # predicate IRI, when constant
    s_var: Optional[str]
    o_var: Optional[str]
    s_const: Optional[str]          # constant subject term, if any
    o_const: Optional[str]          # constant object term, if any
    scan: Est                       # rows when scanned on its own constants
    pred_rows: Optional[float]      # rows of its predicate
    pred_objects: Optional[float]   # distinct objects of its predicate
    pred_uuid: Optional[str] = None
    # Expected rows when probed BY OBJECT with a value drawn from the data
    # itself (a correlated or joined variable): the size-biased mean of the
    # predicate's pair counts, sum(c^2)/sum(c) over `rdf_stats`. Heavy values
    # are probed more often than light ones, so the plain mean (rows/objects)
    # understates it. None when the predicate has no stored pairs.
    probe_fan: Optional[float] = None
    o_uuid: Optional[str] = None    # uuid of the constant object, when there is one
    # Every variable column other than the key, as (column, variable). A quad
    # leaf has at most one (object_uuid); a derived-table row has several: an
    # edge row (edge_uuid key) carries source_node_uuid and dest_node_uuid, a
    # frame_slot row (slot_uuid key) frame_uuid and entity_uuid.
    o_vars: List[Tuple[str, str]] = field(default_factory=list)
    # Derived-table leaves: rows per value when probed by a column, and distinct
    # values per column (PostgreSQL's own statistics on the table, `derived_stats`).
    col_fan: Dict[str, float] = field(default_factory=dict)
    col_ndv: Dict[str, float] = field(default_factory=dict)

    @property
    def constant(self) -> bool:
        """Restricted by its own constants (object, IN, range, FTS, a derived
        row's constant columns), so it can anchor a unit without probing anything."""
        return self.o_const is not None or self.scan.rule in (
            "range", "fts", "in", "values", "values_bound", "derived_count")

    def fan(self, col: Optional[str]) -> Optional[float]:
        """Rows one index probe of this leaf reads, by column `col`."""
        if self.kind == "quad":
            if self.probe_fan:
                return self.probe_fan
            return (self.pred_rows / self.pred_objects) if self.pred_rows and self.pred_objects else None
        return self.col_fan.get(col) if col else None

    def ndv(self, col: Optional[str]) -> Optional[float]:
        """Distinct values of the variable at `col` (quad: the predicate's objects)."""
        return self.pred_objects if self.kind == "quad" else self.col_ndv.get(col)

    def short(self) -> str:
        p = (self.pred or "?").rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        o = self.o_const.rsplit(":", 1)[-1] if self.o_const else (f"?{self.o_var}" if self.o_var else "")
        return f"{self.alias} {p} {o}".strip()


@dataclass
class Link:
    """`leaf` joins its unit to `target` (another unit's subject variable)."""
    leaf: Leaf
    target_var: str
    by_subject: Est                 # rows per source row, probed by subject
    by_object: Est                  # rows per target row, probed by object (the fan-out)


@dataclass
class Unit:
    subject: str                    # "?var" or a constant
    leaves: List[Leaf]
    anchor: Optional[Leaf]
    rows: Est
    probes: List[Leaf] = field(default_factory=list)   # 1:1 subject probes after the anchor
    links: List[Link] = field(default_factory=list)


@dataclass
class Block:
    kind: str                       # bgp | join | left_join | order | slice | project | ...
    rows: Est
    units: List[Unit] = field(default_factory=list)
    children: List["Block"] = field(default_factory=list)
    joins: List[Tuple[str, str, Est]] = field(default_factory=list)  # (unit, unit, rows)
    note: str = ""
    order: Optional[list] = None    # ORDER BY conditions [(expr, direction)]
    project: Optional[List[str]] = None  # projected variables


class _Stats:
    """The statistics the generator loaded, read the way the model reads them."""

    def __init__(self, plan, ctx):
        a = ctx.aliases
        self.consts = getattr(a, "constants", None) or {}
        self.resolved = getattr(a, "resolved_constants", None) or {}
        self.pred_rows = getattr(a, "pred_stats", None) or {}
        self.pred_objects = getattr(a, "pred_object_counts", None) or {}
        self.quad_stats = getattr(a, "quad_stats", None) or {}
        self._sb: Dict[str, Optional[float]] = {}

    def size_biased_fan(self, p_uuid: Optional[str]) -> Optional[float]:
        if not p_uuid:
            return None
        if p_uuid not in self._sb:
            s1 = s2 = 0.0
            for (p, _o), c in self.quad_stats.items():
                if p == p_uuid:
                    s1 += c
                    s2 += c * c
            self._sb[p_uuid] = (s2 / s1) if s1 else None
        return self._sb[p_uuid]

    def uuid_of(self, term) -> Optional[str]:
        from .emit_bgp import _widen_term
        col = self.consts.get(_widen_term(term))
        return self.resolved.get(col) if col else None


#: The column that identifies a derived-table row's subject (its unit), in order
#: of preference; every other variable column is an object (`Leaf.o_vars`).
DERIVED_KEYS = {"edge": ("edge_uuid", "source_node_uuid"),
                "frame_slot": ("slot_uuid", "frame_uuid")}

#: PostgreSQL's statistics for derived tables and capped counts of their
#: constant-filtered leaves, loaded by `qcard.load_derived` before analysis:
#:   DERIVED_STATS[table] = {"rows": reltuples, "ndv": {column: distinct}}
#:   DERIVED_COUNTS[(table, filters)] = rows (capped; >= the cap reads as the cap)
DERIVED_STATS: Dict[str, dict] = {}
DERIVED_COUNTS: Dict[Tuple[str, Tuple[str, ...]], float] = {}


def derived_filters(alias: str, filters: List[str]) -> Tuple[str, ...]:
    """A derived leaf's filters with the alias stripped: its count's cache key."""
    return tuple(sorted(f.replace(f"{alias}.", "") for f in filters))


def _leaves(plan: PlanV2, ctx, st: _Stats) -> List[Leaf]:
    from .emit_bgp import _leaf_cardinality
    card = _leaf_cardinality(plan, ctx)
    var_at: Dict[Tuple[str, str], str] = {}
    by_alias: Dict[str, List[Tuple[str, str]]] = {}
    for var, slot in plan.var_slots.items():
        for pos in slot.positions:
            var_at[pos] = var
            by_alias.setdefault(pos[0], []).append((pos[1], var))
    range_aliases = {a for (a, _c) in (getattr(plan, "range_leaves", None) or {})}
    fts = getattr(plan, "fts_leaf_rows", None) or {}
    out = []
    # a leaf's OWN filters: constraints that reference no other alias (as qplan._Pos)
    filters_by: Dict[str, List[str]] = {}
    for owner, sql in getattr(plan, "tagged_constraints", None) or []:
        if set(re.findall(r"\b([a-z][a-z0-9_]*[0-9])\.", sql)) <= {owner}:
            filters_by.setdefault(owner, []).append(sql)
    for t in plan.tables:
        if t.kind not in LEAF_KINDS:
            continue
        a = t.alias
        if t.kind in DERIVED_KINDS:
            out.append(_derived_leaf(t, by_alias.get(a, []), filters_by.get(a, []), ctx))
            continue
        terms = plan.leaf_terms
        p_term = terms.get((a, "predicate_uuid"))
        o_term = terms.get((a, "object_uuid"))
        s_term = terms.get((a, "subject_uuid"))
        p_uuid = st.uuid_of(p_term) if p_term else None
        rule = ("range" if a in range_aliases else "fts" if a in fts
                else "pair" if o_term else "pred")
        out.append(Leaf(
            alias=a, kind=t.kind,
            pred=str(p_term[0]) if p_term else None,
            s_var=var_at.get((a, "subject_uuid")), o_var=var_at.get((a, "object_uuid")),
            s_const=str(s_term[0]) if s_term else None, o_const=str(o_term[0]) if o_term else None,
            scan=Est(card.get(a), rule if a in card else "unpriced"),
            pred_rows=st.pred_rows.get(p_uuid) if p_uuid else None,
            pred_objects=st.pred_objects.get(p_uuid) if p_uuid else None,
            pred_uuid=p_uuid,
            probe_fan=st.size_biased_fan(p_uuid),
            o_uuid=st.uuid_of(o_term) if o_term else None,
            o_vars=[("object_uuid", var_at[(a, "object_uuid")])] if (a, "object_uuid") in var_at else []))
    return out


def _derived_leaf(t, cols: List[Tuple[str, str]], filters: List[str], ctx) -> Leaf:
    """An edge or frame_slot row as a leaf: keyed by its identifying column,
    every other variable column an object, priced from PostgreSQL's statistics
    on the table and, with constant filters, a capped count (`DERIVED_*`)."""
    a = t.alias
    colvar = dict(cols)
    key = next((c for c in DERIVED_KEYS.get(t.kind, ()) if c in colvar), None)
    st = DERIVED_STATS.get(t.table_name) or {}
    rows = st.get("rows")
    ndv = {c: float(n) for c, n in (st.get("ndv") or {}).items()}
    # constant filters beyond the graph: role, frame type, edge type ...
    const = [f for f in filters if not re.match(rf"\s*{re.escape(a)}\.context_uuid\s*=", f)
             and re.match(rf"\s*{re.escape(a)}\.\w+\s*=\s*\S+\s*$", f)]
    scan = Est(rows, "derived" if rows is not None else "unpriced")
    if const:
        from .generator import substitute_constants
        n = DERIVED_COUNTS.get((t.table_name, derived_filters(a, [substitute_constants(f, ctx.aliases) for f in filters])))
        if n is not None:
            scan = Est(float(n), "derived_count")
    fan = {c: (rows / max(ndv[c], 1.0)) for c in ndv} if rows else {}
    return Leaf(alias=a, kind=t.kind, pred=None,
                s_var=colvar.get(key) if key else None, o_var=None,
                s_const=None, o_const=None, scan=scan,
                pred_rows=rows, pred_objects=None,
                o_vars=[(c, v) for c, v in cols if c != key],
                col_fan=fan, col_ndv=ndv)


def _unit(subject: str, leaves: List[Leaf]) -> Unit:
    """Anchor on the most selective constant leaf; the rest are subject probes.
    Rows: the anchor's count, contained by every other constant leaf (each
    narrows the same subjects); subject probes are one row per subject (the
    single-valued assumption, 297's open question for multi-valued slots)."""
    consts = [l for l in leaves if l.constant and l.scan.rows is not None]
    if consts:
        anchor = min(consts, key=lambda l: l.scan.rows)
        rows = Est(anchor.scan.rows, anchor.scan.rule if len(consts) == 1 else "containment")
    else:
        priced = [l for l in leaves if l.scan.rows is not None]
        anchor = min(priced, key=lambda l: l.scan.rows) if priced else None
        rows = Est(anchor.scan.rows if anchor else None, "pred" if anchor else "unpriced")
    probes = [l for l in leaves if l is not anchor]
    return Unit(subject=subject, leaves=leaves, anchor=anchor, rows=rows, probes=probes)


def _link(leaf: Leaf, target: str) -> Link:
    fan = (leaf.pred_rows / leaf.pred_objects) if leaf.pred_rows and leaf.pred_objects else None
    return Link(leaf=leaf, target_var=target, by_subject=Est(1.0, "1 per subject"),
                by_object=Est(fan, "pred_mean" if fan else "unpriced"))


def _containment(a: Est, b: Est) -> Est:
    """Rows of joining two units on a link: each source row links one target,
    and each target has at most one source of this kind (one slot of a type per
    entity), so at most the smaller side."""
    if a.rows is None or b.rows is None:
        return Est(None, "unpriced")
    return Est(min(a.rows, b.rows), "containment")


def _bgp(plan: PlanV2, ctx, st: _Stats, outer_units: Dict[str, Unit]) -> Block:
    leaves = _leaves(plan, ctx, st)
    by_subject: Dict[str, List[Leaf]] = {}
    for l in leaves:
        key = f"?{l.s_var}" if l.s_var else (l.s_const or l.alias)
        by_subject.setdefault(key, []).append(l)
    units = [_unit(s, ls) for s, ls in by_subject.items()]
    local = {u.subject[1:]: u for u in units if u.subject.startswith("?")}
    scope = {**outer_units, **local}
    # A link: a leaf whose object variable is another unit's subject.
    for u in units:
        for l in u.leaves:
            if l.o_var and l.o_var in scope and scope[l.o_var] is not u:
                u.links.append(_link(l, l.o_var))
    # Block rows: fold the local units along their links (a tree for star
    # queries); units linked only to an OUTER unit are joined to it by the
    # enclosing relation, not here.
    blk = Block(kind="bgp", rows=Est(None, "unpriced"), units=units)
    if not units:
        return blk
    rows = None
    for u in units:
        local_links = [k for k in u.links if k.target_var in local]
        for k in local_links:
            e = _containment(u.rows, local[k.target_var].rows)
            blk.joins.append((u.subject, f"?{k.target_var}", e))
    if blk.joins:
        rows = min((e for *_x, e in blk.joins), key=lambda e: e.rows if e.rows is not None else float("inf"))
        blk.rows = Est(rows.rows, "containment")
    else:
        blk.rows = units[0].rows if len(units) == 1 else Est(None, "unpriced (disconnected units)")
    return blk


def _units_in(b: Block) -> Dict[str, Unit]:
    out = {}
    for u in b.units:
        if u.subject.startswith("?"):
            out[u.subject[1:]] = u
    for c in b.children:
        out.update(_units_in(c))
    return out


def build(plan: PlanV2, ctx, _outer: Optional[Dict[str, Unit]] = None) -> Block:
    """The annotated tree for `plan`."""
    st = _Stats(plan, ctx)
    outer = _outer or {}
    k = plan.kind
    if k == KIND_BGP:
        return _bgp(plan, ctx, st, outer)
    if k in (KIND_JOIN, KIND_LEFT_JOIN):
        left = build(plan.children[0], ctx, outer)
        right = build(plan.children[1], ctx, {**outer, **_units_in(left)})
        if k == KIND_LEFT_JOIN:
            rows = Est(left.rows.rows, "left outer (inner at most one per key)")
        else:
            rows = _containment(left.rows, right.rows)
        return Block(kind=k, rows=rows, children=[left, right])
    if k in (KIND_ORDER, KIND_PROJECT, KIND_DISTINCT, KIND_FILTER):
        child = build(plan.children[0], ctx, outer)
        note = ""
        if k == KIND_ORDER:
            note = "sort keys: " + ", ".join(f"{e} {d}" for e, d in (plan.order_conditions or []))
        rows = child.rows if k != KIND_FILTER else Est(child.rows.rows, "filter (unpriced selectivity, upper bound)")
        return Block(kind=k, rows=rows, children=[child], note=note,
                     order=list(plan.order_conditions or []) if k == KIND_ORDER else None,
                     project=list(plan.project_vars or []) if k == KIND_PROJECT else None)
    if k == KIND_SLICE:
        child = build(plan.children[0], ctx, outer)
        lim = plan.limit if plan.limit >= 0 else None
        r = child.rows.rows
        rows = Est(min(r, lim) if (r is not None and lim is not None) else r, "limit")
        return Block(kind=k, rows=rows, children=[child], note=f"limit {plan.limit} offset {plan.offset}")
    children = [build(c, ctx, outer) for c in plan.children]
    return Block(kind=k, rows=Est(None, f"unpriced ({k})"), children=children)


def render(b: Block, depth: int = 0) -> str:
    """The tree as text, every number with its rule."""
    ind = "  " * depth
    lines = [f"{ind}{b.kind}  rows {b.rows}" + (f"   {b.note}" if b.note else "")]
    for u in b.units:
        lines.append(f"{ind}  unit {u.subject}  rows {u.rows}  anchor {u.anchor.short() if u.anchor else '-'}"
                     f" ({u.anchor.scan if u.anchor else '-'})")
        for p in u.probes:
            lines.append(f"{ind}      probe {p.short()}")
        for k in u.links:
            lines.append(f"{ind}      link {k.leaf.alias} -> ?{k.target_var}: by subject {k.by_subject},"
                         f" by object {k.by_object} per target")
    for a, t, e in b.joins:
        lines.append(f"{ind}  join {a} ~ {t}: {e}")
    for c in b.children:
        lines.append(render(c, depth + 1))
    return "\n".join(lines)

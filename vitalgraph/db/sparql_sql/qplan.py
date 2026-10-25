"""The general planner over the annotated query tree (planning_planner/09).

    analyze(plan, ctx)   PlanV2 -> Query: conjunctive REGIONS of units with
                         their edges, OPTIONAL and NOT EXISTS attachments,
                         and the modifiers above (GROUP BY, HAVING, DISTINCT,
                         ORDER BY, LIMIT, PROJECT)
    search(region)       bottom-up DP over connected subsets of units: for
                         each join, a hash join of two independently built
                         sides, or an index probe from one side into a unit
    render(query, ...)   the chosen tree as SQL (the written JOIN nesting is
                         the plan) + vg:plan advice, in the executor's column
                         contract

Units come from `qtree` (a star per subject, anchored on its most selective
constant). Two kinds of edge join units:

    link     a leaf of u has object ?x, and ?x is v's subject  (?o graph ?d)
    shared   a leaf of u and a leaf of v have the same object ?x, which is no
             unit's subject                                     (?f_k frame ?f, ?f_c frame ?f)

Join sizes: rows1 * rows2 / max(ndv1(x), ndv2(x)) per connecting variable
(System R), with per-variable distinct counts carried up the tree and capped
at the rows. Cost: C_out, the sum of intermediate rows.

Anything outside what is implemented raises `Unsupported`, and the caller
keeps today's SQL.
"""
from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from .ir import (KIND_BGP, KIND_DISTINCT, KIND_EXTEND, KIND_FILTER, KIND_GROUP,
                 KIND_JOIN, KIND_LEFT_JOIN, KIND_ORDER, KIND_PROJECT, KIND_REDUCED,
                 KIND_SLICE, KIND_TABLE)
from .qtree import Est, Leaf, Unit, _Stats, _leaves, _unit

XSD_INTEGER = "http://www.w3.org/2001/XMLSchema#integer"
MAX_UNITS = 12                      # DP over 2^n subsets; beyond this, decline

class Unsupported(Exception):
    pass


# ---------------------------------------------------------------------------
# The query, as the planner sees it
# ---------------------------------------------------------------------------

@dataclass
class Edge:
    u: int
    v: int
    var: str
    kind: str                       # link | shared
    leaf_u: Leaf                    # u's leaf whose object is ?var
    leaf_v: Optional[Leaf] = None   # shared: v's leaf whose object is ?var
    col_u: Optional[str] = None     # leaf_u's column holding ?var (object_uuid; a derived row's own)
    col_v: Optional[str] = None     # shared: leaf_v's column
    # sampled physical fan-out (`qcard`): target unit -> rows one probe reads
    fan: Dict[int, float] = field(default_factory=dict)


@dataclass
class Region:
    units: List[Unit]
    edges: List[Edge]
    values: Dict[str, List[str]]                    # ?var -> value uuids
    plans: List[Any]                                # the BGP PlanV2s (positions, filters)
    aliases: Any                                    # AliasGenerator of its constants
    optionals: List["Region"] = field(default_factory=list)
    antis: List["Anti"] = field(default_factory=list)
    bound: Dict[str, float] = field(default_factory=dict)   # correlated ?var -> ndv (1)
    # sampled join sizes (`qcard`): (unit, unit) -> rows of the two joined
    pair_rows: Dict[Tuple[int, int], Est] = field(default_factory=dict)
    pair_samples: Dict[Tuple[int, int], list] = field(default_factory=dict)


@dataclass
class Anti:
    region: Region
    correlated: List[str]
    filters: List[Any]


@dataclass
class Query:
    region: Region
    group_vars: Optional[List[str]] = None
    aggregates: Dict[str, Any] = field(default_factory=dict)   # placeholder -> ExprAggregator
    extend: Dict[str, str] = field(default_factory=dict)        # var -> placeholder
    having: List[Any] = field(default_factory=list)
    order: List[Tuple[str, str]] = field(default_factory=list)
    project: Optional[List[str]] = None
    distinct: bool = False
    limit: Optional[int] = None
    offset: int = 0
    exclude: frozenset = frozenset()    # leaves left out as implied (`pattern_verdict`)
    # A sub-SELECT directly under the outer aggregate: `SELECT (COUNT(*) …) { SELECT
    # DISTINCT ?e … }`. Its projection (and DISTINCT) is applied to the pattern
    # before the outer GROUP reads it; the outer query sees only these variables.
    sub_project: Optional[List[str]] = None
    sub_distinct: bool = False
    # the ORDER BY is the generator's own, synthesized for a stable page of an
    # unordered LIMIT (`hints["stable_paging"]`, collect._collect_slice), by uuid
    synth_order: bool = False


class _Shim:
    """A minimal EmitContext stand-in for an EXISTS body's own aliases."""
    def __init__(self, aliases):
        self.aliases = aliases


def analyze(plan, ctx, exclude: frozenset = frozenset()) -> Query:
    """`exclude`: leaf aliases to leave out (patterns a stored verdict says are
    implied by the rest, `pattern_verdict`)."""
    q = Query(region=None)                      # type: ignore[arg-type]
    q.exclude = exclude
    p = plan
    seen_group = False
    while p.kind in (KIND_SLICE, KIND_PROJECT, KIND_DISTINCT, KIND_REDUCED, KIND_ORDER,
                     KIND_EXTEND, KIND_GROUP) or (p.kind == KIND_FILTER and not seen_group
                                                  and _is_having(p, q)):
        # One level of modifiers only. A second PROJECT, or any projection,
        # DISTINCT, ORDER or LIMIT below the GROUP, is a SUB-SELECT
        # (`SELECT (COUNT(*) …) { SELECT DISTINCT ?e … }`): read as one level,
        # its inner projection replaced the outer one and the render decoded a
        # column the aggregate level never produces (KGQuery count queries).
        # The one supported nesting: a projection (optionally DISTINCT) directly
        # below the outer GROUP, i.e. an aggregate over a sub-SELECT's rows.
        # (The algebra may put the DISTINCT above or below the sub-SELECT's PROJECT.)
        if seen_group and p.kind == KIND_PROJECT and q.sub_project is None:
            q.sub_project = list(p.project_vars or [])
            p = p.children[0]
            continue
        if seen_group and p.kind in (KIND_DISTINCT, KIND_REDUCED) and not q.sub_distinct:
            q.sub_distinct = True
            p = p.children[0]
            continue
        if (p.kind == KIND_PROJECT and q.project is not None) or (p.kind == KIND_SLICE and q.limit is not None) \
                or (seen_group and p.kind in (KIND_PROJECT, KIND_DISTINCT, KIND_REDUCED, KIND_SLICE, KIND_ORDER)):
            raise Unsupported(f"sub-SELECT ({p.kind} below the outer query's modifiers)")
        if p.kind == KIND_SLICE:
            q.limit = p.limit if p.limit >= 0 else None
            q.offset = p.offset or 0
        elif p.kind == KIND_PROJECT:
            q.project = list(p.project_vars or [])
        elif p.kind in (KIND_DISTINCT, KIND_REDUCED):
            q.distinct = True
        elif p.kind == KIND_ORDER:
            if (getattr(p, "hints", None) or {}).get("stable_paging"):
                q.synth_order = True
            for expr, d in (p.order_conditions or []):
                if not isinstance(expr, str):
                    raise Unsupported(f"ORDER BY an expression: {expr}")
                q.order.append((expr.lstrip("?"), "DESC" if str(d).upper().startswith("DESC") else "ASC"))
        elif p.kind == KIND_EXTEND:
            e = p.extend_expr
            name = getattr(e, "var", None)
            if name is None or not name.startswith("."):
                raise Unsupported(f"BIND / extend of a non-aggregate: {e}")
            q.extend[p.extend_var] = name
        elif p.kind == KIND_GROUP:
            seen_group = True
            gv = p.group_vars or []
            if any(g.expr is not None for g in gv):
                raise Unsupported("GROUP BY an expression")
            q.group_vars = [g.var for g in gv]
            for k, agg in (p.aggregates or {}).items():
                if agg.name.upper() != "COUNT":
                    raise Unsupported(f"aggregate {agg.name}")
                q.aggregates[k] = agg
        elif p.kind == KIND_FILTER:
            q.having.extend(p.filter_exprs or [])
        p = p.children[0]
    q.region = _region(p, ctx, ctx.aliases, outer_vars=set(), exclude=exclude)
    refresh_subqueries(q)
    return q


def _analyze_subselect(p, ctx, exclude: frozenset) -> Query:
    """A grouped sub-SELECT inside a pattern: `{ SELECT ?k (MAX(?v) AS ?m) WHERE
    { ... } GROUP BY ?k }`, i.e. PROJECT, EXTENDs, GROUP over a pattern. Grouped
    on variables, MIN / MAX aggregates of a variable, every projected variable a
    group key or an aggregate."""
    q = Query(region=None)                      # type: ignore[arg-type]
    q.exclude = exclude
    q.project = list(p.project_vars or [])
    p = p.children[0]
    while p.kind == KIND_EXTEND:
        name = getattr(p.extend_expr, "var", None)
        if name is None or not name.startswith("."):
            raise Unsupported(f"sub-SELECT: BIND / extend of a non-aggregate: {p.extend_expr}")
        q.extend[p.extend_var] = name
        p = p.children[0]
    if p.kind != KIND_GROUP:
        raise Unsupported(f"sub-SELECT inside the pattern without GROUP BY ({p.kind})")
    gv = p.group_vars or []
    if not gv or any(g.expr is not None for g in gv):
        raise Unsupported("sub-SELECT: GROUP BY nothing or an expression")
    q.group_vars = [g.var for g in gv]
    for k, agg in (p.aggregates or {}).items():
        if agg.name.upper() not in ("MAX", "MIN") or type(agg.expr).__name__ != "ExprVar":
            raise Unsupported(f"sub-SELECT aggregate {agg.name}")
        q.aggregates[k] = agg
    outside = [v for v in q.project if v not in q.group_vars and v not in q.extend]
    if outside or set(q.extend.values()) - set(q.aggregates):
        raise Unsupported("sub-SELECT projects a variable that is neither a key nor an aggregate")
    q.region = _region(p.children[0], ctx, ctx.aliases, outer_vars=set(), exclude=exclude)
    if q.region.optionals or q.region.antis or any(
            l.kind == "subq" for u in q.region.units for l in u.leaves):
        raise Unsupported("sub-SELECT with OPTIONAL, NOT EXISTS or a nested sub-SELECT")
    return q


def _subq_leaf(p, ctx, exclude: frozenset) -> Leaf:
    """The sub-SELECT as one leaf of the outer pattern: alias `sq_<first alias
    inside>` (unique in the statement), one row per group, a column k_<var> per
    projected variable. Sized and priced by `refresh_subqueries`."""
    inner = _analyze_subselect(p, ctx, exclude)
    first = min((l.alias for u in inner.region.units for l in u.leaves), default="x")
    leaf = Leaf(alias=f"sq_{first}", kind="subq", pred=None, s_var=None, o_var=None,
                s_const=None, o_const=None, scan=Est(None, "subq"), pred_rows=None,
                pred_objects=None, o_vars=[(f"k_{v}", v) for v in inner.project])
    leaf.sub = inner
    _subq_price(leaf)
    return leaf


def _subq_price(leaf: Leaf) -> None:
    """Groups and cost of a sub-SELECT leaf from its inner plan: groups = the
    inner rows, at most the product of the group keys' distinct values; cost =
    the inner plan plus hashing its rows into groups."""
    inner = leaf.sub
    tree = search(inner.region)
    ndv: Dict[str, float] = {}
    for u in inner.region.units:
        for v, n in _unit_ndv(u, inner.region.values, inner.region.bound).items():
            ndv[v] = min(ndv.get(v, n), n)
    groups = 1.0
    for v in inner.group_vars:
        groups *= ndv.get(v, tree.rows)
    groups = max(1.0, min(groups, tree.rows))
    leaf.scan = Est(groups, "subq")
    leaf.col_ndv = {c: groups for c, _v in leaf.o_vars}
    leaf.sub_cost = tree.cost + (tree.rows if COST_MODEL == "cout" else
                                 W["hash_build"] + tree.rows * (W["hash_build_row"] + W["hash_probe_row"]))


def refresh_subqueries(q: Query) -> None:
    """Re-price every sub-SELECT leaf and its unit, after its inner region's
    estimates changed (`qcard.annotate` samples it in place)."""
    def walk(r: Region):
        for u in r.units:
            for l in u.leaves:
                if l.kind == "subq":
                    _subq_price(l)
                    if u.anchor is l:
                        u.rows = Est(l.scan.rows, "subq")
        for o in r.optionals:
            walk(o)
        for a in r.antis:
            walk(a.region)
    walk(q.region)


def _is_having(p, q) -> bool:
    """A FILTER above the GROUP is a HAVING: it compares an aggregate."""
    def refs(e):
        if hasattr(e, "var"):
            yield e.var
        for a in getattr(e, "args", None) or []:
            yield from refs(a)
    names = set(q.extend) | set(q.extend.values())
    return all(any(r.startswith(".") or r in names for r in refs(e)) for e in (p.filter_exprs or []))


def _region(p, ctx, aliases, outer_vars: Set[str], exclude: frozenset = frozenset()) -> Region:
    parts = {"leaves": [], "values": {}, "plans": [], "optionals": [], "antis": [], "exclude": exclude, "ctx": ctx}
    _collect(p, ctx, aliases, parts, outer_vars)
    r = _build_region(parts, ctx, aliases)
    return r


def _collect(p, ctx, aliases, parts, outer_vars):
    st = _Stats(p, ctx)
    if p.kind == KIND_BGP:
        parts["leaves"].extend(l for l in _leaves(p, ctx, st) if l.alias not in parts["exclude"])
        parts["plans"].append(p)
    elif p.kind == KIND_JOIN:
        for c in p.children:
            _collect(c, ctx, aliases, parts, outer_vars)
    elif p.kind == KIND_TABLE:
        vars_ = p.values_vars or []
        if len(vars_) != 1:
            raise Unsupported("VALUES with other than one variable")
        v = vars_[0]
        uuids = []
        for row in p.values_rows or []:
            node = row.get(v)
            if node is None:
                raise Unsupported("VALUES with UNDEF")
            key = _term_key(node)
            col = (aliases.constants or {}).get(key)
            u = (aliases.resolved_constants or {}).get(col) if col else None
            # A term absent from the term table matches nothing in an inner
            # join, so it contributes no row: drop it.
            if u is not None:
                uuids.append(u)
        if not uuids:
            raise Unsupported("VALUES matches no stored term (today's provably-empty path handles it)")
        parts["values"][v] = uuids
    elif p.kind == KIND_LEFT_JOIN:
        if p.left_join_exprs:
            raise Unsupported("OPTIONAL with a FILTER inside")
        _collect(p.children[0], ctx, aliases, parts, outer_vars)
        parts["optionals"].append(_region(p.children[1], ctx, aliases, outer_vars))
    elif p.kind == KIND_FILTER:
        _collect(p.children[0], ctx, aliases, parts, outer_vars)
        for e in p.filter_exprs or []:
            if type(e).__name__ == "ExprExists" and e.negated and e.prepared_plan is not None:
                body = e.prepared_plan
                filters = []
                while body.kind == KIND_FILTER:
                    filters.extend(body.filter_exprs or [])
                    body = body.children[0]
                shim = _Shim(e.prepared_aliases)
                br = _region(body, shim, e.prepared_aliases, outer_vars)
                parts["antis"].append(Anti(region=br, correlated=[], filters=filters))
            else:
                raise Unsupported(f"FILTER {type(e).__name__}")
    elif p.kind == KIND_PROJECT:
        # a grouped sub-SELECT joined into the pattern: one leaf, its own plan
        parts["leaves"].append(_subq_leaf(p, parts["ctx"], parts["exclude"]))
    else:
        raise Unsupported(f"{p.kind} inside the pattern")


def _term_key(node):
    t = type(node).__name__
    if t == "URINode":
        return (node.value, "U", None, None)
    if t == "LiteralNode":
        return (node.value, "L", getattr(node, "lang", None) or None, node.datatype or None)
    raise Unsupported(f"VALUES term of kind {t}")


def _build_region(parts, ctx, aliases) -> Region:
    leaves: List[Leaf] = parts["leaves"]
    values = parts["values"]
    # VALUES pins: a leaf whose object is the VALUES variable is restricted to
    # those terms, priced exactly from rdf_stats where the pairs are stored.
    a = aliases
    quad_stats = getattr(a, "quad_stats", None) or {}
    extra = getattr(a, "extra_quad_stats", None) or {}
    for var, uuids in values.items():
        holders = [l for l in leaves if any(v == var for _c, v in l.o_vars)]
        if not holders:
            raise Unsupported(f"VALUES ?{var} binds no pattern")
        for l in holders:
            if not l.pred_uuid:
                continue
            counts = [quad_stats.get((l.pred_uuid, u), extra.get((l.pred_uuid, u))) for u in uuids]
            if all(c is not None for c in counts):
                l.scan = Est(float(sum(counts)), "values")
            else:
                # absent pairs: each below the smallest stored pair of the predicate
                stored = [n for (p, _o), n in quad_stats.items() if p == l.pred_uuid]
                if stored:
                    low = min(stored)
                    l.scan = Est(float(sum(c if c is not None else low for c in counts)), "values_bound")
    by_subject: Dict[str, List[Leaf]] = {}
    for l in leaves:
        key = l.s_var if l.s_var else (l.s_const or l.alias)
        by_subject.setdefault(key, []).append(l)
    units = [_unit(f"?{s}" if any(l.s_var == s for l in ls) else s, ls) for s, ls in by_subject.items()]
    for u in units:
        if u.rows.rows is None:
            raise Unsupported(f"unit {u.subject} has no priced anchor")
    # A sub-SELECT is joined with the WHOLE pattern, and OPTIONAL blocks are
    # attached after it: Join(LeftJoin(A, B), C) = LeftJoin(Join(A, C), B) only
    # when B and C share no variable A does not bind.
    sub_vars = {ov for l in leaves if l.kind == "subq" for _c, ov in l.o_vars}
    if sub_vars and parts["optionals"]:
        plain = {v for l in leaves if l.kind != "subq" for v in [l.s_var] + [ov for _c, ov in l.o_vars] if v}
        for o in parts["optionals"]:
            if (region_vars(o) & sub_vars) - plain:
                raise Unsupported("an OPTIONAL shares a variable with a sub-SELECT only")
    edges = []
    subj = {u.subject[1:]: i for i, u in enumerate(units) if u.subject.startswith("?")}
    for i, u in enumerate(units):
        for l in u.leaves:
            for c, ov in l.o_vars:
                if ov in subj and subj[ov] != i:
                    edges.append(Edge(i, subj[ov], ov, "link", l, col_u=c))
    for i, j in itertools.combinations(range(len(units)), 2):
        for li in units[i].leaves:
            for lj in units[j].leaves:
                for ci, vi in li.o_vars:
                    for cj, vj in lj.o_vars:
                        if vi == vj and vi not in subj:
                            edges.append(Edge(i, j, vi, "shared", li, lj, col_u=ci, col_v=cj))
    return Region(units=units, edges=edges, values=values, plans=parts["plans"],
                  aliases=aliases, optionals=parts["optionals"], antis=parts["antis"])


def region_vars(r: Region) -> Set[str]:
    out = set()
    for u in r.units:
        for l in u.leaves:
            for v in [l.s_var] + [ov for _c, ov in l.o_vars]:
                if v:
                    out.add(v)
    return out


# ---------------------------------------------------------------------------
# Search: DP over connected subsets of units
# ---------------------------------------------------------------------------

@dataclass
class Node:
    kind: str                       # scan | hash | probe
    units: frozenset
    cost: float
    rows: float
    ndv: Dict[str, float]
    left: Optional["Node"] = None
    right: Optional["Node"] = None
    unit: Optional[int] = None      # scan / probe target
    edge: Optional[Edge] = None     # probe edge


def _unit_ndv(u: Unit, values: Dict[str, List[str]], bound: Dict[str, float]) -> Dict[str, float]:
    r = u.rows.rows or 0.0
    out: Dict[str, float] = {}
    if u.subject.startswith("?"):
        out[u.subject[1:]] = r
    for l in u.leaves:
        for c, ov in l.o_vars:
            d = l.ndv(c)
            n = min(r, d) if d else r
            if ov in values:
                n = min(n, float(len(values[ov])))
            out[ov] = min(out.get(ov, n), n)
    return out


def _join_rows(a: Node, b: Node, vars_: Set[str]) -> Tuple[float, Dict[str, float]]:
    rows = a.rows * b.rows
    for v in vars_:
        rows /= max(a.ndv.get(v, 1.0), b.ndv.get(v, 1.0), 1.0)
    ndv = {}
    for v in set(a.ndv) | set(b.ndv):
        n = min(x for x in (a.ndv.get(v), b.ndv.get(v)) if x is not None)
        ndv[v] = min(n, max(rows, 1.0))
    return max(rows, 1.0 if rows > 0 else 0.0), ndv


def _connecting(r: Region, s1: frozenset, s2: frozenset) -> List[Edge]:
    return [e for e in r.edges if (e.u in s1 and e.v in s2) or (e.u in s2 and e.v in s1)]


def _object_fan(l: Optional[Leaf], col: Optional[str] = None) -> Optional[float]:
    """Rows per probe of leaf `l` by a non-key column, the value coming from the
    data: for a quad, the size-biased mean from rdf_stats, else the predicate's
    plain mean; for a derived row, the table's rows / distinct values of `col`."""
    return l.fan(col) if l is not None else None


def _probe_fan(e: Edge, target: int) -> Optional[float]:
    """Rows per bound row when probing unit `target` through edge e."""
    # The PHYSICAL fan-out: the index range a probe reads, (predicate, object)
    # over every subject, before the unit's own filters narrow it. A
    # characteristic pair (link x subject kind) is the LOGICAL result after those filters
    # and must not stand in for it: measured, it sent probes from ?d through
    # every member of the decision graph (3.1M rows read, 1,159 estimated).
    # The sampled fan-out (`qcard`) is the physical one, measured per probe.
    if target in e.fan:
        return e.fan[target]
    if e.kind == "link":
        if e.u == target:                       # target holds the link leaf: probe it by object
            return _object_fan(e.leaf_u, e.col_u)
        return 1.0                              # target is the link's subject: probe by subject
    return _object_fan(e.leaf_u, e.col_u) if e.u == target else _object_fan(e.leaf_v, e.col_v)


MAX_CCP_PAIRS = 20_000               # ~100 ms of Python; above this, greedy instead of DP


def _bits(mask: int):
    while mask:
        low = mask & -mask
        yield low.bit_length() - 1
        mask ^= low


def _submasks(mask: int):
    """Every non-empty submask of `mask`."""
    s = mask
    while s:
        yield s
        s = (s - 1) & mask


def _ccp_pairs(n: int, adj: List[int]) -> List[Tuple[int, int]]:
    """DPccp (Moerkotte & Neumann 2006): every pair (S1, S2) of disjoint,
    connected unit sets with an edge between them, each unordered pair once.
    Raises Unsupported past MAX_CCP_PAIRS (the caller then goes greedy)."""
    pairs: List[Tuple[int, int]] = []

    def nbh(S: int, X: int) -> int:
        m = 0
        for i in _bits(S):
            m |= adj[i]
        return m & ~S & ~X

    def csg_rec(S: int, X: int, out):
        N = nbh(S, X)
        if not N:
            return
        for s in _submasks(N):
            out(S | s)
        for s in _submasks(N):
            csg_rec(S | s, X | N, out)

    def emit_csg(S1: int):
        lo = (S1 & -S1).bit_length() - 1
        X = ((1 << (lo + 1)) - 1) | S1
        N = nbh(S1, X)
        for i in sorted(_bits(N), reverse=True):
            S2 = 1 << i

            def take(S2b, S1=S1):
                pairs.append((S1, S2b))
                if len(pairs) > MAX_CCP_PAIRS:
                    raise Unsupported("too many connected sub-plans for DP")
            take(S2)
            Bi = (1 << (i + 1)) - 1
            csg_rec(S2, X | (Bi & N), take)

    for i in reversed(range(n)):
        S = 1 << i
        emit_csg(S)
        csg_rec(S, (1 << (i + 1)) - 1, emit_csg)
    return pairs


def _mask_edges(r: Region) -> Tuple[List[int], Dict[Tuple[int, int], List[Edge]]]:
    adj = [0] * len(r.units)
    by_pair: Dict[Tuple[int, int], List[Edge]] = {}
    for e in r.edges:
        adj[e.u] |= 1 << e.v
        adj[e.v] |= 1 << e.u
        by_pair.setdefault((min(e.u, e.v), max(e.u, e.v)), []).append(e)
    return adj, by_pair


def _edges_between(by_pair, m1: int, m2: int) -> List[Edge]:
    out = []
    for i in _bits(m1):
        for j in _bits(m2):
            out += by_pair.get((min(i, j), max(i, j)), [])
    return out


#: Per-operator costs in microseconds, fitted from executed plans on the planner stack
#: (test_scripts_internal/planner_ext/calib/fit.py, 72 plans, results/calibration.md).
#: "calib" (the default since 2026-10-24) prices an index probe row ~10x a hash row, as
#: measured. "cout" is plain C_out (every intermediate row costs 1): within 3% of calib
#: on the UW dashboards, but on wordnet's frame_slot count it chose 285k index probes
#: over a hash join, 2.4x slower than today's SQL; calib matches today there.
COST_MODEL = "calib"
# EXPERIMENTS: VG_PLANNER_COST_MODEL=calib|cout overrides the default for a process.
import os as _os
if _os.getenv("VG_PLANNER_COST_MODEL") in ("cout", "calib"):
    COST_MODEL = _os.environ["VG_PLANNER_COST_MODEL"]
W = {
    "idx_lookup": 3.38,      # one index descent (Index Scan, per loop)
    "idx_row": 1.09,         # one row returned by an index scan (heap fetch included)
    "hash_build_row": 0.30,  # a row inserted into a hash table
    "hash_build": 142.6,     # building a hash table, per build
    "hash_probe_row": 0.072, # a probe-side row looked up in the hash table
    "hash_inner_row": 0.149, # an inner (build-side) row passing the join
    "join_out_row": 0.35,    # a row produced by a join
    # a row of a BULK scan of one predicate's range (covering index, read in order),
    # as when a unit's leaf is scanned on its own for a hash build: measured on lead
    # 100k, 1.1M-4.1M-row ranges, single worker, 0.126-0.128 us/row (2026-10-24).
    # The probe-fitted idx_row (1.09, heap fetch included) priced it 8x too high.
    "scan_row": 0.127,
}


def _scan_cost(rows: float, nleaves: int) -> float:
    """A unit evaluated from its anchor: one index range scan returning `rows`,
    then one index probe per row for each further leaf."""
    if COST_MODEL == "cout":
        return rows * nleaves
    return (W["idx_lookup"] + rows * W["idx_row"]
            + rows * max(0, nleaves - 1) * (W["idx_lookup"] + W["idx_row"]))


def _hash_cost(a: "Node", b: "Node", rows: float) -> float:
    if COST_MODEL == "cout":
        return a.cost + b.cost + rows
    build, probe = (a, b) if a.rows <= b.rows else (b, a)
    return (a.cost + b.cost + W["hash_build"] + build.rows * (W["hash_build_row"] + W["hash_inner_row"])
            + probe.rows * W["hash_probe_row"] + rows * W["join_out_row"])


def _probe_cost(left: "Node", fan: float, rows: float, nleaves: int) -> float:
    """From each left row, one index descent reading `fan` rows, then the
    target unit's remaining leaves probed per surviving row."""
    if COST_MODEL == "cout":
        return left.cost + left.rows * fan + rows * max(0, nleaves - 1)
    return (left.cost + left.rows * (W["idx_lookup"] + fan * W["idx_row"])
            + rows * max(0, nleaves - 1) * (W["idx_lookup"] + W["idx_row"])
            + rows * W["join_out_row"])


class _Card:
    """rows(S) for a set of units, the same whichever split builds it: the
    product of the units' rows times the selectivity of the joins inside S.
    Split-independent rows are what make the DP's optimum well defined.

    Selectivities per unit pair: sampled (`qcard`, over every variable the pair
    shares), else 1 / max(distinct values of the variable on either side).

    ONE VARIABLE SHARED BY THREE OR MORE UNITS is one equivalence class, not a
    set of independent equalities: with `o.d = ca.d = gv.d = f_k.d` the six
    pairwise conditions hold once three do. Multiplying all six made a page
    query estimate 0 rows (category_page without its `?d` unit). Per variable,
    only a spanning tree of its pairs is applied: the LEAST selective one
    (Kruskal on descending selectivity), which under containment is the exact
    k-way estimate and otherwise errs high, never low. PostgreSQL does the same
    with its equivalence classes."""

    def __init__(self, r: Region):
        self.rows = [u.rows.rows or 0.0 for u in r.units]
        ndv = [_unit_ndv(u, r.values, r.bound) for u in r.units]
        n = len(r.units)
        pair_vars: Dict[Tuple[int, int], Set[str]] = {}
        for e in r.edges:
            if e.u < n and e.v < n:
                pair_vars.setdefault((min(e.u, e.v), max(e.u, e.v)), set()).add(e.var)
        # (i, j, selectivity, the one variable joined on, or None for several)
        self.sel: List[Tuple[int, int, float, Optional[str]]] = []
        for (i, j), est in r.pair_rows.items():
            d = self.rows[i] * self.rows[j]
            vs = pair_vars.get((i, j), set())
            self.sel.append((i, j, (est.rows / d) if d > 0 else 0.0, next(iter(vs)) if len(vs) == 1 else None))
        seen = set()
        for e in r.edges:
            key = (min(e.u, e.v), max(e.u, e.v), e.var)
            if key in seen or e.v >= n or e.u >= n or (key[0], key[1]) in r.pair_rows:
                continue
            seen.add(key)
            d = max(ndv[e.u].get(e.var, 1.0), ndv[e.v].get(e.var, 1.0), 1.0)
            self.sel.append((key[0], key[1], 1.0 / d, e.var))
        self.sel.sort(key=lambda x: -x[2])          # Kruskal order: least selective first
        self._memo: Dict[int, float] = {}

    def __call__(self, mask: int) -> float:
        if mask not in self._memo:
            v = 1.0
            for i in _bits(mask):
                v *= self.rows[i]
            parent: Dict[Tuple[str, int], Tuple[str, int]] = {}

            def find(x):
                while parent.get(x, x) != x:
                    x = parent[x]
                return x
            for i, j, sel, var in self.sel:
                if not (mask >> i) & 1 or not (mask >> j) & 1:
                    continue
                if var is None:                     # a pair joined on several variables
                    v *= sel
                    continue
                a, b = find((var, i)), find((var, j))
                if a == b:                          # implied by the variable's class: skip
                    continue
                parent[a] = b
                v *= sel
            self._memo[mask] = v
        return self._memo[mask]


def _mask(units: frozenset) -> int:
    m = 0
    for i in units:
        m |= 1 << i
    return m


def _join_options(r: Region, a: Node, b: Node, edges: List[Edge], S: frozenset,
                  cand: Optional[Node], card: Optional["_Card"] = None) -> Optional[Node]:
    """Both join choices for sides a and b: hash, or probe into a single unit."""
    card = card or _Card(r)
    rows, ndv = card(_mask(S)), {}
    c = _hash_cost(a, b, rows)
    if cand is None or c < cand.cost:
        cand = Node("hash", S, c, rows, ndv, left=a, right=b)
    for left, right in ((a, b), (b, a)):
        if len(right.units) != 1:
            continue
        t = next(iter(right.units))
        for e in edges:
            fan = _probe_fan(e, t)
            if fan is None:
                continue
            c = _probe_cost(left, fan, rows, len(r.units[t].leaves))
            if c < cand.cost:
                cand = Node("probe", S, c, rows, ndv, left=left, unit=t, edge=e)
    return cand


def _unit_build(u: Unit) -> Tuple[float, List[Tuple[Leaf, str]]]:
    """How to build a unit, and its cost: the anchor scanned, then each other
    leaf either PROBED per row by subject (the original chain) or SCANNED on its
    own predicate and HASH-joined on the subject, whichever the cost model
    prices lower. All-probe is the old `_scan_cost` exactly.

    Why: a unit is one star, but not one access path. lead 100k's MQLv2 slot
    unit has 100,000 rows; probing its value leaf per row is ~200,000 index
    descents, where today's SQL hash-joins the two leaves' scans, 1.3x faster
    at production scale. A leaf with no price of its own (no scan estimate) can
    only be probed; so can one whose scan is the whole predicate of a huge
    relation (hasKGGraphURI: 7.4M rows), by cost."""
    rows = u.rows.rows or 0.0
    from .planner_ext import FEATURES as _F
    if not _F.get("unit_hash"):
        return _scan_cost(rows, len(u.leaves)), [(l, "probe") for l in u.probes]
    a = u.anchor
    first = a.scan.rows if (a is not None and a.scan.rows is not None) else rows
    cost = _scan_cost(first, 1)
    plan: List[Tuple[Leaf, str]] = []
    cur = first
    for l in u.probes:
        probe = (cur if COST_MODEL == "cout" else
                 cur * (W["idx_lookup"] + W["idx_row"]))
        lrows = l.scan.rows
        hash_ = None
        if lrows is not None and lrows > 0:
            out = min(cur, lrows)
            if COST_MODEL == "cout":
                hash_ = lrows + cur + out
            else:
                build, prob = (lrows, cur) if lrows <= cur else (cur, lrows)
                hash_ = (W["idx_lookup"] + lrows * W["scan_row"] + W["hash_build"]
                         + build * (W["hash_build_row"] + W["hash_inner_row"])
                         + prob * W["hash_probe_row"] + out * W["join_out_row"])
        if hash_ is not None and hash_ < probe:
            cost += hash_
            plan.append((l, "hash"))
        else:
            cost += probe
            plan.append((l, "probe"))
        cur = rows                                  # after the anchor's partners: the unit's rows
    return cost, plan


def _base(r: Region, i: int) -> Node:
    u = r.units[i]
    rr = u.rows.rows or 0.0
    if u.anchor is not None and u.anchor.kind == "subq":
        return Node("scan", frozenset([i]), u.anchor.sub_cost, rr, _unit_ndv(u, r.values, r.bound), unit=i)
    cost, _plan = _unit_build(u)
    return Node("scan", frozenset([i]), cost, rr, _unit_ndv(u, r.values, r.bound), unit=i)


def search(r: Region) -> Node:
    """Bottom-up DP over connected unit subsets (DPccp), greedy past the cap."""
    n = len(r.units)
    if n == 0:
        raise Unsupported("empty region")
    adj, by_pair = _mask_edges(r)
    card = _Card(r)
    best: Dict[int, Node] = {1 << i: _base(r, i) for i in range(n)}
    try:
        pairs = _ccp_pairs(n, adj)
    except Unsupported:
        return _greedy(r, adj, by_pair)
    pairs.sort(key=lambda p: bin(p[0] | p[1]).count("1"))
    for m1, m2 in pairs:
        a, b = best.get(m1), best.get(m2)
        if a is None or b is None:
            continue
        S = m1 | m2
        edges = _edges_between(by_pair, m1, m2)
        best[S] = _join_options(r, a, b, edges, a.units | b.units, best.get(S), card)
    full = (1 << n) - 1
    if full not in best:
        raise Unsupported("the units are not connected")
    return best[full]


def _greedy(r: Region, adj, by_pair) -> Node:
    """Greedy operator ordering: repeatedly make the cheapest available join."""
    card = _Card(r)
    parts: Dict[int, Node] = {1 << i: _base(r, i) for i in range(len(r.units))}
    while len(parts) > 1:
        best_pair, best_node = None, None
        keys = list(parts)
        for x, y in itertools.combinations(keys, 2):
            edges = _edges_between(by_pair, x, y)
            if not edges:
                continue
            nd = _join_options(r, parts[x], parts[y], edges, parts[x].units | parts[y].units, None, card)
            if best_node is None or nd.cost < best_node.cost:
                best_pair, best_node = (x, y), nd
        if best_pair is None:
            raise Unsupported("the units are not connected")
        x, y = best_pair
        del parts[x], parts[y]
        parts[x | y] = best_node
    return next(iter(parts.values()))


def describe(node: Node, r: Region) -> str:
    if node.kind == "scan":
        return r.units[node.unit].subject
    if node.kind == "hash":
        return f"({describe(node.left, r)} ⋈ {describe(node.right, r)})"
    return f"({describe(node.left, r)} →{node.edge.var} {r.units[node.unit].subject})"


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_ALIAS = re.compile(r"\b([a-z][a-z0-9_]*[0-9])\.")


class _Pos:
    """Positions, filters and table names of one region's BGPs, plus the
    region's VALUES restrictions as filters on the leaves that hold them."""
    def __init__(self, plans, values: Optional[Dict[str, List[str]]] = None):
        self.table: Dict[str, str] = {}
        self.filters: Dict[str, List[str]] = {}
        self.positions: Dict[str, List[Tuple[str, str]]] = {}
        self.term_table: Optional[str] = None
        # leaf alias -> the alias of the term sub-select its range/IN criterion
        # reads (`_name_sublink`), added to every advised set containing the leaf
        self.sublinks: Dict[str, List[str]] = {}
        # leaf alias -> [(sub-select alias, table, selected column, condition, the
        # leaf's column, the rendered IN filter)]: candidates to DRIVE a unit from
        self.sublink_parts: Dict[str, List[Tuple[str, str, str, str, str, str]]] = {}
        # leaves rendered that way: no base size of their own (unfiltered alone)
        self.driven: Set[str] = set()
        for p in plans:
            for t in p.tables:
                if t.kind == "term":
                    self.term_table = self.term_table or t.table_name
                else:
                    self.table[t.alias] = t.table_name
            for owner, sql in p.tagged_constraints:
                refs = set(_ALIAS.findall(sql))
                if refs <= {owner}:
                    self.filters.setdefault(owner, []).append(self._name_sublink(owner, sql))
                elif not re.fullmatch(r"\s*\w+\.\w+ = \w+\.\w+\s*", sql):
                    raise Unsupported(f"cross-table condition that is not a variable equality: {sql}")
            for var, slot in p.var_slots.items():
                for pos in slot.positions:
                    if pos[0] in self.table:
                        self.positions.setdefault(var, []).append(pos)
        for var, uuids in (values or {}).items():
            lits = ", ".join(f"'{u}'::uuid" for u in uuids)
            for a, col in self.positions.get(var, []):
                self.filters.setdefault(a, []).append(f"{a}.{col} IN ({lits})")


from .qtree import SUBLINK_RE as _SUBLINK     # owner, col, sel, table, cond


def _name_sublink_sql(owner: str, sql: str, taken: List[str]) -> Tuple[str, Optional[str]]:
    m = _SUBLINK.match(sql)
    if not m or m.group(1) != owner:
        return sql, None
    alias = f"r_{owner}" + (f"_{len(taken) + 1}" if taken else "")
    return (f"{owner}.{m.group(2)} IN (SELECT {alias}.{m.group(3)} FROM {m.group(4)} AS {alias} "
            f"WHERE {m.group(5)})"), alias


def _pos_name_sublink(self, owner: str, sql: str) -> str:
    """A leaf criterion read from the term table (`o IN (SELECT term_uuid FROM
    term WHERE num_val >= 65)`) gets its sub-select ALIASED, so the advice can
    name it. PostgreSQL pulls the sub-select up and, term_uuid being unique,
    turns it into an ordinary join: a relation in every join above the leaf.
    Unnamed, it made every advised size and method above the leaf match
    nothing (KGQuery range criteria: 15 items not applied)."""
    out, alias = _name_sublink_sql(owner, sql, self.sublinks.get(owner, []))
    if alias:
        self.sublinks.setdefault(owner, []).append(alias)
        m = _SUBLINK.match(sql)
        self.sublink_parts.setdefault(owner, []).append(
            (alias, m.group(4), m.group(3), m.group(5), m.group(2), out))
    return out


_Pos._name_sublink = _pos_name_sublink


class _R:
    """Rendering state: canonical column per variable, what is joined so far."""
    def __init__(self, pos: _Pos, outer: Optional[Dict[str, str]] = None):
        self.pos = pos
        self.bound: Dict[str, str] = dict(outer or {})
        self.outer = set(outer or {})
        self.sizes: List[Tuple[float, List[str]]] = []
        self.units_advice: List[str] = []
        self.methods: List[Tuple[str, List[str]]] = []   # the plan's join choices

    def bind(self, alias):
        for var, poss in self.pos.positions.items():
            for a, col in poss:
                if a == alias and var not in self.bound:
                    self.bound[var] = f"{a}.{col}"

    def eqs(self, alias, present):
        out = []
        for var, poss in self.pos.positions.items():
            canon = self.bound.get(var)
            if canon is None:
                continue
            if var not in self.outer and canon.split(".")[0] not in present:
                continue
            for a, col in poss:
                if a == alias and f"{a}.{col}" != canon:
                    out.append(f"{a}.{col} = {canon}")
        return out


def _chain(r: _R, leaves: List[Leaf], present: Set[str], start_sql: Optional[str],
           pending: List[str], step_rows: Optional[List[float]] = None) -> Tuple[str, List[str]]:
    """Join `leaves` one at a time onto `start_sql` (or start a new nest).
    `step_rows[i]`: the rows after joining leaves[i], recorded as a size so no
    prefix inside a probe chain is left on PostgreSQL's estimate."""
    sql = start_sql
    for i, l in enumerate(leaves):
        a = l.alias
        conds = r.eqs(a, present) + r.pos.filters.get(a, [])
        if sql is None:
            sql = f"{r.pos.table[a]} AS {a}"
            pending = pending + conds
        else:
            allc = conds + pending
            pending = []
            sql = f"{sql}\n  JOIN {r.pos.table[a]} AS {a} ON " + " AND ".join(allc or ["TRUE"])
        present.add(a)
        r.bind(a)
        if step_rows is not None and start_sql is not None and len(present) > 1:
            r.sizes.append((step_rows[i], sorted(present)))
    return sql, pending


def _pick_driver(u: Unit, pos: "_Pos", aliases):
    """The sub-select filter to drive unit u from, or None: among its leaves'
    `col IN (SELECT sel FROM tbl WHERE cond)` filters, the one PostgreSQL
    estimates smallest (qcard.load_sublinks), provided joining it directly is the
    semi-join exactly: `sel`, with `context_uuid` equated to the leaf's where the
    table has one, covers a unique index (else duplicates would multiply rows)."""
    from .generator import substitute_constants
    from .qtree import SUBLINKS
    best = None
    for l in u.leaves:
        for part in pos.sublink_parts.get(l.alias, []):
            ra, tbl, sel, cond, col, fsql = part
            info = SUBLINKS.get((tbl, sel, substitute_constants(cond, aliases).strip()))
            if not info:
                continue
            has_ctx = "context_uuid" in info["cols"] and any(
                f.strip().startswith(f"{l.alias}.context_uuid =") for f in pos.filters.get(l.alias, []))
            cover = {sel} | ({"context_uuid"} if has_ctx else set())
            ok = [set(un) for un in info["unique"] if sel in un and set(un) <= cover]
            if not ok:
                continue
            ctx_eq = any("context_uuid" in un for un in ok) and not any(un == {sel} for un in ok)
            if best is None or info["rows"] < best[2]:
                best = (l, part, info["rows"], ctx_eq, info["cols"])
    return best


def _render_node(node: Node, reg: Region, r: _R) -> Tuple[str, Set[str], List[str]]:
    """SQL for a plan node: (sql, aliases present, conditions still pending)."""
    if node.kind == "scan":
        u = reg.units[node.unit]
        present: Set[str] = set()
        # the unit's build (`_unit_build`): hash-joined leaves first after the
        # anchor, each with a method item for its join and a size for its own
        # scan; probed leaves after, left to PostgreSQL as before
        _c, build = _unit_build(u)
        hashed = [l for l, how in build if how == "hash"]
        order = [u.anchor] + hashed + [l for l, how in build if how == "probe"]
        drv = _pick_driver(u, r.pos, reg.aliases)
        if drv is not None:
            # A unit DRIVEN from a sub-select filter of one of its leaves (a term
            # range, a slot-sort fast path), the one PostgreSQL estimates smallest:
            # the written join order makes it the access path. As a filter it was
            # joined last: lead 100k's MQLRating >= 99.9 read all 100,000 slots to
            # keep 149 (3.3 s, today's SQL 31 ms).
            leaf, (ra, tbl, sel, cond, col, fsql), rows, ctx_eq, cols = drv
            a = leaf.alias
            order = [leaf] + [l for l in order if l is not leaf]
            qcond = re.sub(r"(?<![\w.'])(" + "|".join(map(re.escape, cols)) + r")\b", rf"{ra}.\1", cond) if cols else cond
            conds = [f"{a}.{col} = {ra}.{sel}", qcond] \
                + ([f"{ra}.context_uuid = {a}.context_uuid"] if ctx_eq else []) \
                + r.eqs(a, present) + [f for f in r.pos.filters.get(a, []) if f != fsql]
            sql, pend = f"{tbl} AS {ra}\n  JOIN {r.pos.table[a]} AS {a} ON " + " AND ".join(conds), []
            present.add(a)
            r.bind(a)
            r.pos.driven.add(a)
            r.sizes.append((min(rows, leaf.scan.rows) if leaf.scan.rows else rows, sorted([a, ra])))
        else:
            sql, pend = _chain(r, order[:1], present, None, [])
        for l in hashed:
            sql, pend = _chain(r, [l], present, sql, pend)
            if not l.constant:                      # constant leaves are sized by _base_sizes
                r.sizes.append((l.scan.rows, [l.alias]))
            r.methods.append(("hash", sorted(present)))
        sql, pend = _chain(r, order[1 + len(hashed):], present, sql, pend) if len(order) > 1 + len(hashed) else (sql, pend)
        # (base scans are sized for every constant leaf in render(): see
        #  _base_sizes; not only the anchor)
        if len(u.leaves) > 1 or drv is not None:
            steps = [l.alias for l in order]
            rr = f"{u.rows.rows:.0f}"
            rows_items = [f"{s}:{rr}" for s in steps[1:]]
            if drv is not None:
                # the driver's relation is the first step: every prefix contains it
                rows_items = [f"{steps[0]}:{min(drv[2], drv[0].scan.rows) if drv[0].scan.rows else drv[2]:.0f}"] + rows_items
                steps = [drv[1][0]] + steps
            r.units_advice.append(f"steps({' '.join(steps)}) rows({' '.join(rows_items)})")
            sql = f"({sql})" if pend == [] else sql
        return sql, present, pend
    if node.kind == "probe":
        lsql, present, pend = _render_node(node.left, reg, r)
        u = reg.units[node.unit]
        e = node.edge
        first = (e.leaf_u if e.u == node.unit else (e.leaf_v if e.kind == "shared" else None))
        if first is None:          # probing the link's subject unit: start from its anchor
            first = u.anchor
        rest = [l for l in [u.anchor] + list(u.probes) if l is not first]
        fan = _probe_fan(e, node.unit) or 1.0
        steps = [node.left.rows * fan] + [node.rows] * len(rest)
        r.methods.append(("nl", sorted(present | {first.alias})))
        sql, pend = _chain(r, [first] + rest, present, lsql, pend, step_rows=steps)
        return f"({sql})", present, pend
    lsql, lp, lpend = _render_node(node.left, reg, r)
    rsql, rp, rpend = _render_node(node.right, reg, r)
    conds = []
    for var, poss in r.pos.positions.items():
        canon = r.bound.get(var)
        if canon is None or canon.split(".")[0] not in lp:
            continue
        for a, col in poss:
            if a in rp:
                conds.append(f"{a}.{col} = {canon}")
                break
    present = lp | rp
    r.sizes.append((node.rows, sorted(present)))
    r.methods.append(("hash", sorted(present)))
    on = conds + rpend
    sql = f"({lsql}\n JOIN {rsql} ON " + " AND ".join(on or ["TRUE"]) + ")"
    return sql, present, lpend


def _expr_sql(e, bound: Dict[str, str]) -> str:
    t = type(e).__name__
    if t == "ExprVar":
        if e.var not in bound:
            raise Unsupported(f"filter on unbound ?{e.var}")
        return bound[e.var]
    if t == "ExprFunction" and e.name in ("ne", "eq") and len(e.args) == 2 \
            and all(type(a).__name__ == "ExprVar" for a in e.args):
        op = "<>" if e.name == "ne" else "="
        return f"({_expr_sql(e.args[0], bound)} {op} {_expr_sql(e.args[1], bound)})"
    raise Unsupported(f"filter expression {t} {getattr(e, 'name', '')}")


@dataclass
class Rendered:
    sql: str
    advice: str
    plan: str
    cost: float


def alternatives(r: Region, k: int = 6) -> List[Node]:
    """The best plan plus the cheapest plans that differ at the top join:
    every split of the full unit set, each side its DP-best sub-plan, both
    join choices. For calibrating and testing the cost model (not used to
    plan)."""
    n = len(r.units)
    adj, by_pair = _mask_edges(r)
    card = _Card(r)
    best: Dict[int, Node] = {1 << i: _base(r, i) for i in range(n)}
    pairs = _ccp_pairs(n, adj)
    pairs.sort(key=lambda p: bin(p[0] | p[1]).count("1"))
    full = (1 << n) - 1
    tops: List[Node] = []
    for m1, m2 in pairs:
        a, b = best.get(m1), best.get(m2)
        if a is None or b is None:
            continue
        S = m1 | m2
        edges = _edges_between(by_pair, m1, m2)
        if S == full:
            rows, _ = card(S), None
            tops.append(Node("hash", a.units | b.units, _hash_cost(a, b, rows), rows, {}, left=a, right=b))
            for left, right in ((a, b), (b, a)):
                if len(right.units) == 1:
                    t = next(iter(right.units))
                    for e in edges:
                        fan = _probe_fan(e, t)
                        if fan is not None:
                            c = _probe_cost(left, fan, rows, len(r.units[t].leaves))
                            tops.append(Node("probe", a.units | b.units, c, rows, {}, left=left, unit=t, edge=e))
        best[S] = _join_options(r, a, b, edges, a.units | b.units, best.get(S), card)
    if n == 1:
        return [best[full]]
    tops.sort(key=lambda x: x.cost)
    seen, out = set(), []
    for t in tops:
        d = describe(t, r)
        if d not in seen:
            seen.add(d)
            out.append(t)
        if len(out) >= k:
            break
    return out


@dataclass
class _SubSql:
    sql: str
    sizes: List[Tuple[float, List[str]]]
    units_adv: List[str]
    methods: List[Tuple[str, List[str]]]
    poses: List["_Pos"]
    base_sizes: List[Tuple[float, List[str]]]


def _render_subq(leaf: Leaf, ctx, term_table: str) -> _SubSql:
    """A sub-SELECT leaf's own SQL, keys only: one row per group, a column
    k_<var> per projected variable (a term uuid). MIN / MAX pick the term that
    sorts first under SPARQL's ordering exactly as today's SQL does
    (`emit_group.sparql_order_key`: kind, then number, then text under the SPARQL
    collation), here by the term's own uuid. Its advice items name its own
    relations; the extension maps them inside the sub-query's plan."""
    from .collation import collate
    from .emit_bgp import _NUMERIC_DT_SQL_LIST
    from .sql_type_generation import TypeRegistry
    from .emit_bgp import _NUMERIC_DATATYPES, _BOOLEAN_DT, _DATETIME_DATATYPES
    q = leaf.sub
    reg = q.region
    pos = _Pos(reg.plans, reg.values)
    tree = search(reg)
    r = _R(pos)
    core, _present, pend = _render_node(tree, reg, r)
    need = set(q.group_vars) | {a.expr.var for a in q.aggregates.values()}
    for v in need:
        if v not in r.bound:
            raise Unsupported(f"sub-SELECT: ?{v} is not bound by its plan")
    cols = [f"{r.bound[v]} AS k_{v}" for v in sorted(need)]
    joins: Dict[str, str] = {}                 # term alias -> the variable it decodes
    picks = []
    for out_var, ph in sorted(q.extend.items()):
        agg = q.aggregates[ph]
        v = agg.expr.var
        t = f"m_{leaf.alias}_{v}"
        if t not in joins:
            joins[t] = v
            tcols = TypeRegistry.term_table_columns(
                "mv", t, "x", _NUMERIC_DT_SQL_LIST, dt_case_sql=ctx.dt_case_expr(t),
                numeric_dt_id_list=ctx.dt_ids_for_uris(_NUMERIC_DATATYPES),
                boolean_dt_id=ctx.dt_ids_for_uris([_BOOLEAN_DT]),
                datetime_dt_id_list=ctx.dt_ids_for_uris(_DATETIME_DATATYPES))
            by = {c.rsplit(" AS ", 1)[1]: c.rsplit(" AS ", 1)[0] for c in tcols}
            cols += [f"CASE WHEN {by['mv__type']} = 'B' THEN 1 WHEN {by['mv__type']} = 'U' THEN 2 ELSE 3 END AS r_{v}",
                     f"{by['mv__num']} AS n_{v}", f"{by['mv']} AS x_{v}"]
        d = "DESC" if agg.name.upper() == "MAX" else "ASC"
        picks.append(f"(array_agg(k_{v} ORDER BY r_{v} {d}, n_{v} {d} NULLS LAST, "
                     f"{collate(f'x_{v}')} {d}))[1] AS k_{out_var}")
    tj = "".join(f"\n  JOIN {term_table} AS {t} ON {t}.term_uuid = {r.bound[v]}" for t, v in joins.items())
    inner = (f"SELECT {', '.join(cols)}\nFROM {core}{tj}" + ("\nWHERE " + " AND ".join(pend) if pend else ""))
    gk = [f"k_{v}" for v in q.group_vars]
    sql = f"SELECT {', '.join(gk + picks)}\nFROM ({inner}) AS g_{leaf.alias}\nGROUP BY {', '.join(gk)}"
    return _SubSql(sql=sql, sizes=list(r.sizes), units_adv=list(r.units_advice), methods=list(r.methods),
                   poses=[pos], base_sizes=_base_sizes(reg))


def render(q: Query, names: Dict[str, str], ctx, main_tree: Optional[Node] = None) -> Rendered:
    from .generator import substitute_constants
    reg = q.region
    pos = _Pos(reg.plans, reg.values)
    if pos.term_table is None:
        raise Unsupported("no term table")
    poses = [pos]
    # sub-SELECT leaves: their SQL is the leaf's table, their columns its positions
    subs: List[_SubSql] = []
    for u in reg.units:
        for l in u.leaves:
            if l.kind == "subq":
                s = _render_subq(l, ctx, pos.term_table)
                subs.append(s)
                pos.table[l.alias] = f"({s.sql})"
                for c, v in l.o_vars:
                    pos.positions.setdefault(v, []).append((l.alias, c))
                poses += s.poses
    for o in list(reg.optionals) + [a.region for a in reg.antis]:
        if any(l.kind == "subq" for u in o.units for l in u.leaves):
            raise Unsupported("a sub-SELECT inside an OPTIONAL or NOT EXISTS")
    tree = main_tree or search(reg)
    base_sizes = _base_sizes(reg)
    r = _R(pos)
    core, present, pend = _render_node(tree, reg, r)
    where = list(pend)
    sizes = list(r.sizes)
    units_adv = list(r.units_advice)
    methods = list(r.methods)
    for s in subs:
        sizes += s.sizes
        units_adv += s.units_adv
        methods += s.methods
        base_sizes += s.base_sizes
    rows = tree.rows
    anti_notes: List[str] = []
    # OPTIONAL blocks, each planned on its own, left-joined on the shared vars
    for opt in reg.optionals:
        opos = _Pos(opt.plans, opt.values)
        poses.append(opos)
        otree = search(opt)
        orr = _R(opos)
        osql, op, opend = _render_node(otree, opt, orr)
        conds = []
        for var in sorted(region_vars(opt)):
            if var in r.bound and var in orr.bound:
                conds.append(f"{orr.bound[var]} = {r.bound[var]}")
        if not conds:
            raise Unsupported("OPTIONAL shares no variable with the pattern")
        core = f"({core}\n LEFT JOIN {osql} ON " + " AND ".join(conds + opend) + ")"
        sizes += orr.sizes
        units_adv += orr.units_advice
        methods += orr.methods
        present |= op
        sizes.append((rows, sorted(present)))
        methods.append(("hash", sorted(present)))
        for v, c in orr.bound.items():
            r.bound.setdefault(v, c)
    # NOT EXISTS bodies. Two forms, scored against each other:
    #   correlated    a SubPlan per outer row: outer rows x the body's cost
    #                 when its correlated variables are bound (one row);
    #   decorrelated  the body as a set, its correlation conditions in its
    #                 WHERE, which PostgreSQL turns into an anti-join (it does
    #                 not when they sit in the body's ON clauses).
    for anti in reg.antis:
        body = anti.region
        fvars = set()
        def _fv(e):
            if type(e).__name__ == "ExprVar":
                fvars.add(e.var)
            for a in getattr(e, "args", None) or []:
                _fv(a)
        for f in anti.filters:
            _fv(f)
        corr = sorted((region_vars(body) | fvars) & set(r.bound))
        bpos = _Pos(body.plans, body.values)
        poses.append(bpos)
        set_tree = search(body)
        dec_cost = set_tree.cost + rows
        body.bound = {v: 1.0 for v in corr}
        row_tree = _search_bound(body, corr)
        cor_cost = rows * row_tree.cost
        if dec_cost <= cor_cost:
            br = _R(bpos)
            bsql, bp, bpend = _render_node(set_tree, body, br)
            outer_map = {v: r.bound[v] for v in corr}
            both = {**outer_map, **{k: v for k, v in br.bound.items() if k in region_vars(body)}}
            corr_eq = [f"{br.bound[v]} = {r.bound[v]}" for v in corr if v in br.bound and v in region_vars(body)]
            bconds = bpend + corr_eq + [_expr_sql(f, both) for f in anti.filters]
            form = "decorrelated"
        else:
            br = _R(bpos, outer={v: r.bound[v] for v in corr})
            bsql, bp, bpend = _render_node(row_tree, body, br)
            bconds = bpend + [_expr_sql(f, br.bound) for f in anti.filters]
            form = "correlated"
        bsql_full = f"SELECT 1 FROM {bsql}" + (" WHERE " + " AND ".join(bconds) if bconds else "")
        bsql_full = substitute_constants(bsql_full, body.aliases)
        where.append(f"NOT EXISTS ({bsql_full})")
        units_adv += br.units_advice
        sizes += br.sizes
        methods += br.methods
        anti_notes.append(f"NOT EXISTS {form} (decorrelated {dec_cost:,.0f} vs correlated {cor_cost:,.0f})")
    # ORDER BY ?v ... LIMIT n: sort-then-limit (the key set, sorted, cut) vs
    # an ordered walk of ?v's values with early stop. Scored, measured on
    # decision_page (results/early_stop_decision_page.md): 51k vs ~190k
    # predicted, 114 ms vs 6,237 ms measured. Only sort-then-limit is rendered;
    # the walk's estimate is recorded so a query where it wins is visible.
    if q.order and q.limit is not None and q.group_vars is None and not q.distinct \
            and q.order[0][0] not in q.extend:
        anti_notes.append(_early_stop_note(q, reg, tree, rows))
    # the key set
    agg_vars = {v: ph for v, ph in q.extend.items()}
    # A projected variable that no pattern of the query mentions is UNBOUND on every
    # row (`SELECT ?x WHERE { ... <const> ... }`): no key and no column, as today's
    # SQL (wordnet hub queries: the hub is a constant).
    mentioned = region_vars(reg)
    for o in reg.optionals:
        mentioned |= region_vars(o)
    unbound = {v for v in (q.project or []) if v not in agg_vars and v not in mentioned
               and v not in (q.group_vars or [])}
    q.order = [(v, d) for v, d in q.order if v not in unbound]
    term_vars = [v for v in (q.project or []) if v not in agg_vars and v not in unbound]
    need = set(term_vars) | set(q.group_vars or [])
    for ph, agg in q.aggregates.items():
        if agg.expr is not None:
            need.add(agg.expr.var)
    for v, _d in q.order:
        if v not in agg_vars:
            need.add(v)
    if q.sub_distinct and q.sub_project is None:
        raise Unsupported("DISTINCT below the GROUP without a sub-SELECT projection")
    if q.sub_project is not None:
        # an aggregate over a sub-SELECT: the outer query sees only its projection
        outside = need - set(q.sub_project)
        if outside:
            raise Unsupported(f"the outer query reads ?{', ?'.join(sorted(outside))}, not projected by its sub-SELECT")
        need = set(q.sub_project)
    for v in need:
        if v not in r.bound:
            raise Unsupported(f"?{v} is not bound by the plan")
    keys = [f"{r.bound[v]} AS k_{v}" for v in sorted(need)]
    inner = ("SELECT " + ("DISTINCT " if q.sub_distinct else "") + ", ".join(keys) + "\nFROM " + core
             + ("\nWHERE " + " AND ".join(where) if where else ""))
    level = inner
    out_keys = sorted(need)
    if q.group_vars is not None:
        gk = [f"k_{v}" for v in q.group_vars]
        aggs = []
        for ph, agg in q.aggregates.items():
            if agg.expr is None:
                aggs.append(f"COUNT(*) AS a_{_ph(ph)}")
            else:
                aggs.append(f"COUNT({'DISTINCT ' if agg.distinct else ''}k_{agg.expr.var}) AS a_{_ph(ph)}")
        agg_sql = {}
        for ph, agg in q.aggregates.items():
            agg_sql[ph] = ("COUNT(*)" if agg.expr is None else
                           f"COUNT({'DISTINCT ' if agg.distinct else ''}k_{agg.expr.var})")
        having = [_having_sql(h, q, agg_sql) for h in q.having]
        level = (f"SELECT {', '.join(gk + aggs)}\nFROM ({inner}) AS g0"
                 + (f"\nGROUP BY {', '.join(gk)}" if gk else "")
                 + (f"\nHAVING {' AND '.join(having)}" if having else ""))
        out_keys = list(q.group_vars)
    elif q.distinct:
        level = f"SELECT DISTINCT {', '.join(f'k_{v}' for v in term_vars)}\nFROM ({inner}) AS g0"
        out_keys = list(term_vars)
    # ORDER BY / LIMIT on the keys, values decoded after
    sort_joins, sort_cols = [], []
    for n, (v, d) in enumerate(q.order):
        if v in agg_vars:
            sort_cols.append((f"o.a_{_ph(agg_vars[v])}", d))
        elif q.synth_order:
            # the generator's own stable-paging order is by the term's UUID: the same
            # here, so consecutive pages agree whichever path renders each of them
            sort_cols.append((f"o.k_{v}", d))
        else:
            ts = f"s{n}"
            sort_joins.append(f"LEFT JOIN {pos.term_table} AS {ts} ON {ts}.term_uuid = o.k_{v}")
            sort_cols += [(f"{ts}.dt_val", d), (f"{ts}.num_val", d), (f"{ts}.term_text", d)]
    topsel = ["o.*"] + [f"{c} AS sk{i}" for i, (c, _d) in enumerate(sort_cols)]
    top = f"SELECT {', '.join(topsel)}\nFROM ({level}) AS o\n" + "\n".join(sort_joins)
    if sort_cols:
        top += "\nORDER BY " + ", ".join(f"sk{i} {d}" for i, (_c, d) in enumerate(sort_cols))
    if q.limit is not None:
        top += f"\nLIMIT {q.limit}"
    if q.offset:
        top += f" OFFSET {q.offset}"
    # decode, in the executor's column contract
    from .emit_bgp import (_BOOLEAN_DT, _DATETIME_DATATYPES, _NUMERIC_DATATYPES,
                           _NUMERIC_DT_SQL_LIST)
    from .sql_type_generation import TypeRegistry
    # Every output variable must be a column of the level the decode reads: a
    # mismatch is a planner defect, declined here rather than sent as SQL that fails.
    missing = [v for v in (q.project or []) if v not in agg_vars and v not in out_keys and v not in unbound]
    if missing:
        raise Unsupported(f"projected ?{', ?'.join(missing)} not produced by the plan's top level")
    cols, djoins = [], []
    for v in (q.project or []):
        if v in unbound:
            continue            # no column: the executor leaves an unbound variable out of the bindings
        sn = names.get(v)
        if sn is None:
            raise Unsupported(f"no SQL name for ?{v}")
        if v in agg_vars:
            a = f"top.a_{_ph(agg_vars[v])}"
            cols += [f"{a} AS {sn}", f"'L' AS {sn}__type", f"NULL::uuid AS {sn}__uuid",
                     f"NULL AS {sn}__lang", f"'{XSD_INTEGER}' AS {sn}__datatype",
                     f"{a} AS {sn}__num", f"NULL::boolean AS {sn}__bool", f"NULL::timestamp AS {sn}__dt"]
            continue
        t = f"d_{v}"
        djoins.append(f"LEFT JOIN {pos.term_table} AS {t} ON {t}.term_uuid = top.k_{v}")
        cols += [c.replace(f"top.{sn}__uuid", f"top.k_{v}") for c in TypeRegistry.term_table_columns(
            sn, t, "top", _NUMERIC_DT_SQL_LIST,
            dt_case_sql=ctx.dt_case_expr(t),
            numeric_dt_id_list=ctx.dt_ids_for_uris(_NUMERIC_DATATYPES),
            boolean_dt_id=ctx.dt_ids_for_uris([_BOOLEAN_DT]),
            datetime_dt_id_list=ctx.dt_ids_for_uris(_DATETIME_DATATYPES))]
    outer = f"SELECT {', '.join(cols)}\nFROM ({top}) AS top\n" + "\n".join(djoins)
    if sort_cols:
        outer += "\nORDER BY " + ", ".join(f"top.sk{i} {d}" for i, (_c, d) in enumerate(sort_cols))
    for opt in reg.optionals:
        base_sizes += _base_sizes(opt)
    for anti in reg.antis:
        base_sizes += _base_sizes(anti.region)
    # No base size for a leaf restricted by a sub-select filter (driving or not): alone,
    # its scan is NOT restricted (the filter applies when the sub-select's relation is
    # joined), and sizing it at the filtered rows made PostgreSQL hash a 437,000-row
    # scan it believed was 100 rows. Its restriction is priced in every set holding both.
    unfiltered = set().union(*(set(ps.sublink_parts) | ps.driven for ps in poses))
    sizes = [z for z in base_sizes if not (len(z[1]) == 1 and z[1][0] in unfiltered)] + sizes
    lines = ["/*vg:plan 1"]
    lines += [f"bgp u{i} {a}" for i, a in enumerate(units_adv)]
    subl: Dict[str, List[str]] = {}
    for ps in poses:
        for k, v in ps.sublinks.items():
            subl.setdefault(k, []).extend(x for x in v if x not in subl.get(k, []))

    def named(al: List[str]) -> List[str]:
        # a join set containing a leaf also contains the leaf's aliased sub-select
        # (a scan of the leaf alone does not: its size is the leaf's own)
        if len(al) < 2:
            return al
        return al + [x for a in al for x in subl.get(a, []) if x not in al]
    lines += [f"size k{i} {max(rws, 1):.0f} {' '.join(named(al))}" for i, (rws, al) in enumerate(sizes) if len(al) >= 1]
    # METHOD items: a leaf's sub-select is in the join's set only when PostgreSQL joins
    # it as a relation of that join (a driver; a unique column, reduced to an inner
    # join). A kept semi-join is its own node above, transparent to the extension:
    # with it, the set matched no join (`q0` probed, its slot-sort semi-join above).
    from .generator import substitute_constants as _subst
    from .qtree import SUBLINKS as _SL
    joined: Dict[str, List[str]] = {}         # leaf -> its sub-selects PostgreSQL joins as relations
    for ps in poses:
        for leaf, parts in ps.sublink_parts.items():
            for ra, tbl, sel, cond, _col, _f in parts:
                info = _SL.get((tbl, sel, _subst(cond, reg.aliases).strip())) or {}
                unique_alone = any(set(un) == {sel} for un in info.get("unique", []))
                if leaf in ps.driven or unique_alone:
                    joined.setdefault(leaf, []).append(ra)

    def mnamed(al: List[str]) -> List[str]:
        # a driver, or a sub-select on a unique column (reduced to an inner join): in
        # the join's set; a kept semi-join (non-unique): transparent to the extension
        return al + [x for a in al for x in joined.get(a, []) if x not in al]
    lines += [f"method m{i} {how} {' '.join(mnamed(al))}" for i, (how, al) in enumerate(methods) if len(al) >= 2]
    lines.append("*/")
    return Rendered(sql=outer, advice="\n".join(lines),
                    plan=describe(tree, reg) + "".join(f"; {n}" for n in anti_notes), cost=tree.cost)


def topk_driver(q: Query, reg: Region) -> Optional[Tuple[str, int]]:
    """(?v, unit index) of the variable a LIMIT page is walked by, when it is a
    unit's subject: the ORDER BY's first key, or the one projected variable."""
    if q.limit is None:
        return None
    pv = None
    if q.order:
        pv = q.order[0][0]
    elif q.project and len([v for v in q.project if v not in q.extend]) == 1:
        pv = next(v for v in q.project if v not in q.extend)
    d = next((i for i, u in enumerate(reg.units) if u.subject == f"?{pv}"), None)
    return None if d is None else (pv, d)


def topk_costs(q: Query, reg: Region, tree: Node,
               hit_rate: Optional[float] = None) -> Optional[Tuple[float, float, str]]:
    """(full plan cost, early-stop cost, note) for a LIMIT query whose rows are
    paged by one variable ?v that is a unit's subject, or None when there is no
    such driver.

    Early stop (today's SQL for such pages): walk the driver unit's rows in ?v's
    order and probe the rest of the pattern per row until `limit + offset`
    results are found. Rows walked = needed / (results per driver row), capped
    at the driver's rows; cost per walked row = a probe chain from the driver
    (greedy: each step the cheapest probe into an adjacent unit), divided over
    the driver's rows. The full plan computes every result and cuts.

    `hit_rate`: the share of driver rows that complete the whole pattern, as
    SAMPLED in walk order (`qcard.walk_hit_rate`). Without it the share is the
    plan's own result estimate over the driver's rows, and that is the number a
    chain of joins gets most wrong: on the KGQuery edge pages the pair-by-pair
    estimate was 11-20x low (a high-rated slot's edge belongs to the MQL frame
    always, not at the base rate), the walk read 11-20x too long, and the planner
    took pages today's early stop answers 1.4-10x faster."""
    drv = topk_driver(q, reg)
    if drv is None:
        return None
    pv, d = drv
    n = len(reg.units)
    card = _Card(reg)
    adj, by_pair = _mask_edges(reg)
    cur = _base(reg, d)
    while len(cur.units) < n:
        best = None
        for t in range(n):
            if t in cur.units:
                continue
            m = _mask(cur.units)
            edges = _edges_between(by_pair, m, 1 << t)
            if not edges:
                continue
            S = cur.units | {t}
            rows = card(_mask(S))
            for e in edges:
                fan = _probe_fan(e, t)
                if fan is None:
                    continue
                c = _probe_cost(cur, fan, rows, len(reg.units[t].leaves))
                if best is None or c < best.cost:
                    best = Node("probe", S, c, rows, {}, left=cur, unit=t, edge=e)
        if best is None:
            return None                  # not a pure probe chain from the driver: no early stop
        cur = best
    drows = reg.units[d].rows.rows or 0.0
    if drows <= 0:
        return None
    results = min(tree.rows, drows) if hit_rate is None else hit_rate * drows
    need = (q.limit or 0) + (q.offset or 0)
    walked = drows if results <= 0 else min(drows, need * drows / results)
    early = cur.cost * walked / drows
    return tree.cost, early, (f"top-k: full {tree.cost:,.0f} vs early stop {early:,.0f} "
                              f"(walk {walked:,.0f} of {drows:,.0f} ?{pv} for {need}"
                              + (f", sampled hit rate {hit_rate:.3g}" if hit_rate is not None else "") + ")")


def _early_stop_note(q: Query, reg: Region, tree: Node, rows: float) -> str:
    """Estimated C_out of walking the sort variable's values in order and
    probing the rest of the pattern per candidate until `limit` rows match."""
    v = q.order[0][0]
    holder = next((l for u in reg.units for l in u.leaves if l.o_var == v and l.kind == "quad"), None)
    if holder is None or not holder.pred_rows or not rows:
        return "early stop: unpriced"
    hit = min(1.0, rows / holder.pred_rows)          # candidates that survive the pattern
    walked = q.limit / hit
    per_hit = sum((_object_fan(next((l for l in u.leaves if l.o_var and l.o_var in
                                     {x.s_var for x in reg.units[0].leaves}), None)) or 1.0)
                  for u in reg.units[1:])
    per_hit += sum((_object_fan(next((l for l in o.units[0].leaves if l.o_var), None)) or 1.0)
                   for o in reg.optionals if o.units)
    early = walked * (1 + len(reg.units)) + q.limit * per_hit
    return f"order+limit: sort-then-limit {tree.cost:,.0f} vs early stop ~{early:,.0f}"


def _base_sizes(reg: Region) -> List[Tuple[float, List[str]]]:
    """A base size for EVERY leaf whose own constants the statistics price,
    whatever role it plays in the chosen plan. PostgreSQL may put any scan on
    the outer side of a join (join_collapse_limit keeps the tree, not the
    sides), and it estimates a (predicate, object) pin by multiplying column
    selectivities: 1 row for a 773-row frame-type pin, which made it rescan a
    whole OPTIONAL star per frame (results/calibration.md)."""
    out = []
    for u in reg.units:
        for l in u.leaves:
            if l.constant and l.scan.rows is not None:
                out.append((l.scan.rows, [l.alias]))
    return out


def _ph(ph: str) -> str:
    return ph.strip(".").replace(".", "_") or "0"


def _having_sql(h, q: Query, agg_sql: Dict[str, str]) -> str:
    t = type(h).__name__
    ops = {"eq": "=", "ne": "<>", "gt": ">", "ge": ">=", "lt": "<", "le": "<="}
    if t == "ExprFunction" and h.name in ops and len(h.args) == 2:
        a, b = h.args
        if type(a).__name__ == "ExprVar" and type(b).__name__ == "ExprValue":
            ph = a.var if a.var.startswith(".") else q.extend.get(a.var)
            lit = getattr(b.node, "value", None)
            if ph and lit is not None and re.fullmatch(r"-?\d+", str(lit)):
                return f"{agg_sql[ph]} {ops[h.name]} {int(lit)}"
    raise Unsupported(f"HAVING {h}")


def _search_bound(r: Region, corr: List[str]) -> Node:
    """DP for an EXISTS body whose correlated variables are bound per outer
    row: a pseudo-unit with one row binds them, and the plan starts there."""
    if not corr:
        return search(r)
    pseudo = Unit(subject="<outer>", leaves=[], anchor=None, rows=Est(1.0, "correlated"))
    n = len(r.units)
    units = r.units + [pseudo]
    edges = list(r.edges)
    for i, u in enumerate(r.units):
        for l in u.leaves:
            for c, ov in l.o_vars:
                if ov in corr:
                    edges.append(Edge(i, n, ov, "link_outer", l, col_u=c))
            if l.s_var in corr and l is u.anchor:
                edges.append(Edge(i, n, l.s_var, "subject_outer", l))
    rr = Region(units=units, edges=edges, values=r.values, plans=r.plans, aliases=r.aliases)
    best = {frozenset([n]): Node("scan", frozenset([n]), 0.0, 1.0, {v: 1.0 for v in corr}, unit=n)}
    for i, u in enumerate(r.units):
        best[frozenset([i])] = Node("scan", frozenset([i]), (u.rows.rows or 0) * len(u.leaves),
                                    u.rows.rows or 0, _unit_ndv(u, r.values, {}), unit=i)
    allu = list(range(n + 1))
    for size in range(2, n + 2):
        for combo in itertools.combinations(allu, size):
            S = frozenset(combo)
            cand = None
            for k in range(1, size):
                for left in itertools.combinations(sorted(S), k):
                    s1 = frozenset(left); s2 = S - s1
                    if s1 not in best or s2 not in best:
                        continue
                    es = [e for e in edges if (e.u in s1 and e.v in s2) or (e.u in s2 and e.v in s1)]
                    if not es:
                        continue
                    a, b = best[s1], best[s2]
                    rows, ndv = _join_rows(a, b, {e.var for e in es})
                    if n not in s2 and len(s2) == 1:     # probe into a body unit
                        t = next(iter(s2))
                        for e in es:
                            if e.kind == "link_outer":
                                fan = _object_fan(e.leaf_u, e.col_u)
                            elif e.kind == "subject_outer":
                                fan = 1.0
                            else:
                                fan = _probe_fan(e, t)
                            if fan is None:
                                continue
                            c = a.cost + a.rows * fan + rows * max(0, len(r.units[t].leaves) - 1)
                            if cand is None or c < cand.cost:
                                cand = Node("probe", S, c, rows, ndv, left=a, unit=t, edge=e)
                    if n not in s1 and n not in s2 and min(s1) < min(s2):
                        c = a.cost + b.cost + rows
                        if cand is None or c < cand.cost:
                            cand = Node("hash", S, c, rows, ndv, left=a, right=b)
            if cand is not None:
                best[S] = cand
    full = frozenset(allu)
    if full not in best:
        raise Unsupported("EXISTS body not reachable from its correlation")
    return _strip_pseudo(best[full], n)


def _strip_pseudo(node: Node, n: int) -> Node:
    """Remove the pseudo-unit: a probe from it becomes the body's first unit,
    entered through the correlated leaf (its conditions refer to the outer
    columns, which `_R(outer=...)` provides)."""
    if node.kind == "probe" and node.left.kind == "scan" and node.left.unit == n:
        return Node("probe_root", node.units - {n}, node.cost, node.rows, node.ndv,
                    unit=node.unit, edge=node.edge)
    if node.kind == "probe":
        return Node("probe", node.units - {n}, node.cost, node.rows, node.ndv,
                    left=_strip_pseudo(node.left, n), unit=node.unit, edge=node.edge)
    if node.kind == "hash":
        return Node("hash", node.units - {n}, node.cost, node.rows, node.ndv,
                    left=_strip_pseudo(node.left, n), right=_strip_pseudo(node.right, n))
    return node


_orig_render_node = _render_node


def _render_node(node: Node, reg: Region, r: _R):          # noqa: F811
    if node.kind == "probe_root":
        u = reg.units[node.unit]
        first = node.edge.leaf_u
        rest = [l for l in [u.anchor] + list(u.probes) if l is not first]
        present: Set[str] = set()
        fan = (_object_fan(first, node.edge.col_u) or 1.0) if node.edge.kind == "link_outer" else 1.0
        sql, pend = _chain(r, [first] + rest, present, None, [])
        # the root's prefixes, per outer row: the probe's candidates, then its result
        acc = [first.alias]
        for i, x in enumerate(rest):
            acc.append(x.alias)
            r.sizes.append((fan if i == 0 and len(rest) > 1 else node.rows, sorted(acc)))
        return sql, present, pend
    return _orig_render_node(node, reg, r)

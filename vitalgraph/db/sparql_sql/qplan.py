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
                 KIND_SLICE, KIND_TABLE, KIND_UNION)
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
    # sampled sizes of whole join PREFIXES of a chosen plan (`qcard.annotate_paths`):
    # unit mask -> rows. Pairs sampled one at a time miss correlation along a chain
    # (a high-rated slot's edge always belongs to the MQL frame: 11-20x low on the
    # KGQuery edge chains); a prefix sampled as a whole does not.
    path_rows: Dict[int, Est] = field(default_factory=dict)
    # FILTER expressions over the region's own rows (a comparison, IN, a string or
    # date function, ...), evaluated on VALUE columns (`_value_level`, render).
    filters: List[Any] = field(default_factory=list)
    # `?v != <iri>`: a term-identity test, rendered on the uuid column (var, uuid or
    # None for an IRI the term table does not hold, which every bound ?v differs from)
    iri_ne: List[Tuple[str, Optional[str]]] = field(default_factory=list)
    # BIND(expr AS ?v), in evaluation order: a COMPUTED value (not a term), carried as
    # its own companion columns (`_value_level`); a plain copy of a bound variable is
    # an alias of its key instead (keeps term identity)
    binds: List[Tuple[str, Any]] = field(default_factory=list)
    # leaf alias as the IR names it -> as this region renders it: a UNION branch whose
    # patterns another branch also holds under the same aliases (`_union_leaf`)
    rename: Dict[str, str] = field(default_factory=dict)


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
    # top-level BIND / SELECT (expr AS ?v) above the pattern, outermost first
    binds: List[Tuple[str, Any]] = field(default_factory=list)


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
                if seen_group:
                    raise Unsupported("an expression over aggregates or group keys (C3)")
                q.binds.append((p.extend_var, e))     # SELECT (expr AS ?v), BIND above the pattern
            else:
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
    if q.binds:
        # evaluated innermost first: the loop above met them outermost first
        from .var_scope import compute_scope
        visible = set(compute_scope(p).all_visible)
        for v, e in reversed(q.binds):
            if _expr_vars(e) - visible:
                raise Unsupported("a BIND reads a variable not bound below it")
            if v in visible:
                raise Unsupported(f"BIND to ?{v}, already bound")
            visible.add(v)
        q.region.binds = q.region.binds + list(reversed(q.binds))
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
            l.kind in ("subq", "union", "vtable") for u in q.region.units for l in u.leaves):
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
                if l.kind in ("subq", "union"):
                    (_subq_price if l.kind == "subq" else _union_price)(l)
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
    parts = {"leaves": [], "values": {}, "plans": [], "optionals": [], "antis": [], "exclude": exclude, "ctx": ctx,
             "filters": [], "iri_ne": [], "binds": [], "opt_left": []}
    _collect(p, ctx, aliases, parts, outer_vars)
    r = _build_region(parts, ctx, aliases)
    return r


def _collect(p, ctx, aliases, parts, outer_vars):
    st = _Stats(p, ctx)
    if p.kind == KIND_BGP:
        if any(col == "context_uuid" for slot in p.var_slots.values() for _a, col in slot.positions):
            # GRAPH ?g: the graph is a variable, with the generator's scoping rules
            # (the default graph is not a named one; `graph_scope_rewrite`). Not
            # planned yet (planning_planner/13, C4).
            raise Unsupported("a variable graph (GRAPH ?g)")
        seen = {_leaf_identity(l) for l in parts["leaves"]}
        for l in _leaves(p, ctx, st):
            if l.alias in parts["exclude"]:
                continue
            k = _leaf_identity(l)
            if k is not None and k in seen:
                # The same triple pattern twice (`:x ?p $v . :x ?p ?v`, $v and ?v being
                # one variable): one, as SPARQL's semantics allow. Joined, PostgreSQL 18
                # eliminated the redundant self-join and the advice named a join that
                # no longer existed.
                continue
            seen.add(k)
            parts["leaves"].append(l)
        parts["plans"].append(p)
    elif p.kind == KIND_JOIN:
        for c in p.children:
            _collect(c, ctx, aliases, parts, outer_vars)
    elif p.kind == KIND_TABLE and not p.values_vars and len(p.values_rows or []) == 1:
        pass                    # `{}`: one row binding nothing, the join's identity
    elif p.kind == KIND_TABLE and len(p.values_vars or []) > 1 and len(p.values_rows or []) == 1:
        # one row: a pin per variable. As a table PostgreSQL folds it into constants
        # and the joins the advice names are gone.
        leaf = _vtable_leaf(p, aliases, parts)
        vars_, rows = leaf.sub
        for i, v in enumerate(vars_):
            u = rows[0][i]
            if v in parts["values"]:
                raise Unsupported(f"two VALUES pins on ?{v}")
            parts["values"][v] = [u]
    elif p.kind == KIND_TABLE and len(p.values_vars or []) != 1:
        parts["leaves"].append(_vtable_leaf(p, aliases, parts))
    elif p.kind == KIND_TABLE:
        vars_ = p.values_vars or []
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
        if v in parts["values"]:
            raise Unsupported(f"two VALUES pins on ?{v}")
        parts["values"][v] = uuids
    elif p.kind == KIND_LEFT_JOIN:
        if p.left_join_exprs:
            raise Unsupported("OPTIONAL with a FILTER inside")
        _collect(p.children[0], ctx, aliases, parts, outer_vars)
        from .var_scope import compute_scope
        parts["optionals"].append(_region(p.children[1], ctx, aliases, outer_vars))
        parts["opt_left"].append(set(compute_scope(p.children[0]).all_visible))
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
            elif type(e).__name__ == "ExprExists":
                raise Unsupported("FILTER EXISTS (planning_planner/13, C2)")
            else:
                # A FILTER reads only its own group: a variable bound only OUTSIDE it is
                # unbound inside (an error, so false), and joining first would bind it.
                from .var_scope import compute_scope
                visible = compute_scope(p.children[0]).all_visible
                if _expr_vars(e) - set(visible):
                    raise Unsupported("a FILTER reads a variable its group does not bind")
                if _expr_has_exists(e):
                    raise Unsupported("FILTER with EXISTS inside an expression (C2)")
                for c in _conjuncts(e):
                    ne = _iri_exclusion(c, aliases)
                    if ne is not None:
                        # `?p != <iri>`: on the uuid, no term row needed (the entity-graph
                        # fetch joined a term row for every ?p to compare text: 52 -> 64 ms)
                        parts["iri_ne"].append(ne)
                        continue
                    r = _iri_restriction(c, aliases)
                    if r is None:
                        parts["filters"].append(c)
                        continue
                    # `?v IN (<iri>, ...)`, `?v = <iri>`, sameTerm: for IRIs, equality is
                    # term identity, so this IS a VALUES restriction, priced from the stored
                    # pairs and pushed into the patterns holding ?v. As a FILTER after the
                    # joins it read every quad first: `?s ?p ?o FILTER(?s IN (...))` 1.2 ms
                    # today, 1,792 ms planned.
                    v, uuids = r
                    if v in parts["values"]:
                        uuids = [u for u in uuids if u in set(parts["values"][v])]
                    if not uuids:
                        raise Unsupported("a FILTER restricts to terms absent from the term table (the generator's empty path)")
                    parts["values"][v] = uuids
    elif p.kind == KIND_EXTEND:
        # BIND(expr AS ?v) inside a group: sees only what its group bound BEFORE it
        _collect(p.children[0], ctx, aliases, parts, outer_vars)
        from .var_scope import compute_scope
        visible = set(compute_scope(p.children[0]).all_visible)
        if p.extend_var in visible:
            raise Unsupported(f"BIND to ?{p.extend_var}, already bound")
        if _expr_vars(p.extend_expr) - visible:
            raise Unsupported("a BIND reads a variable its group has not bound before it")
        if _expr_has_exists(p.extend_expr):
            raise Unsupported("BIND with EXISTS (C2)")
        parts["binds"].append((p.extend_var, p.extend_expr))
    elif p.kind == KIND_PROJECT:
        # a grouped sub-SELECT joined into the pattern: one leaf, its own plan
        parts["leaves"].append(_subq_leaf(p, parts["ctx"], parts["exclude"]))
    elif p.kind == KIND_UNION:
        parts["leaves"].append(_union_leaf(p, ctx, aliases, parts, outer_vars))
    else:
        raise Unsupported(f"{p.kind} inside the pattern")


@dataclass
class _Union:
    branches: List[Region]
    vars: List[str]                 # every variable a branch binds
    certain: Set[str]               # bound by every branch: the only ones it joins on


def _union_leaf(p, ctx, aliases, parts, outer_vars) -> Leaf:
    """`{ A } UNION { B } ...` as one leaf of the pattern: each branch a region,
    planned and rendered on its own, the leaf the UNION ALL of their key sets, a
    column k_<var> per variable any branch binds (NULL where a branch does not:
    unbound). It joins the rest of the pattern only on variables EVERY branch binds
    (`_build_region` declines otherwise: joining an unbound one is compatible with
    anything, not equality). Never probed into (no index). Sized and priced by
    `_union_price`."""
    flat = []

    def walk(x):
        if x.kind == KIND_UNION:
            for c in x.children:
                walk(c)
        else:
            flat.append(x)
    walk(p)
    branches = []
    for b in flat:
        reg = _region(b, ctx, aliases, outer_vars, parts["exclude"])
        if not reg.units:
            raise Unsupported("a UNION branch with no pattern")
        if reg.optionals or reg.antis or reg.binds:
            raise Unsupported("a UNION branch with OPTIONAL, NOT EXISTS or BIND (C2)")
        if any(l.kind in ("subq", "union") for u in reg.units for l in u.leaves):
            raise Unsupported("a UNION branch with a sub-SELECT or a nested UNION")
        branches.append(reg)
    # `rewrite_distribute_union` copies the pattern joined to a UNION into every branch
    # under the SAME aliases (unique per SELECT, which is all SQL needs). The advice
    # names each relation once in the statement: a branch's colliding leaves are
    # renamed, the region's `rename` applying it to its BGPs' tables, constraints and
    # positions (`_Pos`), so everything that renders or samples it agrees.
    seen: Set[str] = set()
    for i, reg in enumerate(branches):
        for u in reg.units:
            for l in u.leaves:
                if l.alias in seen:
                    new = f"{l.alias}_{i}"
                    while new in seen:
                        new += "x"
                    reg.rename[l.alias] = new
                    l.alias = new
                seen.add(l.alias)
    bvars = [region_vars(reg) for reg in branches]
    all_vars = sorted(set().union(*bvars))
    certain = set.intersection(*bvars)
    first = min(l.alias for reg in branches for u in reg.units for l in u.leaves)
    leaf = Leaf(alias=f"un_{first}", kind="union", pred=None, s_var=None, o_var=None,
                s_const=None, o_const=None, scan=Est(None, "subq"), pred_rows=None,
                pred_objects=None, o_vars=[(f"k_{v}", v) for v in all_vars])
    leaf.sub = _Union(branches=branches, vars=all_vars, certain=certain)
    _union_price(leaf)
    return leaf


def _union_price(leaf: Leaf) -> None:
    """Rows: the branches' rows summed (UNION ALL keeps every one). A variable's
    distinct values: the branches' summed, at most the rows. Cost: the branches'."""
    rows, cost, ndv = 0.0, 0.0, {}
    for reg in leaf.sub.branches:
        tree = search(reg)
        rows += tree.rows
        cost += tree.cost
        b: Dict[str, float] = {}
        for u in reg.units:
            for v, n in _unit_ndv(u, reg.values, reg.bound).items():
                b[v] = min(b.get(v, n), n)
        for v in leaf.sub.vars:
            if v in region_vars(reg):
                ndv[v] = ndv.get(v, 0.0) + min(b.get(v, tree.rows), tree.rows)
    rows = max(rows, 1.0)
    leaf.scan = Est(rows, "subq")
    leaf.col_ndv = {f"k_{v}": max(1.0, min(n, rows)) for v, n in ndv.items()}
    leaf.sub_cost = cost


def _vtable_leaf(p, aliases, parts, vars_=None, rows=None) -> Leaf:
    """VALUES with several variables (or one no pattern holds) as a leaf of its own:
    an inline table of term uuids, keys only, one column `k_<v>` per variable, its
    rows the VALUES rows and each column's distinct values exact. Never probed into
    (no index). A row with a term the term table does not hold matches nothing in
    an inner join and is dropped; none left is the generator's empty path. UNDEF
    (compatible with anything) is not modelled yet."""
    vars_ = vars_ if vars_ is not None else list(p.values_vars or [])
    if not vars_:
        raise Unsupported("VALUES with no variable")
    cols = getattr(aliases, "constants", None) or {}
    resolved = getattr(aliases, "resolved_constants", None) or {}
    out = []
    for row in (rows if rows is not None else (p.values_rows or [])):
        vals = []
        for v in vars_:
            node = row.get(v) if isinstance(row, dict) else row[vars_.index(v)]
            if node is None:
                raise Unsupported("VALUES with UNDEF")
            if isinstance(node, str):
                vals.append(node)
                continue
            col = cols.get(_term_key(node))
            vals.append(resolved.get(col) if col else None)
        if all(u is not None for u in vals):
            out.append(vals)
    if not out:
        raise Unsupported("VALUES matches no stored term (today's provably-empty path handles it)")
    alias = "vt_" + "_".join(re.sub(r"\W", "", v) for v in vars_)[:30]
    taken = {l.alias for l in parts["leaves"]}
    while alias in taken:
        alias += "x"
    leaf = Leaf(alias=alias, kind="vtable", pred=None, s_var=None, o_var=None, s_const=None,
                o_const=None, scan=Est(float(len(out)), "values"), pred_rows=None, pred_objects=None,
                o_vars=[(f"k_{v}", v) for v in vars_],
                col_ndv={f"k_{v}": float(len({r_[i] for r_ in out})) for i, v in enumerate(vars_)})
    leaf.sub = (vars_, out)
    leaf.sub_cost = 0.01 * len(out)
    return leaf


def _vtable_sql(leaf: Leaf) -> str:
    vars_, rows = leaf.sub
    body = ", ".join("(" + ", ".join(f"'{u}'::uuid" for u in r_) + ")" for r_ in rows)
    return f"(SELECT * FROM (VALUES {body}) AS v({', '.join(f'k_{v}' for v in vars_)}))"


def _leaf_identity(l: Leaf):
    """What makes two quad leaves the same triple pattern, or None (a leaf with
    filters of its own, or a derived table, is never merged)."""
    if l.kind != "quad" or l.scan.rule in ("range", "fts", "in", "values", "values_bound"):
        return None
    return (l.pred, l.s_var, l.s_const, l.o_const, tuple(sorted(l.o_vars)))


def _term_key(node):
    t = type(node).__name__
    if t == "URINode":
        return (node.value, "U", None, None)
    if t == "LiteralNode":
        return (node.value, "L", getattr(node, "lang", None) or None, node.datatype or None)
    raise Unsupported(f"VALUES term of kind {t}")


def _build_region(parts, ctx, aliases) -> Region:
    leaves: List[Leaf] = parts["leaves"]
    # A constant predicate or object the term table does not hold matches nothing:
    # the generator answers that on its provably-empty path (no scan). Priced, the
    # leaf read the generator's estimate (100,000 for an absent entity type), and
    # the planner ran a parallel plan over nothing, 6 ms against 1.
    for l in leaves:
        if l.kind == "quad" and ((l.o_const and l.o_uuid is None) or (l.pred and l.pred_uuid is None)):
            raise Unsupported("a pattern constant absent from the term table (the generator's empty path)")
        if l.kind == "quad" and l.pred is None and l.s_fan is None:
            # a variable predicate the totals could not price (a space with no
            # statistics yet): its rows per subject are unknown, never guessed
            raise Unsupported("a variable-predicate pattern on a space without statistics")
    values = parts["values"]
    # VALUES pins: a leaf whose object is the VALUES variable is restricted to
    # those terms, priced exactly from rdf_stats where the pairs are stored.
    a = aliases
    quad_stats = getattr(a, "quad_stats", None) or {}
    extra = getattr(a, "extra_quad_stats", None) or {}
    for var, uuids in list(values.items()):
        holders = [l for l in leaves if any(v == var for _c, v in l.o_vars)]
        subject_holders = [l for l in leaves if l.s_var == var]
        if not holders and not subject_holders and len(uuids) == 1:
            raise Unsupported("a one-row VALUES binding no pattern (PostgreSQL folds it to a constant)")
        if not holders and not subject_holders:
            # no pattern holds it: the VALUES is a table of its own (a cross product)
            leaves.append(_vtable_leaf(None, aliases, parts, [var], [[u] for u in uuids]))
            del values[var]
            continue
        for l in subject_holders:
            # restricted on its SUBJECT: those subjects' rows of the pattern
            per = l.s_fan or 1.0
            rows = len(uuids) * per
            if l.scan.rows is None or rows < l.scan.rows:
                l.scan = Est(rows, "values")
        for l in holders:
            if l.kind in ("union", "subq", "vtable") and l.scan.rows:
                # a derived table: the pinned share of the column's distinct values
                col = next(c for c, v in l.o_vars if v == var)
                n = l.col_ndv.get(col) or l.scan.rows
                l.scan = Est(max(1.0, l.scan.rows * min(1.0, len(uuids) / n)), l.scan.rule)
                continue
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
    # Every OPTIONAL is attached after the region's joins. Join(LeftJoin(A, B), C) =
    # LeftJoin(Join(A, C), B) only when B shares no variable with C (or with another
    # OPTIONAL) that A does not bind: `?x :n "paul" {?y :n "george" OPTIONAL {?x :e ?z}}`
    # left-joins ?x inside the group, where ?x is free (the W3C "Join scope" test).
    required = {v for l in leaves for v in [l.s_var] + [ov for _c, ov in l.o_vars] if v} | set(values)
    for k, (o, left) in enumerate(zip(parts["optionals"], parts["opt_left"])):
        others = set(required)
        for k2, o2 in enumerate(parts["optionals"]):
            if k2 != k:
                others |= _region_all_vars(o2)
        if (_region_all_vars(o) & others) - left:
            raise Unsupported("an OPTIONAL shares a variable its own group does not bind")
    # A UNION variable some branch leaves unbound joins nothing by equality (unbound
    # is compatible with every value): read anywhere else in the region, decline.
    for l in leaves:
        if l.kind != "union":
            continue
        maybe = set(l.sub.vars) - l.sub.certain
        if not maybe:
            continue
        other = {v for x in leaves if x is not l for v in [x.s_var] + [ov for _c, ov in x.o_vars] if v}
        for o in parts["optionals"]:
            other |= _region_all_vars(o)
        for a_ in parts["antis"]:
            other |= _region_all_vars(a_.region) | set().union(*(_expr_vars(f) for f in a_.filters))
        for f in parts.get("filters", []):
            other |= _expr_vars(f)
        for _v, e in parts.get("binds", []):
            other |= _expr_vars(e)
        other |= {v for v, _u in parts.get("iri_ne", [])} | set(values)
        if maybe & other:
            raise Unsupported("a UNION variable some branch leaves unbound is joined or read outside it")
    binds = parts.get("binds", [])
    if binds:
        # a BIND's variable joining a pattern would join a computed value to stored
        # terms: not planned yet (a value-to-term join)
        pattern_vars = {v for l in leaves for v in [l.s_var] + [ov for _c, ov in l.o_vars] if v}
        for o in parts["optionals"]:
            pattern_vars |= region_vars(o)
        for a in parts["antis"]:
            pattern_vars |= region_vars(a.region)
        if pattern_vars & {v for v, _e in binds}:
            raise Unsupported("a BIND's variable is joined by a pattern")
    return Region(units=units, edges=edges, values=values, plans=parts["plans"],
                  aliases=aliases, optionals=parts["optionals"], antis=parts["antis"],
                  filters=parts.get("filters", []), iri_ne=parts.get("iri_ne", []), binds=binds)


def _conjuncts(e) -> List[Any]:
    """`a && b && c` as [a, b, c]."""
    if type(e).__name__ == "ExprFunction" and e.name in ("and", "logical-and") and len(e.args) == 2:
        return _conjuncts(e.args[0]) + _conjuncts(e.args[1])
    return [e]


def _iri_exclusion(e, aliases):
    """(?v, uuid or None) for `?v != <iri>` / `<iri> != ?v`, or None. For an IRI,
    != is the negation of term identity, so it is a uuid comparison; an unbound
    ?v is false either way (SPARQL: an error; SQL: NULL <> x is NULL)."""
    if type(e).__name__ != "ExprFunction" or e.name != "ne" or len(e.args or []) != 2:
        return None
    a, b = e.args
    if type(a).__name__ != "ExprVar":
        a, b = b, a
    if type(a).__name__ != "ExprVar" or type(b).__name__ != "ExprValue" \
            or type(getattr(b, "node", None)).__name__ != "URINode":
        return None
    # The term's uuid is deterministic (uuid5 of the IRI), whether or not the term
    # table holds it; an IRI it does not hold is matched by no row, so `v <> uuid` is
    # true for every bound ?v, as SPARQL says. (A FILTER's IRIs are not registered as
    # constants: the generator compares them as text.)
    from .bgp_cardinality import _iri_uuid
    return a.var, _iri_uuid(b.node.value)


def _iri_restriction(e, aliases) -> Optional[Tuple[str, List[str]]]:
    """(?v, term uuids) for `?v IN (<iri>, ...)`, `?v = <iri>` / `<iri> = ?v` or
    `sameTerm(?v, <iri>)` where every constant is an IRI, or None. IRIs only: a
    literal `=` compares VALUES ("1"^^xsd:int = "1.0"^^xsd:decimal), not terms.
    An IRI the term table does not hold matches nothing and is dropped."""
    if type(e).__name__ != "ExprFunction" or e.name not in ("in", "eq", "sameterm"):
        return None
    args = list(e.args or [])
    if len(args) < 2:
        return None
    if e.name != "in" and type(args[0]).__name__ != "ExprVar":
        args = [args[1], args[0]]
    if type(args[0]).__name__ != "ExprVar":
        return None
    consts = args[1:]
    if not all(type(c).__name__ == "ExprValue" and type(getattr(c, "node", None)).__name__ == "URINode"
               for c in consts):
        return None
    # deterministic uuids (uuid5 of the IRI): an IRI the term table does not hold
    # matches nothing, which is what SPARQL says of it
    from .bgp_cardinality import _iri_uuid
    return args[0].var, [_iri_uuid(c.node.value) for c in consts]


def _value_level(reg: Region, ctx, r: "_R", core: str, where: List[str], need: List[str],
                 distinct: bool, term_table: str, computed: List[Tuple[str, Any]],
                 out_computed: List[str]) -> str:
    """The region's rows with its BINDs computed and its FILTERs applied, as a level
    of keys (`k_<v>`, term uuids) plus the computed variables' companion columns
    (`c_<v>`, `c_<v>__type`, ...) for `out_computed`.

    VALUE COLUMNS (planning_planner/13, C1.2-C1.3): the planner carries term uuids
    only; a FILTER or a BIND needs values. Each variable they read gets its term
    row's columns under the generator's own companion names, and every expression
    is the GENERATOR's: `expr_to_sql` / `infer_expr_type` / `produce_companions` and
    emit_extend's companion patches for a BIND, `ebv_sql` for a FILTER, each in the
    scope of what it may read. One translator: the planner and the generator cannot
    disagree on a SPARQL function, its type errors or its collations.

    The core joins are their own level, fenced (OFFSET 0), and the term rows join to
    ITS rows: flattened, a FILTER's condition on a term column made the term join
    inner and PostgreSQL drove from the whole term table (`?s ?p ?o FILTER(?s IN
    (...) && ?p != ...)`: 2.1 s, today's SQL 1 ms). The advice applies inside the fence."""
    from types import SimpleNamespace
    from .emit_bgp import (_BOOLEAN_DT, _DATETIME_DATATYPES, _NUMERIC_DATATYPES,
                           _NUMERIC_DT_SQL_LIST)
    from .emit_expressions import ebv_sql, expr_to_sql
    from .emit_extend import _patch_concat_companions, _patch_strafter_strbefore_companions
    from .sql_type_generation import COMPANION_SUFFIXES, ColumnInfo, TypeRegistry, infer_expr_type
    cvars = {v for v, _e in computed}
    read = set().union(*(_expr_vars(e) for e in reg.filters), *(_expr_vars(e) for _v, e in computed)) - cvars
    fvars = sorted(read)
    for v in fvars:
        if v not in r.bound:
            raise Unsupported(f"an expression reads ?{v}, which the plan does not bind")
    bind_vars = sorted(set(need) | set(fvars))
    core_level = ("SELECT " + (", ".join(f"{r.bound[v]} AS b_{v}" for v in bind_vars) or "1 AS one")
                  + "\nFROM " + core + ("\nWHERE " + " AND ".join(where) if where else "") + "\nOFFSET 0")
    cols = [f"cq.b_{v} AS k_{v}" for v in need]
    joins = []
    types = TypeRegistry(aliases=ctx.aliases)
    for i, v in enumerate(fvars):
        sn, t = f"fv{i}", f"tf{i}"
        joins.append(f"LEFT JOIN {term_table} AS {t} ON {t}.term_uuid = cq.b_{v}")
        tc = TypeRegistry.term_table_columns(
            sn, t, "FSUB", _NUMERIC_DT_SQL_LIST, dt_case_sql=ctx.dt_case_expr(t),
            numeric_dt_id_list=ctx.dt_ids_for_uris(_NUMERIC_DATATYPES),
            boolean_dt_id=ctx.dt_ids_for_uris([_BOOLEAN_DT]),
            datetime_dt_id_list=ctx.dt_ids_for_uris(_DATETIME_DATATYPES))
        cols += [c.replace(f"FSUB.{sn}__uuid", f"cq.b_{v}") for c in tc]
        types.register(ColumnInfo.simple_output(v, sn, from_triple=True))
    fctx = ctx.child(types=types)
    before = len(getattr(fctx, "_unresolved_vars", None) or [])
    level = ("SELECT " + (", ".join(cols) or "1 AS one") + f"\nFROM ({core_level}) AS cq"
             + ("\n" + "\n".join(joins) if joins else ""))
    # BINDs, in order: each a level adding its companion columns (a later one may read it)
    visible = set(fvars)
    for i, (v, e) in enumerate(computed):
        with fctx.expression_scope(set(visible)):
            sql_e = expr_to_sql(e, fctx)
        if not sql_e:
            raise Unsupported(f"a BIND expression the translator does not support: {type(e).__name__}")
        typed = infer_expr_type(e, fctx.types)
        ns = SimpleNamespace(extend_expr=e, extend_var=v)
        _patch_strafter_strbefore_companions(ns, fctx, typed)
        _patch_concat_companions(ns, fctx, typed)
        sn = f"c_{v}"
        level = (f"SELECT lv{i}.*, " + ", ".join(typed.produce_companions(sn, sql_e))
                 + f"\nFROM ({level}) AS lv{i}")
        fctx.types.register_extend(v, typed, sn)
        visible.add(v)
    # FILTERs (`emit_filter`'s way: the effective boolean value, scoped)
    conds = []
    with fctx.expression_scope(set(visible)):
        for e in reg.filters:
            c = ebv_sql(e, fctx)
            if not c:
                raise Unsupported(f"a FILTER expression the translator does not support: {type(e).__name__}")
            conds.append(f"({c})")
    if len(getattr(fctx, "_unresolved_vars", None) or []) > before:
        raise Unsupported("an expression reads a variable the value columns do not provide")
    out = [f"k_{v}" for v in need] + [f"c_{v}{suf}" for v in out_computed for suf in ("",) + COMPANION_SUFFIXES]
    return ("SELECT " + ("DISTINCT " if distinct else "") + (", ".join(out) or "1 AS one")
            + f"\nFROM ({level}) AS fl" + ("\nWHERE " + " AND ".join(conds) if conds else ""))


def _expr_vars(e) -> Set[str]:
    """The variables an expression reads (an EXISTS body's own are its own)."""
    out: Set[str] = set()

    def walk(x):
        t = type(x).__name__
        if t == "ExprVar":
            out.add(x.var)
        elif t == "ExprExists":
            return
        for a in getattr(x, "args", None) or []:
            walk(a)
        if getattr(x, "expr", None) is not None and t != "ExprVar":
            walk(x.expr)
    walk(e)
    return out


def _expr_has_exists(e) -> bool:
    if type(e).__name__ == "ExprExists":
        return True
    return any(_expr_has_exists(a) for a in (getattr(e, "args", None) or []))


def _region_all_vars(r: Region) -> Set[str]:
    """A region's pattern variables, its OPTIONALs' included."""
    out = region_vars(r)
    for o in r.optionals:
        out |= _region_all_vars(o)
    return out


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
        self.paths: Dict[int, float] = {m: e.rows for m, e in r.path_rows.items() if e.rows is not None}

    def __call__(self, mask: int) -> float:
        """rows(S). With sampled prefixes (`Region.path_rows`): the largest sampled
        subset P of S, scaled by what the pairwise model says S adds to P,
        rows(P) * indep(S) / indep(P), so a correlation measured on a prefix
        carries to every set containing it, and rows stay split-independent."""
        v = self._indep(mask)
        if self.paths:
            best = None
            for p in self.paths:
                if p & mask == p and (best is None or bin(p).count("1") > bin(best).count("1")):
                    best = p
            if best is not None:
                base = self._indep(best)
                v = self.paths[best] * (v / base) if base > 0 else self.paths[best]
        return v

    def _indep(self, mask: int) -> float:
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
    if u.anchor is not None and u.anchor.kind in ("subq", "vtable", "union"):
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
        comps = _components(n, adj)
        if len(comps) < 2 or any(c not in best for c in comps):
            raise Unsupported("the units are not connected")
        return _cross_all([best[c] for c in comps], card)
    return best[full]


def _components(n: int, adj: List[int]) -> List[int]:
    """The connected groups of units, as masks."""
    seen, out = 0, []
    for i in range(n):
        if seen >> i & 1:
            continue
        m, todo = 1 << i, [i]
        while todo:
            x = todo.pop()
            for j in _bits(adj[x] & ~m):
                m |= 1 << j
                todo.append(j)
        seen |= m
        out.append(m)
    return out


def _cross(a: Node, b: Node, card: "_Card") -> Node:
    """Patterns that share no variable: a cross product (SPARQL's join of
    compatible mappings with nothing in common is every pair), each side planned on
    its own. Rows: the product (the size function's, no selectivity between them);
    cost: both sides plus the rows produced."""
    S = a.units | b.units
    rows = card(_mask(S))
    out = rows if COST_MODEL == "cout" else rows * W["join_out_row"]
    return Node("cross", S, a.cost + b.cost + out, rows, {}, left=a, right=b)


def _cross_all(nodes: List[Node], card: "_Card") -> Node:
    nodes = sorted(nodes, key=lambda x: x.rows)
    node = nodes[0]
    for other in nodes[1:]:
        node = _cross(node, other, card)
    return node


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
            # nothing left shares a variable: cross the smallest two
            x, y = sorted(parts, key=lambda k: parts[k].rows)[:2]
            nd = _cross(parts[x], parts[y], card)
            del parts[x], parts[y]
            parts[x | y] = nd
            continue
        x, y = best_pair
        del parts[x], parts[y]
        parts[x | y] = best_node
    return next(iter(parts.values()))


def describe(node: Node, r: Region) -> str:
    if node.kind == "scan":
        return r.units[node.unit].subject
    if node.kind == "hash":
        return f"({describe(node.left, r)} ⋈ {describe(node.right, r)})"
    if node.kind == "cross":
        return f"({describe(node.left, r)} × {describe(node.right, r)})"
    return f"({describe(node.left, r)} →{node.edge.var} {r.units[node.unit].subject})"


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_ALIAS = re.compile(r"\b([a-z][a-z0-9_]*[0-9])\.")


class _Pos:
    """Positions, filters and table names of one region's BGPs, plus the
    region's VALUES restrictions as filters on the leaves that hold them."""
    def __init__(self, plans, values: Optional[Dict[str, List[str]]] = None,
                 rename: Optional[Dict[str, str]] = None):
        rn = rename or {}
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
                    self.table[rn.get(t.alias, t.alias)] = t.table_name
            for owner, sql in p.tagged_constraints:
                if rn:
                    owner = rn.get(owner, owner)
                    sql = _ALIAS.sub(lambda m: rn.get(m.group(1), m.group(1)) + ".", sql)
                refs = set(_ALIAS.findall(sql))
                if refs <= {owner}:
                    self.filters.setdefault(owner, []).append(self._name_sublink(owner, sql))
                elif not re.fullmatch(r"\s*\w+\.\w+ = \w+\.\w+\s*", sql):
                    raise Unsupported(f"cross-table condition that is not a variable equality: {sql}")
            for var, slot in p.var_slots.items():
                for pos in slot.positions:
                    pos = (rn.get(pos[0], pos[0]),) + tuple(pos[1:])
                    if pos[0] in self.table:
                        self.positions.setdefault(var, []).append(pos)
        for var, uuids in (values or {}).items():
            lits = ", ".join(f"'{u}'::uuid" for u in uuids)
            for a, col in self.positions.get(var, []):
                self.filters.setdefault(a, []).append(f"{a}.{col} IN ({lits})")


def _pos_of(reg: "Region") -> "_Pos":
    return _Pos(reg.plans, reg.values, reg.rename)


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


#: `unit_methods`: advise a nested loop into a constant leaf only when its own scan
#: is at least this many times the rows probing it.
UNIT_NL_RATIO = 10.0


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
        from .planner_ext import FEATURES as _F
        if _F.get("unit_methods") and drv is not None:
            # In a unit DRIVEN from a selective sub-select (a name search, a range), a
            # probed CONSTANT leaf whose own scan is at least UNIT_NL_RATIO times the rows
            # probing it gets a nested-loop item: probing reads a small fraction of what
            # scanning would. Left to PostgreSQL, the KG entity count with a name search
            # SCANNED the type pin's 100,000 rows by bitmap and hashed them, where 2,038
            # probes were needed (149 ms, today's SQL 22 ms). Only there, measured: a
            # nested loop on every probed leaf overrode the hash joins PostgreSQL rightly
            # chose inside the dashboard units (all_of 11 -> 21 ms), and by the ratio
            # alone, in a unit started from its own anchor (l6_const_value 42 -> 65 ms).
            probes = order[1 + len(hashed):]
            prefix = [l.alias for l in order[:1 + len(hashed)]]
            cur = (min(drv[2], drv[0].scan.rows) if drv[0].scan.rows else drv[2]) if drv is not None \
                else (order[0].scan.rows or u.rows.rows or 0.0)
            for i, l in enumerate(probes):
                if l.constant and l.scan.rows and cur * UNIT_NL_RATIO <= l.scan.rows:
                    r.methods.append(("nl", sorted(prefix + [p.alias for p in probes[:i + 1]])))
                cur = min(cur, u.rows.rows or cur)
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
    if node.kind == "cross":
        # no join condition, so no hash or merge: a size, and no method item (an
        # advised hash would match no join PostgreSQL can build)
        present = lp | rp
        r.sizes.append((node.rows, sorted(present)))
        return f"({lsql}\n JOIN {rsql} ON " + " AND ".join(rpend or ["TRUE"]) + ")", present, lpend
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
    if reg.filters or reg.iri_ne or reg.binds:
        raise Unsupported("a FILTER or BIND inside a sub-SELECT (C3)")
    pos = _pos_of(reg)
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


def _derived_tables(reg: Region, pos: "_Pos", ctx, subs: List["_SubSql"], poses: List["_Pos"]) -> Set[str]:
    """Register the region's sub-SELECT, UNION and VALUES leaves in `pos`: each
    one's SQL is its table, its columns its variables' positions. Their own advice
    goes to `subs`, their positions to `poses`. Returns the UNION variables some
    branch leaves unbound."""
    maybe: Set[str] = set()
    for u in reg.units:
        for l in u.leaves:
            if l.kind == "vtable":
                pos.table[l.alias] = _vtable_sql(l)
            elif l.kind in ("subq", "union"):
                s = (_render_subq if l.kind == "subq" else _render_union)(l, ctx, pos.term_table)
                subs.append(s)
                pos.table[l.alias] = f"({s.sql})"
                poses += s.poses
                if l.kind == "union":
                    maybe |= set(l.sub.vars) - l.sub.certain
            else:
                continue
            for c, v in l.o_vars:
                pos.positions.setdefault(v, []).append((l.alias, c))
                if v in reg.values:
                    # the region's VALUES pin holds here too: `_Pos` applied it to the
                    # BGPs' positions only, and a UNION binding ?t went unrestricted
                    lits = ", ".join(f"'{u_}'::uuid" for u_ in reg.values[v])
                    pos.filters.setdefault(l.alias, []).append(f"{l.alias}.{c} IN ({lits})")
    return maybe


def _render_union(leaf: Leaf, ctx, term_table: str) -> _SubSql:
    """A UNION leaf's own SQL: each branch planned and rendered as a key set
    (its FILTERs on value columns, `_value_level`), NULL for a variable it does
    not bind, the branches joined by UNION ALL. Each branch's advice items name its
    own relations."""
    un = leaf.sub
    sqls, sizes, units_adv, methods, poses, base = [], [], [], [], [], []
    for i, reg in enumerate(un.branches):
        pos = _pos_of(reg)
        pos.term_table = pos.term_table or term_table
        _derived_tables(reg, pos, ctx, [], [])
        tree = search(reg)
        r = _R(pos)
        core, _present, pend = _render_node(tree, reg, r)
        where = list(pend)
        mine = sorted(v for v in un.vars if v in region_vars(reg))
        for v in mine:
            if v not in r.bound:
                raise Unsupported(f"UNION branch: ?{v} is not bound by its plan")
        for v, u_ in reg.iri_ne:
            if v not in r.bound:
                raise Unsupported(f"a FILTER reads ?{v}, which the plan does not bind")
            where.append(f"{r.bound[v]} <> '{u_}'::uuid" if u_ else f"{r.bound[v]} IS NOT NULL")
        if reg.filters:
            inner = _value_level(reg, ctx, r, core, where, mine, False, term_table, [], [])
            cols = [f"ub{i}.k_{v}" if v in mine else f"NULL::uuid AS k_{v}" for v in un.vars]
            sqls.append(f"SELECT {', '.join(cols)}\nFROM ({inner}) AS ub{i}")
        else:
            cols = [f"{r.bound[v]} AS k_{v}" if v in mine else f"NULL::uuid AS k_{v}" for v in un.vars]
            sqls.append(f"SELECT {', '.join(cols)}\nFROM {core}" + ("\nWHERE " + " AND ".join(where) if where else ""))
        sizes += r.sizes
        units_adv += r.units_advice
        methods += r.methods
        poses.append(pos)
        base += _base_sizes(reg)
    sql = "\nUNION ALL\n".join(f"({s})" for s in sqls)
    return _SubSql(sql=sql, sizes=sizes, units_adv=units_adv, methods=methods, poses=poses, base_sizes=base)


def render(q: Query, names: Dict[str, str], ctx, main_tree: Optional[Node] = None) -> Rendered:
    from .generator import substitute_constants
    reg = q.region
    pos = _pos_of(reg)
    if pos.term_table is None:
        # the pattern is a UNION (or holds one): the term table of its branches
        pos.term_table = next((_Pos(b.plans).term_table for u in reg.units for l in u.leaves
                               if l.kind == "union" for b in l.sub.branches if _Pos(b.plans).term_table), None)
    if pos.term_table is None:
        raise Unsupported("no term table")
    poses = [pos]
    # sub-SELECT, UNION and VALUES leaves: their SQL is the leaf's table
    subs: List[_SubSql] = []
    maybe_vars = _derived_tables(reg, pos, ctx, subs, poses)
    if maybe_vars & {v for v, _d in q.order}:
        # unbound sorts first in SPARQL; a NULL key sorts last here
        raise Unsupported("ORDER BY a variable a UNION branch leaves unbound")
    outer_vars_ = region_vars(reg)
    for o in list(reg.optionals) + [a.region for a in reg.antis]:
        if o.filters or o.iri_ne or o.binds:
            raise Unsupported("a FILTER or BIND inside an OPTIONAL or NOT EXISTS body (C2)")
    tree = main_tree or search(reg)
    base_sizes = _base_sizes(reg)
    r = _R(pos)
    core, present, pend = _render_node(tree, reg, r)
    where = list(pend)
    sizes = list(r.sizes)
    units_adv = list(r.units_advice)
    methods = list(r.methods)
    rows = tree.rows
    anti_notes: List[str] = []
    late = _late_optional_ok(q, reg, r)
    late_opts: List[Tuple[str, List[str], "_R", List[str], int]] = []   # (LATERAL sql, page join columns, its _R, its projected vars, index)
    # OPTIONAL blocks, each planned on its own, left-joined on the shared vars
    for oi, opt in enumerate(reg.optionals):
        opos = _pos_of(opt)
        opos.term_table = opos.term_table or pos.term_table
        poses.append(opos)
        if _derived_tables(opt, opos, ctx, subs, poses) & outer_vars_:
            raise Unsupported("an OPTIONAL joins on a variable a UNION branch leaves unbound")
        if late:
            # Joined after the cut, in one of two forms, scored like a NOT EXISTS body:
            #   set         the OPTIONAL built once and hash-joined to the page rows;
            #   correlated  planned with its join variables bound and rendered as a
            #               LATERAL subquery, each page row probing its own rows.
            # Measured on category_page: correlated was 381 ms against the set's 93,
            # because the only way to "the slot of type T of entity d" is through d's
            # ~1,000 graph members (per row), while the set reads T's ~965 slots once.
            corr = sorted(v for v in region_vars(opt) if v in r.bound)
            if not corr:
                raise Unsupported("OPTIONAL shares no variable with the pattern")
            page = float(q.limit + (q.offset or 0))
            set_tree = search(opt)
            set_cost = set_tree.cost + _hash_cost(Node("scan", frozenset(), 0.0, page, {}), set_tree, page) - set_tree.cost
            opt.bound = {v: 1.0 for v in corr}
            row_tree = _search_bound(opt, corr)
            cor_cost = page * row_tree.cost
            correlated = cor_cost < set_cost
            if correlated:
                orr = _R(opos, outer={v: f"pg_late.k_{v}" for v in corr})
                osql, op, opend = _render_node(row_tree, opt, orr)
                where_ = opend
            else:
                orr = _R(opos)
                osql, op, opend = _render_node(set_tree, opt, orr)
                where_ = opend
            pvars = sorted(v for v in orr.bound if v not in corr)
            jvars = corr if not correlated else []
            sel = ", ".join(f"{orr.bound[v]} AS k_{v}" for v in pvars + jvars) or "1 AS one"
            sub = (f"(SELECT {sel}\n FROM {osql}" + (f"\n WHERE {' AND '.join(where_)}" if where_ else "")
                   + f") AS lo{oi}")
            if correlated:
                lsql = f"LATERAL {sub} ON TRUE"
            else:
                lsql = f"{sub} ON " + " AND ".join(f"lo{oi}.k_{v} = pg_late.k_{v}" for v in corr)
            late_opts.append((lsql, [f"pg_late.k_{v}" for v in corr], orr, pvars, oi))
            anti_notes.append(f"OPTIONAL {oi} {'correlated' if correlated else 'set'} "
                              f"(set {set_cost:,.0f} vs correlated {cor_cost:,.0f})")
            sizes += orr.sizes
            units_adv += orr.units_advice
            methods += orr.methods
            continue
        otree = search(opt)
        orr = _R(opos)
        osql, op, opend = _render_node(otree, opt, orr)
        conds = []
        for var in sorted(region_vars(opt)):
            if var in r.bound and var in orr.bound:
                conds.append(f"{orr.bound[var]} = " + (f"pg_late.k_{var}" if late else r.bound[var]))
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
        bpos = _pos_of(body)
        bpos.term_table = bpos.term_table or pos.term_table
        poses.append(bpos)
        if _derived_tables(body, bpos, ctx, subs, poses) & (outer_vars_ | set().union(*(_expr_vars(f) for f in anti.filters))):
            raise Unsupported("a NOT EXISTS reads a variable a UNION branch leaves unbound")
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
    # the derived leaves' own advice (the OPTIONALs' and NOT EXISTS bodies' included)
    for s in subs:
        sizes += s.sizes
        units_adv += s.units_adv
        methods += s.methods
        base_sizes += s.base_sizes
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
    # BINDs: a copy of a bound variable is an alias of its key (it keeps its term
    # identity); anything else is COMPUTED, carried as companion columns
    computed: List[Tuple[str, Any]] = []
    for v, e in reg.binds:
        mentioned.add(v)
        if type(e).__name__ == "ExprVar" and e.var in r.bound and not computed:
            r.bound[v] = r.bound[e.var]
        else:
            computed.append((v, e))
    cvars = {v for v, _e in computed}
    if cvars and q.group_vars is not None:
        raise Unsupported("GROUP BY with a computed BIND (C3)")
    if cvars & {v for v, _d in q.order}:
        raise Unsupported("ORDER BY a computed BIND (C3)")
    if q.project is None and q.group_vars is None:
        # SELECT * (no PROJECT in the algebra): every variable the pattern binds, in
        # the generator's order (`names` follows its var_map). Without this the
        # select list was EMPTY: PostgreSQL accepts `SELECT FROM ...`, so the
        # planner returned the right number of rows with no bindings in them (DAWG
        # open-world/date-3, open-eq-02; no query in the dashboard corpus is SELECT *).
        q.project = [v for v in names if v in mentioned] + sorted(v for v in mentioned if v not in names)
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
    late_vars: List[str] = []           # projected variables only the OPTIONALs bind (late mode)
    if late:
        opt_bound = {v for _s, _c, _o, pv, _i in late_opts for v in pv}
        late_vars = [v for v in term_vars if v not in r.bound and v in opt_bound]
        need -= set(late_vars)
        # the page carries every variable an OPTIONAL joins on
        for _s, jcols, _o, _p, _i in late_opts:
            need |= {c.rsplit("pg_late.k_", 1)[1] for c in jcols}
    need -= cvars
    out_computed = [v for v in term_vars if v in cvars]
    for v in need:
        if v not in r.bound:
            raise Unsupported(f"?{v} is not bound by the plan")
    keys = [f"{r.bound[v]} AS k_{v}" for v in sorted(need)]
    for v, u in reg.iri_ne:
        if v not in r.bound:
            raise Unsupported(f"a FILTER reads ?{v}, which the plan does not bind")
        where.append(f"{r.bound[v]} <> '{u}'::uuid" if u else f"{r.bound[v]} IS NOT NULL")
    if reg.filters or computed:
        inner = _value_level(reg, ctx, r, core, where, sorted(need), q.sub_distinct, pos.term_table,
                             computed, out_computed)
    else:
        inner = ("SELECT " + ("DISTINCT " if q.sub_distinct else "") + ", ".join(keys) + "\nFROM " + core
                 + ("\nWHERE " + " AND ".join(where) if where else ""))
    level = inner
    out_keys = sorted(need) + out_computed
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
        dvars = [v for v in term_vars if v not in late_vars]
        if late:
            dvars += sorted(need - set(dvars))      # the join variables ride along (projected: checked)
        from .sql_type_generation import COMPANION_SUFFIXES as _CS
        dcols = [f"k_{v}" for v in dvars if v not in cvars] + [
            f"c_{v}{suf}" for v in dvars if v in cvars for suf in ("",) + _CS]
        level = f"SELECT DISTINCT {', '.join(dcols)}\nFROM ({inner}) AS g0"
        out_keys = list(term_vars)
    if late:
        out_keys = sorted(set(out_keys) | set(late_vars))
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
    if late:
        # The page of the REQUIRED part, offset included, then the OPTIONALs joined onto
        # those rows only, then the real page. Each page row yields at least one row
        # after a LEFT JOIN, so the first limit+offset results come from the first
        # limit+offset page rows (`_late_optional_ok` holds the rest).
        top += f"\nLIMIT {q.limit + (q.offset or 0)}"
        cols = ["pg_late.*"] + [
            f"lo{next(i for _s, _c, _o, pv, i in late_opts if v in pv)}.k_{v}" for v in late_vars]
        joined = f"({top}) AS pg_late"
        for lsql, _jc, _o, _pv, _i in late_opts:
            joined = f"{joined}\n LEFT JOIN {lsql}"
        late_sql = f"SELECT {', '.join(cols)}\nFROM {joined}"
        if q.distinct:
            late_sql = f"SELECT DISTINCT *\nFROM ({late_sql}) AS d_late"
        top = (f"SELECT *\nFROM ({late_sql}) AS o_late\nORDER BY "
               + ", ".join(f"sk{i} {d}" for i, (_c, d) in enumerate(sort_cols))
               + f"\nLIMIT {q.limit}" + (f" OFFSET {q.offset}" if q.offset else ""))
        sizes.append((float(q.limit + (q.offset or 0)), ["pg_late"]))
        anti_notes.append(f"OPTIONALs joined after the cut ({len(late_opts)} onto {q.limit + (q.offset or 0)} rows)")
    else:
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
        if v in cvars:
            # a computed value: its own companion columns, as the generator produced them
            from .sql_type_generation import COMPANION_SUFFIXES as _CS
            cols += [f"top.c_{v}{suf} AS {sn}{suf}" for suf in ("",) + _CS]
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


def _late_optional_ok(q: Query, reg: Region, r: "_R") -> bool:
    """Whether a page may be cut on its REQUIRED part before its OPTIONALs are
    joined, with the same result: an ORDER BY ... LIMIT page (no GROUP, no
    sub-SELECT projection) whose sort keys are all bound by the required part,
    whose NOT EXISTS bodies read none of the OPTIONALs' own variables, and, under
    DISTINCT, whose OPTIONALs join only on projected variables (so deduplicating
    the page first and the joined rows after agree). Each page row then yields at
    least one row after the LEFT JOINs, so the first k results come from the
    first k page rows; a multi-valued OPTIONAL is cut again after the join."""
    from .planner_ext import FEATURES as _F
    if not _F.get("late_optional") or not reg.optionals or q.limit is None or not q.order:
        return False
    if reg.filters or reg.iri_ne or reg.binds:
        return False                    # a FILTER or BIND may read an OPTIONAL's variables
    if q.group_vars is not None or q.sub_project is not None or q.having:
        return False
    if any(v in q.extend or v not in r.bound for v, _d in q.order):
        return False
    core = set(r.bound)
    opt_only = set().union(*(region_vars(o) for o in reg.optionals)) - core
    if any(region_vars(a.region) & opt_only for a in reg.antis):
        return False
    if q.distinct:
        proj = set(q.project or [])
        if any(v not in proj for v, _d in q.order):
            return False                    # a sort key in the page's DISTINCT would change it
        for o in reg.optionals:
            if (region_vars(o) & core) - proj:
                return False
    return True


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
    if node.kind in ("hash", "cross"):
        return Node(node.kind, node.units - {n}, node.cost, node.rows, node.ndv,
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

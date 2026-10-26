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
from typing import Any, Dict, List, Optional, Tuple

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
    kind: str                       # quad | edge | frame_slot | subq
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
    # Rows per SUBJECT when the predicate is a VARIABLE (`?s ?p ?o` probed by its
    # subject): a subject has many predicates, so a unit's rows multiply by this
    # (`_unit`). None for a constant predicate, one value per subject.
    s_fan: Optional[float] = None
    # distinct predicates, for a variable predicate's column (`ndv("predicate_uuid")`)
    pred_ndv: Optional[float] = None
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
    # A grouped sub-SELECT inside the pattern (kind "subq", `qplan._subq_leaf`): its
    # own query, planned and rendered on its own; one row per group, its projected
    # variables as columns k_<var>; no index, so never probed into. `sub_cost`: the
    # inner plan's cost plus the grouping.
    sub: Any = None
    sub_cost: float = 0.0
    # distinct graphs (contexts) of its quad table, for a GRAPH ?g variable's column
    ctx_ndv: Optional[float] = None

    @property
    def constant(self) -> bool:
        """Restricted by its own constants (object, IN, range, FTS, a derived
        row's constant columns), so it can anchor a unit without probing anything."""
        return self.o_const is not None or self.scan.rule in (
            "range", "fts", "in", "values", "values_bound", "derived_count", "subq", "anchorless")

    def fan(self, col: Optional[str]) -> Optional[float]:
        """Rows one index probe of this leaf reads, by column `col`."""
        if self.kind == "quad" and col == "context_uuid":
            # probed by graph: the predicate's rows in one graph
            return (self.pred_rows / self.ctx_ndv) if self.pred_rows and self.ctx_ndv else None
        if self.kind == "quad":
            if self.probe_fan:
                return self.probe_fan
            return (self.pred_rows / self.pred_objects) if self.pred_rows and self.pred_objects else None
        return self.col_fan.get(col) if col else None

    def ndv(self, col: Optional[str]) -> Optional[float]:
        """Distinct values of the variable at `col` (quad: the predicate's objects, or
        the distinct predicates for a variable predicate's column)."""
        if self.kind == "quad" and col == "context_uuid":
            return self.ctx_ndv
        if self.kind == "quad":
            return self.pred_ndv if col == "predicate_uuid" else self.pred_objects
        return self.col_ndv.get(col)

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

#: PostgreSQL's statistics for the derived tables, loaded by `qcard.load_derived`
#: before analysis (one catalog read per table, cached until the space's stats are
#: invalidated):
#:   DERIVED_STATS[table] = {"rows": reltuples, "ndv": {column: distinct},
#:                           "mcv": {column: {value uuid: frequency}}}
DERIVED_STATS: Dict[str, dict] = {}

#: Leaf filters of the form `alias.col IN (SELECT sel FROM tbl WHERE cond)` (a
#: term range, a slot-sort fast path), loaded by `qcard.load_derived`:
#:   SUBLINKS[(tbl, sel, cond)] = {"rows": PostgreSQL's estimate of the sub-select,
#:                                 "cols": tbl's columns, "unique": [unique column sets]}
#: so the planner can DRIVE a unit from the most selective one (qplan render).
SUBLINKS: Dict[Tuple[str, str, str], dict] = {}
SUBLINK_RE = re.compile(r"^\s*(\w+)\.(\w+) IN \(SELECT (\w+) FROM (\w+) WHERE (.+)\)\s*$", re.S)

#: A derived column that IS a quad pair's object, so a constant on it is priced
#: from that pair's stored count (`rdf_stats`), exactly: the derived tables' own
#: definitions (sync_frame_slot_table, sync_edge_table), not any query's schema.
#: Measured on wordnet: frame_slot rows per role 285,348 = the (hasKGSlotType,
#: role) pair, where a capped count saturated at 50,000.
DERIVED_PAIR_COLUMNS = {
    ("frame_slot", "role_uuid"): "http://vital.ai/ontology/haley-ai-kg#hasKGSlotType",
    ("edge", "edge_type_uuid"): "http://vital.ai/ontology/vital-core#vitaltype",
}


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
        if p_term is None or (s_term is not None and a not in card):
            # A VARIABLE predicate, or a constant subject the generator does not
            # price: from the quad table's own totals (qcard.load_derived).
            vl = _anchorless_leaf(t, a, p_term, p_uuid, o_term, s_term, var_at, st)
            if vl is not None:
                n_s = _subject_in_count(a, filters_by.get(a, []), ctx)
                if n_s and vl.s_fan:
                    # `?s ?p ?o` restricted to a list of subjects: those subjects' rows.
                    # Priced as the whole table, the graph fetch of three entities
                    # (7,446,550 estimated, 20 actual) had PostgreSQL hash the term table.
                    vl.scan = Est(min(vl.scan.rows, n_s * vl.s_fan), "in")
                out.append(vl)
                continue
        rule = ("range" if a in range_aliases else "fts" if a in fts
                else "pair" if o_term else "pred")
        scan = Est(card.get(a), rule if a in card else "unpriced")
        in_est = _in_list_rows(a, p_uuid, filters_by.get(a, []), ctx, st)
        if in_est is not None:
            scan = in_est
        n_s = _subject_in_count(a, filters_by.get(a, []), ctx)
        if n_s and (scan.rows is None or n_s < scan.rows):
            scan = Est(float(n_s), "in")    # one value per listed subject
        out.append(Leaf(
            alias=a, kind=t.kind,
            pred=str(p_term[0]) if p_term else None,
            s_var=var_at.get((a, "subject_uuid")), o_var=var_at.get((a, "object_uuid")),
            s_const=str(s_term[0]) if s_term else None, o_const=str(o_term[0]) if o_term else None,
            scan=scan,
            pred_rows=st.pred_rows.get(p_uuid) if p_uuid else None,
            pred_objects=st.pred_objects.get(p_uuid) if p_uuid else None,
            pred_uuid=p_uuid,
            probe_fan=st.size_biased_fan(p_uuid),
            o_uuid=st.uuid_of(o_term) if o_term else None,
            # the predicate's variable too, whichever path prices the leaf: dropped, a
            # FILTER-ed `?s ?p ?o` on a space with no statistics yet returned its
            # triples WITHOUT their predicates (an entity read back with no properties)
            o_vars=([("object_uuid", var_at[(a, "object_uuid")])] if (a, "object_uuid") in var_at else [])
                   + ([("predicate_uuid", var_at[(a, "predicate_uuid")])]
                      if p_term is None and (a, "predicate_uuid") in var_at else [])
                   + _graph_var(a, var_at),
            ctx_ndv=_ctx_ndv(t)))
    return out


def _anchorless_leaf(t, a, p_term, p_uuid, o_term, s_term, var_at, st: "_Stats") -> Optional[Leaf]:
    """A quad leaf with a VARIABLE predicate (`?s ?p ?o`, `?s ?p <o>`, `<s> ?p ?o`), or
    a constant subject the generator does not price (`<s> :p ?o`), priced from what
    the statistics hold. None (unpriced) when the quad table's totals are not loaded.

      variable predicate   rows: total quads; with a constant object, the stored
                           (predicate, object) pairs for that object, summed (else
                           total / distinct objects); with a constant subject, total
                           / distinct subjects. Per subject: total / distinct subjects
                           (`s_fan`); per object probe: total / distinct objects.
      constant subject     rows: the predicate's rows / distinct subjects, at least 1.

    Once they declined outright: ~170 of the W3C suite's queries, ~78 of the API
    suite's (`planning_planner/13`, C1.1)."""
    # Total quads: our own statistics first (rdf_stats' per-predicate rows, maintained
    # with the data), PostgreSQL's reltuples second (it lags until ANALYZE, and is
    # -1 or 0 for a table never analyzed: the W3C harness reloads one per test).
    q = DERIVED_STATS.get(t.table_name) or {}
    total = float(sum(st.pred_rows.values())) if st.pred_rows else 0.0
    if total <= 0:
        total = float(q.get("rows") or 0.0)
    if total <= 0:
        return None
    nd = q.get("ndv", {})
    n_s = nd.get("subject_uuid") or total
    n_o = nd.get("object_uuid") or total
    n_p = nd.get("predicate_uuid") or 1.0
    o_uuid = st.uuid_of(o_term) if o_term else None
    s_uuid = st.uuid_of(s_term) if s_term else None
    if o_term and o_uuid is None or s_term and s_uuid is None:
        return None                       # absent constant: qplan declines it (empty path)
    o_vars = []
    if (a, "object_uuid") in var_at:
        o_vars.append(("object_uuid", var_at[(a, "object_uuid")]))
    if p_term is None:
        if (a, "predicate_uuid") in var_at:
            o_vars.append(("predicate_uuid", var_at[(a, "predicate_uuid")]))
        if o_term:
            pairs = [c for (p, o), c in st.quad_stats.items() if o == o_uuid]
            rows = float(sum(pairs)) if pairs else total / max(n_o, 1.0)
        else:
            rows = total
        if s_term:
            rows = max(1.0, min(rows, total / max(n_s, 1.0)))
        pred_rows, pred_objects, s_fan = total, n_o, total / max(n_s, 1.0)
        probe_fan = total / max(n_o, 1.0)
    else:
        prow = st.pred_rows.get(p_uuid) if p_uuid else None
        if prow is None:
            return None
        rows = max(1.0, float(prow) / max(n_s, 1.0))
        if o_term:
            rows = 1.0
        pred_rows, pred_objects, s_fan = float(prow), st.pred_objects.get(p_uuid), None
        probe_fan = st.size_biased_fan(p_uuid)
    return Leaf(
        alias=a, kind=t.kind,
        pred=str(p_term[0]) if p_term else None,
        s_var=var_at.get((a, "subject_uuid")), o_var=var_at.get((a, "object_uuid")),
        s_const=str(s_term[0]) if s_term else None, o_const=str(o_term[0]) if o_term else None,
        scan=Est(rows, "anchorless"), pred_rows=pred_rows, pred_objects=pred_objects,
        pred_uuid=p_uuid, probe_fan=probe_fan, o_uuid=o_uuid, o_vars=o_vars + _graph_var(a, var_at),
        s_fan=s_fan, pred_ndv=n_p, ctx_ndv=_ctx_ndv(t))


def _graph_var(a, var_at) -> List[Tuple[str, str]]:
    """GRAPH ?g: the leaf's context column is a variable like any other (the
    generator's scoping, the default graph excluded, is in its constraints)."""
    return [("context_uuid", var_at[(a, "context_uuid")])] if (a, "context_uuid") in var_at else []


def _ctx_ndv(t) -> Optional[float]:
    q = DERIVED_STATS.get(getattr(t, "table_name", None)) or {}
    n = (q.get("ndv") or {}).get("context_uuid")
    return float(n) if n else None


def _subject_in_count(alias: str, filters: List[str], ctx) -> Optional[int]:
    """How many subjects a leaf is restricted to by `alias.subject_uuid IN (...)`,
    the generator's pushed-down `FILTER(?s IN (<iri>, ...))`, or None."""
    from .generator import substitute_constants
    for f in filters:
        m = re.match(rf"\s*{re.escape(alias)}\.subject_uuid\s+IN\s*\((.*)\)\s*$",
                     substitute_constants(f, ctx.aliases), re.S)
        if m:
            # a LIST of uuid literals only: `subject_uuid IN (SELECT ...)` is a sub-select,
            # and counting the one constant inside it priced a 100,000-row entity pin at 1
            # (the rating_990 count went 44 -> 347 ms)
            items = [x.strip() for x in m.group(1).split(",")]
            if items and all(re.fullmatch(r"'[0-9a-f-]{36}'::uuid", x) for x in items):
                return len(items)
            return None
    return None


def _in_list_rows(alias: str, p_uuid: Optional[str], filters: List[str], ctx, st: "_Stats") -> Optional[Est]:
    """A quad leaf restricted to a list of objects (`object_uuid IN (...)`, the
    generator's pushed-down VALUES) priced as the sum of its pairs' stored
    counts; a pair absent from rdf_stats is bounded by the predicate's smallest
    stored pair, as VALUES pins are (qplan._build_region). The generator's own
    leaf estimate is the whole predicate: lead 100k's `?state IN ("CA" "TX")`
    read 1,150,000 rows where rdf_stats says 9,227 + 7,259 = 16,486, the actual
    count, so the unit anchored on a 100,000-row pin instead."""
    if not p_uuid:
        return None
    from .generator import substitute_constants
    for f in filters:
        m = re.match(rf"\s*{re.escape(alias)}\.object_uuid\s+IN\s*\((.*)\)\s*$",
                     substitute_constants(f, ctx.aliases), re.S)
        if not m:
            continue
        objs = re.findall(r"'([0-9a-f-]{36})'::uuid", m.group(1))
        if not objs or len(objs) != m.group(1).count("::uuid"):
            return None
        a_ = ctx.aliases
        extra = getattr(a_, "extra_quad_stats", None) or {}
        counts = [st.quad_stats.get((p_uuid, o), extra.get((p_uuid, o))) for o in objs]
        if all(n is not None for n in counts):
            return Est(float(sum(counts)), "in")
        stored = [n for (pp, _o), n in st.quad_stats.items() if pp == p_uuid]
        if not stored:
            return None
        low = min(stored)
        return Est(float(sum(n if n is not None else low for n in counts)), "values_bound")
    return None


def _term_uuid(text: str) -> str:
    """A URI term's uuid, as the loaders and sync_frame_slot_table derive it."""
    import uuid as _uuid
    return str(_uuid.uuid5(_uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8"), f"{text}\x00U"))


def _column_sel(st: dict, col: str, val: str) -> float:
    """Fraction of a derived table's rows with `col = val`, from PostgreSQL's
    statistics: the most-common-value frequency, else the rest spread evenly
    over the other distinct values."""
    mcv = (st.get("mcv") or {}).get(col) or {}
    if val in mcv:
        return mcv[val]
    nd = (st.get("ndv") or {}).get(col)
    if not nd:
        return 1.0
    rest = max(0.0, 1.0 - sum(mcv.values()))
    return rest / max(nd - len(mcv), 1.0) if mcv else 1.0 / nd


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
    scan = Est(rows, "derived" if rows is not None else "unpriced")
    # constant columns beyond the graph (role, frame type, edge type): priced from
    # the stored pair counts where the column is a quad pair's object, else from
    # PostgreSQL's per-column statistics on the table
    from .generator import substitute_constants
    consts = {}
    for f in filters:
        m = re.match(rf"\s*{re.escape(a)}\.(\w+)\s*=\s*'([0-9a-f-]{{36}})'::uuid\s*$",
                     substitute_constants(f, ctx.aliases))
        if m and m.group(1) != "context_uuid":
            consts[m.group(1)] = m.group(2)
    if consts and rows:
        a_ = ctx.aliases
        pairs = dict(getattr(a_, "quad_stats", None) or {})
        pairs.update(getattr(a_, "extra_quad_stats", None) or {})
        stored, sel = None, 1.0
        for col, val in consts.items():
            pred = DERIVED_PAIR_COLUMNS.get((t.kind, col))
            n = pairs.get((_term_uuid(pred), val)) if pred else None
            if n is not None:
                stored = n if stored is None else min(stored, n)
            else:
                sel *= _column_sel(st, col, val)
        est = (float(stored) if stored is not None else rows) * sel
        scan = Est(est, "derived_count")
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
    # a VARIABLE-predicate probe reads every predicate of the subject: rows multiply
    fan = 1.0
    for l in probes:
        if l.s_fan:
            fan *= l.s_fan
    if fan != 1.0 and rows.rows is not None:
        rows = Est(rows.rows * fan, rows.rule + "*s_fan")
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

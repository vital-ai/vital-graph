"""
v2 IR dataclasses — nested plan tree mirroring SPARQL algebra evaluation order.

Produced by collect.py, consumed by the v2 emitter (future).

This module is 100% isolated from v1 pipeline code. All IR infrastructure
is defined locally. Sidecar AST types (Expr, GroupVar, ExprAggregator) are
imported from jena_types — the shared sidecar interface, not v1 pipeline code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ..jena_sparql.jena_types import Expr, ExprAggregator, GroupVar


# ===========================================================================
# Alias Generator
# ===========================================================================

class AliasGenerator:
    """Produces unique SQL table aliases: q0, q1, ... for quads; t0, t1, ..."""

    def __init__(self, alias_prefix: str = ""):
        self._counters: Dict[str, int] = {}
        self._alias_prefix = alias_prefix
        # Constant term lookups: maps (term_text, term_type) → column alias
        self.constants: Dict[Tuple[str, str], str] = {}
        self._const_counter: int = 0
        # Resolved after materialize phase: col_name → uuid string
        self.resolved_constants: Dict[str, str] = {}
        # Graph lock: when set, every quad table is constrained to this context_uuid
        self.graph_lock_uri: Optional[str] = None
        # Default graph: applied to outer BGPs only (not inside GRAPH clauses).
        # SPARQL dataset semantics — separates default graph from named graphs.
        self.default_graph: Optional[str] = None
        # Predicate cardinality stats
        self.quad_stats: Dict[Tuple[str, str], int] = {}
        self.pred_stats: Dict[str, int] = {}
        # SPARQL→SQL variable name mapping: opaque sql_name → original sparql_name
        self.var_map: Dict[str, str] = {}
        self._var_counter: int = 0

    def next(self, prefix: str = "q") -> str:
        n = self._counters.get(prefix, 0)
        self._counters[prefix] = n + 1
        return f"{self._alias_prefix}{prefix}{n}"

    def next_var(self, sparql_name: str) -> str:
        """Allocate an opaque SQL column name for a SPARQL variable."""
        sql_name = f"{self._alias_prefix}v{self._var_counter}"
        self._var_counter += 1
        self.var_map[sql_name] = sparql_name
        return sql_name

    def register_constant(self, term_text: str, term_type: str) -> str:
        """Register a constant term lookup for CTE batching."""
        key = (term_text, term_type)
        if key not in self.constants:
            col = f"c_{self._const_counter}"
            self._const_counter += 1
            self.constants[key] = col
        return self.constants[key]


# ===========================================================================
# Table & Variable Slots
# ===========================================================================

@dataclass
class TableRef:
    """A reference to a quad or term table."""
    ref_id: str          # Logical ID (e.g. "q0", "t3")
    kind: str            # "quad" or "term"
    table_name: str      # e.g. "lead_test_rdf_quad"
    join_col: str = ""   # For term tables: quad column to join on
    alias: str = ""      # SQL alias


@dataclass
class VarSlot:
    """A SPARQL variable's binding positions."""
    name: str
    # (table_ref_id, uuid_col_name) — e.g. ("q0", "subject_uuid")
    positions: List[Tuple[str, str]] = field(default_factory=list)
    # Term table ref_id for the primary binding
    term_ref_id: Optional[str] = None
    # Resolved columns (set during emit)
    uuid_col: Optional[str] = None
    text_col: Optional[str] = None
    type_col: Optional[str] = None
    partial: bool = False


# ---------------------------------------------------------------------------
# Plan kind constants
# ---------------------------------------------------------------------------

# Relation kinds (leaf or binary — produce rows from data)
KIND_BGP = "bgp"
KIND_JOIN = "join"
KIND_LEFT_JOIN = "left_join"
KIND_UNION = "union"
KIND_MINUS = "minus"
KIND_TABLE = "table"
KIND_NULL = "null"
KIND_PATH = "path"

RELATION_KINDS = frozenset({
    KIND_BGP, KIND_JOIN, KIND_LEFT_JOIN, KIND_UNION,
    KIND_MINUS, KIND_TABLE, KIND_NULL, KIND_PATH,
})

# Modifier kinds (unary — wraps exactly one child)
KIND_PROJECT = "project"
KIND_DISTINCT = "distinct"
KIND_REDUCED = "reduced"
KIND_SLICE = "slice"
KIND_ORDER = "order"
KIND_FILTER = "filter"
KIND_EXTEND = "extend"
KIND_GROUP = "group"

MODIFIER_KINDS = frozenset({
    KIND_PROJECT, KIND_DISTINCT, KIND_REDUCED, KIND_SLICE,
    KIND_ORDER, KIND_FILTER, KIND_EXTEND, KIND_GROUP,
})

ALL_KINDS = RELATION_KINDS | MODIFIER_KINDS


# ---------------------------------------------------------------------------
# PlanV2
# ---------------------------------------------------------------------------

@dataclass
class PlanV2:
    """v2 IR node — nested tree mirroring SPARQL algebra evaluation order.

    Relation kinds (bgp, join, union, ...) are leaf or binary nodes that
    produce rows from data.  Modifier kinds (filter, extend, group, project,
    order, slice, distinct, reduced) are unary nodes that transform the rows
    produced by their single child (children[0]).

    This nesting preserves the SPARQL evaluation order that v1's flat
    RelationPlan loses when it flattens modifiers onto the inner plan.
    """

    kind: str

    # --- Fields for relation kinds (bgp, path) ---
    tables: List[TableRef] = field(default_factory=list)
    var_slots: Dict[str, VarSlot] = field(default_factory=dict)
    constraints: List[str] = field(default_factory=list)
    tagged_constraints: List[Tuple[str, str]] = field(default_factory=list)

    # --- Children ---
    # Relation kinds: join/left_join/union/minus have 2 children.
    # Modifier kinds: have 1 child (children[0]).
    # Leaf kinds (bgp, table, null, path): 0 children.
    children: List[PlanV2] = field(default_factory=list)

    # --- Modifier-specific fields ---

    # project
    project_vars: Optional[List[str]] = None

    # slice
    limit: int = -1
    offset: int = 0

    # order
    order_conditions: Optional[List[Tuple[Any, str]]] = None  # [(Expr|str, "ASC"/"DESC")]

    # filter
    filter_exprs: Optional[List[Expr]] = None

    # extend (single binding per node — multiple BINDs = nested extends)
    extend_var: Optional[str] = None
    extend_expr: Optional[Expr] = None

    # group
    group_vars: Optional[List[GroupVar]] = None
    aggregates: Optional[Dict[str, ExprAggregator]] = None
    having_exprs: Optional[List[Expr]] = None

    # left_join ON clause
    left_join_exprs: Optional[List[Expr]] = None

    # table (VALUES)
    values_vars: Optional[List[str]] = None
    values_rows: Optional[List[Dict[str, Any]]] = None

    # path metadata (subject, object, path expr, table names, CTE alias)
    path_meta: Optional[Dict[str, Any]] = None

    # graph URI (for OpGraph with constant URI)
    graph_uri: Optional[str] = None

    # --- Utility ---

    @property
    def child(self) -> PlanV2:
        """The single child of a modifier node. Raises if not exactly 1 child."""
        assert len(self.children) == 1, (
            f"{self.kind} expects 1 child, got {len(self.children)}"
        )
        return self.children[0]

    @property
    def is_modifier(self) -> bool:
        return self.kind in MODIFIER_KINDS

    @property
    def is_relation(self) -> bool:
        return self.kind in RELATION_KINDS

    def walk(self):
        """Yield all nodes in pre-order (self first, then children)."""
        yield self
        for child in self.children:
            yield from child.walk()

    def depth(self) -> int:
        """Max depth of the plan tree."""
        if not self.children:
            return 1
        return 1 + max(c.depth() for c in self.children)

    def summary(self, indent: int = 0) -> str:
        """Pretty-print the plan tree structure for debugging."""
        prefix = "  " * indent
        parts = [f"{prefix}{self.kind}"]

        # Add key details per kind
        if self.kind == KIND_BGP:
            parts.append(f" tables={len(self.tables)} vars={list(self.var_slots.keys())}")
        elif self.kind == KIND_PROJECT:
            parts.append(f" vars={self.project_vars}")
        elif self.kind == KIND_FILTER:
            parts.append(f" exprs={len(self.filter_exprs or [])}")
        elif self.kind == KIND_EXTEND:
            parts.append(f" var={self.extend_var}")
        elif self.kind == KIND_GROUP:
            gv = [getattr(g, 'var', str(g)) for g in (self.group_vars or [])]
            parts.append(f" vars={gv} aggs={list((self.aggregates or {}).keys())}")
        elif self.kind == KIND_SLICE:
            parts.append(f" limit={self.limit} offset={self.offset}")
        elif self.kind == KIND_ORDER:
            parts.append(f" conditions={len(self.order_conditions or [])}")
        elif self.kind == KIND_TABLE:
            parts.append(f" vars={self.values_vars} rows={len(self.values_rows or [])}")
        elif self.kind == KIND_PATH:
            parts.append(f" meta={bool(self.path_meta)}")

        line = "".join(parts)
        lines = [line]
        for child in self.children:
            lines.append(child.summary(indent + 1))
        return "\n".join(lines)

    def __repr__(self) -> str:
        child_reprs = ", ".join(repr(c) for c in self.children)
        return f"PlanV2(kind={self.kind!r}, children=[{child_reprs}])"

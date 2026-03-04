"""
IR dataclasses for the Jena SQL generator pipeline.

Produced by Pass 1 (collect), resolved by Pass 2 (resolve), consumed by Pass 3 (emit).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any

from sqlglot import exp as E

from .jena_types import Expr

PG_DIALECT = "postgres"


# ===========================================================================
# Alias Generator (shared across all passes)
# ===========================================================================

class AliasGenerator:
    """Produces unique SQL table aliases: q0, q1, ... for quads; t0, t1, ..."""

    def __init__(self, alias_prefix: str = ""):
        self._counters: Dict[str, int] = {}
        self._alias_prefix = alias_prefix
        # Constant term lookups: maps (term_text, term_type) → column alias
        # Collected during Pass 1 (collect), consumed in generate_sql to build CTE
        self.constants: Dict[Tuple[str, str], str] = {}
        self._const_counter: int = 0
        # Resolved after materialize phase: col_name → uuid string
        self.resolved_constants: Dict[str, str] = {}
        # Graph lock: when set, every quad table is constrained to this context_uuid
        self.graph_uri: Optional[str] = None

    def next(self, prefix: str = "q") -> str:
        n = self._counters.get(prefix, 0)
        self._counters[prefix] = n + 1
        return f"{self._alias_prefix}{prefix}{n}"

    def register_constant(self, term_text: str, term_type: str) -> str:
        """Register a constant term lookup for CTE batching.

        Returns the CTE column alias (e.g. 'c_0') for this constant.
        Repeated calls with the same (term_text, term_type) return the same alias.
        """
        key = (term_text, term_type)
        if key not in self.constants:
            col = f"c_{self._const_counter}"
            self._const_counter += 1
            self.constants[key] = col
        return self.constants[key]


# ===========================================================================
# IR dataclasses — produced by Pass 1 (collect), consumed by Pass 2 (resolve)
# ===========================================================================

@dataclass
class TableRef:
    """A reference to a quad or term table."""
    ref_id: str          # Logical ID (e.g. "q0", "t3")
    kind: str            # "quad" or "term"
    table_name: str      # e.g. "lead_test_rdf_quad"
    join_col: str = ""   # For term tables: quad column to join on
    # Resolved in Pass 2:
    alias: str = ""      # SQL alias

@dataclass
class VarSlot:
    """A SPARQL variable's binding — positions recorded in collect, resolved in resolve."""
    name: str
    # (table_ref_id, uuid_col_name) — e.g. ("q0", "subject_uuid")
    positions: List[Tuple[str, str]] = field(default_factory=list)
    # Term table ref_id for the primary binding
    term_ref_id: Optional[str] = None
    # Resolved columns (set in Pass 2)
    uuid_col: Optional[str] = None   # e.g. "q0.subject_uuid"
    text_col: Optional[str] = None   # e.g. "t0.term_text"
    type_col: Optional[str] = None   # e.g. "t0.term_type"
    partial: bool = False            # True if from OPTIONAL/UNION

@dataclass
class RelationPlan:
    """IR node produced by Pass 1 (collect)."""
    kind: str   # "bgp", "join", "left_join", "union", "filter", "project",
                # "slice", "distinct", "reduced", "order", "group", "extend",
                # "table", "minus", "graph", "sequence", "null"
    tables: List[TableRef] = field(default_factory=list)
    var_slots: Dict[str, VarSlot] = field(default_factory=dict)
    constraints: List[str] = field(default_factory=list)
    # Tagged constraints: (quad_alias, sql) — same data as constraints but
    # tagged with the originating quad table so emit can build ON clauses.
    tagged_constraints: List[Tuple[str, str]] = field(default_factory=list)
    children: List[RelationPlan] = field(default_factory=list)
    # Modifiers
    select_vars: Optional[List[str]] = None
    distinct: bool = False
    limit: int = -1
    offset: int = 0
    order_by: Optional[List[Tuple[Any, str]]] = None  # [(var_or_Expr, "ASC"/"DESC")]
    group_by: Optional[List[str]] = None
    aggregates: Optional[Dict[str, Expr]] = None  # var → aggregate expr
    filter_exprs: Optional[List[Expr]] = None
    left_join_exprs: Optional[List[Expr]] = None  # OpLeftJoin's own exprs → ON clause
    having_exprs: Optional[List[Expr]] = None
    extend_exprs: Optional[Dict[str, Expr]] = None  # var → expr
    graph_uri: Optional[str] = None
    # For OpTable (VALUES)
    values_vars: Optional[List[str]] = None
    values_rows: Optional[List[Dict[str, Any]]] = None


# ===========================================================================
# Compat shims — keep the public API surface from v1
# ===========================================================================

@dataclass
class VarBinding:
    """Tracks how a SPARQL variable is bound in SQL (v1 compat)."""
    uuid_col: str
    text_col: str
    type_col: str
    term_alias: str

@dataclass
class SQLContext:
    """State for the recursive translation (v1 compat for tests)."""
    space_id: str
    aliases: AliasGenerator = field(default_factory=AliasGenerator)
    bindings: Dict[str, VarBinding] = field(default_factory=dict)
    graph_uri: Optional[str] = None

    @property
    def quad_table(self) -> str:
        return f"{self.space_id}_rdf_quad"

    @property
    def term_table(self) -> str:
        return f"{self.space_id}_term"

    def child_scope(self) -> SQLContext:
        return SQLContext(
            space_id=self.space_id,
            aliases=self.aliases,
            bindings=dict(self.bindings),
            graph_uri=self.graph_uri,
        )

    def bind_var(self, var_name: str, uuid_col: str, term_alias: str) -> VarBinding:
        if var_name in self.bindings:
            return self.bindings[var_name]
        b = VarBinding(
            uuid_col=uuid_col,
            text_col=f"{term_alias}.term_text",
            type_col=f"{term_alias}.term_type",
            term_alias=term_alias,
        )
        self.bindings[var_name] = b
        return b

@dataclass
class SQLFragment:
    """Intermediate SQL fragment (v1 compat for tests)."""
    select: E.Select
    exposed_vars: Dict[str, str] = field(default_factory=dict)
    exposed_uuids: Dict[str, str] = field(default_factory=dict)

"""
Type Generation Module — the v2 "Firewall" for companion column management.

Centralizes all companion column logic (type, uuid, lang, datatype) that in
v1 was scattered across emit(), _emit_bgp_optimized(), _emit_join(), etc.

Key types:
    ColumnInfo   — what we know about a variable's SQL representation
    TypedExpr    — a SQL fragment with its RDF type metadata
    TypeRegistry — manages ColumnInfos, projects companions, infers types
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from ..jena_sparql.jena_types import (
    Expr, ExprVar, ExprValue, ExprFunction, ExprAggregator,
    LiteralNode, URINode, GroupVar,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

XSD = "http://www.w3.org/2001/XMLSchema#"
RDF_LANG_STRING = "http://www.w3.org/1999/02/22-rdf-syntax-ns#langString"

COMPANION_SUFFIXES = ("__type", "__uuid", "__lang", "__datatype",
                     "__num", "__bool", "__dt")

# String functions that preserve the input's lang tag and datatype
_LANG_PRESERVING_FUNCS = frozenset({
    "lcase", "ucase", "substr", "replace", "strafter", "strbefore",
})

# Functions that ALWAYS return xsd:integer regardless of input type
_ALWAYS_INTEGER_FUNCS = frozenset({"strlen", "year", "month", "day",
                                    "hours", "minutes"})

# Numeric functions that preserve input datatype (xsd:decimal → xsd:decimal)
_DTYPE_PRESERVING_NUM_FUNCS = frozenset({"ceil", "floor", "round"})

# Functions that always produce xsd:string
_STRING_RESULT_FUNCS = frozenset({"str", "encode_for_uri"})


# ---------------------------------------------------------------------------
# ColumnInfo — what we know about a variable's SQL representation
# ---------------------------------------------------------------------------

@dataclass
class ColumnInfo:
    """Tracks the SQL columns for a single SPARQL variable.

    After BGP resolution, a variable like ?s has:
      - text_col:  t0.term_text  (the value)
      - type_col:  t0.term_type  (U/L/B)
      - uuid_col:  q0.subject_uuid
      - lang_col:  t0.lang
      - dt_col:    t0.datatype
      - num_col:   t0.term_num   (numeric cast, if applicable)

    After EXTEND (BIND), a computed variable might have:
      - text_col:  "CONCAT(t0.term_text, t1.term_text)"
      - type_col:  "'L'"         (constant)
      - uuid_col:  None
      - lang_col:  "NULL"
      - dt_col:    "'http://...#string'"
    """
    sparql_name: str
    # Opaque SQL column name (e.g., 'v0'). All SQL references use this,
    # never the SPARQL name.  The mapping is owned by AliasGenerator.var_map.
    sql_name: str = ""
    text_col: Optional[str] = None
    type_col: Optional[str] = None
    uuid_col: Optional[str] = None
    lang_col: Optional[str] = None
    dt_col: Optional[str] = None
    num_col: Optional[str] = None
    # Whether this variable came from a triple pattern (has term table)
    # vs being computed (BIND, aggregate)
    from_triple: bool = False
    # Whether this binding may be NULL (from OPTIONAL/UNION)
    partial: bool = False
    # Which typed lane holds this variable's primary value.
    # "num" = __num, "bool" = __bool, "dt" = __dt, None = text only.
    # Set by producers (EXTEND, GROUP). BGP leaves it None because the
    # actual type depends on runtime data.
    typed_lane: Optional[str] = None
    # Whether the child SQL actually has companion columns
    # (__type, __uuid, __lang, __datatype, __num, __bool, __dt).
    # True for BGP, EXTEND, passthrough; False for regular aggregates.
    _sql_has_companions: bool = True

    @staticmethod
    def simple_output(sparql_name: str, sql_name: str,
                      from_triple: bool = False,
                      typed_lane: Optional[str] = None) -> 'ColumnInfo':
        """Create a ColumnInfo with standard output column names.

        All companion columns derive from the opaque *sql_name*
        (e.g., 'v0', 'v0__type', ...).  SPARQL name is preserved
        for the var_map but never appears in SQL.
        """
        return ColumnInfo(
            sparql_name=sparql_name,
            sql_name=sql_name,
            text_col=sql_name,
            type_col=f"{sql_name}__type",
            uuid_col=f"{sql_name}__uuid",
            lang_col=f"{sql_name}__lang",
            dt_col=f"{sql_name}__datatype",
            num_col=f"{sql_name}__num",
            from_triple=from_triple,
            typed_lane=typed_lane,
        )

    def has_companions(self) -> bool:
        """Whether this var has companion columns available."""
        return self.type_col is not None

    def companion_cols(self) -> Dict[str, Optional[str]]:
        """Return companion column mapping for projection."""
        sn = self.sql_name or self.sparql_name
        return {
            f"{sn}__uuid": self.uuid_col or "NULL",
            f"{sn}__type": self.type_col or "'L'",
            f"{sn}__lang": self.lang_col or "NULL",
            f"{sn}__datatype": self.dt_col or "NULL",
        }


# ---------------------------------------------------------------------------
# TypedExpr — a SQL fragment with its RDF type metadata
# ---------------------------------------------------------------------------

@dataclass
class TypedExpr:
    """A SQL expression fragment annotated with its SPARQL/RDF type info.

    The datatype field can be:
      - A constant XSD URI string (e.g. 'http://...#integer')
      - A SQL expression string (e.g. 'sub.o__datatype')
      - None (unknown)

    The datatype_is_sql flag distinguishes the two cases:
      - False: datatype is a constant → emit as 'xsd:integer'
      - True: datatype is a SQL expression → emit raw
    """
    sql: str
    sparql_type: str = "literal"   # "uri", "bnode", "literal"
    datatype: Optional[str] = None
    datatype_is_sql: bool = False
    lang: Optional[str] = None
    lang_is_sql: bool = False
    can_error: bool = False
    # Optional per-suffix overrides for produce_companions.
    # Maps suffix (e.g. '__type') → raw SQL expression.
    _companion_overrides: Optional[Dict[str, str]] = None

    @property
    def type_sql(self) -> str:
        """SQL expression for the __type companion column."""
        if self.sparql_type == "uri":
            return "'U'"
        if self.sparql_type == "bnode":
            return "'B'"
        return "'L'"

    @property
    def datatype_sql(self) -> str:
        """SQL expression for the __datatype companion column."""
        if self.datatype is None:
            return "NULL"
        if self.datatype_is_sql:
            return self.datatype
        return f"'{self.datatype}'"

    @property
    def lang_sql(self) -> str:
        """SQL expression for the __lang companion column."""
        if self.lang is None:
            return "NULL"
        if self.lang_is_sql:
            return self.lang
        return f"'{self.lang}'"

    @property
    def is_numeric(self) -> bool:
        """True if the datatype is a known XSD numeric type."""
        if self.datatype is None or self.datatype_is_sql:
            return False
        return self.datatype.startswith(f"{XSD}") and any(
            self.datatype.endswith(s) for s in (
                "integer", "int", "long", "short", "decimal", "float",
                "double", "byte", "nonNegativeInteger", "positiveInteger",
                "negativeInteger", "nonPositiveInteger", "unsignedInt",
                "unsignedLong", "unsignedShort", "unsignedByte",
            )
        )

    @property
    def is_boolean(self) -> bool:
        """True if the datatype is xsd:boolean."""
        if self.datatype is None or self.datatype_is_sql:
            return False
        return self.datatype == f"{XSD}boolean"

    @property
    def is_datetime(self) -> bool:
        """True if the datatype is xsd:dateTime or xsd:date."""
        if self.datatype is None or self.datatype_is_sql:
            return False
        return self.datatype in (f"{XSD}dateTime", f"{XSD}date")

    def produce_companions(self, var: str, sql_expr: str) -> List[str]:
        """Generate SQL columns for a newly produced variable.

        Returns: ['sql_expr AS var', "'L' AS var__type", 'NULL AS var__uuid', ...]

        This is the standard way for PRODUCER handlers (EXTEND, GROUP, TABLE)
        to emit companion columns for new variables. The suffix list comes
        from COMPANION_SUFFIXES — never hardcoded in handlers.
        """
        num_expr = sql_expr if self.is_numeric else "NULL::numeric"
        bool_expr = sql_expr if self.is_boolean else "NULL::boolean"
        dt_expr = sql_expr if self.is_datetime else "NULL::timestamp"
        suffix_map = {
            "__type": self.type_sql,
            "__uuid": "NULL::uuid",
            "__lang": self.lang_sql,
            "__datatype": self.datatype_sql,
            "__num": num_expr,
            "__bool": bool_expr,
            "__dt": dt_expr,
        }
        cols = [f"{sql_expr} AS {var}"]
        for suffix in COMPANION_SUFFIXES:
            if self._companion_overrides and suffix in self._companion_overrides:
                cols.append(f"{self._companion_overrides[suffix]} AS {var}{suffix}")
            else:
                cols.append(f"{suffix_map[suffix]} AS {var}{suffix}")
        return cols

    @property
    def typed_lane(self) -> Optional[str]:
        """Which typed lane this expression's value belongs to."""
        if self.is_numeric:
            return "num"
        if self.is_boolean:
            return "bool"
        if self.is_datetime:
            return "dt"
        return None

    def to_column_info(self, sparql_name: str, sql_name: str) -> ColumnInfo:
        """Convert this typed expression into a ColumnInfo for registration."""
        return ColumnInfo(
            sparql_name=sparql_name,
            sql_name=sql_name,
            text_col=sql_name,
            type_col=self.type_sql,
            uuid_col=None,
            lang_col=self.lang_sql,
            dt_col=self.datatype_sql,
            from_triple=False,
            typed_lane=self.typed_lane,
        )


# ---------------------------------------------------------------------------
# TypeRegistry — central companion column manager
# ---------------------------------------------------------------------------

class TypeRegistry:
    """Manages type information for all variables in the current scope.

    This is the v2 "firewall" — a single place that knows about companion
    columns, type inference, and projection. Handlers call registry methods
    instead of building companion columns manually.

    The registry owns the SPARQL→SQL name mapping.  Each SPARQL variable
    gets an opaque SQL column name (v0, v1, …) allocated via the shared
    AliasGenerator.  No SPARQL name ever appears in generated SQL.
    """

    def __init__(self, aliases=None):
        self._columns: Dict[str, ColumnInfo] = {}
        # Shared across the whole emit tree; owns the v-counter + var_map
        self._aliases = aliases  # type: Optional[AliasGenerator]

    def allocate(self, sparql_name: str) -> str:
        """Allocate an opaque SQL column name for a SPARQL variable.

        Records the mapping in AliasGenerator.var_map so the executor
        can map results back to SPARQL names.
        """
        if self._aliases is None:
            # Fallback for tests that don't provide an AliasGenerator
            return sparql_name
        return self._aliases.next_var(sparql_name)

    def register(self, info: ColumnInfo) -> None:
        """Register a variable's column info."""
        self._columns[info.sparql_name] = info

    def get(self, var: str) -> Optional[ColumnInfo]:
        """Look up a variable's column info."""
        return self._columns.get(var)

    def has(self, var: str) -> bool:
        return var in self._columns

    def all_vars(self) -> Set[str]:
        return set(self._columns.keys())

    def register_from_triple(self, var: str, uuid_col: str, term_alias: str) -> ColumnInfo:
        """Register a variable bound from a triple pattern (with term table)."""
        info = ColumnInfo(
            sparql_name=var,
            text_col=f"{term_alias}.term_text",
            type_col=f"{term_alias}.term_type",
            uuid_col=uuid_col,
            lang_col=f"{term_alias}.lang",
            dt_col=f"{term_alias}.datatype_id",
            num_col=f"{term_alias}.term_num",
            from_triple=True,
        )
        self._columns[var] = info
        return info

    def register_from_subquery(self, var: str, sub_alias: str,
                                has_text: bool = True) -> ColumnInfo:
        """Register a variable from a subquery (inner/outer split)."""
        info = ColumnInfo(
            sparql_name=var,
            text_col=f"{sub_alias}.{var}" if has_text else None,
            type_col=f"{sub_alias}.{var}__type",
            uuid_col=f"{sub_alias}.{var}__uuid",
            lang_col=f"{sub_alias}.{var}__lang",
            dt_col=f"{sub_alias}.{var}__datatype",
            from_triple=False,
        )
        self._columns[var] = info
        return info

    def register_extend(self, var: str, typed_expr: TypedExpr,
                         sql_name: str) -> ColumnInfo:
        """Register a variable from BIND/EXTEND with inferred type info."""
        info = typed_expr.to_column_info(var, sql_name)
        self._columns[var] = info
        return info

    def register_aggregate(self, var: str, agg_name: str,
                            sql_name: str,
                            input_var: Optional[str] = None) -> ColumnInfo:
        """Register a variable from an aggregate result."""
        dt = _agg_datatype(agg_name, input_var, self)
        # Determine typed_lane for aggregate results
        agg_upper = agg_name.upper()
        if agg_upper in ("COUNT", "SUM", "AVG"):
            lane = "num"
        elif agg_upper in ("MIN", "MAX", "SAMPLE") and input_var:
            inp = self.get(input_var)
            lane = inp.typed_lane if inp else None
        else:
            lane = None
        info = ColumnInfo(
            sparql_name=var,
            sql_name=sql_name,
            text_col=sql_name,
            type_col="'L'",
            uuid_col=None,
            lang_col="NULL",
            dt_col=dt,
            from_triple=False,
            typed_lane=lane,
            _sql_has_companions=False,
        )
        self._columns[var] = info
        return info

    @staticmethod
    def passthrough_columns(sql_name: str, alias: str) -> List[str]:
        """Generate SQL to pass a variable and all companions through a subquery alias.

        *sql_name* is the opaque column name (e.g., 'v0').
        Returns: ['alias.v0 AS v0', 'alias.v0__type AS v0__type', ...]

        This is the standard way for handlers to project variables from a
        wrapped child subquery. Handlers MUST use this instead of manually
        constructing companion column references.
        """
        cols = [f"{alias}.{sql_name} AS {sql_name}"]
        for suffix in COMPANION_SUFFIXES:
            cols.append(f"{alias}.{sql_name}{suffix} AS {sql_name}{suffix}")
        return cols

    @staticmethod
    def remap_columns(src_sql_name: str, dst_sql_name: str,
                       alias: str) -> List[str]:
        """Remap columns from one opaque name to another through a subquery.

        Used by UNION where branches have different sql_names for the same
        SPARQL variable.
        Returns: ['alias.v0 AS v3', 'alias.v0__type AS v3__type', ...]
        """
        if src_sql_name == dst_sql_name:
            return TypeRegistry.passthrough_columns(src_sql_name, alias)
        cols = [f"{alias}.{src_sql_name} AS {dst_sql_name}"]
        for suffix in COMPANION_SUFFIXES:
            cols.append(f"{alias}.{src_sql_name}{suffix} AS {dst_sql_name}{suffix}")
        return cols

    @staticmethod
    def term_table_columns(var: str, t_alias: str, sub_alias: str,
                            numeric_dt_sql_list: str,
                            dt_case_sql: str = "NULL",
                            numeric_dt_id_list: str = "NULL",
                            boolean_dt_id: str = "NULL",
                            datetime_dt_id_list: str = "NULL",
                            dt_alias: str = "") -> List[str]:
        """Generate SQL columns for a variable resolved from the term table.

        This is the BGP producer's mapping from physical term table schema
        to the standard companion column set. Centralizes the schema-specific
        mapping so emit_bgp doesn't hardcode suffix strings.

        When ``dt_alias`` is provided (the _dt CTE approach), the datatype
        URI and type flags come from a LEFT JOIN to the _dt CTE — a single
        ~2KB in-memory hash table. This replaces the per-variable inline
        CASE expressions (which were ~2,500 chars each).

        Args:
            dt_case_sql: SQL CASE expression (legacy, used when dt_alias is empty).
            numeric_dt_id_list: Comma-separated datatype_id ints for numeric types.
            boolean_dt_id: datatype_id int for xsd:boolean.
            datetime_dt_id_list: Comma-separated datatype_id ints for date/time types.
            dt_alias: Alias of the _dt CTE join for this variable (e.g. 'dt_v0').

        Returns: ['t.term_text AS var', 't.term_type AS var__type', ...]
        """
        # Guard CASTs with lightweight validation to avoid errors on
        # malformed literals (e.g. "xyz"^^xsd:integer).
        _NUM_RE = r"'^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$'"
        _DT_RE = r"'^\d{4}-'"

        if dt_alias:
            # CTE scalar subquery approach: resolve datatype info from _dt CTE
            # without adding tables to the join plan (zero join count overhead).
            _dt_sub = f"(SELECT uri FROM _dt WHERE id = {t_alias}.datatype_id)"
            _num_sub = f"(SELECT is_num FROM _dt WHERE id = {t_alias}.datatype_id)"
            _bool_sub = f"(SELECT is_bool FROM _dt WHERE id = {t_alias}.datatype_id)"
            _dts_sub = f"(SELECT is_dt FROM _dt WHERE id = {t_alias}.datatype_id)"
            return [
                f"{t_alias}.term_text AS {var}",
                f"{t_alias}.term_type AS {var}__type",
                f"{sub_alias}.{var}__uuid AS {var}__uuid",
                f"{t_alias}.lang AS {var}__lang",
                f"{_dt_sub} AS {var}__datatype",
                (f"CASE WHEN {_num_sub}"
                 f" AND {t_alias}.term_text ~ {_NUM_RE}"
                 f" THEN CAST({t_alias}.term_text AS NUMERIC) END AS {var}__num"),
                (f"CASE WHEN {_bool_sub}"
                 f" AND {t_alias}.term_text IN ('true','false','1','0')"
                 f" THEN ({t_alias}.term_text = 'true') END AS {var}__bool"),
                (f"CASE WHEN {_dts_sub}"
                 f" AND {t_alias}.term_text ~ {_DT_RE}"
                 f" THEN CAST({t_alias}.term_text AS TIMESTAMP) END AS {var}__dt"),
            ]

        # Legacy: inline CASE expressions
        return [
            f"{t_alias}.term_text AS {var}",
            f"{t_alias}.term_type AS {var}__type",
            f"{sub_alias}.{var}__uuid AS {var}__uuid",
            f"{t_alias}.lang AS {var}__lang",
            f"({dt_case_sql}) AS {var}__datatype",
            (f"CASE WHEN {t_alias}.datatype_id IN ({numeric_dt_id_list})"
             f" AND {t_alias}.term_text ~ {_NUM_RE}"
             f" THEN CAST({t_alias}.term_text AS NUMERIC) END AS {var}__num"),
            (f"CASE WHEN {t_alias}.datatype_id = {boolean_dt_id}"
             f" AND {t_alias}.term_text IN ('true','false','1','0')"
             f" THEN ({t_alias}.term_text = 'true') END AS {var}__bool"),
            (f"CASE WHEN {t_alias}.datatype_id IN ({datetime_dt_id_list})"
             f" AND {t_alias}.term_text ~ {_DT_RE}"
             f" THEN CAST({t_alias}.term_text AS TIMESTAMP) END AS {var}__dt"),
        ]

    @staticmethod
    def coalesce_columns(l_name: str, l_alias: str,
                          r_name: str, r_alias: str) -> List[str]:
        """Rule 4: COALESCE for shared variable projection (§10.5).

        When a shared variable is NULL on one side (UNDEF or OPTIONAL),
        take the value from the other side.
        Returns: ['COALESCE(l.v0, r.v3) AS v0', ...]
        """
        cols = [f"COALESCE({l_alias}.{l_name}, {r_alias}.{r_name}) AS {l_name}"]
        for suffix in COMPANION_SUFFIXES:
            cols.append(
                f"COALESCE({l_alias}.{l_name}{suffix}, "
                f"{r_alias}.{r_name}{suffix}) AS {l_name}{suffix}"
            )
        return cols

    @staticmethod
    def null_companions(var: str) -> List[str]:
        """Rule 5: NULL companions for out-of-scope variables (§10.5).

        Returns: ['NULL AS var', 'NULL AS var__type', ...]
        Used by UNION padding and TABLE for missing variables.
        """
        _TYPED_NULLS = {
            "__uuid": "NULL::uuid",
            "__num": "NULL::numeric",
            "__bool": "NULL::boolean",
            "__dt": "NULL::timestamp",
        }
        cols = [f"NULL AS {var}"]
        for suffix in COMPANION_SUFFIXES:
            null_val = _TYPED_NULLS.get(suffix, "NULL")
            cols.append(f"{null_val} AS {var}{suffix}")
        return cols

    def project_var(self, var: str, source_sql: str) -> List[str]:
        """Generate SQL column expressions for projecting a variable.

        Returns a list of SQL fragments like:
            ["t0.term_text AS s", "t0.term_type AS s__type", ...]
        """
        info = self._columns.get(var)
        if info is None:
            return [f"NULL AS {_q(var)}"]

        cols = [f"{source_sql} AS {_q(var)}"]
        companions = info.companion_cols()
        for alias, expr in companions.items():
            cols.append(f"{expr} AS {alias}")
        return cols

    def project_companions_only(self, var: str) -> List[str]:
        """Generate just the companion column expressions (no value column)."""
        info = self._columns.get(var)
        if info is None:
            return [
                f"NULL AS {var}__uuid",
                f"'L' AS {var}__type",
                f"NULL AS {var}__lang",
                f"NULL AS {var}__datatype",
            ]
        companions = info.companion_cols()
        return [f"{expr} AS {alias}" for alias, expr in companions.items()]

    def group_by_companions(self, var: str) -> List[str]:
        """Return companion column expressions that need to be in GROUP BY."""
        info = self._columns.get(var)
        if info is None:
            return []
        companions = []
        if info.type_col and info.type_col != "'L'":
            companions.append(info.type_col)
        if info.lang_col and info.lang_col != "NULL":
            companions.append(info.lang_col)
        if info.dt_col and info.dt_col != "NULL":
            companions.append(info.dt_col)
        return companions

    def child_registry(self) -> TypeRegistry:
        """Create a child registry that inherits current registrations.

        Used when entering a nested scope (subquery, UNION branch, etc.)
        Shares the same AliasGenerator so sql_name allocation is global.
        """
        child = TypeRegistry(aliases=self._aliases)
        child._columns = dict(self._columns)
        return child


# ---------------------------------------------------------------------------
# Type Inference Functions
# ---------------------------------------------------------------------------

def infer_expr_type(expr: Any, registry: TypeRegistry) -> TypedExpr:
    """Infer the RDF type metadata for a SPARQL expression.

    Returns a TypedExpr with sparql_type, datatype, lang filled in.
    The sql field is left empty — the caller fills it with the actual SQL.

    This replaces the scattered _infer_extend_type(), _infer_extend_datatype(),
    _infer_extend_lang() functions from v1.
    """
    # Variable reference — inherit type from registry
    if isinstance(expr, ExprVar):
        info = registry.get(expr.var)
        if info:
            dt = info.dt_col
            dt_is_sql = True
            lang = info.lang_col
            lang_is_sql = True
            # If dt_col is a SQL string constant (e.g., "'http://...#integer'"),
            # extract the actual value so is_numeric/is_boolean/is_datetime work
            if dt and dt.startswith("'") and dt.endswith("'"):
                dt = dt[1:-1]
                dt_is_sql = False
            if lang and lang.startswith("'") and lang.endswith("'"):
                lang = lang[1:-1]
                lang_is_sql = False
            return TypedExpr(
                sql="",
                sparql_type="literal",  # could be anything — use __type col
                datatype=dt,
                datatype_is_sql=dt_is_sql,
                lang=lang,
                lang_is_sql=lang_is_sql,
            )
        return TypedExpr(sql="")

    # Literal constant
    if isinstance(expr, ExprValue) and hasattr(expr, 'node'):
        node = expr.node
        if isinstance(node, LiteralNode):
            te = TypedExpr(sql="", sparql_type="literal")
            if node.datatype:
                te.datatype = node.datatype
            if node.lang:
                te.lang = node.lang
                te.datatype = RDF_LANG_STRING
            return te
        if isinstance(node, URINode):
            return TypedExpr(sql="", sparql_type="uri")

    # Function call
    if isinstance(expr, ExprFunction):
        return _infer_function_type(expr, registry)

    # Aggregator
    if isinstance(expr, ExprAggregator):
        return _infer_aggregator_type(expr, registry)

    return TypedExpr(sql="")


def _infer_function_type(expr: ExprFunction, registry: TypeRegistry) -> TypedExpr:
    """Infer type for a function expression."""
    fname = (expr.name or "").lower()
    args = expr.args or []

    # XSD cast functions (xsd:integer(?x), xsd:double(?x), etc.)
    if hasattr(expr, 'function_iri') and expr.function_iri:
        iri = expr.function_iri
        if iri.startswith(XSD):
            return TypedExpr(sql="", sparql_type="literal", datatype=iri)

    # IRI/URI constructors → URI
    if fname in ("iri", "uri"):
        return TypedExpr(sql="", sparql_type="uri")

    # BNODE → blank node
    if fname == "bnode":
        return TypedExpr(sql="", sparql_type="bnode")

    # UUID → URI, STRUUID → literal string
    if fname == "uuid":
        return TypedExpr(sql="", sparql_type="uri")
    if fname == "struuid":
        return TypedExpr(sql="", sparql_type="literal",
                         datatype=f"{XSD}string")

    # NOW() → xsd:dateTime
    if fname == "now":
        return TypedExpr(sql="", sparql_type="literal",
                         datatype=f"{XSD}dateTime")

    # RAND() → xsd:double
    if fname == "rand":
        return TypedExpr(sql="", sparql_type="literal",
                         datatype=f"{XSD}double")

    # DATATYPE() → URI
    if fname == "datatype":
        return TypedExpr(sql="", sparql_type="uri")

    # Arithmetic operators
    if fname == "divide":
        return TypedExpr(sql="", sparql_type="literal",
                         datatype=f"{XSD}decimal")
    if fname in ("add", "subtract", "multiply"):
        # Propagate from first arg if available
        if args:
            arg_type = infer_expr_type(args[0], registry)
            if arg_type.datatype and not arg_type.datatype_is_sql:
                return TypedExpr(sql="", sparql_type="literal",
                                 datatype=arg_type.datatype)
        return TypedExpr(sql="", sparql_type="literal",
                         datatype=f"{XSD}integer")

    # Functions that always return xsd:integer
    if fname in _ALWAYS_INTEGER_FUNCS:
        return TypedExpr(sql="", sparql_type="literal",
                         datatype=f"{XSD}integer")

    # Numeric functions that preserve input datatype
    if fname in _DTYPE_PRESERVING_NUM_FUNCS:
        if args:
            arg_type = infer_expr_type(args[0], registry)
            if arg_type.datatype and not arg_type.datatype_is_sql:
                return TypedExpr(sql="", sparql_type="literal",
                                 datatype=arg_type.datatype)
        return TypedExpr(sql="", sparql_type="literal",
                         datatype=f"{XSD}integer")

    # ABS preserves input datatype
    if fname == "abs":
        if args:
            arg_type = infer_expr_type(args[0], registry)
            if arg_type.datatype:
                return TypedExpr(sql="", sparql_type="literal",
                                 datatype=arg_type.datatype,
                                 datatype_is_sql=arg_type.datatype_is_sql)
        return TypedExpr(sql="", sparql_type="literal",
                         datatype=f"{XSD}decimal")

    # String result functions
    if fname in _STRING_RESULT_FUNCS:
        return TypedExpr(sql="", sparql_type="literal",
                         datatype=f"{XSD}string")

    # Lang-preserving string functions
    if fname in _LANG_PRESERVING_FUNCS and args:
        arg_type = infer_expr_type(args[0], registry)
        return TypedExpr(
            sql="", sparql_type="literal",
            datatype=arg_type.datatype,
            datatype_is_sql=arg_type.datatype_is_sql,
            lang=arg_type.lang,
            lang_is_sql=arg_type.lang_is_sql,
        )

    # SECONDS → xsd:decimal
    if fname == "seconds":
        return TypedExpr(sql="", sparql_type="literal",
                         datatype=f"{XSD}decimal")

    # TIMEZONE → xsd:dayTimeDuration
    if fname == "timezone":
        return TypedExpr(sql="", sparql_type="literal",
                         datatype=f"{XSD}dayTimeDuration")

    # TZ → plain literal
    if fname == "tz":
        return TypedExpr(sql="", sparql_type="literal")

    # STRDT explicitly sets datatype
    if fname == "strdt" and len(args) >= 2:
        if isinstance(args[1], ExprValue) and hasattr(args[1], 'node'):
            if args[1].node:
                return TypedExpr(sql="", sparql_type="literal",
                                 datatype=args[1].node.value)

    # STRLANG → rdf:langString with explicit lang tag
    if fname == "strlang" and len(args) >= 2:
        lang_val = None
        if isinstance(args[1], ExprValue) and hasattr(args[1], 'node'):
            if args[1].node:
                lang_val = args[1].node.value
        return TypedExpr(sql="", sparql_type="literal",
                         datatype=RDF_LANG_STRING,
                         lang=lang_val)

    # IF(cond, then, else) — infer from branches
    if fname == "if" and len(args) >= 3:
        then_type = infer_expr_type(args[1], registry)
        else_type = infer_expr_type(args[2], registry)
        # Prefer constant datatype from either branch
        if then_type.datatype and not then_type.datatype_is_sql:
            return TypedExpr(sql="", sparql_type="literal",
                             datatype=then_type.datatype)
        if else_type.datatype and not else_type.datatype_is_sql:
            return TypedExpr(sql="", sparql_type="literal",
                             datatype=else_type.datatype)
        return TypedExpr(sql="", sparql_type="literal")

    # COALESCE — dynamic companions when first arg is a variable
    if fname == "coalesce" and args:
        # If the first arg is a variable with dynamic companions, produce
        # COALESCE/CASE SQL for each companion so runtime type metadata
        # flows through correctly (e.g. integer vs date fallback).
        if isinstance(args[0], ExprVar):
            src = registry.get(args[0].var)
            if src and src.sql_name and src._sql_has_companions:
                sn = src.sql_name
                # Infer fallback type from remaining args
                fb_type = "'L'"
                fb_dt = "NULL"
                fb_lang = "NULL"
                fb_num = "NULL::numeric"
                fb_bool = "NULL::boolean"
                fb_dt_ts = "NULL::timestamp"
                for a in args[1:]:
                    a_t = infer_expr_type(a, registry)
                    if a_t.sparql_type == "uri":
                        fb_type = "'U'"
                    if a_t.datatype and not a_t.datatype_is_sql:
                        fb_dt = f"'{a_t.datatype}'"
                        if a_t.is_numeric:
                            # Fallback literal text for numeric cast
                            pass
                        if a_t.is_datetime:
                            # Extract literal text for timestamp cast
                            if isinstance(a, ExprValue) and hasattr(a, 'node'):
                                fb_dt_ts = f"CAST('{a.node.value}' AS TIMESTAMP)"
                    if a_t.lang and not a_t.lang_is_sql:
                        fb_lang = f"'{a_t.lang}'"
                    break  # only need first fallback

                overrides = {
                    "__type": f"CASE WHEN {sn} IS NOT NULL THEN {sn}__type ELSE {fb_type} END",
                    "__lang": f"CASE WHEN {sn} IS NOT NULL THEN {sn}__lang ELSE {fb_lang} END",
                    "__datatype": f"CASE WHEN {sn} IS NOT NULL THEN {sn}__datatype ELSE {fb_dt} END",
                    "__num": f"CASE WHEN {sn} IS NOT NULL THEN {sn}__num ELSE {fb_num} END",
                    "__bool": f"CASE WHEN {sn} IS NOT NULL THEN {sn}__bool ELSE {fb_bool} END",
                    "__dt": f"CASE WHEN {sn} IS NOT NULL THEN {sn}__dt ELSE {fb_dt_ts} END",
                }
                return TypedExpr(
                    sql="", sparql_type="literal",
                    datatype=f"CASE WHEN {sn} IS NOT NULL THEN {sn}__datatype ELSE {fb_dt} END",
                    datatype_is_sql=True,
                    _companion_overrides=overrides,
                )

        # Fallback: pick first static datatype
        for a in args:
            a_type = infer_expr_type(a, registry)
            if a_type.datatype and not a_type.datatype_is_sql:
                return TypedExpr(sql="", sparql_type="literal",
                                 datatype=a_type.datatype)
        return TypedExpr(sql="", sparql_type="literal")

    # CONCAT → no datatype (plain literal per spec)
    if fname == "concat":
        return TypedExpr(sql="", sparql_type="literal")

    # BOUND, sameTerm, isIRI, isBlank, isLiteral, isNumeric → boolean
    if fname in ("bound", "sameterm", "isiri", "isuri", "isblank",
                 "isliteral", "isnumeric", "regex", "contains",
                 "strstarts", "strends", "langmatches"):
        return TypedExpr(sql="", sparql_type="literal",
                         datatype=f"{XSD}boolean")

    # NOT / logical operators → boolean
    if fname in ("not", "and", "or", "unaryNot"):
        return TypedExpr(sql="", sparql_type="literal",
                         datatype=f"{XSD}boolean")

    # Comparison operators → boolean
    if fname in ("lt", "gt", "le", "ge", "eq", "ne",
                 "numericEqual", "numericLessThan", "numericGreaterThan"):
        return TypedExpr(sql="", sparql_type="literal",
                         datatype=f"{XSD}boolean")

    # Default: literal with unknown datatype
    return TypedExpr(sql="", sparql_type="literal")


def _infer_aggregator_type(expr: ExprAggregator,
                            registry: TypeRegistry) -> TypedExpr:
    """Infer type for an aggregate expression."""
    agg_name = (expr.name or "").upper()

    if agg_name == "COUNT":
        return TypedExpr(sql="", sparql_type="literal",
                         datatype=f"{XSD}integer")

    if agg_name == "AVG":
        return TypedExpr(sql="", sparql_type="literal",
                         datatype=f"{XSD}decimal")

    if agg_name in ("SUM", "MIN", "MAX", "SAMPLE"):
        # Propagate input datatype if available
        if expr.expr:
            inner_type = infer_expr_type(expr.expr, registry)
            if inner_type.datatype:
                return TypedExpr(sql="", sparql_type="literal",
                                 datatype=inner_type.datatype,
                                 datatype_is_sql=inner_type.datatype_is_sql)
        if agg_name == "SUM":
            return TypedExpr(sql="", sparql_type="literal",
                             datatype=f"{XSD}integer")
        return TypedExpr(sql="", sparql_type="literal")

    if agg_name == "GROUP_CONCAT":
        return TypedExpr(sql="", sparql_type="literal",
                         datatype=f"{XSD}string")

    return TypedExpr(sql="", sparql_type="literal")


def _agg_datatype(agg_name: str, input_var: Optional[str],
                   registry: TypeRegistry) -> str:
    """Return the __datatype SQL expression for an aggregate result.

    IMPORTANT: Must return only constant strings, not column references,
    because aggregate results live after GROUP BY where the original
    columns are no longer accessible.
    """
    agg_upper = agg_name.upper()
    if agg_upper == "COUNT":
        return f"'{XSD}integer'"
    if agg_upper == "AVG":
        return f"'{XSD}decimal'"
    if input_var:
        info = registry.get(input_var)
        if info and info.dt_col:
            # Only use dt_col if it's a constant (quoted string), not a
            # column reference — column refs won't survive GROUP BY
            dt = info.dt_col
            if dt.startswith("'") and dt.endswith("'"):
                return dt
    if agg_upper in ("SUM", "MIN", "MAX"):
        return f"'{XSD}integer'"
    if agg_upper == "GROUP_CONCAT":
        return f"'{XSD}string'"
    return "NULL"


# ---------------------------------------------------------------------------
# Error Guard
# ---------------------------------------------------------------------------

def sparql_error_guard(sql_expr: str, typed: TypedExpr) -> str:
    """Wrap a SQL expression with SPARQL error semantics if it can error.

    SPARQL spec: type errors produce unbound (NULL), not SQL errors.
    """
    if not typed.can_error:
        return sql_expr
    return f"CASE WHEN ({sql_expr}) IS NOT NULL THEN ({sql_expr}) ELSE NULL END"


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _q(name: str) -> str:
    """Quote a SQL identifier if needed."""
    if name.isidentifier() and not name.startswith("_"):
        return name
    return f'"{name}"'

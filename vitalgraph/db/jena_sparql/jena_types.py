"""
Python dataclasses mirroring the Jena sidecar JSON types.

These are the target types that jena_ast_mapper.py converts JSON into.
They form the intermediate representation between Jena's output and
the SQL generator.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Union


# ---------------------------------------------------------------------------
# RDF Node types
# ---------------------------------------------------------------------------

@dataclass
class VarNode:
    """A SPARQL variable (?x)."""
    name: str


@dataclass
class URINode:
    """An RDF URI/IRI."""
    value: str


@dataclass
class LiteralNode:
    """An RDF literal with optional language tag or datatype."""
    value: str
    lang: Optional[str] = None
    datatype: Optional[str] = None


@dataclass
class BNodeNode:
    """An RDF blank node."""
    label: str


RDFNode = Union[VarNode, URINode, LiteralNode, BNodeNode]


# ---------------------------------------------------------------------------
# Property path types
# ---------------------------------------------------------------------------

@dataclass
class PathLink:
    """A simple URI predicate path."""
    uri: str


@dataclass
class PathInverse:
    """Inverse path: ^<path>."""
    sub: PathExpr


@dataclass
class PathSeq:
    """Sequence path: <path1>/<path2>."""
    left: PathExpr
    right: PathExpr


@dataclass
class PathAlt:
    """Alternative path: <path1>|<path2>."""
    left: PathExpr
    right: PathExpr


@dataclass
class PathOneOrMore:
    """One-or-more repetition: <path>+."""
    sub: PathExpr


@dataclass
class PathZeroOrMore:
    """Zero-or-more repetition: <path>*."""
    sub: PathExpr


@dataclass
class PathZeroOrOne:
    """Zero-or-one (optional): <path>?."""
    sub: PathExpr


@dataclass
class PathNegPropSet:
    """Negated property set: !<uri> or !(<uri1>|<uri2>)."""
    uris: List[str]


PathExpr = Union[
    PathLink, PathInverse, PathSeq, PathAlt,
    PathOneOrMore, PathZeroOrMore, PathZeroOrOne,
    PathNegPropSet,
]


# ---------------------------------------------------------------------------
# Triple / Quad patterns
# ---------------------------------------------------------------------------

@dataclass
class TriplePattern:
    """A single triple pattern (subject, predicate, object)."""
    subject: RDFNode
    predicate: RDFNode
    object: RDFNode


@dataclass
class QuadPattern:
    """A quad pattern (graph, subject, predicate, object)."""
    graph: Optional[RDFNode]
    subject: RDFNode
    predicate: RDFNode
    object: RDFNode


# ---------------------------------------------------------------------------
# Expression types
# ---------------------------------------------------------------------------

@dataclass
class ExprVar:
    """Reference to a SPARQL variable in an expression."""
    var: str


@dataclass
class ExprValue:
    """A constant node value in an expression."""
    node: RDFNode


@dataclass
class ExprFunction:
    """A function call or operator (=, <, CONTAINS, regex, etc.)."""
    name: str
    args: List[Expr]
    function_iri: Optional[str] = None  # IRI for XSD casts, custom functions


@dataclass
class ExprAggregator:
    """An aggregate expression (COUNT, SUM, AVG, MIN, MAX, SAMPLE, GROUP_CONCAT)."""
    name: str
    distinct: bool = False
    expr: Optional[Expr] = None
    separator: Optional[str] = None  # for GROUP_CONCAT


@dataclass
class ExprExists:
    """FILTER EXISTS { ... } or FILTER NOT EXISTS { ... }."""
    graph_pattern: Any  # Op node (forward ref to avoid circular import)
    negated: bool = False  # True for NOT EXISTS


Expr = Union[ExprVar, ExprValue, ExprFunction, ExprAggregator, ExprExists]


# ---------------------------------------------------------------------------
# Sort condition
# ---------------------------------------------------------------------------

@dataclass
class SortCondition:
    """ORDER BY condition."""
    direction: str  # "ASC" or "DESC"
    expr: Expr


# ---------------------------------------------------------------------------
# Op (algebra) types — queries
# ---------------------------------------------------------------------------

@dataclass
class OpBGP:
    """Basic Graph Pattern — one or more triple patterns."""
    triples: List[TriplePattern]


@dataclass
class OpJoin:
    """Inner join of two sub-ops."""
    left: Op
    right: Op


@dataclass
class OpLeftJoin:
    """Left outer join (OPTIONAL)."""
    left: Op
    right: Op
    exprs: List[Expr] = field(default_factory=list)


@dataclass
class OpUnion:
    """UNION of two sub-ops."""
    left: Op
    right: Op


@dataclass
class OpFilter:
    """FILTER expression(s) over a sub-op."""
    exprs: List[Expr]
    sub_op: Op


@dataclass
class OpProject:
    """SELECT projection — restricts visible variables."""
    vars: List[str]
    sub_op: Op


@dataclass
class OpSlice:
    """LIMIT / OFFSET."""
    start: int
    length: int  # -1 or large negative means no limit
    sub_op: Op


@dataclass
class OpDistinct:
    """SELECT DISTINCT."""
    sub_op: Op


@dataclass
class OpReduced:
    """SELECT REDUCED."""
    sub_op: Op


@dataclass
class OpOrder:
    """ORDER BY."""
    conditions: List[SortCondition]
    sub_op: Op


@dataclass
class GroupVar:
    """A GROUP BY variable, optionally with a defining expression.

    For ``GROUP BY ?x`` → GroupVar(var="x", expr=None)
    For ``GROUP BY (DATATYPE(?o) AS ?d)`` → GroupVar(var="d", expr=ExprFunction("datatype", [...]))
    """
    var: str
    expr: Optional[Expr] = None


@dataclass
class OpGroup:
    """GROUP BY with optional aggregators."""
    group_vars: List[GroupVar]
    aggregators: List[Dict[str, Any]]  # raw aggregator defs
    sub_op: Op


@dataclass
class OpExtend:
    """BIND (expr AS ?var)."""
    var: str
    expr: Expr
    sub_op: Op


@dataclass
class OpTable:
    """VALUES inline data."""
    vars: List[str]
    rows: List[Dict[str, RDFNode]]


@dataclass
class OpMinus:
    """MINUS pattern."""
    left: Op
    right: Op


@dataclass
class OpGraph:
    """GRAPH ?g { ... } or GRAPH <uri> { ... }."""
    graph_node: RDFNode
    sub_op: Op


@dataclass
class OpSequence:
    """Sequence of operations (multiple update WHERE clauses)."""
    elements: List[Op]


@dataclass
class OpNull:
    """Empty/null operation."""
    pass


@dataclass
class OpPath:
    """Property path pattern (subject, path, object)."""
    subject: RDFNode
    path: PathExpr
    object: RDFNode


Op = Union[
    OpBGP, OpJoin, OpLeftJoin, OpUnion, OpFilter,
    OpProject, OpSlice, OpDistinct, OpReduced, OpOrder,
    OpGroup, OpExtend, OpTable, OpMinus, OpGraph,
    OpSequence, OpNull, OpPath,
]


# ---------------------------------------------------------------------------
# Update operation types
# ---------------------------------------------------------------------------

@dataclass
class UpdateDataInsert:
    """INSERT DATA { ... }."""
    quads: List[QuadPattern]


@dataclass
class UpdateDataDelete:
    """DELETE DATA { ... }."""
    quads: List[QuadPattern]


@dataclass
class UpdateModify:
    """DELETE/INSERT WHERE pattern."""
    with_graph: Optional[str] = None
    delete_quads: List[QuadPattern] = field(default_factory=list)
    insert_quads: List[QuadPattern] = field(default_factory=list)
    using_graphs: List[str] = field(default_factory=list)
    using_named_graphs: List[str] = field(default_factory=list)
    where_pattern: Optional[Op] = None


@dataclass
class UpdateLoad:
    """LOAD <source> INTO GRAPH <dest>."""
    source: str
    dest_graph: Optional[str] = None
    silent: bool = False


@dataclass
class UpdateClear:
    """CLEAR GRAPH <uri> / CLEAR DEFAULT / CLEAR ALL."""
    graph: Optional[str] = None
    target: str = "DEFAULT"  # "DEFAULT", "NAMED", "ALL", or graph URI
    silent: bool = False


@dataclass
class UpdateDrop:
    """DROP GRAPH <uri>."""
    graph: Optional[str] = None
    target: str = "DEFAULT"
    silent: bool = False


@dataclass
class UpdateCreate:
    """CREATE GRAPH <uri>."""
    graph: str = ""
    silent: bool = False


@dataclass
class UpdateCopy:
    """COPY source TO dest."""
    source: str = ""
    dest: str = ""
    silent: bool = False


@dataclass
class UpdateMove:
    """MOVE source TO dest."""
    source: str = ""
    dest: str = ""
    silent: bool = False


@dataclass
class UpdateAdd:
    """ADD source TO dest."""
    source: str = ""
    dest: str = ""
    silent: bool = False


@dataclass
class UpdateDeleteWhere:
    """DELETE WHERE { pattern } — shorthand where delete template = WHERE pattern."""
    quads: List[QuadPattern] = field(default_factory=list)


UpdateOp = Union[
    UpdateDataInsert, UpdateDataDelete, UpdateModify,
    UpdateLoad, UpdateClear, UpdateDrop, UpdateCreate,
    UpdateCopy, UpdateMove, UpdateAdd, UpdateDeleteWhere,
]


# ---------------------------------------------------------------------------
# Top-level compile result
# ---------------------------------------------------------------------------

@dataclass
class ParsedQueryMeta:
    """Metadata from the parsedQuery phase."""
    sparql_form: str  # "QUERY" or "UPDATE"
    query_type: Optional[str] = None  # "SELECT", "CONSTRUCT", "ASK", "DESCRIBE"
    base_uri: Optional[str] = None  # BASE <uri> declaration for IRI()/URI() resolution
    project_vars: List[str] = field(default_factory=list)
    distinct: bool = False
    reduced: bool = False
    limit: Optional[int] = None
    offset: int = 0
    order_by: List[Dict[str, Any]] = field(default_factory=list)
    group_by: List[Any] = field(default_factory=list)
    having: List[Any] = field(default_factory=list)
    operation_count: int = 0  # for UPDATE
    construct_template: List[TriplePattern] = field(default_factory=list)
    describe_nodes: List[RDFNode] = field(default_factory=list)


@dataclass
class CompileResult:
    """Complete result from parsing and compiling a SPARQL statement."""
    ok: bool
    meta: ParsedQueryMeta
    algebra: Optional[Op] = None
    update_ops: List[UpdateOp] = field(default_factory=list)
    error: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    raw: Optional[Dict[str, Any]] = None  # original JSON for debugging

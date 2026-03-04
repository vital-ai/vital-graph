"""
Maps Jena sidecar JSON responses into Python dataclass instances.

Entry point: map_compile_response(json_dict) -> CompileResult
"""

from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

from .jena_types import (
    # Nodes
    VarNode, URINode, LiteralNode, BNodeNode, RDFNode,
    # Patterns
    TriplePattern, QuadPattern,
    # Path types
    PathLink, PathInverse, PathSeq, PathAlt,
    PathOneOrMore, PathZeroOrMore, PathZeroOrOne,
    PathNegPropSet, PathExpr,
    # Expressions
    ExprVar, ExprValue, ExprFunction, ExprAggregator, Expr,
    SortCondition,
    # Ops
    OpBGP, OpJoin, OpLeftJoin, OpUnion, OpFilter,
    OpProject, OpSlice, OpDistinct, OpReduced, OpOrder,
    OpGroup, OpExtend, OpTable, OpMinus, OpGraph,
    OpSequence, OpNull, OpPath, Op,
    # Updates
    UpdateDataInsert, UpdateDataDelete, UpdateModify,
    UpdateLoad, UpdateClear, UpdateDrop, UpdateCreate,
    UpdateCopy, UpdateMove, UpdateAdd, UpdateDeleteWhere, UpdateOp,
    # Top-level
    ParsedQueryMeta, CompileResult,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def map_compile_response(data: Dict[str, Any]) -> CompileResult:
    """
    Convert a full sidecar JSON response into a CompileResult.

    Args:
        data: The raw JSON dict from the sidecar /v1/sparql/compile endpoint.

    Returns:
        A CompileResult with parsed metadata, algebra tree, and/or update ops.
    """
    ok = data.get("ok", False)
    error = data.get("error")
    warnings = data.get("warnings", [])

    # Parse metadata
    phases = data.get("phases", {})
    pq = phases.get("parsedQuery", {})
    meta = _map_parsed_query_meta(pq)

    # Error case
    if not ok:
        error_msg = error
        if isinstance(error, dict):
            error_msg = error.get("message", str(error))
        return CompileResult(
            ok=False, meta=meta, error=error_msg, warnings=warnings, raw=data
        )

    # Map algebra (for queries)
    algebra = None
    ac = phases.get("algebraCompiled")
    if ac and isinstance(ac, dict) and "op" in ac:
        algebra = map_op(ac["op"])

    # Map update operations
    update_ops = []
    raw_updates = phases.get("updateOperations")
    if raw_updates and isinstance(raw_updates, list):
        for u in raw_updates:
            update_ops.append(map_update_op(u))

    return CompileResult(
        ok=True,
        meta=meta,
        algebra=algebra,
        update_ops=update_ops,
        warnings=warnings,
        raw=data,
    )


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

def _map_parsed_query_meta(pq: Dict[str, Any]) -> ParsedQueryMeta:
    """Map the parsedQuery phase to ParsedQueryMeta."""
    limit_raw = pq.get("limit")
    # Jena uses a large negative number for "no limit"
    limit = None if limit_raw is None or limit_raw < 0 else limit_raw

    # CONSTRUCT template
    construct_template = []
    for t in pq.get("constructTemplate", []):
        construct_template.append(TriplePattern(
            subject=map_node(t["subject"]),
            predicate=map_node(t["predicate"]),
            object=map_node(t["object"]),
        ))

    # DESCRIBE nodes
    describe_nodes = [map_node(n) for n in pq.get("describeNodes", [])]

    return ParsedQueryMeta(
        sparql_form=pq.get("sparqlForm", "QUERY"),
        query_type=pq.get("queryType"),
        project_vars=pq.get("projectVars", []),
        distinct=pq.get("distinct", False),
        reduced=pq.get("reduced", False),
        limit=limit,
        offset=pq.get("offset", 0),
        order_by=pq.get("orderBy", []),
        group_by=pq.get("groupBy", []),
        having=pq.get("having", []),
        operation_count=pq.get("operationCount", 0),
        construct_template=construct_template,
        describe_nodes=describe_nodes,
    )


# ---------------------------------------------------------------------------
# Node mapping
# ---------------------------------------------------------------------------

def map_node(n: Dict[str, Any]) -> RDFNode:
    """Map a JSON node object to the appropriate Python RDFNode type."""
    ntype = n.get("type", "")
    if ntype == "var":
        return VarNode(name=n["name"])
    elif ntype == "uri":
        return URINode(value=n["value"])
    elif ntype == "literal":
        return LiteralNode(
            value=n.get("value", ""),
            lang=n.get("lang"),
            datatype=n.get("datatype"),
        )
    elif ntype == "bnode":
        return BNodeNode(label=n.get("label", n.get("value", "")))
    else:
        logger.warning("Unknown node type: %s", ntype)
        return URINode(value=n.get("value", f"unknown:{ntype}"))


# ---------------------------------------------------------------------------
# Expression mapping
# ---------------------------------------------------------------------------

def map_expr(e: Dict[str, Any]) -> Expr:
    """Map a JSON expression to the appropriate Python Expr type."""
    etype = e.get("type", "")

    if etype == "ExprVar":
        return ExprVar(var=e["var"])

    elif etype == "NodeValue":
        return ExprValue(node=map_node(e["node"]))

    elif etype in ("ExprFunction1", "ExprFunction2", "ExprFunctionN"):
        # Jena uses "arg" (singular) for ExprFunction1, "args" (plural) for 2/N
        raw_args = e.get("args", [])
        if not raw_args and "arg" in e:
            raw_args = [e["arg"]]
        args = [map_expr(a) for a in raw_args]
        return ExprFunction(name=e.get("name", ""), args=args)

    elif etype == "ExprAggregator":
        agg = e.get("aggregator", {})
        inner_expr = None
        if "expr" in agg and agg["expr"] is not None:
            inner_expr = map_expr(agg["expr"])
        return ExprAggregator(
            name=agg.get("name", e.get("name", "")),
            distinct=agg.get("distinct", False),
            expr=inner_expr,
            separator=agg.get("separator"),
        )

    elif etype == "ExprFunctionOp":
        from .jena_types import ExprExists
        name = e.get("name", "").lower()
        graph_pattern = map_op(e["graphPattern"])
        return ExprExists(graph_pattern=graph_pattern, negated=(name == "notexists"))

    elif etype == "E_Now":
        return ExprFunction(name="now", args=[])

    elif etype == "E_StrUUID":
        return ExprFunction(name="struuid", args=[])

    elif etype == "E_UUID":
        return ExprFunction(name="uuid", args=[])

    elif etype == "BNode0":
        return ExprFunction(name="bnode", args=[])

    elif etype == "ExprFunction0":
        return ExprFunction(name=e.get("name", ""), args=[])

    else:
        logger.warning("Unknown expr type: %s", etype)
        return ExprValue(node=LiteralNode(value=str(e)))


def map_sort_condition(sc: Dict[str, Any]) -> SortCondition:
    """Map a JSON sort condition."""
    direction = sc.get("direction", "ASC")
    expr_data = sc.get("expr")
    if isinstance(expr_data, str):
        # Simple "?var" string form
        var_name = expr_data.lstrip("?")
        expr = ExprVar(var=var_name)
    else:
        expr = map_expr(expr_data)
    return SortCondition(direction=direction, expr=expr)


# ---------------------------------------------------------------------------
# Op (algebra) mapping
# ---------------------------------------------------------------------------

_OP_MAPPERS = {}


def _register_op(type_name: str):
    """Decorator to register an Op mapper by Jena type name."""
    def decorator(fn):
        _OP_MAPPERS[type_name] = fn
        return fn
    return decorator


def map_op(o: Dict[str, Any]) -> Op:
    """Map a JSON Op object to the appropriate Python Op type."""
    otype = o.get("type", "")
    mapper = _OP_MAPPERS.get(otype)
    if mapper:
        return mapper(o)
    logger.warning("Unknown op type: %s — returning OpNull", otype)
    return OpNull()


@_register_op("OpBGP")
def _map_bgp(o: Dict) -> OpBGP:
    triples = []
    for t in o.get("triples", []):
        triples.append(TriplePattern(
            subject=map_node(t["subject"]),
            predicate=map_node(t["predicate"]),
            object=map_node(t["object"]),
        ))
    return OpBGP(triples=triples)


@_register_op("OpJoin")
def _map_join(o: Dict) -> OpJoin:
    return OpJoin(left=map_op(o["left"]), right=map_op(o["right"]))


@_register_op("OpLeftJoin")
def _map_left_join(o: Dict) -> OpLeftJoin:
    exprs = [map_expr(e) for e in o.get("exprs", [])]
    return OpLeftJoin(
        left=map_op(o["left"]),
        right=map_op(o["right"]),
        exprs=exprs,
    )


@_register_op("OpUnion")
def _map_union(o: Dict) -> OpUnion:
    return OpUnion(left=map_op(o["left"]), right=map_op(o["right"]))


@_register_op("OpFilter")
def _map_filter(o: Dict) -> OpFilter:
    exprs = [map_expr(e) for e in o.get("exprs", [])]
    return OpFilter(exprs=exprs, sub_op=map_op(o["subOp"]))


@_register_op("OpProject")
def _map_project(o: Dict) -> OpProject:
    return OpProject(vars=o.get("vars", []), sub_op=map_op(o["subOp"]))


@_register_op("OpSlice")
def _map_slice(o: Dict) -> OpSlice:
    start = o.get("start", 0)
    length = o.get("length", -1)
    # Normalize Jena's large negative "no offset" sentinel
    if start < 0:
        start = 0
    if length < 0:
        length = -1  # our convention for "no limit"
    return OpSlice(start=start, length=length, sub_op=map_op(o["subOp"]))


@_register_op("OpDistinct")
def _map_distinct(o: Dict) -> OpDistinct:
    return OpDistinct(sub_op=map_op(o["subOp"]))


@_register_op("OpReduced")
def _map_reduced(o: Dict) -> OpReduced:
    return OpReduced(sub_op=map_op(o["subOp"]))


@_register_op("OpOrder")
def _map_order(o: Dict) -> OpOrder:
    conditions = [map_sort_condition(c) for c in o.get("conditions", [])]
    return OpOrder(conditions=conditions, sub_op=map_op(o["subOp"]))


@_register_op("OpGroup")
def _map_group(o: Dict) -> OpGroup:
    group_vars = o.get("groupVars", [])
    aggregators = o.get("aggregators", [])
    return OpGroup(
        group_vars=group_vars,
        aggregators=aggregators,
        sub_op=map_op(o["subOp"]),
    )


@_register_op("OpExtend")
def _map_extend(o: Dict) -> Op:
    # Sidecar may emit either:
    #   {"var": "x", "expr": {...}, "subOp": {...}}  (single)
    #   {"extensions": [{"var": "x", "expr": {...}}, ...], "subOp": {...}}  (array)
    sub_op = map_op(o["subOp"])
    extensions = o.get("extensions")
    if extensions and isinstance(extensions, list):
        # Wrap from innermost out: last extension is outermost
        for ext in extensions:
            sub_op = OpExtend(
                var=ext["var"],
                expr=map_expr(ext["expr"]),
                sub_op=sub_op,
            )
        return sub_op
    else:
        return OpExtend(
            var=o["var"],
            expr=map_expr(o["expr"]),
            sub_op=sub_op,
        )


@_register_op("OpTable")
def _map_table(o: Dict) -> OpTable:
    vars_ = o.get("vars", [])
    rows = []
    for row in o.get("rows", []):
        mapped_row = {}
        for var_name, node_data in row.items():
            mapped_row[var_name] = map_node(node_data)
        rows.append(mapped_row)
    return OpTable(vars=vars_, rows=rows)


@_register_op("OpMinus")
def _map_minus(o: Dict) -> OpMinus:
    return OpMinus(left=map_op(o["left"]), right=map_op(o["right"]))


@_register_op("OpGraph")
def _map_graph(o: Dict) -> OpGraph:
    return OpGraph(
        graph_node=map_node(o["graphNode"]),
        sub_op=map_op(o["subOp"]),
    )


@_register_op("OpSequence")
def _map_sequence(o: Dict) -> OpSequence:
    elements = [map_op(e) for e in o.get("elements", [])]
    return OpSequence(elements=elements)


@_register_op("OpNull")
def _map_null(o: Dict) -> OpNull:
    return OpNull()


@_register_op("OpPath")
def _map_path(o: Dict) -> OpPath:
    tp = o["triplePath"]
    subject = map_node(tp["subject"])
    obj = map_node(tp["object"])
    pred = tp["predicate"]
    path_str = pred.get("value", "")
    path = parse_path_string(path_str)
    return OpPath(subject=subject, path=path, object=obj)


# ---------------------------------------------------------------------------
# Property path string parser
# ---------------------------------------------------------------------------

def parse_path_string(s: str) -> PathExpr:
    """Parse a Jena Path.toString() SPARQL path string into a PathExpr tree.

    Grammar:
      path       = alt_path
      alt_path   = seq_path ( "|" seq_path )*
      seq_path   = unary_path ( "/" unary_path )*
      unary_path = primary_path ( "+" | "*" | "?" )?
                 | "^" unary_path
                 | "!" neg_set
      primary    = "<" uri ">" | "(" path ")"
      neg_set    = primary | "(" primary ( "|" primary )* ")"
    """
    s = s.strip()
    path, rest = _parse_alt(s)
    if rest.strip():
        logger.warning("Trailing characters in path string: %r", rest)
    return path


def _parse_alt(s: str) -> tuple:
    """Parse alt_path = seq_path ( '|' seq_path )*."""
    left, rest = _parse_seq(s)
    while rest.startswith("|"):
        right, rest = _parse_seq(rest[1:])
        left = PathAlt(left=left, right=right)
    return left, rest


def _parse_seq(s: str) -> tuple:
    """Parse seq_path = unary_path ( '/' unary_path )*."""
    left, rest = _parse_unary(s)
    while rest.startswith("/"):
        right, rest = _parse_unary(rest[1:])
        left = PathSeq(left=left, right=right)
    return left, rest


def _parse_unary(s: str) -> tuple:
    """Parse unary_path = primary ('+' | '*' | '?')? | '^' unary | '!' neg_set."""
    s = s.lstrip()

    # Inverse: ^path
    if s.startswith("^"):
        sub, rest = _parse_unary(s[1:])
        return PathInverse(sub=sub), rest

    # Negated property set: !uri or !(uri|uri)
    if s.startswith("!"):
        inner = s[1:].lstrip()
        if inner.startswith("("):
            # Parse !(uri|uri|...)
            uris = []
            pos = 1  # skip '('
            inner = inner[pos:]
            while True:
                inner = inner.lstrip()
                if inner.startswith(")"):
                    inner = inner[1:]
                    break
                if inner.startswith("|"):
                    inner = inner[1:].lstrip()
                p, inner = _parse_primary(inner)
                if isinstance(p, PathLink):
                    uris.append(p.uri)
                elif isinstance(p, PathInverse) and isinstance(p.sub, PathLink):
                    uris.append("^" + p.sub.uri)
            return PathNegPropSet(uris=uris), inner
        else:
            p, rest = _parse_primary(inner)
            if isinstance(p, PathLink):
                return PathNegPropSet(uris=[p.uri]), rest
            return PathNegPropSet(uris=[]), rest

    # Primary with optional repetition suffix
    primary, rest = _parse_primary(s)
    rest = rest.lstrip()
    if rest.startswith("+"):
        return PathOneOrMore(sub=primary), rest[1:]
    if rest.startswith("*"):
        return PathZeroOrMore(sub=primary), rest[1:]
    if rest.startswith("?"):
        return PathZeroOrOne(sub=primary), rest[1:]
    return primary, rest


def _parse_primary(s: str) -> tuple:
    """Parse primary = '<' uri '>' | '(' path ')'."""
    s = s.lstrip()

    # Parenthesized sub-path
    if s.startswith("("):
        inner, rest = _parse_alt(s[1:])
        rest = rest.lstrip()
        if rest.startswith(")"):
            rest = rest[1:]
        return inner, rest

    # URI: <...>
    if s.startswith("<"):
        end = s.index(">", 1)
        uri = s[1:end]
        return PathLink(uri=uri), s[end + 1:]

    # Fallback: consume as bare token (shouldn't happen with well-formed input)
    logger.warning("Unexpected path token: %r", s[:20])
    return PathLink(uri=s), ""


# ---------------------------------------------------------------------------
# Update operation mapping
# ---------------------------------------------------------------------------

def _map_quad(q: Dict[str, Any]) -> QuadPattern:
    """Map a JSON quad to QuadPattern."""
    graph = None
    if q.get("graph") is not None:
        graph = map_node(q["graph"])
    return QuadPattern(
        graph=graph,
        subject=map_node(q["subject"]),
        predicate=map_node(q["predicate"]),
        object=map_node(q["object"]),
    )


def map_update_op(u: Dict[str, Any]) -> UpdateOp:
    """Map a JSON update operation to the appropriate Python type."""
    utype = u.get("type", "")

    if utype == "UpdateDataInsert":
        return UpdateDataInsert(quads=[_map_quad(q) for q in u.get("quads", [])])

    elif utype == "UpdateDataDelete":
        return UpdateDataDelete(quads=[_map_quad(q) for q in u.get("quads", [])])

    elif utype == "UpdateModify":
        where_pattern = None
        if "wherePattern" in u and u["wherePattern"] is not None:
            wp = u["wherePattern"]
            wp_type = wp.get("type", "") if isinstance(wp, dict) else ""
            if wp_type.startswith("Element"):
                where_pattern = map_element_to_op(wp)
            else:
                where_pattern = map_op(wp)
        return UpdateModify(
            with_graph=u.get("withGraph"),
            delete_quads=[_map_quad(q) for q in u.get("deleteQuads", [])],
            insert_quads=[_map_quad(q) for q in u.get("insertQuads", [])],
            using_graphs=u.get("usingGraphs", []),
            where_pattern=where_pattern,
        )

    elif utype == "UpdateDeleteWhere":
        quads = [_map_quad(q) for q in u.get("quads", [])]
        if not quads:
            # Sidecar may not serialize quads; try to extract from template
            quads = _extract_delete_where_quads(u)
        return UpdateDeleteWhere(quads=quads)

    elif utype == "UpdateLoad":
        return UpdateLoad(
            source=u.get("source", ""),
            dest_graph=u.get("destGraph"),
            silent=u.get("silent", False),
        )

    elif utype == "UpdateClear":
        scope, graph = _extract_graph_target(u.get("target"))
        return UpdateClear(
            graph=graph,
            target=scope,
            silent=u.get("silent", False),
        )

    elif utype == "UpdateDrop":
        scope, graph = _extract_graph_target(u.get("target"))
        return UpdateDrop(
            graph=graph,
            target=scope,
            silent=u.get("silent", False),
        )

    elif utype == "UpdateCreate":
        return UpdateCreate(
            graph=u.get("graph", ""),
            silent=u.get("silent", False),
        )

    elif utype == "UpdateCopy":
        return UpdateCopy(
            source=_extract_graph_uri(u.get("source")),
            dest=_extract_graph_uri(u.get("dest")),
            silent=u.get("silent", False),
        )

    elif utype == "UpdateMove":
        return UpdateMove(
            source=_extract_graph_uri(u.get("source")),
            dest=_extract_graph_uri(u.get("dest")),
            silent=u.get("silent", False),
        )

    elif utype == "UpdateAdd":
        return UpdateAdd(
            source=_extract_graph_uri(u.get("source")),
            dest=_extract_graph_uri(u.get("dest")),
            silent=u.get("silent", False),
        )

    else:
        logger.warning("Unknown update type: %s", utype)
        return UpdateClear(target="UNKNOWN")


def _extract_graph_target(target) -> tuple:
    """Parse Jena's target dict {'scope': ..., 'graph': ...} into (scope, graph).

    Returns (scope_str, graph_uri_or_None).
    """
    if target is None:
        return ("DEFAULT", None)
    if isinstance(target, str):
        return (target, None)
    if isinstance(target, dict):
        scope = target.get("scope", "DEFAULT")
        graph = target.get("graph")
        return (scope if scope != "GRAPH" else (graph or "DEFAULT"), graph)
    return ("DEFAULT", None)


def _extract_graph_uri(val) -> str:
    """Parse Jena's source/dest dict {'scope': 'GRAPH', 'graph': uri} to uri string."""
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        return val.get("graph", "")
    return ""


def _extract_delete_where_quads(u: Dict[str, Any]) -> List[QuadPattern]:
    """Try to extract quads from an UpdateDeleteWhere that the sidecar didn't serialize.

    Falls back to empty list if no data available.
    """
    # Some sidecar versions may include a 'template' or 'quads' field
    for key in ("template", "deleteQuads", "quads"):
        raw = u.get(key)
        if raw and isinstance(raw, list):
            return [_map_quad(q) for q in raw]
    logger.warning("UpdateDeleteWhere: sidecar did not provide quads; "
                   "consider using explicit DELETE { } WHERE { } form")
    return []


def map_element_to_op(elem: Dict[str, Any]) -> Op:
    """Convert a Jena syntax Element to an algebra Op.

    The WHERE pattern in UpdateModify uses Element types (syntax level)
    rather than compiled algebra Op types. This converts common elements.
    """
    etype = elem.get("type", "")

    if etype == "ElementPathBlock":
        triples = []
        for t in elem.get("triples", []):
            triples.append(TriplePattern(
                subject=map_node(t["subject"]),
                predicate=map_node(t["predicate"]),
                object=map_node(t["object"]),
            ))
        return OpBGP(triples=triples)

    if etype == "ElementGroup":
        elements = elem.get("elements", [])
        if not elements:
            return OpBGP(triples=[])
        ops = [map_element_to_op(e) for e in elements]
        result = ops[0]
        for op in ops[1:]:
            if isinstance(op, OpFilter):
                # Wrap the accumulated result with the filter
                result = OpFilter(exprs=op.exprs, sub_op=result)
            else:
                result = OpJoin(left=result, right=op)
        return result

    if etype == "ElementFilter":
        expr_data = elem.get("expr")
        if expr_data:
            return OpFilter(exprs=[map_expr(expr_data)], sub_op=OpBGP(triples=[]))
        return OpBGP(triples=[])

    if etype == "ElementOptional":
        inner = elem.get("element")
        if inner:
            return OpLeftJoin(
                left=OpBGP(triples=[]),
                right=map_element_to_op(inner),
                exprs=[],
            )
        return OpBGP(triples=[])

    if etype == "ElementUnion":
        elements = elem.get("elements", [])
        if len(elements) == 0:
            return OpBGP(triples=[])
        ops = [map_element_to_op(e) for e in elements]
        result = ops[0]
        for op in ops[1:]:
            result = OpUnion(left=result, right=op)
        return result

    if etype == "ElementNamedGraph":
        raw_graph = elem.get("graphNode") or elem.get("graph")
        inner = elem.get("sub") or elem.get("element")
        g_node: RDFNode = URINode("urn:default")
        if raw_graph:
            if isinstance(raw_graph, dict):
                g_node = map_node(raw_graph)
            elif isinstance(raw_graph, str):
                g_node = URINode(raw_graph)
        inner_op = map_element_to_op(inner) if inner else OpBGP(triples=[])
        return OpGraph(graph_node=g_node, sub_op=inner_op)

    logger.warning("Unknown element type: %s — returning empty BGP", etype)
    return OpBGP(triples=[])

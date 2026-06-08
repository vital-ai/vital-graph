"""
VitalGraph custom SPARQL function handling for the v2 SQL pipeline.

Handles four vg: function IRIs that appear as ExprFunctionN in the Jena
sidecar JSON AST:

  BIND functions (produce a scalar value):
    - vg:vectorSimilarity(?entity, "text", "index_name")
        → cosine similarity score via server-side vectorization
    - vg:vectorNearby(?entity, "[0.1,0.2,...]", "index_name")
        → cosine similarity with a pre-computed embedding vector
    - vg:geoDistance(?entity, lat, lon)
        → distance in meters (PostGIS ST_Distance)

  FILTER function (produces a boolean):
    - vg:withinRadius(?entity, lat, lon, meters)
        → true if entity is within radius (PostGIS ST_DWithin)

SQL generation strategy:
  - Vector functions → correlated subquery against {space}_vec_{index}
  - Geo functions → correlated subquery against {space}_geo
  - withinRadius in FILTER → EXISTS subquery with ST_DWithin

The vectorSimilarity function requires server-side vectorization of the
search text before SQL execution.  The pipeline records a VectorRequest
on EmitContext so the orchestrator can vectorize and inject the embedding.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Tuple

from ..jena_sparql.jena_types import (
    ExprFunction, ExprVar, ExprValue, LiteralNode,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# VitalGraph namespace and function IRIs
# ---------------------------------------------------------------------------

VG_NS = "http://vital.ai/ontology/vitalgraph#"

VG_VECTOR_SIMILARITY = f"{VG_NS}vectorSimilarity"
VG_VECTOR_NEARBY = f"{VG_NS}vectorNearby"
VG_GEO_DISTANCE = f"{VG_NS}geoDistance"
VG_WITHIN_RADIUS = f"{VG_NS}withinRadius"

VG_VECTOR_FUNCTIONS = frozenset({VG_VECTOR_SIMILARITY, VG_VECTOR_NEARBY})
VG_GEO_FUNCTIONS = frozenset({VG_GEO_DISTANCE, VG_WITHIN_RADIUS})
VG_ALL_FUNCTIONS = VG_VECTOR_FUNCTIONS | VG_GEO_FUNCTIONS


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------

def is_vg_function(expr) -> bool:
    """Check if an expression is a VitalGraph custom function."""
    return (isinstance(expr, ExprFunction)
            and expr.function_iri is not None
            and expr.function_iri in VG_ALL_FUNCTIONS)


def is_vg_vector_function(expr) -> bool:
    """Check if an expression is a VitalGraph vector function."""
    return (isinstance(expr, ExprFunction)
            and expr.function_iri is not None
            and expr.function_iri in VG_VECTOR_FUNCTIONS)


def is_vg_geo_function(expr) -> bool:
    """Check if an expression is a VitalGraph geo function."""
    return (isinstance(expr, ExprFunction)
            and expr.function_iri is not None
            and expr.function_iri in VG_GEO_FUNCTIONS)


# ---------------------------------------------------------------------------
# VectorRequest — metadata for deferred vectorization
# ---------------------------------------------------------------------------

@dataclass
class VectorRequest:
    """Records that a query needs server-side vectorization before execution.

    The orchestrator inspects these after SQL generation, vectorizes each
    search_text using the provider configured on the named index, and
    replaces the placeholder token in the SQL with the actual embedding.
    """
    placeholder: str       # Token in the SQL, e.g. '__VG_EMBED_0__'
    search_text: str       # The raw text to vectorize
    index_name: str        # Which vector index (determines provider + dims)
    space_id: str          # Space for table lookup


# ---------------------------------------------------------------------------
# Argument extraction
# ---------------------------------------------------------------------------

def _literal_value(expr) -> Optional[str]:
    """Extract the string value from an ExprValue(LiteralNode(...))."""
    if isinstance(expr, ExprValue):
        node = expr.node
        if isinstance(node, LiteralNode):
            return node.value
    return None


def _numeric_value(expr) -> Optional[float]:
    """Extract a numeric value from an ExprValue(LiteralNode(...))."""
    val = _literal_value(expr)
    if val is not None:
        try:
            return float(val)
        except (ValueError, TypeError):
            pass
    return None


def _var_name(expr) -> Optional[str]:
    """Extract variable name from an ExprVar."""
    if isinstance(expr, ExprVar):
        return expr.var
    return None


@dataclass
class VectorArgs:
    """Extracted arguments for vg:vectorSimilarity / vg:vectorNearby."""
    entity_var: str        # SPARQL variable name (e.g. "entity")
    search_text: Optional[str]   # For vectorSimilarity: raw search text
    vector_literal: Optional[str]  # For vectorNearby: "[0.1,0.2,...]"
    index_name: str        # Vector index name (e.g. "entity_default")


@dataclass
class GeoArgs:
    """Extracted arguments for vg:geoDistance / vg:withinRadius."""
    entity_var: str        # SPARQL variable name
    latitude: float
    longitude: float
    max_distance_m: Optional[float] = None  # For withinRadius only


def extract_vector_args(expr: ExprFunction) -> Optional[VectorArgs]:
    """Extract arguments from a vg:vectorSimilarity or vg:vectorNearby call.

    Expected signatures:
      vg:vectorSimilarity(?entity, "search text", "index_name")
      vg:vectorNearby(?entity, "[0.1,0.2,...]", "index_name")
    """
    args = expr.args or []
    if len(args) != 3:
        logger.warning("vg: vector function expects 3 args, got %d", len(args))
        return None

    entity_var = _var_name(args[0])
    if entity_var is None:
        logger.warning("vg: vector function arg[0] must be a variable")
        return None

    text_or_vec = _literal_value(args[1])
    if text_or_vec is None:
        logger.warning("vg: vector function arg[1] must be a string literal")
        return None

    index_name = _literal_value(args[2])
    if index_name is None:
        logger.warning("vg: vector function arg[2] must be a string literal")
        return None

    if expr.function_iri == VG_VECTOR_SIMILARITY:
        return VectorArgs(
            entity_var=entity_var,
            search_text=text_or_vec,
            vector_literal=None,
            index_name=index_name,
        )
    else:  # VG_VECTOR_NEARBY
        return VectorArgs(
            entity_var=entity_var,
            search_text=None,
            vector_literal=text_or_vec,
            index_name=index_name,
        )


def extract_geo_args(expr: ExprFunction) -> Optional[GeoArgs]:
    """Extract arguments from a vg:geoDistance or vg:withinRadius call.

    Expected signatures:
      vg:geoDistance(?entity, lat, lon)
      vg:withinRadius(?entity, lat, lon, meters)
    """
    args = expr.args or []
    expected = 4 if expr.function_iri == VG_WITHIN_RADIUS else 3
    if len(args) != expected:
        logger.warning("vg: geo function expects %d args, got %d",
                       expected, len(args))
        return None

    entity_var = _var_name(args[0])
    if entity_var is None:
        logger.warning("vg: geo function arg[0] must be a variable")
        return None

    lat = _numeric_value(args[1])
    lon = _numeric_value(args[2])
    if lat is None or lon is None:
        logger.warning("vg: geo function lat/lon must be numeric literals")
        return None

    max_dist = None
    if expr.function_iri == VG_WITHIN_RADIUS:
        max_dist = _numeric_value(args[3])
        if max_dist is None:
            logger.warning("vg:withinRadius arg[3] (meters) must be numeric")
            return None

    return GeoArgs(
        entity_var=entity_var,
        latitude=lat,
        longitude=lon,
        max_distance_m=max_dist,
    )


# ---------------------------------------------------------------------------
# SQL generation helpers
# ---------------------------------------------------------------------------

def _resolve_uuid_col(entity_var: str, ctx) -> Optional[str]:
    """Resolve the UUID column for a SPARQL variable from the TypeRegistry.

    Returns the uuid_col string (e.g. 'v0__uuid') or None if not found.
    """
    info = ctx.types.get(entity_var)
    if info and info.uuid_col:
        return info.uuid_col
    logger.warning("Cannot resolve UUID column for ?%s", entity_var)
    return None


def _context_clause(ctx) -> str:
    """Return a SQL AND clause for context_uuid scoping, or empty string.

    When graph_lock_uri is set (single-graph queries), vector/geo side-table
    rows are scoped to that graph's context_uuid via a term-table subquery.
    """
    graph_uri = getattr(ctx, 'graph_lock_uri', None)
    if not graph_uri:
        return ""
    # Resolve graph URI to its UUID via a scalar subquery on term table
    term_table = f"{ctx.space_id}_term"
    return (
        f" AND context_uuid = (SELECT term_uuid FROM {term_table} "
        f"WHERE term_text = '{graph_uri}' AND term_type = 'U' LIMIT 1)"
    )


def vector_similarity_sql(
    expr: ExprFunction,
    ctx,
) -> Tuple[Optional[str], Optional[VectorRequest]]:
    """Generate SQL for vg:vectorSimilarity or vg:vectorNearby.

    Returns (sql_expr, vector_request) where:
      - sql_expr: correlated scalar subquery computing cosine similarity
      - vector_request: non-None for vectorSimilarity (needs embedding)
    """
    vargs = extract_vector_args(expr)
    if vargs is None:
        return None, None

    uuid_col = _resolve_uuid_col(vargs.entity_var, ctx)
    if uuid_col is None:
        return None, None

    vec_table = f"{ctx.space_id}_vec_{vargs.index_name}"
    vec_request = None

    if vargs.vector_literal is not None:
        # Pre-computed vector — inline directly
        embedding_sql = f"'{vargs.vector_literal}'::vector"
    else:
        # Needs server-side vectorization — use placeholder
        placeholder = f"__VG_EMBED_{id(expr) % 100000}__"
        embedding_sql = f"'{placeholder}'::vector"
        vec_request = VectorRequest(
            placeholder=placeholder,
            search_text=vargs.search_text or "",
            index_name=vargs.index_name,
            space_id=ctx.space_id,
        )

    # Read optimizer hints (set by vg_optimize pass via emit_extend)
    vg_hints = getattr(ctx, 'vg_hints', {})
    threshold = vg_hints.get('vg_threshold')
    top_k = vg_hints.get('vg_top_k')
    ctx_clause = _context_clause(ctx)

    # Build optional WHERE clauses
    threshold_clause = ""
    if threshold is not None:
        threshold_clause = f" AND 1 - (embedding <=> {embedding_sql}) > {threshold}"

    if top_k:
        # Top-K optimization: ORDER BY distance inside subquery with LIMIT
        # This allows pgvector's HNSW index to drive the search efficiently
        top_limit = top_k['limit']
        direction = top_k.get('direction', 'DESC')
        order_dir = "" if direction == "DESC" else " DESC"  # <=> is distance, lower = more similar
        sql = (
            f"(SELECT 1 - (embedding <=> {embedding_sql}) "
            f"FROM {vec_table} "
            f"WHERE subject_uuid = {uuid_col}{ctx_clause}{threshold_clause} "
            f"ORDER BY embedding <=> {embedding_sql}{order_dir} "
            f"LIMIT 1)"
        )
    else:
        # Standard correlated subquery: cosine similarity score
        # 1 - (embedding <=> query) gives cosine similarity [0, 1] for normalized vectors
        sql = (
            f"(SELECT 1 - (embedding <=> {embedding_sql}) "
            f"FROM {vec_table} "
            f"WHERE subject_uuid = {uuid_col}{ctx_clause}{threshold_clause} "
            f"LIMIT 1)"
        )

    return sql, vec_request


@dataclass
class VectorDrivingSQL:
    """Components for a vector-driving top-K query.

    Instead of a correlated subquery per row, this lets the vector table
    drive the query with a JOIN subquery that pgvector's HNSW index can
    efficiently serve.
    """
    join_subquery: str     # SELECT subject_uuid, score FROM vec ORDER BY dist LIMIT K
    uuid_col: str          # column in child SQL to JOIN on (e.g. 'v0__uuid')
    score_alias: str       # column alias for the score in the join subquery
    vec_request: Optional[VectorRequest]  # non-None if needs vectorization


def vector_top_k_driving_sql(
    expr: ExprFunction,
    ctx,
    limit: int,
    threshold: Optional[float] = None,
) -> Optional[VectorDrivingSQL]:
    """Generate a vector-driving subquery for top-K optimization.

    Instead of computing similarity as a correlated subquery per row,
    this generates a standalone subquery that:
      1. Scans the vector index for top-K nearest neighbors
      2. Returns (subject_uuid, score) tuples
      3. Is joined to the base query by uuid

    This allows pgvector's HNSW/IVFFlat index to drive the search.
    """
    vargs = extract_vector_args(expr)
    if vargs is None:
        return None

    uuid_col = _resolve_uuid_col(vargs.entity_var, ctx)
    if uuid_col is None:
        return None

    vec_table = f"{ctx.space_id}_vec_{vargs.index_name}"
    vec_request = None

    if vargs.vector_literal is not None:
        embedding_sql = f"'{vargs.vector_literal}'::vector"
    else:
        placeholder = f"__VG_EMBED_{id(expr) % 100000}__"
        embedding_sql = f"'{placeholder}'::vector"
        vec_request = VectorRequest(
            placeholder=placeholder,
            search_text=vargs.search_text or "",
            index_name=vargs.index_name,
            space_id=ctx.space_id,
        )

    ctx_clause = _context_clause(ctx)
    # Remove leading " AND " for standalone WHERE
    where_parts = [f"TRUE{ctx_clause}"]
    if threshold is not None:
        where_parts.append(f"1 - (embedding <=> {embedding_sql}) > {threshold}")

    where_sql = " AND ".join(where_parts)

    score_alias = "__vg_score"
    join_subquery = (
        f"SELECT subject_uuid, 1 - (embedding <=> {embedding_sql}) AS {score_alias} "
        f"FROM {vec_table} "
        f"WHERE {where_sql} "
        f"ORDER BY embedding <=> {embedding_sql} "
        f"LIMIT {limit}"
    )

    return VectorDrivingSQL(
        join_subquery=join_subquery,
        uuid_col=uuid_col,
        score_alias=score_alias,
        vec_request=vec_request,
    )


def geo_distance_sql(expr: ExprFunction, ctx) -> Optional[str]:
    """Generate SQL for vg:geoDistance.

    Returns a correlated scalar subquery computing distance in meters.
    """
    gargs = extract_geo_args(expr)
    if gargs is None:
        return None

    uuid_col = _resolve_uuid_col(gargs.entity_var, ctx)
    if uuid_col is None:
        return None

    geo_table = f"{ctx.space_id}_geo"

    # ST_Distance with geography type returns meters
    ctx_clause = _context_clause(ctx)
    sql = (
        f"(SELECT ST_Distance(location, "
        f"ST_MakePoint({gargs.longitude}, {gargs.latitude})::geography) "
        f"FROM {geo_table} "
        f"WHERE subject_uuid = {uuid_col}{ctx_clause} "
        f"LIMIT 1)"
    )

    return sql


def within_radius_sql(expr: ExprFunction, ctx) -> Optional[str]:
    """Generate SQL for vg:withinRadius (FILTER usage).

    Returns an EXISTS subquery for use in WHERE clause.
    """
    gargs = extract_geo_args(expr)
    if gargs is None:
        return None

    uuid_col = _resolve_uuid_col(gargs.entity_var, ctx)
    if uuid_col is None:
        return None

    geo_table = f"{ctx.space_id}_geo"

    # ST_DWithin uses the GiST index for efficient spatial filtering
    ctx_clause = _context_clause(ctx)
    sql = (
        f"EXISTS (SELECT 1 FROM {geo_table} "
        f"WHERE subject_uuid = {uuid_col}{ctx_clause} "
        f"AND ST_DWithin(location, "
        f"ST_MakePoint({gargs.longitude}, {gargs.latitude})::geography, "
        f"{gargs.max_distance_m}))"
    )

    return sql

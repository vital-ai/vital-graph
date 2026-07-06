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
    - vg:trigramSimilarity(?var, "text")
        → pg_trgm word_similarity score (0.0–1.0) on term table

  FILTER function (produces a boolean):
    - vg:withinRadius(?entity, lat, lon, meters)
        → true if entity is within radius (PostGIS ST_DWithin)

SQL generation strategy:
  - Vector functions → correlated subquery against {space}_vec_{index}
  - Text search → correlated subquery against {space}_fts_{index}
  - Hybrid search → JOIN of {space}_fts_{index} + {space}_vec_{index}
  - Trigram similarity → inline word_similarity() on term table column
  - Geo functions → correlated subquery against {space}_geo
  - withinRadius in FILTER → EXISTS subquery with ST_DWithin

The vectorSimilarity function requires server-side vectorization of the
search text before SQL execution.  The pipeline records a VectorRequest
on EmitContext so the orchestrator can vectorize and inject the embedding.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

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
VG_MULTI_VECTOR_SIMILARITY = f"{VG_NS}multiVectorSimilarity"
VG_MULTI_VECTOR_NEARBY = f"{VG_NS}multiVectorNearby"
VG_GEO_DISTANCE = f"{VG_NS}geoDistance"
VG_WITHIN_RADIUS = f"{VG_NS}withinRadius"
VG_WITHIN_BOUNDS = f"{VG_NS}withinBounds"
VG_WITHIN_POLYGON = f"{VG_NS}withinPolygon"

VG_TEXT_SEARCH = f"{VG_NS}textSearch"
VG_HYBRID_SEARCH = f"{VG_NS}hybridSearch"
VG_FUZZY_MATCH = f"{VG_NS}fuzzyMatch"
VG_TRIGRAM_SIMILARITY = f"{VG_NS}trigramSimilarity"

VG_VECTOR_FUNCTIONS = frozenset({VG_VECTOR_SIMILARITY, VG_VECTOR_NEARBY})
VG_TEXT_FUNCTIONS = frozenset({VG_TEXT_SEARCH, VG_HYBRID_SEARCH})
VG_MULTI_VECTOR_FUNCTIONS = frozenset({VG_MULTI_VECTOR_SIMILARITY, VG_MULTI_VECTOR_NEARBY})
VG_GEO_FUNCTIONS = frozenset({VG_GEO_DISTANCE, VG_WITHIN_RADIUS, VG_WITHIN_BOUNDS, VG_WITHIN_POLYGON})
VG_FUZZY_FUNCTIONS = frozenset({VG_FUZZY_MATCH})
VG_TRIGRAM_FUNCTIONS = frozenset({VG_TRIGRAM_SIMILARITY})
VG_ALL_FUNCTIONS = (VG_VECTOR_FUNCTIONS | VG_TEXT_FUNCTIONS
                    | VG_MULTI_VECTOR_FUNCTIONS | VG_GEO_FUNCTIONS
                    | VG_FUZZY_FUNCTIONS | VG_TRIGRAM_FUNCTIONS)


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------

def is_vg_function(expr) -> bool:
    """Check if an expression is a VitalGraph custom function."""
    return (isinstance(expr, ExprFunction)
            and expr.function_iri is not None
            and expr.function_iri in VG_ALL_FUNCTIONS)


def is_vg_vector_function(expr) -> bool:
    """Check if an expression is a VitalGraph vector function (single or multi)."""
    return (isinstance(expr, ExprFunction)
            and expr.function_iri is not None
            and expr.function_iri in (VG_VECTOR_FUNCTIONS | VG_MULTI_VECTOR_FUNCTIONS))


def is_vg_multi_vector_function(expr) -> bool:
    """Check if an expression is a VitalGraph multi-vector function."""
    return (isinstance(expr, ExprFunction)
            and expr.function_iri is not None
            and expr.function_iri in VG_MULTI_VECTOR_FUNCTIONS)


def is_vg_text_function(expr) -> bool:
    """Check if an expression is a VitalGraph text/hybrid search function."""
    return (isinstance(expr, ExprFunction)
            and expr.function_iri is not None
            and expr.function_iri in VG_TEXT_FUNCTIONS)


def is_vg_geo_function(expr) -> bool:
    """Check if an expression is a VitalGraph geo function."""
    return (isinstance(expr, ExprFunction)
            and expr.function_iri is not None
            and expr.function_iri in VG_GEO_FUNCTIONS)


def is_vg_fuzzy_function(expr) -> bool:
    """Check if an expression is a VitalGraph fuzzy match function."""
    return (isinstance(expr, ExprFunction)
            and expr.function_iri is not None
            and expr.function_iri in VG_FUZZY_FUNCTIONS)


def is_vg_trigram_function(expr) -> bool:
    """Check if an expression is a VitalGraph trigram similarity function."""
    return (isinstance(expr, ExprFunction)
            and expr.function_iri is not None
            and expr.function_iri in VG_TRIGRAM_FUNCTIONS)


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


@dataclass
class FuzzyRequest:
    """Records that a query needs fuzzy search resolution before execution.

    The orchestrator inspects these after SQL generation, performs MinHash
    band lookup + RapidFuzz scoring, then replaces the placeholder tokens
    in the SQL with the resolved UUID filter and CASE score expression.
    """
    filter_placeholder: str    # Token for WHERE clause, e.g. '__VG_FUZZY_FILTER_0__'
    score_placeholder: str     # Token for score expression, e.g. '__VG_FUZZY_SCORE_0__'
    search_text: str           # The name string to fuzzy match
    min_score: float           # Minimum score threshold (0-100)
    entity_var: str            # SPARQL variable name for the entity
    uuid_col: str              # SQL column for subject_uuid
    space_id: str              # Space for table lookup


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
class TextSearchArgs:
    """Extracted arguments for vg:textSearch / vg:hybridSearch."""
    entity_var: str        # SPARQL variable name (e.g. "entity")
    search_text: str       # Raw search text
    index_name: str        # Vector index name (e.g. "entity_default")
    alpha: Optional[float] = None  # For hybridSearch: 0..1 vector weight


@dataclass
class FuzzyMatchArgs:
    """Extracted arguments for vg:fuzzyMatch."""
    entity_var: str        # SPARQL variable name
    search_name: str       # Name to fuzzy-match against
    min_score: float       # Minimum similarity threshold (0-100)


@dataclass
class GeoArgs:
    """Extracted arguments for vg:geoDistance / vg:withinRadius."""
    entity_var: str        # SPARQL variable name
    latitude: float
    longitude: float
    max_distance_m: Optional[float] = None  # For withinRadius only


@dataclass
class BoundsArgs:
    """Extracted arguments for vg:withinBounds."""
    entity_var: str        # SPARQL variable name
    min_lat: float         # Southwest corner latitude
    min_lon: float         # Southwest corner longitude
    max_lat: float         # Northeast corner latitude
    max_lon: float         # Northeast corner longitude


@dataclass
class PolygonArgs:
    """Extracted arguments for vg:withinPolygon."""
    entity_var: str        # SPARQL variable name
    wkt_or_geojson: str    # WKT polygon string or GeoJSON


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


def extract_text_search_args(expr: ExprFunction) -> Optional[TextSearchArgs]:
    """Extract arguments from a vg:textSearch or vg:hybridSearch call.

    Expected signatures:
      vg:textSearch(?entity, "search text", "index_name")
      vg:hybridSearch(?entity, "search text", "index_name", alpha)

    alpha is a float in [0,1]: 0 = pure BM25, 1 = pure vector.
    """
    args = expr.args or []
    is_hybrid = expr.function_iri == VG_HYBRID_SEARCH
    expected_min = 4 if is_hybrid else 3
    if len(args) < expected_min:
        logger.warning("vg: text search function expects %d args, got %d",
                       expected_min, len(args))
        return None

    entity_var = _var_name(args[0])
    if entity_var is None:
        logger.warning("vg: text search function arg[0] must be a variable")
        return None

    search_text = _literal_value(args[1])
    if search_text is None:
        logger.warning("vg: text search function arg[1] must be a string literal")
        return None

    index_name = _literal_value(args[2])
    if index_name is None:
        logger.warning("vg: text search function arg[2] must be a string literal")
        return None

    alpha = None
    if is_hybrid:
        alpha = _numeric_value(args[3])
        if alpha is None:
            logger.warning("vg:hybridSearch arg[3] (alpha) must be numeric")
            return None

    return TextSearchArgs(
        entity_var=entity_var,
        search_text=search_text,
        index_name=index_name,
        alpha=alpha,
    )


def extract_fuzzy_match_args(expr: ExprFunction) -> Optional[FuzzyMatchArgs]:
    """Extract arguments from a vg:fuzzyMatch call.

    Expected signature:
      vg:fuzzyMatch(?entity, "search name", min_score)
    """
    args = expr.args or []
    if len(args) not in (2, 3):
        logger.warning("vg:fuzzyMatch expects 2-3 args, got %d", len(args))
        return None

    entity_var = _var_name(args[0])
    if entity_var is None:
        logger.warning("vg:fuzzyMatch arg[0] must be a variable")
        return None

    search_name = _literal_value(args[1])
    if search_name is None:
        logger.warning("vg:fuzzyMatch arg[1] must be a string literal")
        return None

    min_score = 50.0  # Default threshold
    if len(args) == 3:
        val = _numeric_value(args[2])
        if val is None:
            logger.warning("vg:fuzzyMatch arg[2] (min_score) must be numeric")
            return None
        min_score = val

    return FuzzyMatchArgs(
        entity_var=entity_var,
        search_name=search_name,
        min_score=min_score,
    )


def extract_bounds_args(expr: ExprFunction) -> Optional[BoundsArgs]:
    """Extract arguments from a vg:withinBounds call.

    Expected signature:
      vg:withinBounds(?entity, minLat, minLon, maxLat, maxLon)
    """
    args = expr.args or []
    if len(args) != 5:
        logger.warning("vg:withinBounds expects 5 args, got %d", len(args))
        return None

    entity_var = _var_name(args[0])
    if entity_var is None:
        logger.warning("vg:withinBounds arg[0] must be a variable")
        return None

    min_lat = _numeric_value(args[1])
    min_lon = _numeric_value(args[2])
    max_lat = _numeric_value(args[3])
    max_lon = _numeric_value(args[4])

    if min_lat is None or min_lon is None or max_lat is None or max_lon is None:
        logger.warning("vg:withinBounds lat/lon args must be numeric literals")
        return None

    return BoundsArgs(
        entity_var=entity_var,
        min_lat=min_lat,
        min_lon=min_lon,
        max_lat=max_lat,
        max_lon=max_lon,
    )


def extract_polygon_args(expr: ExprFunction) -> Optional[PolygonArgs]:
    """Extract arguments from a vg:withinPolygon call.

    Expected signature:
      vg:withinPolygon(?entity, "POLYGON((...))")
      vg:withinPolygon(?entity, '{"type":"Polygon","coordinates":...}')
    """
    args = expr.args or []
    if len(args) != 2:
        logger.warning("vg:withinPolygon expects 2 args, got %d", len(args))
        return None

    entity_var = _var_name(args[0])
    if entity_var is None:
        logger.warning("vg:withinPolygon arg[0] must be a variable")
        return None

    wkt_or_geojson = _literal_value(args[1])
    if wkt_or_geojson is None:
        logger.warning("vg:withinPolygon arg[1] must be a string literal (WKT or GeoJSON)")
        return None

    return PolygonArgs(
        entity_var=entity_var,
        wkt_or_geojson=wkt_or_geojson,
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


@dataclass
class MultiVectorTriplet:
    """A single (query, index, weight) triplet for multi-vector search."""
    search_text: Optional[str]       # For multiVectorSimilarity: raw text
    vector_literal: Optional[str]    # For multiVectorNearby: "[0.1,0.2,...]"
    index_name: str
    weight: float


@dataclass
class MultiVectorArgs:
    """Extracted arguments for vg:multiVectorSimilarity / vg:multiVectorNearby."""
    entity_var: str
    triplets: List[MultiVectorTriplet] = field(default_factory=list)


def extract_multi_vector_args(expr: ExprFunction) -> Optional[MultiVectorArgs]:
    """Extract arguments from vg:multiVectorSimilarity or vg:multiVectorNearby.

    Expected signature:
      vg:multiVectorSimilarity(?entity, text1, idx1, w1, text2, idx2, w2, ...)
      vg:multiVectorNearby(?entity, vec1, idx1, w1, vec2, idx2, w2, ...)

    Args after the entity variable come in repeating triplets:
      (query_text_or_vector, index_name, weight)
    """
    args = expr.args or []
    if len(args) < 4:
        logger.warning("vg: multi-vector function expects at least 4 args "
                       "(entity + 1 triplet), got %d", len(args))
        return None

    entity_var = _var_name(args[0])
    if entity_var is None:
        logger.warning("vg: multi-vector function arg[0] must be a variable")
        return None

    remaining = args[1:]
    if len(remaining) % 3 != 0:
        logger.warning("vg: multi-vector function args after entity must be "
                       "in triplets (query, index, weight), got %d extra args",
                       len(remaining))
        return None

    is_nearby = (expr.function_iri == VG_MULTI_VECTOR_NEARBY)
    triplets = []

    for i in range(0, len(remaining), 3):
        text_or_vec = _literal_value(remaining[i])
        if text_or_vec is None:
            logger.warning("vg: multi-vector triplet[%d] query must be a "
                           "string literal", i // 3)
            return None

        index_name = _literal_value(remaining[i + 1])
        if index_name is None:
            logger.warning("vg: multi-vector triplet[%d] index_name must be a "
                           "string literal", i // 3)
            return None

        weight = _numeric_value(remaining[i + 2])
        if weight is None:
            logger.warning("vg: multi-vector triplet[%d] weight must be "
                           "numeric", i // 3)
            return None

        triplets.append(MultiVectorTriplet(
            search_text=None if is_nearby else text_or_vec,
            vector_literal=text_or_vec if is_nearby else None,
            index_name=index_name,
            weight=weight,
        ))

    return MultiVectorArgs(entity_var=entity_var, triplets=triplets)


# ---------------------------------------------------------------------------
# SQL generation helpers
# ---------------------------------------------------------------------------

def _resolve_uuid_col(entity_var: str, ctx) -> Optional[str]:
    """Resolve the UUID column for a SPARQL variable from the TypeRegistry.

    Returns the uuid_col string (e.g. 'v0__uuid') or a deferred placeholder
    token if the variable isn't registered yet (child pattern not yet emitted).
    Returns None only if deferred resolution is not available on the context.
    """
    info = ctx.types.get(entity_var)
    if info and info.uuid_col:
        return info.uuid_col
    # Attempt deferred resolution: emit a placeholder that will be resolved
    # after the child pattern is emitted and populates the TypeRegistry.
    if hasattr(ctx, 'add_deferred_uuid'):
        placeholder = f"__VG_UUID_{entity_var}__"
        ctx.add_deferred_uuid(entity_var, placeholder)
        logger.debug("Deferred UUID resolution for ?%s → %s", entity_var, placeholder)
        return placeholder
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


def _resolve_index_name(mapping_name: str, index_type: str, ctx) -> str:
    """Resolve a mapping name to the actual underlying index name.

    Uses search_mapping_meta (mapping_name → {'vector': ..., 'fts': ...})
    loaded at generation time.  Falls back to using mapping_name directly
    if no junction entry exists (backward compat / direct index references).
    """
    meta = getattr(ctx, 'search_mapping_meta', {})
    entry = meta.get(mapping_name)
    if entry and index_type in entry:
        return entry[index_type]
    # Fallback: treat as direct index name
    return mapping_name


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

    resolved_vec_index = _resolve_index_name(vargs.index_name, 'vector', ctx)
    vec_table = f"{ctx.space_id}_vec_{resolved_vec_index}"
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
            index_name=resolved_vec_index,
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
    child_sql: Optional[str] = None,
    child_uuid_col: Optional[str] = None,
) -> Optional[VectorDrivingSQL]:
    """Generate a vector-driving subquery for top-K optimization.

    Instead of computing similarity as a correlated subquery per row,
    this generates a standalone subquery that:
      1. Scans the vector index for top-K nearest neighbors
      2. Returns (subject_uuid, score) tuples
      3. Is joined to the base query by uuid

    When child_sql and child_uuid_col are provided, the vector scan is
    restricted to subjects present in the child pattern.  This guarantees
    the top-K results will all survive the downstream INNER JOIN.
    """
    vargs = extract_vector_args(expr)
    if vargs is None:
        return None

    uuid_col = _resolve_uuid_col(vargs.entity_var, ctx)
    if uuid_col is None:
        return None

    resolved_vec_index = _resolve_index_name(vargs.index_name, 'vector', ctx)
    vec_table = f"{ctx.space_id}_vec_{resolved_vec_index}"
    vec_request = None

    if vargs.vector_literal is not None:
        embedding_sql = f"'{vargs.vector_literal}'::vector"
    else:
        placeholder = f"__VG_EMBED_{id(expr) % 100000}__"
        embedding_sql = f"'{placeholder}'::vector"
        vec_request = VectorRequest(
            placeholder=placeholder,
            search_text=vargs.search_text or "",
            index_name=resolved_vec_index,
            space_id=ctx.space_id,
        )

    ctx_clause = _context_clause(ctx)
    # Remove leading " AND " for standalone WHERE
    where_parts = [f"TRUE{ctx_clause}"]
    if threshold is not None:
        where_parts.append(f"1 - (embedding <=> {embedding_sql}) > {threshold}")

    # Filter to only subjects present in the child pattern so the top-K
    # results are guaranteed to survive the downstream INNER JOIN.
    if child_sql and child_uuid_col:
        where_parts.append(
            f"subject_uuid IN "
            f"(SELECT DISTINCT {child_uuid_col} FROM ({child_sql}) AS __cs "
            f"WHERE {child_uuid_col} IS NOT NULL)"
        )

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


def _resolve_fts_languages(index_name: str, ctx) -> List[str]:
    """Resolve the language list for an FTS index from pre-loaded metadata.

    Falls back to ``['english']`` if the index is not found in fts_index_meta.
    """
    fts_meta = getattr(ctx, 'fts_index_meta', {})
    meta = fts_meta.get(index_name)
    if meta and meta.get('languages'):
        return meta['languages']
    return ['english']


def _build_tsquery_expr(languages: List[str], safe_text: str) -> str:
    """Build a multi-language plainto_tsquery expression.

    For a single language::

        plainto_tsquery('english'::regconfig, 'search text')

    For multiple languages::

        (plainto_tsquery('english'::regconfig, 'search text')
         || plainto_tsquery('spanish'::regconfig, 'search text'))
    """
    parts = [
        f"plainto_tsquery('{lang}'::regconfig, '{safe_text}')"
        for lang in languages
    ]
    if len(parts) == 1:
        return parts[0]
    return "(" + " || ".join(parts) + ")"


def text_search_sql(
    expr: ExprFunction,
    ctx,
) -> Optional[str]:
    """Generate SQL for vg:textSearch.

    Returns a correlated scalar subquery computing BM25 rank via
    ``ts_rank_cd(tsv, plainto_tsquery(...))``.  Uses the GIN tsvector
    index on ``{space}_fts_{index_name}``.

    When the FTS index is configured with multiple languages, generates
    a concatenated tsquery (``tsquery1 || tsquery2``) so that matches
    via any configured stemmer are found.
    """
    targs = extract_text_search_args(expr)
    if targs is None:
        return None

    uuid_col = _resolve_uuid_col(targs.entity_var, ctx)
    if uuid_col is None:
        return None

    resolved_fts_index = _resolve_index_name(targs.index_name, 'fts', ctx)
    fts_table = f"{ctx.space_id}_fts_{resolved_fts_index}"
    ctx_clause = _context_clause(ctx)
    safe_text = targs.search_text.replace("'", "''")
    languages = _resolve_fts_languages(resolved_fts_index, ctx)
    tsquery = _build_tsquery_expr(languages, safe_text)

    # Read optimizer hints (set by vg_optimize pass)
    vg_hints = getattr(ctx, 'vg_hints', {})
    top_k = vg_hints.get('vg_top_k')
    threshold = vg_hints.get('vg_threshold')

    threshold_clause = ""
    if threshold is not None:
        threshold_clause = f" AND ts_rank_cd(tsv, {tsquery}) > {threshold}"

    if top_k:
        # Top-K optimization: ORDER BY rank inside subquery with LIMIT
        # This allows the GIN tsvector index to drive the search efficiently
        sql = (
            f"(SELECT ts_rank_cd(tsv, {tsquery}) "
            f"FROM {fts_table} "
            f"WHERE subject_uuid = {uuid_col}{ctx_clause} "
            f"AND tsv @@ {tsquery}{threshold_clause} "
            f"ORDER BY ts_rank_cd(tsv, {tsquery}) DESC "
            f"LIMIT 1)"
        )
    else:
        sql = (
            f"(SELECT ts_rank_cd(tsv, {tsquery}) "
            f"FROM {fts_table} "
            f"WHERE subject_uuid = {uuid_col}{ctx_clause} "
            f"AND tsv @@ {tsquery}{threshold_clause} "
            f"LIMIT 1)"
        )
    return sql


def hybrid_search_sql(
    expr: ExprFunction,
    ctx,
) -> Tuple[Optional[str], Optional[VectorRequest]]:
    """Generate SQL for vg:hybridSearch.

    Computes a two-table fusion of BM25 (from ``_fts_`` table) + vector
    similarity (from ``_vec_`` table)::

        (1 - alpha) * ts_rank_cd(f.tsv, query) + alpha * (1 - (v.embedding <=> vec))

    The two tables are JOINed on ``(subject_uuid, context_uuid)``.
    Both tables share the same primary key, so the join is O(1) per candidate.

    Returns (sql_expr, vector_request).  The vector_request is non-None
    because the search text needs server-side vectorization.
    """
    targs = extract_text_search_args(expr)
    if targs is None:
        return None, None

    uuid_col = _resolve_uuid_col(targs.entity_var, ctx)
    if uuid_col is None:
        return None, None

    resolved_fts_index = _resolve_index_name(targs.index_name, 'fts', ctx)
    resolved_vec_index = _resolve_index_name(targs.index_name, 'vector', ctx)
    fts_table = f"{ctx.space_id}_fts_{resolved_fts_index}"
    vec_table = f"{ctx.space_id}_vec_{resolved_vec_index}"
    ctx_clause = _context_clause(ctx)
    # Build context clause variants for the two table aliases
    ctx_clause_f = ctx_clause.replace('context_uuid', 'f.context_uuid') if ctx_clause else ''
    ctx_clause_v = ctx_clause.replace('context_uuid', 'v.context_uuid') if ctx_clause else ''
    safe_text = targs.search_text.replace("'", "''")
    alpha = targs.alpha if targs.alpha is not None else 0.5
    languages = _resolve_fts_languages(resolved_fts_index, ctx)
    tsquery = _build_tsquery_expr(languages, safe_text)

    placeholder = f"__VG_EMBED_{id(expr) % 100000}__"
    embedding_sql = f"'{placeholder}'::vector"
    vec_request = VectorRequest(
        placeholder=placeholder,
        search_text=targs.search_text,
        index_name=resolved_vec_index,
        space_id=ctx.space_id,
    )

    bm25 = f"ts_rank_cd(f.tsv, {tsquery})"
    cosine_sim = f"(1 - (v.embedding <=> {embedding_sql}))"

    sql = (
        f"(SELECT {1.0 - alpha:.6f} * {bm25} + {alpha:.6f} * {cosine_sim} "
        f"FROM {fts_table} f "
        f"JOIN {vec_table} v ON f.subject_uuid = v.subject_uuid "
        f"AND f.context_uuid = v.context_uuid "
        f"WHERE f.subject_uuid = {uuid_col}{ctx_clause_f} "
        f"AND (f.tsv @@ {tsquery} "
        f"OR (v.embedding <=> {embedding_sql}) < 0.6) "
        f"LIMIT 1)"
    )
    return sql, vec_request


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
    # Use MIN to return closest distance when subject has multiple geo rows
    ctx_clause = _context_clause(ctx)
    sql = (
        f"(SELECT MIN(ST_Distance(location, "
        f"ST_MakePoint({gargs.longitude}, {gargs.latitude})::geography)) "
        f"FROM {geo_table} "
        f"WHERE subject_uuid = {uuid_col}{ctx_clause})"
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


def within_bounds_sql(expr: ExprFunction, ctx) -> Optional[str]:
    """Generate SQL for vg:withinBounds (FILTER usage).

    Returns an EXISTS subquery checking if entity location falls within
    the bounding box defined by (minLat, minLon) to (maxLat, maxLon).
    Uses ST_Within + ST_MakeEnvelope which leverages the GiST spatial index.
    """
    bargs = extract_bounds_args(expr)
    if bargs is None:
        return None

    uuid_col = _resolve_uuid_col(bargs.entity_var, ctx)
    if uuid_col is None:
        return None

    geo_table = f"{ctx.space_id}_geo"
    ctx_clause = _context_clause(ctx)

    # ST_MakeEnvelope(xmin, ymin, xmax, ymax, srid)
    # In geography terms: (minLon, minLat, maxLon, maxLat, 4326)
    sql = (
        f"EXISTS (SELECT 1 FROM {geo_table} "
        f"WHERE subject_uuid = {uuid_col}{ctx_clause} "
        f"AND ST_Within(location::geometry, "
        f"ST_MakeEnvelope({bargs.min_lon}, {bargs.min_lat}, "
        f"{bargs.max_lon}, {bargs.max_lat}, 4326)))"
    )

    return sql


def within_polygon_sql(expr: ExprFunction, ctx) -> Optional[str]:
    """Generate SQL for vg:withinPolygon (FILTER usage).

    Returns an EXISTS subquery checking if entity location falls within
    the specified polygon. Accepts WKT or GeoJSON polygon strings.
    Uses ST_Within which leverages the GiST spatial index.
    """
    pargs = extract_polygon_args(expr)
    if pargs is None:
        return None

    uuid_col = _resolve_uuid_col(pargs.entity_var, ctx)
    if uuid_col is None:
        return None

    geo_table = f"{ctx.space_id}_geo"
    ctx_clause = _context_clause(ctx)
    safe_geom = pargs.wkt_or_geojson.replace("'", "''")

    # Detect if GeoJSON (starts with '{') or WKT
    if safe_geom.strip().startswith('{'):
        # GeoJSON
        geom_expr = f"ST_GeomFromGeoJSON('{safe_geom}')"
    else:
        # WKT
        geom_expr = f"ST_GeomFromText('{safe_geom}', 4326)"

    sql = (
        f"EXISTS (SELECT 1 FROM {geo_table} "
        f"WHERE subject_uuid = {uuid_col}{ctx_clause} "
        f"AND ST_Within(location::geometry, {geom_expr}))"
    )

    return sql


def fuzzy_match_sql(
    expr: ExprFunction, ctx,
) -> Tuple[Optional[str], Optional[FuzzyRequest]]:
    """Generate SQL for vg:fuzzyMatch.

    Returns (sql_expr, fuzzy_request) where:
      - sql_expr: a placeholder token that will be replaced with a CASE
        expression mapping subject UUIDs to their fuzzy scores.
      - fuzzy_request: non-None, contains the search text and min_score
        for the resolve step to perform MinHash + RapidFuzz scoring.

    If no fuzzy mapping is configured for the space, the resolve step
    falls back to pg_trgm similarity() via the existing GIN trigram index.
    """
    fargs = extract_fuzzy_match_args(expr)
    if fargs is None:
        return None, None

    uuid_col = _resolve_uuid_col(fargs.entity_var, ctx)
    if uuid_col is None:
        return None, None

    # Generate unique placeholder tokens
    expr_id = id(expr) % 100000
    score_placeholder = f"__VG_FUZZY_SCORE_{expr_id}__"
    filter_placeholder = f"__VG_FUZZY_FILTER_{expr_id}__"

    # The score expression is the placeholder — the resolve step will
    # replace it with a CASE expression mapping UUIDs to scores.
    sql = score_placeholder

    fuzzy_request = FuzzyRequest(
        filter_placeholder=filter_placeholder,
        score_placeholder=score_placeholder,
        search_text=fargs.search_name,
        min_score=fargs.min_score,
        entity_var=fargs.entity_var,
        uuid_col=uuid_col,
        space_id=ctx.space_id,
    )

    return sql, fuzzy_request


# ---------------------------------------------------------------------------
# Multi-vector SQL generation
# ---------------------------------------------------------------------------

# Default oversample factor: fetch this many × final limit from each vector
_MULTI_VEC_OVERSAMPLE = 5
# Absolute cap on oversampled candidates per vector
_MULTI_VEC_OVERSAMPLE_CAP = 300


def multi_vector_similarity_sql(
    expr: ExprFunction,
    ctx,
) -> Tuple[Optional[str], List[VectorRequest]]:
    """Generate SQL for vg:multiVectorSimilarity or vg:multiVectorNearby.

    Produces a correlated scalar subquery that:
    1. Fetches oversampled top-K candidates from each vector index
    2. Intersects the candidate sets (entity must exist in all indexes)
    3. Computes normalized weighted score
    4. Returns the combined score for the correlated entity

    The SQL uses CTEs internally via a LATERAL subquery pattern.

    Returns (sql_expr, vector_requests) where vector_requests is a list
    of VectorRequest objects for triplets that need server-side vectorization.
    """
    mvargs = extract_multi_vector_args(expr)
    if mvargs is None:
        return None, []

    uuid_col = _resolve_uuid_col(mvargs.entity_var, ctx)
    if uuid_col is None:
        return None, []

    ctx_clause = _context_clause(ctx)
    vec_requests: List[VectorRequest] = []

    # Read multi-vector config from context (set by REST API layer)
    mv_config = getattr(ctx, 'multi_vector_config', {})
    fusion_strategy = mv_config.get('fusion_strategy', 'weighted_sum')
    oversample_factor = mv_config.get('oversample_factor', _MULTI_VEC_OVERSAMPLE)

    # Auto-detect mixed models: if indexes use different embedding models or
    # dimensions and no explicit strategy was requested, upgrade to relative_score
    # so that raw cosine scores from different models are normalized to [0,1].
    if fusion_strategy == 'weighted_sum':
        vi_meta = getattr(ctx, 'vector_index_meta', {})
        if vi_meta:
            models = set()
            for t in mvargs.triplets:
                meta = vi_meta.get(t.index_name)
                if meta and meta.get('model_name'):
                    models.add((meta['model_name'], meta.get('dimensions')))
            if len(models) > 1:
                fusion_strategy = 'relative_score'

    # Determine oversample limit from optimizer hints or use default
    vg_hints = getattr(ctx, 'vg_hints', {})
    top_k_hint = vg_hints.get('vg_top_k')
    final_limit = top_k_hint['limit'] if top_k_hint else 20
    oversample = min(final_limit * oversample_factor, _MULTI_VEC_OVERSAMPLE_CAP)

    # Normalize weights to sum to 1.0
    total_weight = sum(t.weight for t in mvargs.triplets)
    if total_weight <= 0:
        total_weight = 1.0
    norm_weights = [t.weight / total_weight for t in mvargs.triplets]

    # Build per-triplet embedding SQL and collect VectorRequests
    embedding_sqls: List[str] = []
    resolved_triplet_indexes: List[str] = []
    for i, triplet in enumerate(mvargs.triplets):
        resolved_idx = _resolve_index_name(triplet.index_name, 'vector', ctx)
        resolved_triplet_indexes.append(resolved_idx)
        if triplet.vector_literal is not None:
            embedding_sqls.append(f"'{triplet.vector_literal}'::vector")
        else:
            placeholder = f"__VG_EMBED_MV{i}_{id(expr) % 100000}__"
            embedding_sqls.append(f"'{placeholder}'::vector")
            vec_requests.append(VectorRequest(
                placeholder=placeholder,
                search_text=triplet.search_text or "",
                index_name=resolved_idx,
                space_id=ctx.space_id,
            ))

    # Build CTE-based SQL: one CTE per vector
    cte_parts: List[str] = []
    n = len(mvargs.triplets)
    for i, triplet in enumerate(mvargs.triplets):
        vec_table = f"{ctx.space_id}_vec_{resolved_triplet_indexes[i]}"
        emb = embedding_sqls[i]
        cte_parts.append(
            f"__mv_v{i} AS (\n"
            f"  SELECT subject_uuid, 1 - (embedding <=> {emb}) AS score\n"
            f"  FROM {vec_table}\n"
            f"  WHERE subject_uuid = {uuid_col}{ctx_clause}\n"
            f"  LIMIT 1\n"
            f")"
        )

    # For a correlated subquery, we only need the score for the specific entity
    # (uuid_col). Each CTE checks if that entity exists in the index and gets
    # its score. If it doesn't exist in ALL indexes, the result is NULL.

    null_checks = [f"__mv_v{i}.score IS NOT NULL" for i in range(n)]
    null_check_expr = " AND ".join(null_checks)
    from_parts = [f"__mv_v{i}" for i in range(n)]
    from_clause = ", ".join(from_parts)

    # Build score expression based on fusion strategy
    if fusion_strategy == 'relative_score':
        # Relative score: normalize each score to [0,1] within the CTE,
        # then weighted sum. For correlated single-entity lookups, we use
        # window functions over a wider candidate set per-index.
        # In the correlated pattern (LIMIT 1 per entity), min/max are the
        # same value, so normalization degrades to 1.0. We add normalization
        # CTEs for when we switch to non-correlated top-K.
        # For now, generate the same SQL with CASE-guarded normalization.
        norm_cte_parts = list(cte_parts)  # copy raw CTEs
        for i in range(n):
            norm_cte_parts.append(
                f"__mv_n{i} AS (\n"
                f"  SELECT subject_uuid,\n"
                f"    CASE WHEN MAX(score) OVER () = MIN(score) OVER () THEN 1.0\n"
                f"         ELSE (score - MIN(score) OVER ()) / "
                f"(MAX(score) OVER () - MIN(score) OVER ())\n"
                f"    END AS score\n"
                f"  FROM __mv_v{i}\n"
                f")"
            )
        score_parts = [f"{nw:.6f} * __mv_n{i}.score" for i, nw in enumerate(norm_weights)]
        score_expr = " + ".join(score_parts)
        null_checks_norm = [f"__mv_n{i}.score IS NOT NULL" for i in range(n)]
        null_check_expr_norm = " AND ".join(null_checks_norm)
        from_parts_norm = [f"__mv_n{i}" for i in range(n)]
        from_clause_norm = ", ".join(from_parts_norm)
        cte_sql = ",\n".join(norm_cte_parts)
        sql = (
            f"(WITH {cte_sql}\n"
            f" SELECT CASE WHEN {null_check_expr_norm} "
            f"THEN {score_expr} ELSE NULL END\n"
            f" FROM {from_clause_norm})"
        )
    elif fusion_strategy == 'ranked':
        # Ranked fusion (Reciprocal Rank Fusion): 1/(rank + 60)
        # For correlated single-entity lookups, rank is always 1,
        # so RRF score = 1/61 per index. Normalized weighted sum.
        rank_cte_parts = list(cte_parts)
        for i in range(n):
            rank_cte_parts.append(
                f"__mv_r{i} AS (\n"
                f"  SELECT subject_uuid,\n"
                f"    1.0 / (ROW_NUMBER() OVER (ORDER BY score DESC) + 60) "
                f"AS rank_score\n"
                f"  FROM __mv_v{i}\n"
                f")"
            )
        score_parts = [f"{nw:.6f} * __mv_r{i}.rank_score"
                       for i, nw in enumerate(norm_weights)]
        score_expr = " + ".join(score_parts)
        null_checks_rank = [f"__mv_r{i}.rank_score IS NOT NULL" for i in range(n)]
        null_check_expr_rank = " AND ".join(null_checks_rank)
        from_parts_rank = [f"__mv_r{i}" for i in range(n)]
        from_clause_rank = ", ".join(from_parts_rank)
        cte_sql = ",\n".join(rank_cte_parts)
        sql = (
            f"(WITH {cte_sql}\n"
            f" SELECT CASE WHEN {null_check_expr_rank} "
            f"THEN {score_expr} ELSE NULL END\n"
            f" FROM {from_clause_rank})"
        )
    else:
        # Default: weighted_sum — simple weighted combination of raw scores
        score_parts = [f"{nw:.6f} * __mv_v{i}.score"
                       for i, nw in enumerate(norm_weights)]
        score_expr = " + ".join(score_parts)
        cte_sql = ",\n".join(cte_parts)
        sql = (
            f"(WITH {cte_sql}\n"
            f" SELECT CASE WHEN {null_check_expr} "
            f"THEN {score_expr} ELSE NULL END\n"
            f" FROM {from_clause})"
        )

    return sql, vec_requests


# =====================================================================
# Trigram similarity  (pg_trgm word_similarity on the term table)
# =====================================================================

@dataclass
class TrigramArgs:
    """Parsed arguments for vg:trigramSimilarity(?var, "text")."""
    var_name: str       # SPARQL variable (e.g. "name")
    search_text: str    # The fuzzy search string


def extract_trigram_args(expr: ExprFunction) -> Optional[TrigramArgs]:
    """Extract arguments from vg:trigramSimilarity(?var, "text").

    Returns None if the arguments are malformed.
    """
    args = expr.args or []
    if len(args) < 2:
        logger.warning("vg:trigramSimilarity requires 2 args, got %d", len(args))
        return None

    var_name = _var_name(args[0])
    search_text = _literal_value(args[1])

    if var_name is None or search_text is None:
        logger.warning(
            "vg:trigramSimilarity: arg[0] must be a variable, arg[1] a literal"
        )
        return None

    return TrigramArgs(var_name=var_name, search_text=search_text)


def trigram_similarity_sql(
    expr: ExprFunction,
    ctx,
) -> Optional[str]:
    """Generate SQL for vg:trigramSimilarity(?var, "text").

    Returns an inline ``word_similarity(search_text, column)`` expression
    that uses the existing GIN trigram index (``gin_trgm_ops``) on the
    ``{space}_term`` table.

    Unlike vector/text/hybrid search functions which use correlated
    subqueries, trigram similarity is a simple scalar expression on the
    variable's already-bound text column.

    Example SPARQL::

        BIND(vg:trigramSimilarity(?name, "Jonh Smth") AS ?similarity)

    Generates::

        word_similarity('Jonh Smth', q1.term_text)
    """
    targs = extract_trigram_args(expr)
    if targs is None:
        return None

    # Resolve the variable to its SQL text column
    info = ctx.types.get(targs.var_name) if hasattr(ctx, 'types') else None
    if info is None or not info.text_col:
        logger.warning(
            "vg:trigramSimilarity: variable ?%s has no text column",
            targs.var_name,
        )
        return None

    text_col = info.text_col
    safe_text = targs.search_text.replace("'", "''")

    # word_similarity is asymmetric: word_similarity(query, text)
    # Returns 0.0–1.0 where 1.0 = exact match
    sql = f"word_similarity('{safe_text}', {text_col})"
    return sql

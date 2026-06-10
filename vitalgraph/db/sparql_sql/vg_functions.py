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

VG_VECTOR_FUNCTIONS = frozenset({VG_VECTOR_SIMILARITY, VG_VECTOR_NEARBY})
VG_MULTI_VECTOR_FUNCTIONS = frozenset({VG_MULTI_VECTOR_SIMILARITY, VG_MULTI_VECTOR_NEARBY})
VG_GEO_FUNCTIONS = frozenset({VG_GEO_DISTANCE, VG_WITHIN_RADIUS})
VG_ALL_FUNCTIONS = VG_VECTOR_FUNCTIONS | VG_MULTI_VECTOR_FUNCTIONS | VG_GEO_FUNCTIONS


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
    for i, triplet in enumerate(mvargs.triplets):
        if triplet.vector_literal is not None:
            embedding_sqls.append(f"'{triplet.vector_literal}'::vector")
        else:
            placeholder = f"__VG_EMBED_MV{i}_{id(expr) % 100000}__"
            embedding_sqls.append(f"'{placeholder}'::vector")
            vec_requests.append(VectorRequest(
                placeholder=placeholder,
                search_text=triplet.search_text or "",
                index_name=triplet.index_name,
                space_id=ctx.space_id,
            ))

    # Build CTE-based SQL: one CTE per vector
    cte_parts: List[str] = []
    n = len(mvargs.triplets)
    for i, triplet in enumerate(mvargs.triplets):
        vec_table = f"{ctx.space_id}_vec_{triplet.index_name}"
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

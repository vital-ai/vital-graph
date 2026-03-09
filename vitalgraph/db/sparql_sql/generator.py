"""
v2 SQL Generator — orchestrates the full SPARQL → SQL pipeline.

Pipeline stages:
  1. Compile (sidecar) → JSON
  2. Map (jena_ast_mapper) → Op tree
  3. Collect → PlanV2
  4. Materialize constants (resolve __CONST__ tokens to UUIDs)
  5. Emit → SQL string
  6. Substitute constants into SQL
  7. Apply var_map renaming

This module is the v2 equivalent of v1's jena_sql_generator.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..jena_sparql.jena_ast_mapper import map_compile_response, CompileResult

from .ir import AliasGenerator
from .collect import collect, _CONST_PREFIX, _CONST_SUFFIX, _esc
from .emit import emit
from .emit_context import EmitContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class GenerateResult:
    """Result of the v2 SQL generation pipeline."""
    sql: str = ""
    var_map: Dict[str, str] = field(default_factory=dict)
    sparql_vars: List[str] = field(default_factory=list)
    ok: bool = True
    error: Optional[str] = None
    trace_json: Optional[str] = None


# ---------------------------------------------------------------------------
# Constant materialization (copied from v1 for isolation)
# ---------------------------------------------------------------------------

def substitute_constants(sql: str, aliases: AliasGenerator) -> str:
    """Replace __CONST_c_N__ tokens with resolved 'uuid'::uuid literals."""
    if not aliases.constants:
        return sql

    for (text, ttype), col_name in aliases.constants.items():
        token = f"{_CONST_PREFIX}{col_name}{_CONST_SUFFIX}"
        uuid_str = aliases.resolved_constants.get(col_name)
        if uuid_str:
            replacement = f"'{uuid_str}'::uuid"
        else:
            # Fallback: inline scalar subquery
            term_table = "_const"
            replacement = (
                f"(SELECT term_uuid FROM {term_table} "
                f"WHERE term_text = '{_esc(text)}' AND term_type = '{ttype}')"
            )
        sql = sql.replace(token, replacement)

    return sql


def build_constants_cte(aliases: AliasGenerator, term_table: str) -> str:
    """Build WITH _const AS (...) CTE for unresolved constants."""
    if not aliases.constants:
        return ""
    if len(aliases.resolved_constants) == len(aliases.constants):
        return ""
    pairs = [
        (text, ttype) for (text, ttype), col_name in aliases.constants.items()
        if col_name not in aliases.resolved_constants
    ]
    if not pairs:
        return ""
    if len(pairs) == 1:
        text, ttype = pairs[0]
        where = f"term_text = '{_esc(text)}' AND term_type = '{ttype}'"
    else:
        values = ", ".join(
            f"('{_esc(text)}', '{ttype}')" for text, ttype in pairs
        )
        where = f"(term_text, term_type) IN ({values})"
    return (
        f"WITH _const AS (\n"
        f"  SELECT term_text, term_type, term_uuid FROM {term_table}\n"
        f"  WHERE {where}\n"
        f")\n"
    )


# ---------------------------------------------------------------------------
# Predicate cardinality stats for join reordering
# ---------------------------------------------------------------------------

_stats_cache: Dict[str, tuple] = {}


def invalidate_stats_cache(space_id: str) -> None:
    """Clear cached stats for a space so the next query reloads from DB."""
    _stats_cache.pop(space_id, None)


async def _load_quad_stats(
    aliases: 'AliasGenerator',
    space_id: str,
    conn_params: Optional[Dict[str, Any]] = None,
    conn=None,
):
    """Load predicate cardinality stats from stats tables.

    Populates aliases.quad_stats and aliases.pred_stats for use by
    the join reorder heuristic.
    """
    if space_id in _stats_cache:
        aliases.quad_stats, aliases.pred_stats = _stats_cache[space_id]
        return

    from . import db_provider as db

    try:
        pred_rows = await db.execute_query(
            f"SELECT predicate_uuid::text, row_count "
            f"FROM {space_id}_rdf_pred_stats",
            conn_params=conn_params, conn=conn,
        )
        pred_stats = {r["predicate_uuid"]: r["row_count"] for r in pred_rows}

        quad_rows = await db.execute_query(
            f"SELECT predicate_uuid::text, object_uuid::text, row_count "
            f"FROM {space_id}_rdf_stats "
            f"WHERE row_count >= 2 AND row_count <= 200000",
            conn_params=conn_params, conn=conn,
        )
        quad_stats = {
            (r["predicate_uuid"], r["object_uuid"]): r["row_count"]
            for r in quad_rows
        }

        aliases.quad_stats = quad_stats
        aliases.pred_stats = pred_stats
        _stats_cache[space_id] = (quad_stats, pred_stats)
        logger.debug("Loaded %d pred stats, %d quad stats for %s",
                     len(pred_stats), len(quad_stats), space_id)

    except Exception as e:
        logger.debug("No quad stats for %s (MV may not exist): %s", space_id, e)
        _stats_cache[space_id] = ({}, {})


# ---------------------------------------------------------------------------
# Datatype cache loader
# ---------------------------------------------------------------------------

async def _load_datatype_cache(
    space_id: str,
    conn_params: Optional[Dict[str, Any]] = None,
    conn=None,
) -> Dict[int, str]:
    """Load datatype_id → datatype_uri mapping from {space}_datatype table."""
    if conn is None and conn_params is None:
        return {}

    from . import db_provider as db

    datatype_table = f"{space_id}_datatype"
    try:
        rows = await db.execute_query(
            f"SELECT datatype_id, datatype_uri FROM {datatype_table}",
            conn_params=conn_params, conn=conn,
        )
        cache = {r["datatype_id"]: r["datatype_uri"] for r in rows}
        logger.debug("Loaded %d datatype mappings from %s",
                     len(cache), datatype_table)
        return cache
    except Exception:
        logger.debug("No datatype table for space %s — datatype cache empty",
                     space_id)
        return {}


async def warm_stats_cache(
    space_id: str,
    conn_params: Optional[Dict[str, Any]] = None,
    conn=None,
) -> None:
    """Pre-load predicate cardinality stats into the global cache."""
    if space_id in _stats_cache:
        return

    from .ir import AliasGenerator
    dummy = AliasGenerator()
    await _load_quad_stats(dummy, space_id,
                           conn_params=conn_params, conn=conn)


# ---------------------------------------------------------------------------
# Main generator function
# ---------------------------------------------------------------------------

async def materialize_constants(
    aliases: AliasGenerator,
    term_table: str,
    conn_params: Optional[Dict[str, Any]] = None,
    conn=None,
) -> None:
    """Batch-resolve all registered constants to UUIDs via one DB query."""
    if not aliases.constants:
        return

    from . import db_provider as db

    pairs = list(aliases.constants.keys())
    if len(pairs) == 1:
        text, ttype = pairs[0]
        sql = (
            f"SELECT term_text, term_type, term_uuid FROM {term_table} "
            f"WHERE term_text = '{_esc(text)}' AND term_type = '{ttype}' LIMIT 1"
        )
    else:
        values = ", ".join(
            f"('{_esc(text)}', '{ttype}')" for text, ttype in pairs
        )
        sql = (
            f"SELECT term_text, term_type, term_uuid FROM {term_table} "
            f"WHERE (term_text, term_type) IN ({values})"
        )

    rows = await db.execute_query(sql, conn_params=conn_params, conn=conn)
    text_map = {(r["term_text"], r["term_type"]): str(r["term_uuid"]) for r in rows}

    for (text, ttype), col_name in aliases.constants.items():
        uuid_str = text_map.get((text, ttype))
        if uuid_str:
            aliases.resolved_constants[col_name] = uuid_str
        else:
            logger.warning("Constant not found: text=%r type=%r", text, ttype)

    logger.debug("Materialized %d/%d constants",
                 len(aliases.resolved_constants), len(aliases.constants))


async def generate_sql(
    compile_result: CompileResult,
    space_id: str,
    conn_params: Optional[Dict[str, Any]] = None,
    conn=None,
    graph_lock_uri: Optional[str] = None,
    default_graph: Optional[str] = None,
) -> GenerateResult:
    """Generate SQL from a compiled SPARQL query using the v2 pipeline.

    The collect/emit pipeline is pure (no I/O).  Only constant
    materialization, stats loading, datatype loading, and MV checks
    are awaited.
    """
    if not compile_result.ok:
        return GenerateResult(ok=False, error=compile_result.error)

    # --- UPDATE dispatch ---
    if compile_result.update_ops:
        from .emit_update import update_to_sql
        sql = await update_to_sql(compile_result.update_ops, space_id,
                                  conn_params=conn_params, conn=conn,
                                  default_graph_uri=default_graph)
        return GenerateResult(ok=True, sql=sql, var_map={}, sparql_vars=[])

    algebra = compile_result.algebra
    meta = compile_result.meta

    if algebra is None:
        return GenerateResult(ok=False, error="No algebra in compile result")

    try:
        # Stage 1: Collect → PlanV2 (pure, no I/O)
        aliases = AliasGenerator()
        if graph_lock_uri:
            aliases.graph_lock_uri = graph_lock_uri
        if default_graph:
            aliases.default_graph = default_graph
        plan = collect(algebra, space_id, aliases)

        # Inject PROJECT to exclude anonymous blank node variables
        from .var_scope import compute_scope
        from .ir import PlanV2, KIND_PROJECT, KIND_DISTINCT, KIND_REDUCED

        def _is_anon(v: str) -> bool:
            return v.startswith("?") or v.startswith(".")

        def _needs_anon_project(p: PlanV2) -> bool:
            if p.kind == KIND_PROJECT:
                return False
            scope = compute_scope(p)
            return any(_is_anon(v) for v in scope.all_visible)

        if _needs_anon_project(plan):
            if plan.kind in (KIND_DISTINCT, KIND_REDUCED) and plan.children:
                inner = plan.children[0]
                scope = compute_scope(inner)
                named = [v for v in sorted(scope.all_visible)
                         if not _is_anon(v)]
                proj = PlanV2(kind=KIND_PROJECT,
                              project_vars=named,
                              children=[inner])
                plan.children = [proj]
            else:
                scope = compute_scope(plan)
                named = [v for v in sorted(scope.all_visible)
                         if not _is_anon(v)]
                plan = PlanV2(kind=KIND_PROJECT,
                              project_vars=named,
                              children=[plan])

        # Stage 2: Materialize constants
        term_table = f"{space_id}_term"
        if conn is not None or conn_params is not None:
            await materialize_constants(aliases, term_table,
                                        conn_params=conn_params, conn=conn)

        # Stage 2 post: Prune dead UNION branches (constants absent from term table)
        from .prune_union import prune_dead_union_branches
        plan = prune_dead_union_branches(plan, aliases)

        # Stage 2a: Load predicate cardinality stats
        if conn is not None or conn_params is not None:
            await _load_quad_stats(aliases, space_id,
                                   conn_params=conn_params, conn=conn)

        # Stage 2a.1: Edge table rewrite
        from .ensure_edge_table import ensure_edge_table
        from .ensure_frame_entity_table import ensure_frame_entity_table
        if conn is not None or conn_params is not None:
            if await ensure_edge_table(space_id, conn=conn, conn_params=conn_params):
                from .rewrite_edge_table import rewrite_edge_table
                plan = rewrite_edge_table(plan, aliases, space_id)

            # Stage 2a.2: Frame-entity table rewrite
            if await ensure_frame_entity_table(space_id, conn=conn, conn_params=conn_params):
                from .rewrite_frame_entity_table import rewrite_frame_entity_table
                plan = rewrite_frame_entity_table(plan, aliases, space_id)

        # Stage 2b: Load datatype cache
        datatype_cache = await _load_datatype_cache(
            space_id, conn_params=conn_params, conn=conn)

        # Stage 2c: Compute text-needed vars (skip term JOINs for internal-only vars)
        from .var_scope import compute_text_needed_vars
        text_needed = compute_text_needed_vars(plan)

        # Stage 3: Emit → SQL (pure, no I/O)
        from .emit_context import ProcessingTrace
        sparql_text = getattr(meta, 'sparql', '') if meta else ''
        trace = ProcessingTrace(sparql_query=sparql_text)
        base_uri = meta.base_uri if meta else None
        ctx = EmitContext(space_id=space_id, aliases=aliases,
                          graph_lock_uri=graph_lock_uri, base_uri=base_uri,
                          trace=trace, datatype_cache=datatype_cache,
                          text_needed_vars=text_needed)
        sql_str = emit(plan, ctx)

        # Stage 4: Substitute constants
        sql_str = substitute_constants(sql_str, aliases)

        # Stage 5: Prepend CTE for unresolved constants
        cte_prefix = build_constants_cte(aliases, term_table)
        if cte_prefix:
            sql_str = cte_prefix + sql_str

        # Extract sparql_vars
        sparql_vars = []
        if meta and meta.project_vars:
            sparql_vars = [v for v in meta.project_vars if v != "*"]
        if not sparql_vars and plan.kind == "project" and plan.project_vars:
            sparql_vars = list(plan.project_vars)
        if not sparql_vars:
            from .var_scope import compute_scope
            scope = compute_scope(plan)
            sparql_vars = sorted(scope.all_visible)

        # Build var_map from TypeRegistry
        var_map = {}
        for sparql_name in ctx.types.all_vars():
            info = ctx.types.get(sparql_name)
            if info and info.sql_name:
                var_map[info.sql_name] = sparql_name

        ctx.trace.log_step(0, "final", "generator",
                           f"var_map: {var_map}")

        return GenerateResult(
            sql=sql_str,
            var_map=var_map,
            sparql_vars=sparql_vars,
            trace_json=ctx.trace.to_json(),
        )

    except Exception as e:
        logger.error("v2 SQL generation failed: %s", e, exc_info=True)
        return GenerateResult(ok=False, error=str(e))

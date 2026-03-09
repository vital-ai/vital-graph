"""
Translates Jena Op/Expr trees into PostgreSQL SQL using sqlglot.

Architecture (v2 — three-pass collect/resolve/emit):
  Pass 1 (collect): Walk Op tree → RelationPlan IR tree.
  Pass 2 (resolve): Assign concrete aliases, column names, ON clauses.
  Pass 3 (emit):    Walk resolved plan → SQL string.

Modules:
  jena_sql_ir.py          — IR dataclasses (TableRef, VarSlot, RelationPlan, etc.)
  jena_sql_helpers.py     — Shared utilities (_esc, _node_text, _vars_in_expr)
  jena_sql_collect.py     — Pass 1: Op → RelationPlan
  jena_sql_resolve.py     — Pass 2: resolve aliases/columns
  jena_sql_emit.py        — Pass 3: plan → SQL string
  jena_sql_expressions.py — Expr/Function/Agg → SQL
  jena_sql_updates.py     — Update operations → SQL

This file is the public API entry point and re-exports for backward compatibility.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import sqlglot

from .jena_sparql.jena_types import CompileResult, VarNode, URINode
from .jena_sql_helpers import _esc

# --- IR re-exports (used by tests and orchestrator) ---
from .jena_sql_ir import (
    PG_DIALECT,
    AliasGenerator,
    SQLGenResult,
    TableRef,
    VarSlot,
    RelationPlan,
    VarBinding,
    SQLContext,
    SQLFragment,
)

# --- Expression re-exports ---
from .jena_sql_expressions import (
    expr_to_sql,
    _expr_to_sql_str,
    _expr_to_sql_str_inner,
    _FUNC_MAP,
)

# --- Helpers re-exports ---
from .jena_sql_helpers import (
    _esc, _node_text, _node_type, _vars_in_expr,
    build_constants_cte, materialize_constants, substitute_constants,
)

# --- Pass functions ---
from .jena_sql_collect import collect as _collect
from .jena_sql_resolve import resolve as _resolve
from .jena_sql_emit import emit as _emit

# --- Update re-exports ---
from .jena_sql_updates import update_to_sql

logger = logging.getLogger(__name__)


# ===========================================================================
# Predicate cardinality stats for join ordering
# ===========================================================================

# Module-level cache: {space_id: (quad_stats, pred_stats)}
_stats_cache: Dict[str, tuple] = {}


def _load_quad_stats(aliases: AliasGenerator, space_id: str,
                     conn_params=None, conn=None):
    """Load predicate cardinality stats from materialized views.

    Populates aliases.quad_stats and aliases.pred_stats for use by
    the join reorder heuristic.  Stats are cached per space_id.
    Falls back silently if the MVs don't exist yet.
    """
    if space_id in _stats_cache:
        aliases.quad_stats, aliases.pred_stats = _stats_cache[space_id]
        return

    from . import db

    try:
        # Predicate-only stats (small: ~14 rows for WordNet)
        pred_rows = db.execute_query(
            f"SELECT predicate_uuid::text, row_count "
            f"FROM {space_id}_rdf_pred_stats",
            conn_params=conn_params, conn=conn,
        )
        pred_stats = {r["predicate_uuid"]: r["row_count"] for r in pred_rows}

        # (pred, obj) pair stats — only load pairs where obj has few values
        # (high-selectivity pairs).  Skip predicates where every object is
        # unique (e.g. hasName) since those have cardinality = 1 anyway.
        quad_rows = db.execute_query(
            f"SELECT predicate_uuid::text, object_uuid::text, row_count "
            f"FROM {space_id}_rdf_stats "
            f"WHERE row_count <= 200000",
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


# ===========================================================================
# SPARQL→SQL variable name mapping (Pass 6)
# ===========================================================================

_COMPANION_SUFFIXES = ("__type", "__uuid", "__lang", "__datatype", "__num")


def _apply_var_map(
    sql_str: str,
    sparql_vars: List[str],
    aliases: AliasGenerator,
) -> tuple:
    """Rename outermost SELECT column aliases to opaque v{N} names.

    Args:
        sql_str: The emitted SQL (no CTE prefix).
        sparql_vars: Projected SPARQL variable names in order.
        aliases: AliasGenerator to allocate opaque names.

    Returns:
        (renamed_sql, var_map) where var_map maps sql_name → sparql_name.
    """
    try:
        parsed = sqlglot.parse_one(sql_str, dialect=PG_DIALECT)
    except Exception:
        logger.warning("var_map: sqlglot parse failed, skipping rename")
        return sql_str, {}

    # Collect all column aliases from the outermost SELECT
    alias_set = set()
    for expr in parsed.expressions:
        if hasattr(expr, "alias") and expr.alias:
            alias_set.add(expr.alias)

    # Build rename mapping: sparql_name → opaque, companion → opaque companion
    rename_map: Dict[str, str] = {}
    var_map: Dict[str, str] = {}
    for sparql_name in sparql_vars:
        opaque = aliases.next_var(sparql_name)
        var_map[opaque] = sparql_name
        rename_map[sparql_name] = opaque
        for suffix in _COMPANION_SUFFIXES:
            old = sparql_name + suffix
            if old in alias_set:
                rename_map[old] = opaque + suffix

    # Apply renames to the outermost SELECT aliases
    for expr in parsed.expressions:
        if hasattr(expr, "alias") and expr.alias in rename_map:
            new_name = rename_map[expr.alias]
            expr.set("alias", sqlglot.exp.to_identifier(new_name))

    return parsed.sql(dialect=PG_DIALECT), var_map


# ===========================================================================
# Public API
# ===========================================================================

def generate_sql(result: CompileResult, space_id: str,
                 conn_params=None, conn=None, graph_uri: str = None,
                 optimize: bool = False) -> SQLGenResult:
    """Top-level entry point: CompileResult → SQLGenResult.

    Returns a ``SQLGenResult`` containing the SQL string, a var_map
    (opaque SQL column name → original SPARQL variable name), and the
    ordered list of projected SPARQL variable names.

    Args:
        result: Compiled SPARQL algebra from the sidecar.
        space_id: PostgreSQL table prefix.
        conn_params: Optional DB connection params. When provided,
            constants are resolved to literal UUIDs via a batch query
            (materialize phase) for dramatically faster execution.
        conn: Optional existing psycopg connection to reuse (avoids
            pool checkout overhead in the materialize phase).
        graph_uri: Optional graph lock. When provided, ALL quad tables
            are constrained to ``context_uuid = <graph_uri>``, applied
            after collect so GRAPH clauses add their own constraints
            independently (conflicting values → empty result).
        optimize: If True, run sqlglot optimizer passes on the emitted
            SQL (pushdown_predicates, simplify, eliminate_joins,
            eliminate_ctes).  Safe — falls back to original SQL on error.
    """
    if result.update_ops:
        parts = []
        for uop in result.update_ops:
            parts.append(update_to_sql(uop, space_id))
        return SQLGenResult(sql=";".join(parts))

    query_type = getattr(result.meta, 'query_type', None) if result.meta else None

    # DESCRIBE without algebra or with OpNull: generate direct triple lookup SQL
    from .jena_sparql.jena_types import OpNull as _OpNull
    if query_type == "DESCRIBE" and (result.algebra is None or isinstance(result.algebra, _OpNull)):
        return SQLGenResult(sql=_generate_describe_sql(result, space_id))

    if result.algebra is None:
        raise ValueError("CompileResult has no algebra and no update_ops")

    term_table = f"{space_id}_term"
    aliases = AliasGenerator()

    import time as _time

    # Graph lock: set before collect so _collect_bgp applies it per quad
    if graph_uri:
        aliases.graph_uri = graph_uri

    # Pass 1: collect
    _t0 = _time.monotonic()
    plan = _collect(result.algebra, space_id, aliases)
    _t_collect = _time.monotonic()

    # Pass 1.5: materialize — resolve constants to literal UUIDs
    if aliases.constants:
        try:
            materialize_constants(aliases, term_table, conn_params=conn_params, conn=conn)
        except Exception as e:
            logger.warning("Constants materialize failed, will use CTE fallback: %s", e)
    _t_materialize = _time.monotonic()

    # Pass 1.6: load predicate cardinality stats for join ordering
    _load_quad_stats(aliases, space_id, conn_params=conn_params, conn=conn)

    # Pass 1.7: edge MV rewrite — replace hasEdgeSource/hasEdgeDestination
    # quad pairs with single edge_mv table lookups
    from .jena_sql_edge_mv import rewrite_edge_mv as _rewrite_edge_mv
    from .jena_sql_edge_mv import ensure_edge_mv as _ensure_edge_mv
    if _ensure_edge_mv(space_id, conn=conn, conn_params=conn_params):
        plan = _rewrite_edge_mv(plan, aliases, space_id)

    # Pass 1.8: frame-entity MV rewrite — collapse slot+edge patterns into
    # a single pre-computed frame→entity lookup (5 fewer JOINs per hop)
    from .jena_sql_frame_entity_mv import rewrite_frame_entity_mv as _rewrite_femv
    from .jena_sql_frame_entity_mv import ensure_frame_entity_mv as _ensure_femv
    if _ensure_femv(space_id, conn=conn, conn_params=conn_params):
        plan = _rewrite_femv(plan, aliases, space_id)

    # Pass 2: resolve
    resolved = _resolve(plan, space_id, aliases)
    _t_resolve = _time.monotonic()

    # Pass 2.5: load datatype cache (datatype_id → URI mapping)
    from .jena_sql_emit import set_datatype_cache as _set_dt_cache
    try:
        dt_rows = db.execute_query(
            f"SELECT datatype_id, datatype_uri FROM {space_id}_datatype",
            conn=conn, conn_params=conn_params,
        )
        _set_dt_cache({r["datatype_id"]: r["datatype_uri"] for r in dt_rows})
    except Exception:
        _set_dt_cache({})

    # Pass 3: emit — set stats before emitting so join reorder can use them
    from .jena_sql_emit import set_quad_stats as _set_stats
    _set_stats(aliases.quad_stats, aliases.pred_stats)
    sql_str = _emit(resolved, space_id)
    _t_emit = _time.monotonic()

    # Pass 4: substitute placeholder tokens with resolved UUIDs (or CTE refs)
    sql_str = substitute_constants(sql_str, aliases)
    _t_subst = _time.monotonic()

    # Pass 5 (optional): sqlglot optimizer
    if optimize:
        from .optimize import optimize_sql
        sql_str = optimize_sql(sql_str, space_id=space_id)
    _t_opt = _time.monotonic()

    generate_sql.last_timing = {
        "collect_ms": (_t_collect - _t0) * 1000,
        "materialize_ms": (_t_materialize - _t_collect) * 1000,
        "resolve_ms": (_t_resolve - _t_materialize) * 1000,
        "emit_ms": (_t_emit - _t_resolve) * 1000,
        "substitute_ms": (_t_subst - _t_emit) * 1000,
        "optimize_ms": (_t_opt - _t_subst) * 1000 if optimize else 0,
    }

    # Prepend constants CTE only if some constants were NOT resolved
    cte_prefix = build_constants_cte(aliases, term_table)

    # ASK: wrap as boolean EXISTS check — no user-facing columns
    if query_type == "ASK":
        return SQLGenResult(sql=f"{cte_prefix}SELECT EXISTS({sql_str}) AS result")

    # DESCRIBE with WHERE clause: find all triples about matched resources
    if query_type == "DESCRIBE":
        return SQLGenResult(
            sql=cte_prefix + _wrap_describe_sql(result, space_id, sql_str))

    # Pass 6: apply SPARQL→SQL variable name mapping
    # Rename outermost SELECT column aliases from SPARQL names to opaque v{N}
    sparql_vars = _all_vars(resolved)
    sql_str, var_map = _apply_var_map(sql_str, sparql_vars, aliases)

    return SQLGenResult(
        sql=cte_prefix + sql_str,
        var_map=var_map,
        sparql_vars=sparql_vars,
    )


def op_to_sql(op, ctx: SQLContext) -> SQLFragment:
    """v1-compat: Op → SQLFragment via the 3-pass pipeline."""
    aliases = ctx.aliases
    plan = _collect(op, ctx.space_id, aliases, graph_uri=ctx.graph_uri)
    resolved = _resolve(plan, ctx.space_id, aliases)
    sql_str = _emit(resolved, ctx.space_id)
    parsed = sqlglot.parse_one(sql_str, dialect=PG_DIALECT)
    # Build exposed vars from the resolved plan
    exposed = {}
    for var in _all_vars(resolved):
        exposed[var] = var
    # Include extend vars
    if resolved.extend_exprs:
        for var in resolved.extend_exprs:
            exposed[var] = var
    return SQLFragment(select=parsed, exposed_vars=exposed)


def _all_vars(plan: RelationPlan) -> List[str]:
    """Collect all variable names from a plan, including EXTEND (BIND) vars."""
    if plan.select_vars is not None:
        return list(plan.select_vars)
    vars = list(plan.var_slots.keys())
    if plan.extend_exprs:
        for v in plan.extend_exprs:
            if v not in vars:
                vars.append(v)
    return vars


# ===========================================================================
# DESCRIBE helpers
# ===========================================================================

def _describe_triples_sql(space_id: str, uri: str) -> str:
    """Generate SQL to fetch all triples where a URI appears as subject or object."""
    quad = f"{space_id}_rdf_quad"
    term = f"{space_id}_term"
    esc_uri = _esc(uri)
    return (
        f"SELECT s.term_text AS subject, p.term_text AS predicate, "
        f"o.term_text AS object, o.term_type AS object_type, "
        f"o.lang AS object_lang, o.datatype_id AS object_datatype "
        f"FROM {quad} q "
        f"JOIN {term} s ON q.subject_uuid = s.term_uuid "
        f"JOIN {term} p ON q.predicate_uuid = p.term_uuid "
        f"JOIN {term} o ON q.object_uuid = o.term_uuid "
        f"WHERE s.term_text = '{esc_uri}' "
        f"UNION "
        f"SELECT s.term_text AS subject, p.term_text AS predicate, "
        f"o.term_text AS object, o.term_type AS object_type, "
        f"o.lang AS object_lang, o.datatype_id AS object_datatype "
        f"FROM {quad} q "
        f"JOIN {term} s ON q.subject_uuid = s.term_uuid "
        f"JOIN {term} p ON q.predicate_uuid = p.term_uuid "
        f"JOIN {term} o ON q.object_uuid = o.term_uuid "
        f"WHERE o.term_text = '{esc_uri}' AND o.term_type = 'U'"
    )


def _generate_describe_sql(result: CompileResult, space_id: str) -> str:
    """Generate DESCRIBE SQL for direct URI nodes (no WHERE clause)."""
    parts = []
    for node in (result.meta.describe_nodes if result.meta else []):
        if isinstance(node, URINode):
            parts.append(_describe_triples_sql(space_id, node.value))
    if not parts:
        return "SELECT NULL AS subject, NULL AS predicate, NULL AS object WHERE FALSE"
    return " UNION ".join(parts)


def _wrap_describe_sql(result: CompileResult, space_id: str, where_sql: str) -> str:
    """Wrap a WHERE-clause SQL as a DESCRIBE: find all triples about matched resources."""
    quad = f"{space_id}_rdf_quad"
    term = f"{space_id}_term"
    # The WHERE clause gives us URIs for the describe variables
    # Find all triples where those URIs appear as subject or object
    return (
        f"SELECT s.term_text AS subject, p.term_text AS predicate, "
        f"o.term_text AS object, o.term_type AS object_type, "
        f"o.lang AS object_lang, o.datatype_id AS object_datatype "
        f"FROM {quad} q "
        f"JOIN {term} s ON q.subject_uuid = s.term_uuid "
        f"JOIN {term} p ON q.predicate_uuid = p.term_uuid "
        f"JOIN {term} o ON q.object_uuid = o.term_uuid "
        f"WHERE s.term_text IN (SELECT * FROM ({where_sql}) AS _desc) "
        f"UNION "
        f"SELECT s.term_text AS subject, p.term_text AS predicate, "
        f"o.term_text AS object, o.term_type AS object_type, "
        f"o.lang AS object_lang, o.datatype_id AS object_datatype "
        f"FROM {quad} q "
        f"JOIN {term} s ON q.subject_uuid = s.term_uuid "
        f"JOIN {term} p ON q.predicate_uuid = p.term_uuid "
        f"JOIN {term} o ON q.object_uuid = o.term_uuid "
        f"WHERE o.term_text IN (SELECT * FROM ({where_sql}) AS _desc2) "
        f"AND o.term_type = 'U'"
    )

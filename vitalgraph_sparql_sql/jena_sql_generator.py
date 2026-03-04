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

from .jena_types import CompileResult, VarNode, URINode
from .jena_sql_helpers import _esc

# --- IR re-exports (used by tests and orchestrator) ---
from .jena_sql_ir import (
    PG_DIALECT,
    AliasGenerator,
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
# Public API
# ===========================================================================

def generate_sql(result: CompileResult, space_id: str,
                 conn_params=None, conn=None, graph_uri: str = None,
                 optimize: bool = False) -> str:
    """Top-level entry point: CompileResult → PostgreSQL SQL string.

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
        return ";".join(parts)

    query_type = getattr(result.meta, 'query_type', None) if result.meta else None

    # DESCRIBE without algebra or with OpNull: generate direct triple lookup SQL
    from .jena_types import OpNull as _OpNull
    if query_type == "DESCRIBE" and (result.algebra is None or isinstance(result.algebra, _OpNull)):
        return _generate_describe_sql(result, space_id)

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

    # Pass 2: resolve
    resolved = _resolve(plan, space_id, aliases)
    _t_resolve = _time.monotonic()

    # Pass 3: emit
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

    # ASK: wrap as boolean EXISTS check
    if query_type == "ASK":
        return f"{cte_prefix}SELECT EXISTS({sql_str}) AS result"

    # DESCRIBE with WHERE clause: find all triples about matched resources
    if query_type == "DESCRIBE":
        return cte_prefix + _wrap_describe_sql(result, space_id, sql_str)

    return cte_prefix + sql_str


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
    """Collect all variable names from a plan."""
    if plan.select_vars is not None:
        return list(plan.select_vars)
    return list(plan.var_slots.keys())


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

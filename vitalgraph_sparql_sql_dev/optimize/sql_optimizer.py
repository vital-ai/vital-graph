"""
Post-emit SQL optimizer using sqlglot.

Takes a raw SQL string from the emit phase, parses it into a sqlglot AST,
runs a curated set of optimizer passes, and serializes back to a string.

This is a **non-invasive** layer: the existing emit code stays unchanged.
The optimizer is called after emit + substitute in generate_sql.

Passes applied (in order):
    1. pushdown_predicates — push WHERE conditions into subqueries/JOINs
    2. simplify            — boolean/math simplification, remove AND TRUE
    3. eliminate_joins      — remove JOINs whose columns are never used
    4. eliminate_ctes       — remove CTEs that became unused after other passes

All passes verified to preserve MATERIALIZED CTEs (see tests/).
"""

from __future__ import annotations

import logging
import time
from typing import Dict, Optional

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.pushdown_predicates import pushdown_predicates
from sqlglot.optimizer.simplify import simplify
from sqlglot.optimizer.eliminate_ctes import eliminate_ctes
from sqlglot.optimizer.eliminate_joins import eliminate_joins

logger = logging.getLogger(__name__)

PG_DIALECT = "postgres"

# Ordered list of safe passes
SAFE_PASSES = [
    ("pushdown_predicates", pushdown_predicates),
    ("simplify", simplify),
    ("eliminate_joins", eliminate_joins),
    ("eliminate_ctes", eliminate_ctes),
]


def build_schema(space_id: str) -> Dict:
    """Build a sqlglot-compatible schema dict for our quad/term tables.

    Several optimizer passes (qualify, pushdown_projections, annotate_types)
    work better when they know the table structure.
    """
    quad = f"{space_id}_rdf_quad"
    term = f"{space_id}_term"
    return {
        quad: {
            "subject_uuid": "UUID",
            "predicate_uuid": "UUID",
            "object_uuid": "UUID",
            "context_uuid": "UUID",
        },
        term: {
            "term_uuid": "UUID",
            "term_text": "TEXT",
            "term_type": "CHAR",
            "lang": "TEXT",
        },
    }


def optimize_sql(sql: str, space_id: Optional[str] = None) -> str:
    """Apply sqlglot optimizer passes to a SQL string.

    Args:
        sql: Raw SQL string from the emit phase.
        space_id: If provided, builds a schema hint for the optimizer.

    Returns:
        Optimized SQL string.  If parsing or optimization fails, returns
        the original SQL unchanged (never breaks the pipeline).
    """
    t0 = time.monotonic()

    try:
        ast = sqlglot.parse_one(sql, dialect=PG_DIALECT)
    except Exception as e:
        logger.debug("sqlglot parse failed, skipping optimization: %s", e)
        return sql

    original_sql = sql  # keep for fallback
    timing = {}

    for name, pass_fn in SAFE_PASSES:
        tp = time.monotonic()
        try:
            ast = pass_fn(ast)
        except Exception as e:
            logger.debug("sqlglot pass %s failed, skipping: %s", name, e)
        timing[name] = (time.monotonic() - tp) * 1000

    try:
        optimized = ast.sql(dialect=PG_DIALECT)
    except Exception as e:
        logger.debug("sqlglot serialization failed, returning original: %s", e)
        return original_sql

    total_ms = (time.monotonic() - t0) * 1000
    timing["total_ms"] = total_ms

    # Stash timing for inspection
    optimize_sql.last_timing = timing

    if logger.isEnabledFor(logging.DEBUG):
        delta = len(optimized) - len(original_sql)
        logger.debug(
            "sqlglot optimize: %.1fms, SQL %+d chars (%s)",
            total_ms, delta,
            ", ".join(f"{k}={v:.1f}ms" for k, v in timing.items() if k != "total_ms"),
        )

    return optimized


# Initialize timing attribute
optimize_sql.last_timing = {}

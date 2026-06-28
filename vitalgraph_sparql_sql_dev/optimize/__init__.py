"""
sqlglot-based post-emit SQL optimizer.

This package applies sqlglot optimizer passes to SQL strings produced by the
existing f-string emit phase.  It is an **optional** layer — the current emit
code is unchanged, and the optimizer can be toggled on/off via a flag in
``generate_sql``.

Safe passes (verified to preserve MATERIALIZED CTEs):
    pushdown_predicates, pushdown_projections, simplify,
    eliminate_ctes, eliminate_joins
"""

from .sql_optimizer import optimize_sql, build_schema

__all__ = ["optimize_sql", "build_schema"]

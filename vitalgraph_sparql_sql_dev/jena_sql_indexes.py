"""
Recommended PostgreSQL indexes for SPARQL query performance.

Provides functions to check existing indexes and create missing ones
for the rdf_quad and term tables used by the SQL generator.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


def get_recommended_indexes(space_id: str) -> List[Dict[str, str]]:
    """Return a list of recommended indexes for the given space.

    Each entry has 'name', 'table', and 'sql' keys.
    """
    quad = f"{space_id}_rdf_quad"
    term = f"{space_id}_term"

    return [
        # --- quad table indexes ---
        {
            "name": f"idx_{space_id}_quad_predicate",
            "table": quad,
            "sql": f"CREATE INDEX IF NOT EXISTS idx_{space_id}_quad_predicate "
                   f"ON {quad} (predicate_uuid)",
        },
        {
            "name": f"idx_{space_id}_quad_subject",
            "table": quad,
            "sql": f"CREATE INDEX IF NOT EXISTS idx_{space_id}_quad_subject "
                   f"ON {quad} (subject_uuid)",
        },
        {
            "name": f"idx_{space_id}_quad_object",
            "table": quad,
            "sql": f"CREATE INDEX IF NOT EXISTS idx_{space_id}_quad_object "
                   f"ON {quad} (object_uuid)",
        },
        {
            "name": f"idx_{space_id}_quad_context",
            "table": quad,
            "sql": f"CREATE INDEX IF NOT EXISTS idx_{space_id}_quad_context "
                   f"ON {quad} (context_uuid)",
        },
        {
            "name": f"idx_{space_id}_quad_po",
            "table": quad,
            "sql": f"CREATE INDEX IF NOT EXISTS idx_{space_id}_quad_po "
                   f"ON {quad} (predicate_uuid, object_uuid)",
        },
        {
            "name": f"idx_{space_id}_quad_sp",
            "table": quad,
            "sql": f"CREATE INDEX IF NOT EXISTS idx_{space_id}_quad_sp "
                   f"ON {quad} (subject_uuid, predicate_uuid)",
        },
        # --- term table indexes ---
        {
            "name": f"idx_{space_id}_term_text",
            "table": term,
            "sql": f"CREATE INDEX IF NOT EXISTS idx_{space_id}_term_text "
                   f"ON {term} (term_text)",
        },
        {
            "name": f"idx_{space_id}_term_text_type",
            "table": term,
            "sql": f"CREATE INDEX IF NOT EXISTS idx_{space_id}_term_text_type "
                   f"ON {term} (term_text, term_type)",
        },
    ]


def check_missing_indexes(space_id: str,
                          conn_params: Optional[Dict[str, Any]] = None
                          ) -> List[Dict[str, str]]:
    """Check which recommended indexes are missing.

    Returns the subset of get_recommended_indexes() that don't exist yet.
    """
    from . import db

    recommended = get_recommended_indexes(space_id)
    existing = set()

    rows = db.execute_query(
        "SELECT indexname FROM pg_indexes "
        "WHERE tablename IN (%s, %s)",
        (f"{space_id}_rdf_quad", f"{space_id}_term"),
        conn_params=conn_params,
    )
    for r in rows:
        existing.add(r["indexname"])

    return [idx for idx in recommended if idx["name"] not in existing]


def ensure_indexes(space_id: str,
                   conn_params: Optional[Dict[str, Any]] = None,
                   concurrent: bool = True) -> List[str]:
    """Create any missing recommended indexes.

    Args:
        space_id: Space identifier.
        conn_params: Optional DB connection parameters.
        concurrent: If True, use CREATE INDEX CONCURRENTLY (non-blocking).
                    Requires autocommit; falls back to regular CREATE INDEX
                    if inside a transaction.

    Returns:
        List of index names that were created.
    """
    from . import db

    missing = check_missing_indexes(space_id, conn_params)
    if not missing:
        logger.info("All recommended indexes already exist for space %s", space_id)
        return []

    created = []
    conninfo = db.get_connection_string(conn_params)

    import psycopg
    # CONCURRENTLY requires autocommit
    conn = psycopg.connect(conninfo, autocommit=True)
    try:
        with conn.cursor() as cur:
            for idx in missing:
                sql = idx["sql"]
                if concurrent:
                    sql = sql.replace("CREATE INDEX IF NOT EXISTS",
                                      "CREATE INDEX CONCURRENTLY IF NOT EXISTS")
                try:
                    logger.info("Creating index: %s", idx["name"])
                    cur.execute(sql)
                    created.append(idx["name"])
                except Exception as e:
                    logger.warning("Failed to create index %s: %s", idx["name"], e)
    finally:
        conn.close()

    logger.info("Created %d/%d missing indexes for space %s",
                len(created), len(missing), space_id)
    return created

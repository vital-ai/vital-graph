"""
Resolve VectorRequests by vectorizing search text and substituting
placeholder tokens in the generated SQL.

Called between SQL generation and SQL execution by both orchestration paths:
  - SparqlOrchestrator.execute()              (dev / test)
  - SparqlSQLSpaceImpl.execute_sparql_query()  (production)

Flow:
  1. generate_sql() returns GenerateResult with vector_requests list.
  2. resolve_vector_requests() is awaited with the SQL and an asyncpg conn.
  3. For each VectorRequest, look up the vector index → provider config,
     instantiate/cache the provider, vectorize the search text, and replace
     the placeholder token in the SQL with the actual embedding literal.
  4. Return the modified SQL string (ready for execution).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .vg_functions import VectorRequest

logger = logging.getLogger(__name__)


async def resolve_vector_requests(
    sql: str,
    vector_requests: List[VectorRequest],
    space_id: str,
    conn,
) -> str:
    """Replace placeholder tokens in SQL with actual embedding vectors.

    Args:
        sql: Generated SQL string containing ``__VG_EMBED_*__`` placeholders.
        vector_requests: List of VectorRequest objects from GenerateResult.
        space_id: Space ID for vector index table lookups.
        conn: asyncpg connection (already acquired).

    Returns:
        SQL string with all placeholders replaced by embedding literals.
    """
    if not vector_requests:
        return sql

    from vitalgraph.vectorization.registry import get_provider

    for vr in vector_requests:
        # Look up vector index to get provider info
        row = await conn.fetchrow(
            f"SELECT provider, provider_config, dimensions "
            f"FROM {space_id}_vector_index "
            f"WHERE index_name = $1",
            vr.index_name,
        )

        if row is None:
            logger.error(
                "Vector index '%s' not found in %s_vector_index — "
                "cannot vectorize search text for placeholder %s",
                vr.index_name, space_id, vr.placeholder,
            )
            # Replace placeholder with a zero vector so the query doesn't
            # crash with a syntax error (will return 0 similarity)
            sql = sql.replace(f"'{vr.placeholder}'::vector", "'[]'::vector")
            continue

        provider_name = str(row["provider"])
        provider_config = row["provider_config"] or {}

        try:
            provider = get_provider(
                provider_name,
                provider_config,
                cache_key=f"{space_id}:{vr.index_name}",
            )

            embedding = await provider.vectorize_text(vr.search_text)

            # Format as pgvector literal: '[0.1,0.2,...]'
            vec_literal = "[" + ",".join(f"{v:.8f}" for v in embedding) + "]"
            sql = sql.replace(
                f"'{vr.placeholder}'::vector",
                f"'{vec_literal}'::vector",
            )

            logger.debug(
                "Vectorized '%s' via %s/%s → %d dims for placeholder %s",
                vr.search_text[:50], provider_name, provider.model_name,
                len(embedding), vr.placeholder,
            )

        except Exception as e:
            logger.error(
                "Vectorization failed for placeholder %s (index=%s, text='%s'): %s",
                vr.placeholder, vr.index_name, vr.search_text[:50], e,
            )
            # Replace with zero vector so query doesn't crash
            sql = sql.replace(f"'{vr.placeholder}'::vector", "'[]'::vector")

    return sql

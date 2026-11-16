"""pgvector HNSW settings for a filtered top-k statement.

THE PROBLEM. A filtered vector query has the form

    WHERE <filters> ORDER BY embedding <=> q LIMIT k

and Postgres serves it from the HNSW index. Without iterative scan the index
hands back `hnsw.ef_search` (default 40) candidates and the filter runs on those
alone, so a selective filter returns fewer than k rows, and not the nearest
ones. Measured on 100k real MiniLM embeddings (vitalsigns
`planning/vector/pgvector_filtered_search.md`): a type holding 1% of rows got
recall 0.015 at LIMIT 20, i.e. 0-1 rows of the 20 that exist.

`hnsw.iterative_scan = relaxed_order` (pgvector >= 0.8.0) makes the scan keep
going until k rows pass the filter or `hnsw.max_scan_tuples` is reached:
recall 0.97-1.0 for the same queries.

TWO CONDITIONS ON THE STATEMENT, both required, or this makes it worse:

  * A certainty cutoff must NOT sit in the scan's WHERE. If fewer than k rows
    pass it, the scan runs to `max_scan_tuples` (20,000): 55-80 ms per query
    even with no other filter. Take the top k in a subquery and apply the cutoff
    outside it. Same rows: the cutoff is monotone in distance, so "top k, then
    cutoff" and "cutoff, then top k" select the same set.
  * `relaxed_order` returns rows slightly out of order. Re-sort outside the
    subquery by an expression the planner cannot match to the index order
    (`ORDER BY distance + 0`); PostgreSQL 17+ otherwise reuses the subquery's
    claimed order and drops the sort (43 of 100 queries out of order in the
    measurement).

SAVE/RESTORE, not bare SET LOCAL, for the reason in
`db/sparql_sql/db_provider.py:bounded_lock_wait`: a caller that already holds a
transaction gets ours as a savepoint, and SET LOCAL survives a savepoint
RELEASE to the end of the OUTER transaction. Applied only when the installed
pgvector has the setting (>= 0.8.0); an older one rejects the name, and inside
a transaction that error aborts it.
"""

from __future__ import annotations

import contextlib
import logging

logger = logging.getLogger(__name__)

#: Candidates the index yields per iteration. 100 rather than pgvector's 40:
#: recall 0.97 -> 0.99 in the measurement, for about +1 ms. Never lowers a
#: larger value the session already has.
EF_SEARCH = 100

_APPLY_SQL = """
SELECT current_setting('hnsw.iterative_scan', true) AS prev_scan,
       current_setting('hnsw.ef_search', true)      AS prev_ef,
       set_config('hnsw.iterative_scan', 'relaxed_order', true),
       set_config('hnsw.ef_search',
                  GREATEST(COALESCE(NULLIF(current_setting('hnsw.ef_search', true), '')::int, 0),
                           $1::int)::text,
                  true)
FROM pg_extension
WHERE extname = 'vector'
  AND string_to_array(split_part(extversion, '-', 1), '.')::int[] >= '{0,8,0}'::int[]
"""

_RESTORE_SQL = """
SELECT set_config('hnsw.iterative_scan', COALESCE(NULLIF($1, ''), 'off'), true),
       set_config('hnsw.ef_search',      COALESCE(NULLIF($2, ''), '40'),  true)
"""


@contextlib.asynccontextmanager
async def hnsw_iterative_scan(conn):
    """Iterative HNSW scan for the statements run inside the block.

    Must be entered inside a transaction (the settings are transaction-local
    and restored on exit). Yields True when applied, False when pgvector is
    missing or older than 0.8.0, in which case nothing was set.
    """
    row = await conn.fetchrow(_APPLY_SQL, EF_SEARCH)
    try:
        yield row is not None
    finally:
        if row is not None:
            try:
                await conn.execute(_RESTORE_SQL, row["prev_scan"], row["prev_ef"])
            except Exception:  # pragma: no cover - abort path
                # The statement failed inside the transaction, so this fails
                # too; the ROLLBACK reverts the settings. Masking the real
                # error with this one would be strictly worse.
                logger.debug("could not restore hnsw settings")


async def apply_hnsw_iterative_scan_local(conn) -> bool:
    """Iterative HNSW scan to the end of the current transaction, no restore.

    For a caller that owns the transaction and opened it for this one
    statement, as the SPARQL read path does for its other SET LOCAL
    settings. Returns False when pgvector is missing or older than 0.8.0.
    """
    return await conn.fetchrow(_APPLY_SQL, EF_SEARCH) is not None

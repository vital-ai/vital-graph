"""Register the graphs a space's quads actually use.

`issues/116`. Graph registration is implicit on three impl functions —
`add_rdf_quad`, `add_rdf_quads_batch`, `add_rdf_quads_batch_bulk`, all of which
call `_ensure_graphs_registered`. Any path that lands quads another way skips
it, and the catalog then describes less than the space holds: the data is
queryable by naming the URI, so anything hardcoding the graph works, while
everything that LISTS graphs sees nothing.

Two paths did exactly that. `scripts/load_wordnet_csv.py` COPYed 31M quads
across three fixtures with no catalog row, and `bulk_export.import_space`
copied a whole space in and registered nothing.

DERIVED FROM THE DATA, never from a parameter. A caller saying which graph it
*meant* to write can be wrong — it was, in both cases, by omission. The
contexts present in the quads cannot be.
"""

from __future__ import annotations

import logging

from .sparql_sql_schema import SparqlSQLSchema

logger = logging.getLogger(__name__)


async def register_graphs_from_data(conn, space_id: str) -> int:
    """Insert a `graph` row for every context present in the space's quads.

    Idempotent — existing rows are left alone, so this is safe to call after
    any write. Runs on the caller's connection and inside its transaction.
    Returns the number of graphs newly registered.
    """
    t = SparqlSQLSchema.get_table_names(space_id)
    quad, term = t["rdf_quad"], t["term"]

    result = await conn.execute(
        f"""
        INSERT INTO graph (space_id, graph_uri, graph_name, created_time)
        SELECT $1, tm.term_text, tm.term_text, now()
        FROM (SELECT DISTINCT context_uuid FROM {quad}) c
        JOIN {term} tm ON tm.term_uuid = c.context_uuid
        ON CONFLICT (space_id, graph_uri) DO NOTHING
        """,
        space_id,
    )
    # asyncpg returns "INSERT 0 <n>"
    try:
        n = int(str(result).split()[-1])
    except (ValueError, IndexError):
        n = 0
    if n:
        logger.info("register_graphs_from_data(%s): registered %d graph(s)",
                    space_id, n)
    return n

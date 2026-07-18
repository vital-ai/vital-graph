"""Bulk-load strategies for the term and rdf_quad tables.

The right strategy depends on load *context*, not batch size alone:

- ``insert_terms_quads_executemany`` — asyncpg pipelines the parameter sets;
  PostgreSQL maintains every index incrementally as it inserts.  This is the
  right choice for incremental writes into a **served** table: it touches only
  the new rows' index entries (cost ∝ batch size, not table size) and never
  disrupts concurrent readers.

- ``bulk_load_with_index_rebuild`` — drop the secondary indexes, COPY the rows
  in via staging temp tables (``INSERT … SELECT … ON CONFLICT``), then rebuild
  the indexes once with a bulk sort-merge build.  COPY moves data ~6× faster
  than executemany and the one-shot index build beats N random index writes —
  but the rebuild cost is ∝ the **whole table**, and dropping indexes disrupts
  reads, so this is only for loading into an **empty** space (or an explicit
  maintenance window).  Loading a small batch into a huge existing table this
  way would rebuild billions of rows to add thousands — the opposite of a win.

``insert_terms_quads_copy`` (COPY + staging, indexes left in place) is the
building block the rebuild path reuses once the secondary indexes are gone.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Sequence, Tuple
import uuid

logger = logging.getLogger(__name__)

# Below this many quads the COPY/rebuild fixed overhead (temp tables, index
# build startup) costs more than it saves — use executemany.
REBUILD_MIN_QUADS = 10_000

_TERM_COLS = ("term_uuid", "term_text", "term_type", "lang", "datatype_id")
_QUAD_COLS = ("subject_uuid", "predicate_uuid", "object_uuid", "context_uuid")


async def insert_terms_quads_executemany(
    conn,
    t: Dict[str, str],
    term_args: List[Tuple],
    quad_rows: List[Tuple],
) -> int:
    """Insert terms and quads via executemany (ON CONFLICT DO NOTHING)."""
    await conn.executemany(
        f"INSERT INTO {t['term']} ({', '.join(_TERM_COLS)}) "
        f"VALUES ($1, $2, $3, $4, $5) ON CONFLICT DO NOTHING",
        term_args,
    )
    await conn.executemany(
        f"INSERT INTO {t['rdf_quad']} ({', '.join(_QUAD_COLS)}) "
        f"VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING",
        quad_rows,
    )
    return len(quad_rows)


async def insert_terms_quads_copy(
    conn,
    t: Dict[str, str],
    term_args: List[Tuple],
    quad_rows: List[Tuple],
    terms_direct: bool = False,
) -> int:
    """Insert terms and quads via COPY.

    - Quads carry a random ``quad_uuid`` default in their PK, so an insert can
      never conflict (matching the executemany path, where ON CONFLICT is a
      no-op for quads).  Quads always COPY **directly** — no staging.
    - Terms have a deterministic PK (term_uuid), so a term already in the table
      would collide.  When the term table is empty (``terms_direct=True``, a
      fresh-space load) and the caller's ``term_args`` are pre-deduped, terms
      also COPY directly.  Otherwise COPY into an ``ON COMMIT DROP`` staging
      table then ``INSERT … SELECT … ON CONFLICT DO NOTHING`` to dedup against
      existing rows.

    Requires an open transaction when staging (``ON COMMIT DROP``).
    """
    term_table = t['term'].split('.')[-1]
    if terms_direct:
        await conn.copy_records_to_table(
            term_table, records=term_args, columns=list(_TERM_COLS))
    else:
        stage_term = f"_stage_term_{uuid.uuid4().hex[:12]}"
        await conn.execute(
            f"CREATE TEMP TABLE {stage_term} "
            f"(term_uuid uuid, term_text text, term_type char(1), "
            f"lang text, datatype_id int) ON COMMIT DROP")
        await conn.copy_records_to_table(stage_term, records=term_args)
        await conn.execute(
            f"INSERT INTO {t['term']} ({', '.join(_TERM_COLS)}) "
            f"SELECT {', '.join(_TERM_COLS)} FROM {stage_term} "
            f"ON CONFLICT DO NOTHING")

    quad_table = t['rdf_quad'].split('.')[-1]
    await conn.copy_records_to_table(
        quad_table, records=quad_rows, columns=list(_QUAD_COLS))

    return len(quad_rows)


async def bulk_load_with_index_rebuild(
    conn,
    t: Dict[str, str],
    term_args: List[Tuple],
    quad_rows: List[Tuple],
    drop_index_sql: Sequence[str],
    create_index_sql: Sequence[str],
    terms_direct: bool = False,
) -> int:
    """Drop secondary indexes → COPY the rows in → rebuild the indexes once.

    Caller must ensure this is safe: the target space is empty or in a
    maintenance window (dropping indexes disrupts concurrent reads, and the
    rebuild cost is proportional to the whole table).  The 5-col PK is a table
    constraint (not in drop_index_sql), so it stays for the COPY.  Pass
    ``terms_direct=True`` only when the term table is empty.  Runs inside the
    caller's transaction; index DDL is non-CONCURRENT (fine on an empty/idle
    table) so it commits atomically with the load.
    """
    for stmt in drop_index_sql:
        await conn.execute(stmt)
    await insert_terms_quads_copy(conn, t, term_args, quad_rows,
                                  terms_direct=terms_direct)
    for stmt in create_index_sql:
        await conn.execute(stmt)
    return len(quad_rows)

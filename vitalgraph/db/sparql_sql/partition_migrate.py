"""Per-space migration of an existing (non-partitioned) space to the P3
partitioned + slim-PK + UUIDv7 layout.

Strategy: build alongside → backfill → swap.
  1. Build ``_new`` partitioned core tables (rdf_quad/edge/frame_entity),
     indexes deferred.
  2. Backfill from the live tables via INSERT … SELECT. rdf_quad backfills with
     ON CONFLICT DO NOTHING against the new slim 4-col PK, so duplicate (s,p,o,c)
     rows the old 5-col PK allowed collapse (a correct dedup; SPARQL is
     set-based so query results are unchanged).
  3. Swap in one transaction: DROP the old core tables CASCADE (frees every
     index / extended-statistics name tied to them), rename the ``_new`` tables
     (and their partition children) into place, rebuild the core indexes on the
     now-partitioned tables, and resync stats.

Runs inside the caller's transaction — atomic (readers see the old layout until
commit, the new one after). The backfill holds locks for its duration, so this
is a maintenance-window operation per space, not zero-downtime.
"""

from __future__ import annotations

import logging
from typing import Dict

from .sparql_sql_schema import SparqlSQLSchema

logger = logging.getLogger(__name__)

_CORE = ("rdf_quad", "edge", "frame_entity")


def _bare(name: str) -> str:
    return name.split(".")[-1]


def _new_core_ddl(t: Dict[str, str], n: int):
    """DDL to build the three partitioned core tables under a `_new` suffix."""
    q, e, f = _bare(t["rdf_quad"]), _bare(t["edge"]), _bare(t["frame_entity"])
    stmts = [
        f"""CREATE TABLE {q}_new (
                subject_uuid   UUID NOT NULL,
                predicate_uuid UUID NOT NULL,
                object_uuid    UUID NOT NULL,
                context_uuid   UUID NOT NULL,
                quad_uuid      UUID NOT NULL DEFAULT uuidv7(),
                dataset        VARCHAR(50) NOT NULL DEFAULT 'primary',
                PRIMARY KEY (subject_uuid, predicate_uuid, object_uuid, context_uuid)
            ) PARTITION BY HASH (context_uuid)""",
        f"""CREATE TABLE {e}_new (
                edge_uuid        UUID NOT NULL,
                source_node_uuid UUID NOT NULL,
                dest_node_uuid   UUID NOT NULL,
                context_uuid     UUID NOT NULL,
                PRIMARY KEY (edge_uuid, context_uuid)
            ) PARTITION BY HASH (context_uuid)""",
        f"""CREATE TABLE {f}_new (
                frame_uuid         UUID NOT NULL,
                source_entity_uuid UUID,
                dest_entity_uuid   UUID,
                context_uuid       UUID NOT NULL,
                PRIMARY KEY (frame_uuid, context_uuid)
            ) PARTITION BY HASH (context_uuid)""",
    ]
    for base in (q, e, f):
        for i in range(n):
            stmts.append(
                f"CREATE TABLE {base}_new_p{i} PARTITION OF {base}_new "
                f"FOR VALUES WITH (MODULUS {n}, REMAINDER {i})")
    return stmts


async def distinct_quads(conn, space_id: str):
    """Set of distinct (s,p,o,c) — the set-semantics fingerprint of the space."""
    t = SparqlSQLSchema.get_table_names(space_id)
    return {(r["s"], r["p"], r["o"], r["c"]) for r in await conn.fetch(
        f"SELECT subject_uuid s, predicate_uuid p, object_uuid o, context_uuid c "
        f"FROM {t['rdf_quad']}")}


async def migrate_space_to_partitioned(conn, space_id: str,
                                       n_partitions: int = 16) -> Dict[str, int]:
    """Migrate one space to the partitioned layout. Returns row-count summary.

    Must run inside a transaction. Assumes PostgreSQL 18 (uuidv7).
    """
    schema = SparqlSQLSchema()
    t = schema.get_table_names(space_id)
    q, e, f = _bare(t["rdf_quad"]), _bare(t["edge"]), _bare(t["frame_entity"])

    old_quads = await conn.fetchval(f"SELECT count(*) FROM {t['rdf_quad']}")

    # 1. build _new partitioned core tables (indexes deferred)
    for stmt in _new_core_ddl(t, n_partitions):
        await conn.execute(stmt)

    # 2. backfill (rdf_quad dedups against the new slim PK)
    await conn.execute(
        f"INSERT INTO {q}_new "
        f"(subject_uuid, predicate_uuid, object_uuid, context_uuid, quad_uuid, dataset) "
        f"SELECT subject_uuid, predicate_uuid, object_uuid, context_uuid, quad_uuid, dataset "
        f"FROM {q} ON CONFLICT DO NOTHING")
    await conn.execute(f"INSERT INTO {e}_new SELECT * FROM {e} ON CONFLICT DO NOTHING")
    await conn.execute(f"INSERT INTO {f}_new SELECT * FROM {f} ON CONFLICT DO NOTHING")
    new_quads = await conn.fetchval(f"SELECT count(*) FROM {q}_new")

    # 3. swap: drop old (CASCADE frees all index/stat names), rename _new in
    for base in (q, e, f):
        await conn.execute(f"DROP TABLE {base} CASCADE")
        await conn.execute(f"ALTER TABLE {base}_new RENAME TO {base}")
        for i in range(n_partitions):
            await conn.execute(
                f"ALTER TABLE {base}_new_p{i} RENAME TO {base}_p{i}")

    # 4. rebuild indexes (names freed by the DROP CASCADE); create_space_indexes
    #    is comprehensive — unrelated tables' indexes already exist (IF NOT EXISTS)
    for stmt in schema.create_space_indexes_sql(space_id):
        await conn.execute(stmt)

    # 5. rebuild stats over the migrated quads
    from .sync_stats_tables import resync_stats_tables
    await resync_stats_tables(conn, space_id)

    logger.info("migrate_space_to_partitioned(%s): %d -> %d quads (%d dupes dropped), "
                "%d partitions", space_id, old_quads, new_quads,
                old_quads - new_quads, n_partitions)
    return {"old_quads": old_quads, "new_quads": new_quads,
            "dupes_dropped": old_quads - new_quads}

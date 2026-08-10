"""Compute `{space}_edge_fanout`: how much one traversal step multiplies rows.

The statistic nothing else expresses. `rdf_stats` and PostgreSQL's
`stat_*_quad_po` both describe single-table selectivity; the errors that matter
in a multi-hop traversal are **join** cardinality — measured at 305x and 4,761x
underestimates, which is the whole of the 700ms vs >200s gap in `issues/059`.
Fan-out is what multiplies through those hops, and PostgreSQL cannot infer it
from column statistics because it is a property of the join, not of a column.

Why the key is (edge type, relation type, direction)
----------------------------------------------------
Measured on `sp_kg_rel`, where all four are `Edge_hasKGRelation`:

    reportsTo   forward 1.00 / max 1     backward 4.77 / max 5      a tree
    worksFor    forward 1.00 / max 1     backward 39.00 / max 886   a hub

Recorded per edge type those average into a number describing neither, and per
space the whole table reports 1.80 / 1.51, which hides both. The granularity has
to reach `hasKGRelationType`.

Why the tail and not just the mean
----------------------------------
`wordnet_frames`' slot-value in-degree averages 5.20 with a maximum of 1,342 — a
258x mean-to-max ratio. A plan chosen on the average can be that far wrong, and
the cost of being wrong here is a timeout rather than a slightly worse plan. p99
and max are stored alongside avg so a caller can plan for the tail when the
downside is asymmetric.

What the numbers are good for
-----------------------------
Direction choice, primarily. Containment edges are a tree — a slot has exactly
one parent, a frame none or one — so backward fan-out is 1 *by construction*,
and walking them backward cannot amplify. Relations have no safe direction: an
entity may be source or destination in many. A rewrite that picks a traversal
direction needs to know which case it is in, and this is the only place that
records it.
"""

from __future__ import annotations

import logging
import uuid
from typing import Dict

logger = logging.getLogger(__name__)

NO_RELATION = uuid.UUID("00000000-0000-0000-0000-000000000000")

_RELATION_TYPE_URI = "http://vital.ai/ontology/haley-ai-kg#hasKGRelationType"
_VITALGRAPH_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
_REL_TYPE_UUID = uuid.uuid5(_VITALGRAPH_NS, f"{_RELATION_TYPE_URI}\x00U")


async def compute_edge_fanout(conn, space_id: str) -> int:
    """Recompute the fan-out table from the edge table. Returns rows written.

    One pass per direction over `{space}_edge`, grouped by edge type and (where
    present) relation type. Requires `edge_type_uuid` to be populated — without
    it every edge pools into one bucket and the result describes nothing
    (`issues/060`).

    Not incremental. Fan-out is a structural property of the schema and moves
    slowly, so recomputing it on the maintenance cadence is enough; making it
    incremental would mean maintaining a distribution under every write, which
    is far more machinery than the thing is worth.
    """
    t_edge = f"{space_id}_edge"
    t_quad = f"{space_id}_rdf_quad"
    t_fan = f"{space_id}_edge_fanout"

    has_type = await conn.fetchval(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = $1 AND column_name = 'edge_type_uuid'", t_edge)
    if not has_type:
        logger.info("compute_edge_fanout(%s): edge_type_uuid absent, skipping "
                    "— every edge would pool into one bucket", space_id)
        return 0

    written = 0
    for direction, group_col, count_col in (
        ("forward", "source_node_uuid", "dest_node_uuid"),
        ("backward", "dest_node_uuid", "source_node_uuid"),
    ):
        # `typed` attaches the relation type where there is one. LEFT JOIN, so a
        # containment edge keeps its row and lands in the NO_RELATION bucket
        # rather than vanishing.
        rows = await conn.fetch(f"""
            WITH typed AS (
                SELECT e.edge_type_uuid,
                       COALESCE(rt.object_uuid, $1) AS relation_type_uuid,
                       e.{group_col} AS node,
                       e.{count_col} AS other
                FROM {t_edge} e
                LEFT JOIN {t_quad} rt
                       ON rt.subject_uuid = e.edge_uuid
                      AND rt.predicate_uuid = $2
                      AND rt.context_uuid = e.context_uuid
            ),
            per_node AS (
                SELECT edge_type_uuid, relation_type_uuid, node,
                       count(*) AS n
                FROM typed
                GROUP BY edge_type_uuid, relation_type_uuid, node
            )
            SELECT edge_type_uuid, relation_type_uuid,
                   avg(n)::double precision AS avg_fanout,
                   percentile_disc(0.99) WITHIN GROUP (ORDER BY n) AS p99_fanout,
                   max(n) AS max_fanout,
                   count(*) AS sample_nodes
            FROM per_node
            GROUP BY edge_type_uuid, relation_type_uuid
        """, NO_RELATION, _REL_TYPE_UUID)

        for r in rows:
            await conn.execute(f"""
                INSERT INTO {t_fan} (edge_type_uuid, relation_type_uuid,
                                     direction, avg_fanout, p99_fanout,
                                     max_fanout, sample_nodes, updated_time)
                VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
                ON CONFLICT (edge_type_uuid, relation_type_uuid, direction)
                DO UPDATE SET avg_fanout = EXCLUDED.avg_fanout,
                              p99_fanout = EXCLUDED.p99_fanout,
                              max_fanout = EXCLUDED.max_fanout,
                              sample_nodes = EXCLUDED.sample_nodes,
                              updated_time = NOW()
            """, r["edge_type_uuid"], r["relation_type_uuid"], direction,
                 float(r["avg_fanout"] or 0), int(r["p99_fanout"] or 0),
                 int(r["max_fanout"] or 0), int(r["sample_nodes"] or 0))
            written += 1

    # Buckets whose edges are all gone should not linger claiming a fan-out.
    await conn.execute(f"""
        DELETE FROM {t_fan} f WHERE NOT EXISTS (
            SELECT 1 FROM {t_edge} e WHERE e.edge_type_uuid = f.edge_type_uuid)
    """)

    logger.info("compute_edge_fanout(%s): %d bucket(s)", space_id, written)
    return written


async def load_edge_fanout(conn, space_id: str) -> Dict[tuple, dict]:
    """Read the table into `{(edge_type, relation_type, direction): stats}`.

    For a planner-side caller. Returns an empty dict rather than raising when
    the table does not exist yet, so a space that predates it simply has no
    fan-out information rather than failing every query.
    """
    t_fan = f"{space_id}_edge_fanout"
    try:
        rows = await conn.fetch(
            f"SELECT edge_type_uuid, relation_type_uuid, direction, "
            f"avg_fanout, p99_fanout, max_fanout, sample_nodes FROM {t_fan}")
    except Exception:
        return {}
    return {
        (r["edge_type_uuid"], r["relation_type_uuid"], r["direction"]): {
            "avg": r["avg_fanout"], "p99": r["p99_fanout"],
            "max": r["max_fanout"], "nodes": r["sample_nodes"],
        }
        for r in rows
    }

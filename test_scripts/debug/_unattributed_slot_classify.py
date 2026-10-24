"""Why does the slot repair call these slots `unattributed`?

`issues/194`, `277`. `backfill_entity_slot_sort_missing_slots` reports a slot
`unattributed` when the edge table gives no slot -> frame -> entity path for it,
and the maintenance job logs that at ERROR every cycle. This takes the same
candidate slots (absent from entity_slot_sort, carrying a sortable value) and
classifies each one by what the EDGE TABLE and the QUADS say about it:

  orphan_slot     no Edge_hasKGSlot points at it, in the edge table OR the quads
  orphan_frame    its frame has no Edge_hasEntityKGFrame and no parent frame
  nested_frame    its frame is reached from a parent frame (Edge_hasKGFrame)
  edge_table_short  the quads hold an edge the edge table lacks
  attributed      reachable in two hops (not unattributed)

Read-only. Targets the DEV database (host Postgres, sparql_sql_graph):

    /opt/homebrew/anaconda3/envs/vital-graph/bin/python \
        test_scripts/debug/_unattributed_slot_classify.py space_kgquery_test ...
"""
import asyncio
import collections
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import asyncpg  # noqa: E402

PG = dict(host=os.getenv("PG_HOST", "localhost"),
          port=int(os.getenv("PG_PORT", "5432")),
          database=os.getenv("PG_DATABASE", "sparql_sql_graph"),
          user=os.getenv("PG_USER", "postgres"),
          password=os.getenv("PG_PASSWORD") or None)


async def classify(conn, space_id):
    from vitalgraph.db.sparql_sql.space_names import space_prefix
    from vitalgraph.db.sparql_sql import sync_entity_slot_sort as ess
    from vitalgraph.db.sparql_sql.ensure_edge_table import EDGE_DEST_URI

    p = space_prefix(space_id)
    src = ess._u("http://vital.ai/ontology/vital-core#hasEdgeSource")
    dst = ess._u(EDGE_DEST_URI)
    slots = [r["slot_uuid"] for r in await conn.fetch(
        f"SELECT q.subject_uuid AS slot_uuid FROM {p}_rdf_quad q "
        f" WHERE q.predicate_uuid = $1 "
        f"   AND NOT EXISTS (SELECT 1 FROM {p}_entity_slot_sort e "
        f"                    WHERE e.slot_uuid = q.subject_uuid "
        f"                      AND e.context_uuid = q.context_uuid) "
        f"   AND EXISTS (SELECT 1 FROM {p}_rdf_quad v "
        f"                WHERE v.subject_uuid = q.subject_uuid "
        f"                  AND v.predicate_uuid = ANY($2::uuid[]))",
        ess._SLOT_TYPE, ess._SLOT_VALUE_PREDS)]

    out = collections.Counter()
    for s in slots:
        frames = [r["f"] for r in await conn.fetch(
            f"SELECT source_node_uuid AS f FROM {p}_edge "
            f" WHERE dest_node_uuid = $1 AND edge_type_uuid = $2",
            s, ess._SLOT_EDGE)]
        if not frames:
            # Does the QUAD side hold an edge object pointing at this slot?
            in_quads = await conn.fetchval(
                f"SELECT count(*) FROM {p}_rdf_quad d "
                f"  JOIN {p}_rdf_quad s ON s.subject_uuid = d.subject_uuid "
                f"   AND s.predicate_uuid = $3 "
                f" WHERE d.predicate_uuid = $2 AND d.object_uuid = $1",
                s, dst, src)
            out["edge_table_short" if in_quads else "orphan_slot"] += 1
            continue
        ent = await conn.fetchval(
            f"SELECT count(*) FROM {p}_edge WHERE dest_node_uuid = ANY($1) "
            f"   AND edge_type_uuid = $2", frames, ess._ENTITY_FRAME_EDGE)
        if ent:
            out["attributed"] += 1
            continue
        parent = await conn.fetchval(
            f"SELECT count(*) FROM {p}_edge WHERE dest_node_uuid = ANY($1) "
            f"   AND edge_type_uuid = $2", frames, ess._CHILD_FRAME_EDGE)
        out["nested_frame" if parent else "orphan_frame"] += 1
    return len(slots), dict(out)


async def main(space_ids):
    from vitalgraph.db.sparql_sql.space_storage_key import load_storage_keys
    conn = await asyncpg.connect(**PG)
    try:
        await load_storage_keys(conn)
        for sid in space_ids:
            n, cls = await classify(conn, sid)
            print(f"{sid}: {n} candidate slots -> {cls}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))

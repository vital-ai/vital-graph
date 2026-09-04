"""P1/P2 from issues/151: is selecting a batch cheap, and how does it scale?"""
import asyncio, os, sys, time, uuid
sys.path.insert(0, '.')
import asyncpg
from vitalgraph.db.sparql_sql import sync_entity_slot_sort as E

async def main():
    c = await asyncpg.connect(host='localhost', port=5433, user='postgres',
                              password='testpass', database='sparql_sql_graph')
    sp = f"p151_{uuid.uuid4().hex[:8]}"
    from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
    await SparqlSQLSchema.create_space_core(c, sp)
    for st in SparqlSQLSchema.create_space_indexes_sql(SparqlSQLSchema, sp):
        try:
            await c.execute(st)
        except Exception:
            pass
    ctx, etype = uuid.uuid4(), uuid.uuid4()
    N = 2000
    edges, quads, terms = [], [], []
    for _ in range(N):
        e,f,s1,v1 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        edges += [(uuid.uuid4(), e, f, ctx, E._ENTITY_FRAME_EDGE),
                  (uuid.uuid4(), f, s1, ctx, E._SLOT_EDGE)]
        terms.append((v1, "x"))
        quads += [(f, E._FRAME_TYPE, uuid.uuid4(), ctx),
                  (s1, E._SLOT_TYPE, uuid.uuid4(), ctx),
                  (e, E._ENTITY_TYPE, etype, ctx),
                  (s1, E._SLOT_VALUE_PREDS[0], v1, ctx)]
    await c.executemany(f"INSERT INTO {sp}_edge (edge_uuid,source_node_uuid,dest_node_uuid,context_uuid,edge_type_uuid) VALUES ($1,$2,$3,$4,$5)", edges)
    await c.executemany(f"INSERT INTO {sp}_term (term_uuid,term_text,term_type) VALUES ($1,$2,'L') ON CONFLICT DO NOTHING", terms)
    await c.executemany(f"INSERT INTO {sp}_rdf_quad (subject_uuid,predicate_uuid,object_uuid,context_uuid) VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING", quads)
    await c.execute(f"ANALYZE {sp}_rdf_quad"); await c.execute(f"ANALYZE {sp}_edge")
    print(f"  seeded {N} entities into {sp}")

    t=time.time()
    await c.fetch(f"SELECT DISTINCT q.subject_uuid FROM {sp}_rdf_quad q WHERE q.predicate_uuid=$1 AND q.object_uuid=$2 AND NOT EXISTS (SELECT 1 FROM {sp}_entity_slot_sort e WHERE e.entity_uuid=q.subject_uuid) LIMIT 500", E._ENTITY_TYPE, etype)
    print(f"  P1 batch-select (500 of {N}): {(time.time()-t)*1000:.0f} ms")

    print("  P2 batch scaling:")
    for bs in (100, 500, 2000):
        await c.execute(f"TRUNCATE {sp}_entity_slot_sort")
        t=time.time()
        sel, ins = await E.backfill_entity_slot_sort_batch(c, sp, etype, batch_size=bs)
        el=(time.time()-t)*1000
        print(f"    batch={bs:<5} selected={sel:<5} inserted={ins:<5} {el:7.0f} ms  ({el/max(sel,1):.2f} ms/entity)")
    # Use drop_space, NOT a hand-written list. A space has ~24 tables; this
    # script originally dropped four and leaked twenty, which is the exact
    # failure `drop_space`'s self-healing sweep exists to prevent (see
    # tests/unit/test_drop_space_orphan_sweep.py: one forgotten table meant
    # "every space ever created leaked one table — 116 orphans on one local
    # stack").
    await SparqlSQLSchema.drop_space(c, sp)
    await c.close()
asyncio.run(main())

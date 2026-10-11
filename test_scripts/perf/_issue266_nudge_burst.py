"""issues/266: the REAL backfill loop under a nudge burst, against the test DB.

One throwaway space with a few KGEntities; a nudge for it every 2 s for 60 s;
BACKFILL_NUDGE_MIN_INTERVAL_S=10. Counts cycles that started FORCED (taking the
pending force) and graph discoveries. Old behaviour: one forced cycle per nudge.
"""
import asyncio, os, sys, time
os.environ["BACKFILL_NUDGE_MIN_INTERVAL_S"] = "10"
os.environ["BACKFILL_ACTIVE_INTERVAL"] = "0.2"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from rdflib import URIRef

async def main():
    from vitalgraph.db.sparql_sql.sparql_sql_space_impl import SparqlSQLSpaceImpl
    from vitalgraph.space.space_manager import SpaceManager
    from vitalgraph.tasks import backfill_server_properties_task as B
    impl = SparqlSQLSpaceImpl(postgresql_config=dict(host="localhost", port=5433, database="sparql_sql_graph",
        username="postgres", password="testpass", min_pool_size=1, max_pool_size=4),
        sidecar_config={"url": "http://localhost:7071"})
    assert await impl.connect()
    sm = SpaceManager(db_impl=impl.db_impl, space_backend=impl)
    sp = "inttest_t266burst"
    if not await sm.get_space_or_load(sp):
        await sm.create_space_with_tables(sp, sp, "issues/266 burst check")
    g = URIRef("urn:t266:g"); KG = "http://vital.ai/ontology/haley-ai-kg#"
    await impl.add_rdf_quads_batch(sp, [(URIRef(f"urn:t266:e{i}"),
        URIRef("http://vital.ai/ontology/vital-core#vitaltype"), URIRef(f"{KG}KGEntity"), g) for i in range(5)])

    class OneSpace:            # scope the task to the throwaway space only
        def list_active_spaces(self): return [sp]
        list_spaces = list_active_spaces
    task = B.BackfillServerPropertiesTask(impl.db_impl.connection_pool, OneSpace())
    forced, discoveries = [], []
    orig_begin, orig_disc = task._begin_cycle, B.discover_graphs_sql
    def begin():
        orig_begin()
        if task._cycle_force_all or task._cycle_force_spaces:
            forced.append(round(time.monotonic() - t0, 1))
    async def disc(pool, space_id):
        discoveries.append(space_id); return await orig_disc(pool, space_id)
    task._begin_cycle = begin; B.discover_graphs_sql = disc
    t0 = time.monotonic()
    task._running = True
    loop_task = asyncio.create_task(task._run_loop())
    await asyncio.sleep(11)           # past the loop's 10 s startup delay + first forced cycle
    forced.clear(); discoveries.clear(); t0 = time.monotonic()
    nudges = 0
    while time.monotonic() - t0 < 60:
        task.nudge(sp); nudges += 1
        await asyncio.sleep(2)
    await asyncio.sleep(12)           # let the last held nudge be honoured
    task._running = False; task._nudge_event.set(); loop_task.cancel()
    print(f"nudges {nudges} in 60 s -> forced cycles {len(forced)} at t={forced}")
    print(f"discoveries during the burst: {len(discoveries)}")
    await sm.delete_space_with_tables(sp)

asyncio.run(main())

"""Write cost with and without the write-log trigger, on a real scratch space (API-created,
all indexes, the index-sync trigger), planner stack. Alternating rounds; median of each.

    LOCAL_CLIENT_SERVER_URL=http://localhost:8003 python test_scripts/debug/_write_log_overhead.py
"""
import asyncio, os, statistics, subprocess, sys, time, uuid
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")); sys.path.insert(0, REPO)
import asyncpg
PG = dict(host="localhost", port=5434, database="sparql_sql_graph", user="postgres", password="testpass")
ROUNDS = 7

async def main():
    from vitalgraph.client.vitalgraph_client import VitalGraphClient
    from vitalgraph.model.spaces_model import Space
    from vitalgraph.db.sparql_sql import write_log
    from vitalgraph.db.sparql_sql.space_storage_key import load_storage_keys
    from vitalgraph.db.sparql_sql.space_names import space_prefix
    sid = f"zzwlcost_{uuid.uuid4().hex[:8]}"
    client = VitalGraphClient(); await client.open()
    cr = await client.spaces.create_space(Space(space=sid, space_name=sid, space_description="write log overhead (deleted on exit)"))
    assert cr.is_success, cr.error_message
    c = await asyncpg.connect(**PG)
    try:
        await load_storage_keys(c, sid)
        async with c.transaction():
            for s in write_log.create_sql(sid):
                await c.execute(s)
        q = f"{space_prefix(sid)}_rdf_quad"; trg = write_log.trigger_name(sid)
        cols = await c.fetch(f"SELECT column_name FROM information_schema.columns WHERE table_name = '{q}' "
                             f"AND column_name IN ('subject_uuid','predicate_uuid','object_uuid','context_uuid') ORDER BY ordinal_position")
        names = [r[0] for r in cols]
        g = uuid.uuid4()
        row = lambda: tuple(g if n == "context_uuid" else uuid.uuid4() for n in names)
        ins = f"INSERT INTO {q} ({', '.join(names)}) VALUES ({', '.join(f'${i+1}' for i in range(len(names)))})"

        async def single():           # 200 autocommit single-row statements
            t0 = time.perf_counter()
            for _ in range(200):
                await c.execute(ins, *row())
            return (time.perf_counter() - t0) * 1000 / 200
        async def many():             # executemany of 44 rows in a transaction (an entity graph)
            t0 = time.perf_counter()
            async with c.transaction():
                await c.executemany(ins, [row() for _ in range(44)])
            return (time.perf_counter() - t0) * 1000
        async def copy():             # COPY of 20,000 rows
            recs = [row() for _ in range(20000)]
            t0 = time.perf_counter()
            await c.copy_records_to_table(q, records=recs, columns=names)
            return (time.perf_counter() - t0) * 1000
        res = {(k, on): [] for k in ("single", "many", "copy") for on in (False, True)}
        for r in range(ROUNDS):
            for on in ((False, True) if r % 2 == 0 else (True, False)):
                await c.execute(f"ALTER TABLE {q} {'ENABLE' if on else 'DISABLE'} TRIGGER {trg}")
                for k, f in (("single", single), ("many", many), ("copy", copy)):
                    res[(k, on)].append(await f())
        print(f"{'case':34s} {'without':>10s} {'with':>10s} {'added':>9s}")
        for k, label in (("single", "one-row INSERT, autocommit (ms)"), ("many", "executemany 44 rows, one txn (ms)"),
                         ("copy", "COPY 20,000 rows (ms)")):
            a, b = statistics.median(res[(k, False)]), statistics.median(res[(k, True)])
            print(f"{label:34s} {a:10.3f} {b:10.3f} {100*(b-a)/a:8.1f}%")
    finally:
        await c.close()
        await client.spaces.delete_space(sid); await client.close()

asyncio.run(main())

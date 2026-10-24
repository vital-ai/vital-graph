"""Does the type-agreement change token move as soon as a write commits? (issues/302)

`edge_type_agreement._stored_verdict` accepts a stored verdict while
`pg_stat_get_tuples_inserted + _updated + _deleted || ':' || relfilenode` equals the token
recorded with it. Those counters are cumulative statistics, which a backend flushes to shared
memory asynchronously (PG15+: at most once per PGSTAT_MIN_INTERVAL, 1 s, and later when it
is busy or goes idle). This writes, commits, and reads the token from another connection.

Fixture table only (no space), dropped on exit. Planner stack :5434 by default.
"""
import asyncio, os, time
import asyncpg
PG = dict(host="localhost", port=int(os.getenv("VG_PG_PORT", "5434")), database="sparql_sql_graph",
          user="postgres", password="testpass")
TOKEN = ("SELECT pg_stat_get_tuples_inserted(c.oid) + pg_stat_get_tuples_updated(c.oid) "
         "+ pg_stat_get_tuples_deleted(c.oid) || ':' || c.relfilenode FROM pg_class c WHERE c.oid = to_regclass('zz_tok')")

async def main():
    w = await asyncpg.connect(**PG); r = await asyncpg.connect(**PG)
    await w.execute("DROP TABLE IF EXISTS zz_tok; CREATE TABLE zz_tok (x int)")
    await asyncio.sleep(1.5)
    try:
        for trial in range(5):
            await w.execute("INSERT INTO zz_tok VALUES (1)")           # warm-up write: starts the flush interval
            await asyncio.sleep(1.2)
            before = await r.fetchval(TOKEN)
            await w.execute("INSERT INTO zz_tok VALUES (1)")           # first write after a flush: flushed at commit
            await w.execute("INSERT INTO zz_tok VALUES (2)")           # second write within 1 s: deferred
            committed = time.perf_counter()
            seen = await r.fetchval(TOKEN)
            rows = await r.fetchval("SELECT count(*) FROM zz_tok")
            lag = None
            while lag is None and time.perf_counter() - committed < 30:
                await asyncio.sleep(0.05)
                if await r.fetchval(TOKEN) != seen:
                    lag = time.perf_counter() - committed
            print(f"trial {trial}: token before {before}  right after commit {seen}  "
                  f"(rows visible {rows})  moved again after {lag if lag is None else round(lag, 2)} s")
    finally:
        await w.execute("DROP TABLE IF EXISTS zz_tok")
        await w.close(); await r.close()

asyncio.run(main())

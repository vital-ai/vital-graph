"""Does `migrate_space_to_partitioned` keep the triggers on `rdf_quad`? (issues/303)

A scratch space created and deleted through the API (planner stack :8003 / :5434), the
write log installed by its script, one triple written. Then the migration, in-process, in
one transaction as its docstring requires. Lists the triggers on `{space}_rdf_quad` before
and after, and checks whether a write after the migration still reaches the index-sync
queue and the write log.

    LOCAL_CLIENT_SERVER_URL=http://localhost:8003 python test_scripts/debug/_partition_migrate_drops_triggers.py
"""
import asyncio, os, subprocess, sys, uuid
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")); sys.path.insert(0, REPO)
import asyncpg
PG = dict(host="localhost", port=int(os.getenv("VG_PG_PORT", "5434")), database="sparql_sql_graph",
          user="postgres", password="testpass")

async def main():
    from vitalgraph.client.vitalgraph_client import VitalGraphClient
    from vitalgraph.model.spaces_model import Space
    from vitalgraph.model.sparql_model import SPARQLUpdateRequest
    from vitalgraph.db.sparql_sql.space_storage_key import load_storage_keys
    from vitalgraph.db.sparql_sql.space_names import space_prefix
    from vitalgraph.db.sparql_sql.partition_migrate import migrate_space_to_partitioned
    sid = f"zzpm_{uuid.uuid4().hex[:8]}"; g = "urn:zzpm:g"
    client = VitalGraphClient(); await client.open()
    cr = await client.spaces.create_space(Space(space=sid, space_name=sid, space_description="partition migrate probe (deleted on exit)"))
    assert cr.is_success, cr.error_message
    c = await asyncpg.connect(**PG)
    try:
        await client.graphs.create_graph(sid, g)
        await load_storage_keys(c, sid)
        subprocess.run([sys.executable, os.path.join(REPO, "scripts/install_write_log.py"), "--space", sid, "--apply",
                        "--host", "localhost", "--port", str(PG["port"]), "--database", PG["database"],
                        "--user", PG["user"], "--password", PG["password"]], capture_output=True, check=True)
        upd = lambda q: client.sparql.execute_sparql_update(sid, SPARQLUpdateRequest(update=q))
        await upd(f"INSERT DATA {{ GRAPH <{g}> {{ <urn:zzpm:s1> <urn:zzpm:p> <urn:zzpm:o> . }} }}")
        q = f"{space_prefix(sid)}_rdf_quad"
        trig = lambda: c.fetch("SELECT tgname FROM pg_trigger WHERE tgrelid = to_regclass($1) AND NOT tgisinternal ORDER BY 1", q)
        part = lambda: c.fetchval("SELECT relkind FROM pg_class WHERE oid = to_regclass($1)", q)
        print("before:", await part(), [r[0] for r in await trig()])
        async with c.transaction():
            print("migrate:", await migrate_space_to_partitioned(c, sid, n_partitions=4))
        after = [r[0] for r in await trig()]
        print("after: ", await part(), after)
        isq = f"{space_prefix(sid)}_index_sync_queue"; wl = f"{space_prefix(sid)}_write_log"
        n_isq0 = await c.fetchval(f"SELECT count(*) FROM {isq}"); n_wl0 = await c.fetchval(f"SELECT coalesce(sum(n),0) FROM {wl}")
        await c.execute(f"DELETE FROM {isq}")
        await upd(f"INSERT DATA {{ GRAPH <{g}> {{ <urn:zzpm:s2> <urn:zzpm:p> <urn:zzpm:o> . }} }}")
        n_isq = await c.fetchval(f"SELECT count(*) FROM {isq} WHERE subject_uuid IS NOT NULL")
        n_wl = await c.fetchval(f"SELECT coalesce(sum(n),0) FROM {wl}")
        print(f"a write after the migration: index-sync rows queued {n_isq}, write log {n_wl0} -> {n_wl}")
        print("RESULT:", "triggers KEPT" if after else "triggers LOST")
    finally:
        await c.close(); await client.spaces.delete_space(sid); await client.close()

asyncio.run(main())

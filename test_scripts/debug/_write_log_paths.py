"""The write log (`write_log.py`) on every write path, planner stack (:8003 / :5434).

Part A, trigger mechanics on FIXTURE tables (no space: a plain and a
HASH-partitioned `zzwl*_rdf_quad`, dropped on exit). Partitioned spaces cannot
be created through the API, so this is where that layout is tested:
INSERT, a multi-statement transaction, executemany, COPY, UPDATE, DELETE,
TRUNCATE, rollback, a rolled-back savepoint, two concurrent writers, compaction,
and snapshot visibility (a REPEATABLE READ reader does not see an uncommitted
or later write).

Part B, a real scratch space created and deleted through the API, the log
installed by `scripts/install_write_log.py`: SPARQL INSERT DATA, DELETE DATA,
DELETE WHERE, graph clear; a rename; a disabled trigger; and that deleting the
space removes the log.

    LOCAL_CLIENT_SERVER_URL=http://localhost:8003 \
    /opt/homebrew/anaconda3/envs/vital-graph/bin/python test_scripts/debug/_write_log_paths.py
"""
import asyncio
import os
import subprocess
import sys
import uuid

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

import asyncpg  # noqa: E402

PG = dict(host="localhost", port=int(os.getenv("VG_PG_PORT", "5434")), database="sparql_sql_graph",
          user="postgres", password="testpass")
FAILS = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   ({detail})" if detail else ""))
    if not ok:
        FAILS.append(name)


def fixture_sql(prefix):
    """write_log.create_sql, for a fixture prefix instead of a space's."""
    from vitalgraph.db.sparql_sql import write_log
    real = "vgs_zzfixture"
    stmts = []
    orig = write_log.space_prefix
    write_log.space_prefix = lambda _sid: real
    try:
        stmts = write_log.create_sql("x")
    finally:
        write_log.space_prefix = orig
    return [s.replace(real, prefix) for s in stmts]


async def count(c, prefix):
    return await c.fetchval(f"SELECT coalesce(sum(n), 0) FROM {prefix}_write_log")


async def part_a(pool, partitioned):
    prefix = "zzwlpart" if partitioned else "zzwlplain"
    print(f"\nA. fixture {prefix} ({'HASH-partitioned' if partitioned else 'plain'})")
    q = f"{prefix}_rdf_quad"
    async with pool.acquire() as c:
        await c.execute(f"DROP TABLE IF EXISTS {q}, {prefix}_write_log CASCADE")
        cols = "subject_uuid uuid, predicate_uuid uuid, object_uuid uuid, context_uuid uuid"
        if partitioned:
            await c.execute(f"CREATE TABLE {q} ({cols}) PARTITION BY HASH (context_uuid)")
            for i in range(4):
                await c.execute(f"CREATE TABLE {q}_p{i} PARTITION OF {q} "
                                f"FOR VALUES WITH (MODULUS 4, REMAINDER {i})")
        else:
            await c.execute(f"CREATE TABLE {q} ({cols})")
        for s in fixture_sql(prefix):
            await c.execute(s)
        row = lambda: (uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
        ins = f"INSERT INTO {q} VALUES ($1, $2, $3, $4)"

        n0 = await count(c, prefix)
        await c.execute(ins, *row())
        check("INSERT counts one", await count(c, prefix) == n0 + 1)

        n0 = await count(c, prefix)
        async with c.transaction():
            for _ in range(3):
                await c.execute(ins, *row())
            await c.execute(f"DELETE FROM {q} WHERE false")
        check("one transaction, four statements: one", await count(c, prefix) == n0 + 1)

        n0 = await count(c, prefix)
        async with c.transaction():
            await c.executemany(ins, [row() for _ in range(50)])
        check("executemany of 50: one", await count(c, prefix) == n0 + 1)

        n0 = await count(c, prefix)
        await c.copy_records_to_table(q, records=[row() for _ in range(100)])
        check("COPY: one", await count(c, prefix) == n0 + 1)

        n0 = await count(c, prefix)
        await c.execute(f"UPDATE {q} SET object_uuid = object_uuid WHERE true")
        check("UPDATE: one", await count(c, prefix) == n0 + 1)

        n0 = await count(c, prefix)
        await c.execute(f"DELETE FROM {q} WHERE ctid IN (SELECT ctid FROM {q} LIMIT 5)")
        check("DELETE: one", await count(c, prefix) == n0 + 1)

        n0 = await count(c, prefix)
        await c.execute(f"DELETE FROM {q} WHERE false")
        check("a DELETE that matches nothing still counts (safe direction)", await count(c, prefix) == n0 + 1)

        n0 = await count(c, prefix)
        try:
            async with c.transaction():
                await c.execute(ins, *row())
                raise RuntimeError("rollback")
        except RuntimeError:
            pass
        check("rolled-back transaction: none", await count(c, prefix) == n0)

        n0 = await count(c, prefix)
        async with c.transaction():
            try:
                async with c.transaction():          # savepoint
                    await c.execute(ins, *row())
                    raise RuntimeError("rollback savepoint")
            except RuntimeError:
                pass
            await c.execute(ins, *row())             # marker reverted with the savepoint
        check("savepoint rolled back, then another write: one", await count(c, prefix) == n0 + 1)

        n0 = await count(c, prefix)
        await c.execute(f"TRUNCATE {q}")
        check("TRUNCATE: one", await count(c, prefix) == n0 + 1)

    # concurrent writers do not wait for each other, and a reader's snapshot holds
    async with pool.acquire() as w1, pool.acquire() as w2, pool.acquire() as r:
        n0 = await count(r, prefix)
        t1, t2 = w1.transaction(), w2.transaction()
        await t1.start(); await t2.start()
        await w1.execute(ins, *row())
        await w2.execute("SET LOCAL lock_timeout = '500ms'")
        try:
            await w2.execute(ins, *row())
            check("second concurrent writer does not wait on the first", True)
        except asyncpg.exceptions.LockNotAvailableError:
            check("second concurrent writer does not wait on the first", False, "lock wait")
        check("uncommitted writes invisible to a reader", await count(r, prefix) == n0)
        rr = r.transaction(isolation="repeatable_read", readonly=True)
        await rr.start()
        before = await count(r, prefix)
        await t1.commit(); await t2.commit()
        check("REPEATABLE READ reader keeps its count across commits", await count(r, prefix) == before)
        await rr.rollback()
        check("a new snapshot sees both", await count(r, prefix) == n0 + 2)

        from vitalgraph.db.sparql_sql import write_log
        n0 = await count(r, prefix)
        rows = await r.fetchval(write_log.compact_sql(f"{prefix}_write_log"))
        left = await r.fetchval(f"SELECT count(*) FROM {prefix}_write_log")
        check("compaction keeps the count", await count(r, prefix) == n0, f"{rows} rows folded, {left} left")
        await r.execute(ins, *row())
        check("a write after compaction counts", await count(r, prefix) == n0 + 1)
        # a rename (what space_rename does: objects, not function bodies)
        await r.execute(f"ALTER TABLE {q} RENAME TO {prefix}ren_rdf_quad")
        await r.execute(f"ALTER TABLE {prefix}_write_log RENAME TO {prefix}ren_write_log")
        n0 = await count(r, prefix + "ren")
        await r.execute(f"INSERT INTO {prefix}ren_rdf_quad VALUES ($1, $2, $3, $4)", *row())
        check("after a rename, writes count in the renamed log", await count(r, prefix + "ren") == n0 + 1)
        await r.execute(f"DROP TABLE {prefix}ren_rdf_quad, {prefix}ren_write_log CASCADE")
        await r.execute(f"DROP FUNCTION IF EXISTS {prefix}_wlog_capture() CASCADE")


async def part_b(pool):
    from vitalgraph.client.vitalgraph_client import VitalGraphClient
    from vitalgraph.model.spaces_model import Space
    from vitalgraph.model.sparql_model import SPARQLUpdateRequest
    from vitalgraph.db.sparql_sql import write_log
    from vitalgraph.db.sparql_sql.space_storage_key import load_storage_keys
    from vitalgraph.db.sparql_sql.space_names import space_prefix

    space_id = f"zzwlog_{uuid.uuid4().hex[:8]}"
    g = "urn:zzwlog:g"
    print(f"\nB. scratch space {space_id} through the API")
    client = VitalGraphClient()
    await client.open()
    created = False
    try:
        cr = await client.spaces.create_space(Space(space=space_id, space_name=space_id,
                                                    space_description="write log probe (deleted on exit)"))
        assert cr.is_success, cr.error_message
        created = True
        await client.graphs.create_graph(space_id, g)
        async with pool.acquire() as c:
            await load_storage_keys(c, space_id)
            check("a new space has no log (installed by script only)",
                  not await write_log.installed(c, space_id))
        out = subprocess.run([sys.executable, os.path.join(REPO, "scripts", "install_write_log.py"),
                              "--space", space_id, "--apply", "--host", "localhost", "--port", str(PG["port"]),
                              "--database", PG["database"], "--user", PG["user"], "--password", PG["password"]],
                             capture_output=True, text=True)
        async with pool.acquire() as c:
            check("install script installs it", await write_log.installed(c, space_id), out.stdout.strip()[-80:])

        async def update(q):
            r = await client.sparql.execute_sparql_update(space_id, SPARQLUpdateRequest(update=q))
            assert getattr(r, "success", True), r

        async def state():
            async with pool.acquire() as c:
                return await write_log.guard_state(c, space_id)

        cases = [
            ("SPARQL INSERT DATA", f"INSERT DATA {{ GRAPH <{g}> {{ <urn:zzwlog:s1> <urn:zzwlog:p> <urn:zzwlog:o> . "
                                   f"<urn:zzwlog:s2> <urn:zzwlog:p> <urn:zzwlog:o> . }} }}"),
            ("SPARQL DELETE DATA", f"DELETE DATA {{ GRAPH <{g}> {{ <urn:zzwlog:s1> <urn:zzwlog:p> <urn:zzwlog:o> . }} }}"),
            ("SPARQL DELETE WHERE", f"DELETE WHERE {{ GRAPH <{g}> {{ ?s <urn:zzwlog:p> ?o }} }}"),
            ("SPARQL INSERT then CLEAR GRAPH", None),
        ]
        for name, q in cases:
            before = await state()
            if q is None:
                await update(f"INSERT DATA {{ GRAPH <{g}> {{ <urn:zzwlog:s3> <urn:zzwlog:p> <urn:zzwlog:o> . }} }}")
                mid = await state()
                await update(f"CLEAR GRAPH <{g}>")
                after = await state()
                check(name, mid[0] > before[0] and after[0] > mid[0], f"{before[0]} -> {mid[0]} -> {after[0]}")
            else:
                await update(q)
                after = await state()
                check(name, after[0] > before[0], f"{before[0]} -> {after[0]}")

        quad = f"{space_prefix(space_id)}_rdf_quad"
        async with pool.acquire() as c:
            await c.execute(f"ALTER TABLE {quad} DISABLE TRIGGER {write_log.trigger_name(space_id)}")
            check("a disabled trigger: the log vouches for nothing", await write_log.guard_state(c, space_id) is None)
            await c.execute(f"ALTER TABLE {quad} ENABLE TRIGGER {write_log.trigger_name(space_id)}")
            check("re-enabled: it vouches again", await write_log.guard_state(c, space_id) is not None)
    finally:
        if created:
            r = await client.spaces.delete_space(space_id)
            async with pool.acquire() as c:
                gone_t = not await c.fetchval("SELECT to_regclass($1) IS NOT NULL", write_log.table_name(space_id))
                gone_f = not await c.fetchval("SELECT EXISTS (SELECT 1 FROM pg_proc WHERE proname = $1)",
                                              write_log.function_name(space_id))
            check("deleting the space drops the log table and its function", gone_t and gone_f,
                  f"table gone {gone_t}, function gone {gone_f}")
        await client.close()


async def main():
    pool = await asyncpg.create_pool(**PG, min_size=1, max_size=4)
    try:
        await part_a(pool, partitioned=False)
        await part_a(pool, partitioned=True)
        if "--no-api" not in sys.argv:
            await part_b(pool)
    finally:
        await pool.close()
    print(f"\n{'ALL PASS' if not FAILS else f'{len(FAILS)} FAILED: {FAILS}'}")
    sys.exit(1 if FAILS else 0)


asyncio.run(main())

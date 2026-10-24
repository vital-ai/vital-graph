"""A written counterexample retires a pattern verdict at once, and the snapshot guard holds.

Planner stack (:8003 API, :5434 PG), space uw_prodshape2 with the write log and
`pattern_verdict` installed (`scripts/install_write_log.py`). The query is by_reason; its
pattern `?d hasKGEntityType UWNewBusinessDecision` is implied by the inbound link from a
ReasonKind slot, and the census found the verdict holds.

  1. refresh: the verdict holds and is current
  2. generate with the drop forced (VG_PLANNER_IMPLIED_MARGIN=1.0): the plan uses it
  3. open a REPEATABLE READ snapshot, check the guard (holds)
  4. write a counterexample THROUGH THE API: a ReasonKind slot linking to a graph that has
     no entity type, with a ReasonCode slot in the same frame
  5. in the old snapshot: the guard still holds, and the dropped plan's result is the
     pre-write one (the guard and the query agree: one snapshot)
  6. in a new snapshot: the guard fails
  7. regenerate: no drop (the verdict is out of date), and the result differs from what
     the dropped plan now returns: the counterexample is real, the drop would be wrong
  8. refresh: the verdict is decided FALSE
  9. delete the counterexample through the API; refresh: TRUE again, usable again

    LOCAL_CLIENT_SERVER_URL=http://localhost:8003 VG_PLANNER_FEATURES=qtree,oracle,implied \
    VG_PLANNER_IMPLIED_MARGIN=1.0 python test_scripts/debug/_pattern_verdict_counterexample.py
"""
import asyncio
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import asyncpg  # noqa: E402

PG = dict(host="localhost", port=5434, database="sparql_sql_graph", user="postgres", password="testpass")
SPACE = "uw_prodshape2"
QUERY = REPO / "test_scripts_internal/aws_test_scale/bench_uw_prodshape2/by_reason.sparql"
# The space's own graph and slot-type IRIs, read from the (untracked) query file so they
# are not spelled out here.
_Q = QUERY.read_text()
GRAPH = re.search(r"GRAPH <([^>]+)>", _Q).group(1)
_SLOT = {t.rsplit(":", 1)[-1]: t for t in re.findall(r"hasKGSlotType> <([^>]+)>", _Q)}
H = "http://vital.ai/ontology/haley-ai-kg#"
TRIPLES = (f"<urn:zzcx:slot_k> <{H}hasKGGraphURI> <urn:zzcx:d> . "
           f"<urn:zzcx:slot_k> <{H}hasKGSlotType> <{_SLOT['UwNbdReasonKind']}> . "
           f"<urn:zzcx:slot_k> <{H}hasFrameGraphURI> <urn:zzcx:f> . "
           f"<urn:zzcx:slot_k> <{H}hasChoiceSlotValue> <urn:zzcx:kind> . "
           f"<urn:zzcx:slot_c> <{H}hasKGSlotType> <{_SLOT['UwNbdReasonCode']}> . "
           f"<urn:zzcx:slot_c> <{H}hasFrameGraphURI> <urn:zzcx:f> . "
           f"<urn:zzcx:slot_c> <{H}hasTextSlotValue> \"zzcx_code\" . ")
FAILS = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   ({detail})" if detail else ""))
    if not ok:
        FAILS.append(name)


def rowset(rows):
    return sorted(repr(sorted(dict(r).items(), key=repr)) for r in rows)


async def main():
    from vitalgraph.client.vitalgraph_client import VitalGraphClient
    from vitalgraph.model.sparql_model import SPARQLUpdateRequest
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.sparql_sql.generator import generate_sql
    from vitalgraph.db.sparql_sql import pattern_verdict, planner_ext
    from vitalgraph.db.sparql_sql.space_storage_key import load_storage_keys
    assert planner_ext.FEATURES["implied"] and planner_ext.IMPLIED_MARGIN >= 1.0, "see the usage line"

    c = await asyncpg.connect(**PG)
    snap = await asyncpg.connect(**PG)
    await load_storage_keys(c)
    sc = AsyncSidecarClient("http://localhost:7072")
    client = VitalGraphClient()
    await client.open()
    cr = map_compile_response(await sc.compile(QUERY.read_text()))

    async def update(q):
        r = await client.sparql.execute_sparql_update(SPACE, SPARQLUpdateRequest(update=q))
        assert getattr(r, "success", True), r

    async def gen(verdicts=True):
        pattern_verdict._MISSING.clear()
        return await generate_sql(cr, SPACE, conn=c, planner_ext=True, planner_verdicts=verdicts)

    async def run(conn, g):
        async with conn.transaction():
            await conn.execute("SET LOCAL join_collapse_limit = 1")
            await conn.execute("SET LOCAL vg_planner.on_mismatch = warning")
            return await conn.fetch(g.plan_advice + "\n" + g.sql)

    inserted = False
    try:
        print("1. refresh")
        await pattern_verdict.refresh(c, SPACE)
        g = await gen()
        check("2. the plan uses the verdict (drops q0)", g.verdict_guard is not None,
              (g.plan_decisions.get("detail", {}).get("implied_drop") or g.plan_decisions.get("declined", {}).get("implied_drop")))
        if g.verdict_guard is None:
            return
        guard = g.verdict_guard
        before = rowset(await run(c, g))

        tx = snap.transaction(isolation="repeatable_read", readonly=True)
        await tx.start()
        check("3. guard holds in a snapshot taken before the write",
              await pattern_verdict.guard_holds(snap, SPACE, guard[1:]))

        await update(f"INSERT DATA {{ GRAPH <{GRAPH}> {{ {TRIPLES} }} }}")
        inserted = True
        print("4. counterexample written through the API")

        check("5a. old snapshot: guard still holds", await pattern_verdict.guard_holds(snap, SPACE, guard[1:]))
        async with snap.transaction():          # a savepoint: SET LOCAL inside the same snapshot
            await snap.execute("SET LOCAL join_collapse_limit = 1")
            await snap.execute("SET LOCAL vg_planner.on_mismatch = warning")
            in_old = rowset(await snap.fetch(g.plan_advice + "\n" + g.sql))
        check("5b. old snapshot: the dropped plan returns the pre-write result", in_old == before)
        await tx.rollback()

        check("6. new snapshot: guard fails", not await pattern_verdict.guard_holds(c, SPACE, guard[1:]))

        g2 = await gen()
        check("7a. regenerated: no verdict used", g2.verdict_guard is None,
              g2.plan_decisions.get("declined", {}).get("implied_drop"))
        correct = rowset(await run(c, g2))
        wrong = rowset(await run(c, g))
        off = await generate_sql(cr, SPACE, conn=c)
        async with c.transaction():
            if off.fixed_join_order:
                await c.execute("SET LOCAL join_collapse_limit = 1")
            today = await c.fetch(off.sql)
        def names(gg, rows):
            return sorted(repr(sorted((((gg.var_map.get(k.partition("__")[0], k), k.partition("__")[2]), v)
                                       for k, v in dict(r).items()), key=repr)) for r in rows)
        check("7b. the kept plan agrees with today's path", names(g2, await run(c, g2)) == names(off, today))
        check("7c. the dropped plan is now WRONG (the counterexample is real)", wrong != correct,
              f"{len(wrong)} vs {len(correct)} rows")

        res = await pattern_verdict.refresh(c, SPACE)
        mine = [r for r in res if '"b7b5b297' in r["key"]]
        check("8. refresh decides it FALSE", any(r.get("holds") is False for r in mine), str(mine)[:120])
    finally:
        if inserted:
            await update(f"DELETE DATA {{ GRAPH <{GRAPH}> {{ {TRIPLES} }} }}")
            print("9. counterexample deleted through the API")
            res = await pattern_verdict.refresh(c, SPACE)
            mine = [r for r in res if '"b7b5b297' in r["key"]]
            check("9a. refresh decides it TRUE again", any(r.get("holds") is True for r in mine), str(mine)[:120])
            g3 = await gen()
            check("9b. usable again", g3.verdict_guard is not None)
        await client.close()
        await snap.close()
        await c.close()
    print(f"\n{'ALL PASS' if not FAILS else f'{len(FAILS)} FAILED: {FAILS}'}")
    sys.exit(1 if FAILS else 0)


asyncio.run(main())

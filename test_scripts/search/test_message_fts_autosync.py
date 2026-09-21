#!/usr/bin/env python3
"""T7 — the FTS index stays correct as messages are created, edited and deleted.

Plan §5 T7. This is the test that would have caught `issues/217`, and it
asserts the three things that defect got wrong:

  1. a NEW message becomes findable, indexed by the MAPPING (hasTextSlotValue
     alone) rather than by "every literal the slot owns";
  2. an EDITED message stops matching its old text and starts matching the new;
  3. a DELETED entity takes its slots' index rows with it, instead of leaving
     rows that still match a search and resolve to nothing.

It also asserts the scope rule: a slot of a DIFFERENT type, written to the same
space, must NOT appear in a message index. Before issues/217 every write went
into every index regardless of type.

Writes and deletes real data, so it uses its own entity URIs and cleans up.

    VG_SERVER_URL=http://localhost:8002 VG_SEARCH_SPACE=... VG_SEARCH_GRAPH=... \\
        VG_KG_NS=... python3 test_scripts/search/test_message_fts_autosync.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

_failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}"
          + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _failures.append(name)


async def main() -> int:
    space = os.environ.get("VG_SEARCH_SPACE")
    graph = os.environ.get("VG_SEARCH_GRAPH")
    ns = os.environ.get("VG_KG_NS")
    index = os.environ.get("VG_FTS_INDEX", "message_content")
    if not (space and graph and ns):
        print("Set VG_SEARCH_SPACE, VG_SEARCH_GRAPH, VG_KG_NS.")
        return 2

    H = "http://vital.ai/ontology/haley-ai-kg#"
    slot_type = f"{ns}:slot:MsgContent"
    other_slot_type = f"{ns}:slot:MsgChannel"

    import asyncpg
    pg = dict(host=os.environ.get("VG_PG_HOST", "localhost"),
              port=int(os.environ.get("VG_PG_PORT", "5433")),
              database=os.environ.get("VG_PG_DB", "sparql_sql_graph"),
              user=os.environ.get("VG_PG_USER", "postgres"),
              password=os.environ.get("VG_PG_PASSWORD", "testpass"))
    conn = await asyncpg.connect(**pg)

    from vitalgraph.vectorization.auto_sync import _sync_fts_for_subjects
    from vitalgraph.endpoint.impl.data_import_impl import _term_uuid

    tag = uuid.uuid4().hex[:8]
    ent = f"urn:t7:{tag}:entity"
    slot = f"urn:t7:{tag}:slot:msg"
    other = f"urn:t7:{tag}:slot:chan"
    needle_a = f"zqxtest{tag}alpha"
    needle_b = f"zqxtest{tag}bravo"
    ctx_u = _term_uuid(graph, "U")

    async def put_quads(triples):
        """Insert (s,p,o) with o typed, minting terms as needed."""
        for s, p, o, otype in triples:
            for text, ttype in ((s, "U"), (p, "U"), (o, otype)):
                await conn.execute(
                    f"INSERT INTO {space}_term (term_uuid, term_text, term_type) "
                    f"VALUES ($1,$2,$3) ON CONFLICT DO NOTHING",
                    _term_uuid(text, ttype), text, ttype)
            await conn.execute(
                f"INSERT INTO {space}_rdf_quad "
                f"(subject_uuid, predicate_uuid, object_uuid, context_uuid) "
                f"VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING",
                _term_uuid(s, "U"), _term_uuid(p, "U"),
                _term_uuid(o, otype), ctx_u)

    async def del_subject(s):
        await conn.execute(
            f"DELETE FROM {space}_rdf_quad WHERE subject_uuid=$1 AND context_uuid=$2",
            _term_uuid(s, "U"), ctx_u)

    async def in_index(s) -> bool:
        return bool(await conn.fetchval(
            f"SELECT 1 FROM {space}_fts_{index} "
            f"WHERE subject_uuid=$1 AND context_uuid=$2",
            _term_uuid(s, "U"), ctx_u))

    async def text_of(s):
        return await conn.fetchval(
            f"SELECT search_text FROM {space}_fts_{index} "
            f"WHERE subject_uuid=$1 AND context_uuid=$2",
            _term_uuid(s, "U"), ctx_u)

    async def sync(subjects, op):
        await _sync_fts_for_subjects(
            conn, space, [_term_uuid(s, "U") for s in subjects], ctx_u, op)

    try:
        print("\nT7  AUTO-SYNC ON WRITE")

        # --- 1. INSERT --------------------------------------------------
        await put_quads([
            (ent, H + "hasKGEntityType", f"{ns}:entity:NurtureAction", "U"),
            (slot, H + "hasKGSlotType", slot_type, "U"),
            (slot, H + "hasKGGraphURI", ent, "U"),
            (slot, H + "hasTextSlotValue", f"hello {needle_a} world", "L"),
            (slot, H + "hasFrameGraphURI", f"{ent}:frame:1", "U"),
            (other, H + "hasKGSlotType", other_slot_type, "U"),
            (other, H + "hasKGGraphURI", ent, "U"),
            (other, H + "hasTextSlotValue", f"channel {needle_a}", "L"),
        ])
        await sync([ent, slot, other], "upsert")

        check("a new message is indexed", await in_index(slot))
        stored = await text_of(slot)
        # THE issues/217 ASSERTION. Auto-sync used to pass no mapping_rule, so
        # build_search_text fell back to "every literal property" and the row
        # held the slot type URI, the frame URI and the graph URI alongside the
        # text. The mapping says hasTextSlotValue ALONE.
        check("indexed by the MAPPING, not every literal",
              stored is not None and needle_a in stored
              and "hasKGSlotType" not in (stored or "")
              and slot_type not in (stored or ""),
              repr(stored))
        check("a slot of a DIFFERENT type is NOT in the message index",
              not await in_index(other),
              "MsgChannel slot leaked into the message index")

        # --- 2. UPDATE ---------------------------------------------------
        await conn.execute(
            f"DELETE FROM {space}_rdf_quad WHERE subject_uuid=$1 "
            f"AND predicate_uuid=$2 AND context_uuid=$3",
            _term_uuid(slot, "U"), _term_uuid(H + "hasTextSlotValue", "U"), ctx_u)
        await put_quads([(slot, H + "hasTextSlotValue",
                          f"goodbye {needle_b} world", "L")])
        await sync([slot], "upsert")
        after = await text_of(slot)
        check("edit: new text is indexed", needle_b in (after or ""), repr(after))
        check("edit: old text is GONE", needle_a not in (after or ""), repr(after))

        # --- 3. DELETE ----------------------------------------------------
        # The entity AND its members, which is what the issues/217 fix made the
        # endpoint pass. Deleting only the entity left the slot row behind.
        await del_subject(slot)
        await del_subject(ent)
        await sync([ent, slot], "delete")
        check("delete removes the slot's index row", not await in_index(slot))

        return 0
    finally:
        for s in (slot, other, ent):
            try:
                await del_subject(s)
                await conn.execute(
                    f"DELETE FROM {space}_fts_{index} WHERE subject_uuid=$1",
                    _term_uuid(s, "U"))
            except Exception:
                pass
        await conn.close()


if __name__ == "__main__":
    rc = asyncio.run(main())
    print()
    if _failures:
        print(f"FAILED — {len(_failures)}: {', '.join(_failures)}")
        sys.exit(1)
    if rc == 0:
        print("All checks passed.")
    sys.exit(rc)

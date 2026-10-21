"""An entity upsert rewrites only the subjects whose quads changed — issues/271.

`upsert_objects_atomic` deleted every quad of every subject of the entity and
inserted the whole new graph. A subject whose quads were identical was deleted
and written again, paying its index and WAL cost twice, and the insert path's
own skip of stored quads could never fire because the rows had just gone:
`pg_stat_statements` on production showed calls = rows for every UW quad insert.

Now a stored subject whose quads equal its new ones is left alone. Two things
have to hold, and both are checked against the real database:

* NOTHING UNCHANGED IS WRITTEN. Each quad row's `xmin` is the transaction that
  wrote it; a row left alone keeps its `xmin`, a deleted-and-reinserted one does
  not. That is a direct observation of "not rewritten", not an inference from
  timings or counts.
* THE DERIVED TABLES STAY EXACT. They are maintained by subject (a frame through
  itself, its slots, or the edges joining them), so skipping a subject must not
  leave a row stale or drop one a changed neighbour's sync removed. After each
  upsert, every derived table is compared row for row with a from-scratch
  rebuild of the same quads.

Driven through the real adapter, because the claim is about what the database
holds afterwards, which a fake cannot establish.
"""

from __future__ import annotations

import pytest
from rdflib import Literal, URIRef

from .conftest import skip_no_infra

from vitalgraph.kg_impl.kg_backend_utils import create_backend_adapter
from vitalgraph.db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid
from vitalgraph.db.sparql_sql.space_names import space_prefix

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

KG = "http://vital.ai/ontology/haley-ai-kg#"
CORE = "http://vital.ai/ontology/vital-core#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
EX = "http://example.org/upsert-diff/"
GRAPH = f"{EX}graph"
ENTITY = f"{EX}lead"

DERIVED = ("edge", "frame_slot", "entity_slot_sort", "entity_prop_sort",
           "frame_prop_sort")


class _Obj:
    """The one thing `upsert_objects_atomic` asks of a GraphObject."""

    def __init__(self, triples):
        self._triples = triples

    def to_triples(self):
        return self._triples


def _graph(values: dict, src_entity: str, dst_entity: str, extra_slot: bool = True):
    """An entity graph: the entity, a frame with text slots, a binary connection
    frame with source/destination entity slots, and the edges between them.
    Every subject names the entity in `hasKGGraphURI`, as the KG writes do."""
    u = URIRef
    e = u(ENTITY)
    member = u(f"{KG}hasKGGraphURI")
    subjects: dict = {}

    def add(s, p, o):
        subjects.setdefault(s, []).append((u(s), u(p), o))

    add(ENTITY, RDF_TYPE, u(f"{KG}KGEntity"))
    add(ENTITY, f"{KG}hasKGEntityType", u(f"{EX}LeadType"))
    add(ENTITY, f"{CORE}hasName", Literal("lead one"))

    frame = f"{EX}frame"
    add(frame, f"{KG}hasKGFrameType", u(f"{EX}DecisionFrame"))
    add(f"{EX}e_ef", f"{CORE}vitaltype", u(f"{KG}Edge_hasEntityKGFrame"))
    add(f"{EX}e_ef", f"{CORE}hasEdgeSource", e)
    add(f"{EX}e_ef", f"{CORE}hasEdgeDestination", u(frame))
    for name, value in values.items():
        if name == "b" and not extra_slot:
            continue
        slot, edge = f"{EX}slot_{name}", f"{EX}e_slot_{name}"
        add(slot, f"{KG}hasKGSlotType", u(f"{EX}Slot_{name}"))
        add(slot, f"{KG}hasTextSlotValue", Literal(value))
        add(edge, f"{CORE}vitaltype", u(f"{KG}Edge_hasKGSlot"))
        add(edge, f"{CORE}hasEdgeSource", u(frame))
        add(edge, f"{CORE}hasEdgeDestination", u(slot))

    conn_frame = f"{EX}conn_frame"
    add(conn_frame, RDF_TYPE, u(f"{KG}KGFrame"))
    for role, target in (("src", src_entity), ("dst", dst_entity)):
        slot, edge = f"{EX}conn_{role}", f"{EX}e_conn_{role}"
        add(slot, f"{KG}hasKGSlotType",
            u("urn:hasSourceEntity" if role == "src" else "urn:hasDestinationEntity"))
        add(slot, f"{KG}hasEntitySlotValue", u(target))
        add(edge, f"{CORE}hasEdgeSource", u(conn_frame))
        add(edge, f"{CORE}hasEdgeDestination", u(slot))
    add(f"{EX}e_ecf", f"{CORE}vitaltype", u(f"{KG}Edge_hasEntityKGFrame"))
    add(f"{EX}e_ecf", f"{CORE}hasEdgeSource", e)
    add(f"{EX}e_ecf", f"{CORE}hasEdgeDestination", u(conn_frame))

    for s in list(subjects):
        add(s, str(member), e)
    return [_Obj(triples) for triples in subjects.values()]


async def _xmins(pool, space: str) -> dict:
    """subject uri -> the set of writing transactions of its quad rows."""
    async with pool.acquire() as c:
        rows = await c.fetch(
            f"SELECT t.term_text, q.xmin::text AS x FROM {space_prefix(space)}_rdf_quad q "
            f"JOIN {space_prefix(space)}_term t ON t.term_uuid = q.subject_uuid "
            f"WHERE q.context_uuid = $1", _generate_term_uuid(GRAPH, 'U'))
    out: dict = {}
    for r in rows:
        out.setdefault(r["term_text"], set()).add(r["x"])
    return out


async def _snapshot(conn, space: str) -> dict:
    return {name: sorted(r[0] for r in await conn.fetch(
                f"SELECT to_jsonb(x)::text FROM {space_prefix(space)}_{name} x"))
            for name in DERIVED}


async def _assert_derived_exact(pool, space: str):
    """Every derived table equals a from-scratch rebuild of the same quads."""
    from vitalgraph.db.sparql_sql.sync_edge_table import resync_edge_table
    from vitalgraph.db.sparql_sql.sync_frame_slot_table import resync_frame_slot_table
    from vitalgraph.db.sparql_sql.sync_entity_slot_sort import resync_entity_slot_sort
    from vitalgraph.db.sparql_sql.sync_entity_prop_sort import resync_entity_prop_sort
    from vitalgraph.db.sparql_sql.sync_frame_prop_sort import resync_frame_prop_sort

    async with pool.acquire() as c:
        live = await _snapshot(c, space)
        tr = c.transaction()
        await tr.start()
        try:
            await resync_edge_table(c, space)
            await resync_frame_slot_table(c, space)
            await resync_entity_slot_sort(c, space)
            await resync_entity_prop_sort(c, space)
            await resync_frame_prop_sort(c, space)
            rebuilt = await _snapshot(c, space)
        finally:
            await tr.rollback()
    for name in DERIVED:
        assert live[name] == rebuilt[name], (
            f"{space_prefix(space)}_{name} differs from a rebuild of the same quads after the "
            f"upsert:\n  live    {live[name]}\n  rebuilt {rebuilt[name]}")
    assert any(live[n] for n in DERIVED), "the fixture derived nothing at all"


@pytest.fixture
def upsert(test_space, space_impl):
    adapter = create_backend_adapter(space_impl)

    async def _do(objects):
        assert await adapter.upsert_objects_atomic(
            test_space, GRAPH, [ENTITY], objects) is True
    return _do


BASE = dict(values={"a": "alpha", "b": "bravo"},
            src_entity=f"{EX}x", dst_entity=f"{EX}y")


async def test_an_unchanged_reupsert_rewrites_nothing_but_the_entity(
        upsert, test_space, pg_pool):
    await upsert(_graph(**BASE))
    before = await _xmins(pg_pool, test_space)

    await upsert(_graph(**BASE))
    after = await _xmins(pg_pool, test_space)

    rewritten = sorted(s for s in before if after.get(s) != before[s])
    # The entity is re-stamped with a new modification time on every upsert,
    # so it alone is replaced; every other subject must keep its rows.
    assert rewritten == [ENTITY], (
        f"an identical re-upsert rewrote {rewritten}; only the entity, whose "
        f"server-stamped times move, should have been written")
    assert set(after) == set(before)
    await _assert_derived_exact(pg_pool, test_space)


async def test_one_changed_value_rewrites_only_its_subject(
        upsert, test_space, pg_pool):
    await upsert(_graph(**BASE))
    before = await _xmins(pg_pool, test_space)

    await upsert(_graph(**{**BASE, "values": {"a": "alpha", "b": "zulu"}}))
    after = await _xmins(pg_pool, test_space)

    rewritten = sorted(s for s in before if after.get(s) != before[s])
    assert rewritten == sorted([ENTITY, f"{EX}slot_b"]), rewritten
    await _assert_derived_exact(pg_pool, test_space)


async def test_a_repointed_entity_slot_moves_the_connection_row(
        upsert, test_space, pg_pool):
    """The slot is the only subject touched; its frame is unchanged and skipped,
    so the frame_slot row has to be re-derived through the slot alone."""
    await upsert(_graph(**BASE))
    await upsert(_graph(**{**BASE, "dst_entity": f"{EX}z"}))

    async with pg_pool.acquire() as c:
        targets = {r[0] for r in await c.fetch(
            f"SELECT t.term_text FROM {space_prefix(test_space)}_frame_slot fs "
            f"JOIN {space_prefix(test_space)}_term t ON t.term_uuid = fs.entity_uuid")}
    assert f"{EX}z" in targets and f"{EX}y" not in targets, targets
    await _assert_derived_exact(pg_pool, test_space)


async def test_a_dropped_subject_and_its_edge_are_removed(
        upsert, test_space, pg_pool):
    await upsert(_graph(**BASE))
    await upsert(_graph(**BASE, extra_slot=False))

    after = await _xmins(pg_pool, test_space)
    assert f"{EX}slot_b" not in after and f"{EX}e_slot_b" not in after, sorted(after)
    await _assert_derived_exact(pg_pool, test_space)


async def test_a_new_subject_is_added_without_rewriting_the_rest(
        upsert, test_space, pg_pool):
    await upsert(_graph(**BASE, extra_slot=False))
    before = await _xmins(pg_pool, test_space)

    await upsert(_graph(**BASE))
    after = await _xmins(pg_pool, test_space)

    assert f"{EX}slot_b" in after and f"{EX}e_slot_b" in after
    rewritten = sorted(s for s in before if after.get(s) != before[s])
    assert rewritten == [ENTITY], rewritten
    await _assert_derived_exact(pg_pool, test_space)


async def test_a_value_gaining_a_datatype_is_rewritten(
        upsert, test_space, pg_pool):
    """`"7"` stored untyped, then sent as `"7"^^xsd:integer`. If the comparison
    hashed the typed literal without its datatype id it would match the stored
    untyped one and skip a write that changes the value's type."""
    from rdflib.namespace import XSD
    await upsert(_graph(**{**BASE, "values": {"a": "alpha", "b": "7"}}))
    objs = _graph(**{**BASE, "values": {"a": "alpha", "b": "7"}})
    for o in objs:
        o._triples = [(s, p, Literal("7", datatype=XSD.integer))
                      if str(p) == f"{KG}hasTextSlotValue" and str(v) == "7" else (s, p, v)
                      for s, p, v in o._triples]
    before = await _xmins(pg_pool, test_space)
    await upsert(objs)
    after = await _xmins(pg_pool, test_space)

    assert after[f"{EX}slot_b"] != before[f"{EX}slot_b"], (
        "the slot's value changed type but the subject was skipped as unchanged")
    async with pg_pool.acquire() as c:
        dt = await c.fetchval(
            f"SELECT t.datatype_id FROM {space_prefix(test_space)}_rdf_quad q "
            f"JOIN {space_prefix(test_space)}_term t ON t.term_uuid = q.object_uuid "
            f"WHERE q.subject_uuid = $1 AND q.predicate_uuid = $2",
            _generate_term_uuid(f"{EX}slot_b", 'U'),
            _generate_term_uuid(f"{KG}hasTextSlotValue", 'U'))
    assert dt is not None, "the stored value is still untyped"
    await _assert_derived_exact(pg_pool, test_space)

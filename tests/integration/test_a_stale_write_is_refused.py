"""The lost update: a slower save must not overwrite a newer one (`issues/253`).

Reported from production: "a slower, older save can overwrite a newer one even
when nothing fails", with every request reporting success. No amount of locking
prevents it — the entity lock makes one WRITE atomic, while the race spans the
caller's READ, its merge and its write, issued as three separate requests. An
autosave sending 138 writes for one lead in four minutes is exactly the shape
that loses them.

So a caller may pass the `hasObjectModificationDateTime` it read, and the write
is refused if the stored value has moved. The comparison happens INSIDE the write
transaction and under the entity lock, because anywhere else is a race of its
own: the endpoint stamps that property AFTER the write and OUTSIDE the lock,
which leaves a window where the next writer reads a value its predecessor has not
published yet.

Driven through the real backend against a real database, because the claim is
about concurrency and ordering, which a fake cannot establish.
"""
import pytest
import pytest_asyncio
from rdflib import Literal, URIRef

from .conftest import skip_no_infra

from vitalgraph.kg_impl.kg_backend_utils import (
    AmbiguousStamp, StaleWrite, UnguardableWrite, create_backend_adapter)
from vitalgraph.kg_impl.kg_server_properties import MODIFICATION_TIME_URI
from vitalgraph.db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

ENTITY = "urn:lead:stale-probe"
FRAME = "urn:frame:stale-probe"


@pytest_asyncio.fixture(loop_scope="session")
async def arena(make_space, space_impl):
    """A space, an adapter, and readers for the stamp and the written value."""
    space_id = await make_space()
    graph = f"urn:{space_id}"
    adapter = create_backend_adapter(space_impl)
    t = space_impl.schema.get_table_names(space_id)
    pool = space_impl.db_impl.connection_pool

    async def stamp():
        async with pool.acquire() as c:
            return await c.fetchval(
                f"SELECT tt.term_text FROM {t['rdf_quad']} q "
                f"JOIN {t['term']} tt ON tt.term_uuid = q.object_uuid "
                f"WHERE q.subject_uuid=$1 AND q.predicate_uuid=$2 AND q.context_uuid=$3",
                _generate_term_uuid(ENTITY, 'U'),
                _generate_term_uuid(MODIFICATION_TIME_URI, 'U'),
                _generate_term_uuid(graph, 'U'))

    async def value():
        async with pool.acquire() as c:
            return await c.fetchval(
                f"SELECT tt.term_text FROM {t['rdf_quad']} q "
                f"JOIN {t['term']} tt ON tt.term_uuid = q.object_uuid "
                f"JOIN {t['term']} tp ON tp.term_uuid = q.predicate_uuid "
                f"WHERE q.subject_uuid=$1 AND tp.term_text='urn:p' AND q.context_uuid=$2",
                _generate_term_uuid(FRAME, 'U'), _generate_term_uuid(graph, 'U'))

    async def write(val, *, expect=None, stamp_it=True):
        return await adapter.update_subjects_graph(
            space_id, graph, [FRAME],
            [(URIRef(FRAME), URIRef("urn:p"), Literal(val), URIRef(graph))],
            lock_uris=[ENTITY],
            guard_subject=ENTITY if stamp_it else None,
            if_unmodified_since=expect)

    await write("v0")
    return {"stamp": stamp, "value": value, "write": write,
            "space_id": space_id, "graph": graph, "t": t, "pool": pool,
            "adapter": adapter}


class TestTheLostUpdate:
    async def test_the_stale_writer_is_refused_and_the_newer_value_survives(
            self, arena):
        # Both callers read the same stamp — the production shape exactly.
        shared = await arena["stamp"]()
        assert shared is not None

        assert await arena["write"]("B", expect=shared) is True
        assert await arena["value"]() == "B"

        with pytest.raises(StaleWrite):
            await arena["write"]("A-STALE", expect=shared)

        # THE DEFECT, prevented: A's slower save did not overwrite B.
        assert await arena["value"]() == "B"

    async def test_the_refused_writer_succeeds_after_re_reading(self, arena):
        shared = await arena["stamp"]()
        await arena["write"]("B", expect=shared)
        with pytest.raises(StaleWrite):
            await arena["write"]("A-STALE", expect=shared)

        assert await arena["write"]("A-FRESH", expect=await arena["stamp"]()) is True
        assert await arena["value"]() == "A-FRESH"

    async def test_the_write_moves_the_stamp(self, arena):
        before = await arena["stamp"]()
        await arena["write"]("next", expect=before)
        assert await arena["stamp"]() != before

    async def test_a_caller_that_does_not_opt_in_is_unaffected(self, arena):
        # Backwards compatibility is the whole reason this is opt-in: today's
        # callers pass nothing and must keep working exactly as before.
        shared = await arena["stamp"]()
        await arena["write"]("B", expect=shared)
        assert await arena["write"]("legacy", stamp_it=False) is True
        assert await arena["value"]() == "legacy"


class TestTheStampIsReadableAndNotJustPresent:
    """A quad whose predicate has no term row exists and cannot be read.

    Found over HTTP, not here: the frame came back with no stamp while the quad
    sat in `rdf_quad`. Every read joins the term table to turn uuids back into
    text, so a missing term row makes the join drop the row — silently, with the
    write reporting success.

    It could not happen on the ENTITY path, which is why the first version of
    this mechanism looked correct: an entity already carries this predicate from
    ordinary server-property stamping, so the term row was always already there.
    The first subject ever stamped WITHOUT one was a standalone frame in a fresh
    space. These tests assert the join, not the row count, because the row count
    was right.
    """

    async def test_the_predicate_has_a_term_row(self, arena):
        async with arena["pool"].acquire() as c:
            assert await c.fetchval(
                f"SELECT EXISTS(SELECT 1 FROM {arena['t']['term']} "
                f"WHERE term_text = $1)", MODIFICATION_TIME_URI), (
                    "the stamp predicate has no term row, so every read that "
                    "joins terms drops the stamp")

    async def test_the_stamp_quad_survives_the_join(self, arena):
        # The same shape as an API read: subject, predicate and object all
        # resolved through the term table.
        async with arena["pool"].acquire() as c:
            got = await c.fetchval(
                f"SELECT tt.term_text FROM {arena['t']['rdf_quad']} q "
                f"JOIN {arena['t']['term']} ts ON ts.term_uuid = q.subject_uuid "
                f"JOIN {arena['t']['term']} tp ON tp.term_uuid = q.predicate_uuid "
                f"JOIN {arena['t']['term']} tt ON tt.term_uuid = q.object_uuid "
                f"WHERE ts.term_text = $1 AND tp.term_text = $2",
                ENTITY, MODIFICATION_TIME_URI)
        assert got, "the stamp is in the table but no read can see it"

    async def test_a_subject_stamped_without_being_written_is_readable(self, arena):
        # The slot-route shape: the FRAME's version advances while only its slots
        # are written, so the stamped subject is not among `subject_uris` and
        # nothing else in the write puts its term row there.
        other = "urn:lead:stamped-but-not-written"
        assert await arena["adapter"].update_subjects_graph(
            arena["space_id"], arena["graph"], [FRAME],
            [(URIRef(FRAME), URIRef("urn:p"), Literal("x"), URIRef(arena["graph"]))],
            lock_uris=[ENTITY], stamp_subjects=[other]) is True

        async with arena["pool"].acquire() as c:
            got = await c.fetchval(
                f"SELECT tt.term_text FROM {arena['t']['rdf_quad']} q "
                f"JOIN {arena['t']['term']} ts ON ts.term_uuid = q.subject_uuid "
                f"JOIN {arena['t']['term']} tp ON tp.term_uuid = q.predicate_uuid "
                f"JOIN {arena['t']['term']} tt ON tt.term_uuid = q.object_uuid "
                f"WHERE ts.term_text = $1 AND tp.term_text = $2",
                other, MODIFICATION_TIME_URI)
        assert got, "a stamped subject the write did not insert has no term row"

    async def test_a_stamped_subject_that_is_also_rewritten_keeps_its_stamp(self, arena):
        # The standalone-frame shape: the guarded subject is ALSO among the
        # subjects being replaced. Stamping before the subject-level DELETE put
        # the stamp in front of the statement that removes it, so a successful
        # write left the subject with no stamp at all.
        assert await arena["adapter"].update_subjects_graph(
            arena["space_id"], arena["graph"], [FRAME],
            [(URIRef(FRAME), URIRef("urn:p"), Literal("y"), URIRef(arena["graph"]))],
            lock_uris=[FRAME], guard_subject=FRAME) is True

        async with arena["pool"].acquire() as c:
            got = await c.fetchval(
                f"SELECT tt.term_text FROM {arena['t']['rdf_quad']} q "
                f"JOIN {arena['t']['term']} tp ON tp.term_uuid = q.predicate_uuid "
                f"JOIN {arena['t']['term']} tt ON tt.term_uuid = q.object_uuid "
                f"WHERE q.subject_uuid = $1 AND tp.term_text = $2 "
                f"AND q.context_uuid = $3",
                _generate_term_uuid(FRAME, 'U'), MODIFICATION_TIME_URI,
                _generate_term_uuid(arena["graph"], 'U'))
        assert got, ("the write deleted its own stamp: it was written before the "
                     "subject-level DELETE that covers the same subject")


class TestAnUndecidableGuardCarriesItsReason:
    """The guard cannot be decided, so nothing is written AND the reason escapes.

    `STORE_FAILED` promises "a describable data reason", and the description has
    to reach the response. These were collapsed into `update_subjects_graph`'s
    bare `False`, so the caller built a fresh `SubjectWriteFailed("slot update",
    N)` and the real cause lived only in the log — the body said how MANY
    subjects, never which, nor why. Driven against a real database because the
    claim is about what escapes a real transaction.
    """

    async def test_a_precondition_with_no_subject_refuses_and_says_so(self, arena):
        with pytest.raises(UnguardableWrite) as e:
            await arena["adapter"].update_subjects_graph(
                arena["space_id"], arena["graph"], [FRAME],
                [(URIRef(FRAME), URIRef("urn:p"), Literal("nope"),
                  URIRef(arena["graph"]))],
                # The defect's shape: a precondition, and nothing to compare it
                # against. This used to write unconditionally and report success.
                if_unmodified_since="2026-01-01T00:00:00+00:00")
        assert FRAME in str(e.value)

    async def test_nothing_was_written_by_the_refused_call(self, arena):
        before = await arena["value"]()
        with pytest.raises(UnguardableWrite):
            await arena["adapter"].update_subjects_graph(
                arena["space_id"], arena["graph"], [FRAME],
                [(URIRef(FRAME), URIRef("urn:p"), Literal("must-not-land"),
                  URIRef(arena["graph"]))],
                if_unmodified_since="2026-01-01T00:00:00+00:00")
        assert await arena["value"]() == before

    async def test_two_stamps_refuse_and_name_both(self, arena):
        # Break the single-valued invariant deliberately — `issues/173` is it
        # breaking by accident — then show the guard refuses instead of picking
        # whichever row the scan reaches first.
        from vitalgraph.kg_impl.kg_backend_utils import _insert_stamp, _stamp_keys

        t, s_uuid, p_uuid, g_uuid = _stamp_keys(
            arena["space_id"], arena["graph"], ENTITY)
        async with arena["pool"].acquire() as c:
            await _insert_stamp(c, t, s_uuid, p_uuid, g_uuid,
                                "2099-01-01T00:00:00+00:00", subject_uri=ENTITY)
        try:
            with pytest.raises(AmbiguousStamp) as e:
                await arena["write"]("x", expect=await arena["stamp"]())
            assert "2" in str(e.value)
        finally:
            # Put the entity back to one stamp, or every later test in this
            # module inherits the broken invariant.
            async with arena["pool"].acquire() as c:
                await c.execute(
                    f"DELETE FROM {t['rdf_quad']} WHERE subject_uuid = $1 "
                    f"AND predicate_uuid = $2 AND context_uuid = $3",
                    s_uuid, p_uuid, g_uuid)
                await _insert_stamp(c, t, s_uuid, p_uuid, g_uuid,
                                    "2026-10-01T00:00:00+00:00",
                                    subject_uri=ENTITY)

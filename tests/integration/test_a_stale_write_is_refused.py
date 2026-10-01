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

from vitalgraph.kg_impl.kg_backend_utils import StaleWrite, create_backend_adapter
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
            stamp_entity=ENTITY if stamp_it else None,
            if_unmodified_since=expect)

    await write("v0")
    return {"stamp": stamp, "value": value, "write": write}


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

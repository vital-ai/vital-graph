"""A write that fails must not be reported as a write of nothing (issues/105).

`add_rdf_quads_batch_bulk` caught every exception, logged it, and returned 0. A
failed write and an empty write then look identical, and of nine call sites only
one told them apart — by INFERRING failure from "0 inserted from a non-empty
input", which is why its message could only say "likely a PostgreSQL index
overflow or constraint error". The exception was already gone.

`issues/100` is what that costs. `sp_kg_types` was missing
`{space}_entity_slot_sort`, which this write maintains:

    1. the write fails, logs at ERROR, returns 0
    2. `update_quads` discards the count and returns True — its own
       `except -> return False` is unreachable, because nothing raises
    3. `create_kgtype` DOES check, and is told True
    4. the API reports the types created; nothing was written, and six
       subsequent searches returned zero rows for a reason no layer reported

Three separate error checks, each written by someone expecting to catch this, all
defeated by a `return 0` at the bottom. It took two days and three wrong
hypotheses to find, and the cause was in the log the whole time — nobody reads
the server log for a request that succeeded.

These tests break the table the write depends on, which is the real failure from
`issues/100` rather than a mocked one, and assert the failure survives each layer.

THE SPACE IS THIS FILE'S OWN. An earlier version renamed a table inside
`sp_kg_types`, which `test_new_space_matches_schema` and two API suites also
read — a rename is global, so the window was visible to anything touching that
space. One run failed with "relation does not exist" in the HEALTHY-write test
and did not reproduce in five more; rather than call a shared-state hazard a
flake, the fixture space is now created per module by `make_space`.
"""

from __future__ import annotations

import pytest
from rdflib import URIRef
import pytest_asyncio

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

# The table `add_rdf_quads_batch_bulk` maintains, and the one that was missing on
# `sp_kg_types` when issues/100 was traced.
DEPENDENCY_SUFFIX = "_entity_slot_sort"


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def write_space(make_space):
    """A space this file owns, so breaking its schema cannot reach another test."""
    return await make_space()


@pytest.fixture
def quads(write_space):
    # rdflib terms, not bare strings. A quad position takes a TERM: a string
    # cannot say whether it is a URI, a literal or a blank node label, and
    # guessing is what stored `"entity 3 (Topic)"` as a URI (`issues/135`).
    # This is also what the live write paths pass —
    # `get_existing_quads_for_uris` returns rdflib Identifiers.
    return [(URIRef("urn:issues105:s"), URIRef("urn:issues105:p"),
             URIRef("urn:issues105:o"), URIRef(f"urn:{write_space}"))]


async def _space_impl(pg_conn):
    from devtools.target import get_connection_params
    from vitalgraph.db.sparql_sql.sparql_sql_space_impl import SparqlSQLSpaceImpl

    p = get_connection_params()
    impl = SparqlSQLSpaceImpl({
        "host": p["host"], "port": p["port"], "database": p["dbname"],
        # this impl reads `username`, not `user`
        "username": p["user"], "password": p["password"],
    })
    if not await impl.connect():
        pytest.skip("could not connect the space impl to the configured stack")
    return impl


class _BreakDependency:
    """Rename the maintained table away, and always put it back."""

    def __init__(self, conn, space_id):
        self._conn = conn
        self._table = f"{space_id}{DEPENDENCY_SUFFIX}"
        self._hidden = f"{self._table}_hidden_105"

    async def __aenter__(self):
        exists = await self._conn.fetchval(
            "SELECT 1 FROM pg_tables WHERE tablename = $1", self._table)
        if not exists:
            pytest.skip(f"{self._table} is not present on this stack")
        await self._conn.execute(
            f'ALTER TABLE {self._table} RENAME TO {self._hidden}')
        return self

    async def __aexit__(self, *exc):
        await self._conn.execute(
            f'ALTER TABLE {self._hidden} RENAME TO {self._table}')
        return False


async def test_the_write_raises_rather_than_returning_zero(pg_conn, write_space, quads):
    impl = await _space_impl(pg_conn)
    try:
        async with _BreakDependency(pg_conn, write_space):
            with pytest.raises(Exception) as caught:
                await impl.add_rdf_quads_batch_bulk(write_space, quads)
        # The point is not merely that it raised, but that the CAUSE survives.
        # A returned 0 carried no cause at all.
        assert f"{write_space}{DEPENDENCY_SUFFIX}" in str(caught.value), (
            f"the exception should name what was missing, got: {caught.value}")
    finally:
        await impl.disconnect()


async def test_update_quads_reports_false(pg_conn, write_space, quads):
    """Layer 2: it discarded the count and returned True unconditionally.

    No change was needed there — its `except -> return False` was already
    written and merely unreachable. This asserts it is reachable now.
    """
    from vitalgraph.kg_impl.kg_backend_utils import SparqlSQLBackendAdapter

    impl = await _space_impl(pg_conn)
    try:
        async with _BreakDependency(pg_conn, write_space):
            adapter = SparqlSQLBackendAdapter(impl)
            ok = await adapter.update_quads(write_space, f"urn:{write_space}", [], quads)
        assert ok is False, "a failed write was reported as a successful update"
    finally:
        await impl.disconnect()


async def test_a_healthy_write_still_returns_a_count(pg_conn, write_space, quads):
    """The guard has to stay quiet on the working path.

    Without this, "always raise" and "raise only on failure" both pass, and the
    first one breaks every caller.
    """
    impl = await _space_impl(pg_conn)
    try:
        n = await impl.add_rdf_quads_batch_bulk(write_space, quads)
        assert n == len(quads), f"expected {len(quads)} written, got {n}"
        empty = await impl.add_rdf_quads_batch_bulk(write_space, [])
        assert empty == 0, "an empty write must still be a legitimate zero"
    finally:
        await impl.remove_rdf_quads_batch_bulk(write_space, quads)
        await impl.disconnect()

"""The maintenance cycle reports quads in a graph the catalog does not list.

issues/116. Graph registration is implicit on three impl write functions rather
than on the act of landing quads, so any other path skips it silently: the data
stays queryable by URI while everything that LISTS graphs sees nothing. Two
writers did exactly that and were found one at a time, months apart —
load_wordnet_csv.py (31M quads across three fixtures) and
bulk_export.import_space.

This is the general guard those two instances argued for. It reports; it does
not repair, because registering from a sweep fixes the symptom on a schedule
and leaves every writer free to keep skipping it.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from rdflib import URIRef

from .conftest import skip_no_infra, TEST_SPACE_PREFIX

pytestmark = [pytest.mark.integration, skip_no_infra,
              pytest.mark.asyncio(loop_scope="session")]


@pytest_asyncio.fixture(loop_scope="session")
async def reg_space(make_space):
    return await make_space(f"{TEST_SPACE_PREFIX}graphreg_{uuid.uuid4().hex[:8]}")


def _job(space_impl):
    from vitalgraph.process.maintenance_job import MaintenanceJob
    return MaintenanceJob(pool=space_impl.db_impl.connection_pool)


async def test_a_registered_graph_is_not_reported(space_impl, reg_space):
    """The write path registers, so a normally-written space is clean."""
    g = URIRef("urn:graphreg:ok")
    await space_impl.add_rdf_quads_batch_bulk(reg_space, [
        (URIRef("urn:graphreg:s"), URIRef("urn:graphreg:p"),
         URIRef("urn:graphreg:o"), g)])

    assert await _job(space_impl)._run_graph_registration_check([reg_space]) is None


async def test_an_unlisted_graph_is_reported(space_impl, reg_space, caplog):
    """Delete the catalog row to simulate a writer that never made one."""
    g = URIRef("urn:graphreg:missing")
    await space_impl.add_rdf_quads_batch_bulk(reg_space, [
        (URIRef("urn:graphreg:s2"), URIRef("urn:graphreg:p"),
         URIRef("urn:graphreg:o2"), g)])

    async with space_impl.db_impl.connection_pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM graph WHERE space_id = $1 AND graph_uri = $2",
            reg_space, str(g))

    with caplog.at_level("WARNING"):
        result = await _job(space_impl)._run_graph_registration_check([reg_space])

    assert result is not None, "an unlisted graph went unreported"
    assert str(g) in result["unlisted_graphs"], result
    assert any("issues/116" in r.getMessage() for r in caplog.records)

    # Reports only — the row must NOT have been recreated.
    async with space_impl.db_impl.connection_pool.acquire() as conn:
        still_missing = await conn.fetchval(
            "SELECT count(*) FROM graph WHERE space_id = $1 AND graph_uri = $2",
            reg_space, str(g))
    assert still_missing == 0, "the check repaired instead of reporting"


async def test_a_space_without_a_quad_table_is_not_a_finding(space_impl):
    """A space mid-creation must not read as a defect."""
    job = _job(space_impl)
    assert await job._run_graph_registration_check(["nosuchspace_zzz"]) is None

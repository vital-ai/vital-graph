"""`prop_sort_coverage` must actually be written.

The table was created alongside `entity_prop_sort` and then nothing ever
recorded into it. That is worse than not having it: diagnosing a slow listing in
production, an operator found it empty and reasonably read that as "coverage was
never established" — when in truth no code path had ever written a number. An
empty table that looks like a signal costs more than an absent one.

These assert the LIFECYCLE, not just the insert: a complete type records
`complete=true` and RELEASES its block, a short one records `complete=false` and
TAKES one. Splitting measurement from gating is what produced every
marker-lifecycle bug in `issues/161`.
"""

from __future__ import annotations

import pytest

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

KG = "http://vital.ai/ontology/haley-ai-kg#"
CORE = "http://vital.ai/ontology/vital-core#"
EX = "http://example.org/cov2/"
GRAPH = "http://example.org/cov2/graph"
ETYPE = f"{EX}CoveredType"


def _quads():
    from rdflib import URIRef, Literal
    g = URIRef(GRAPH)
    out = []
    for n in ("a", "b", "c"):
        e = URIRef(f"{EX}{n}")
        out += [
            (e, URIRef(f"{CORE}vitaltype"), URIRef(f"{KG}KGEntity"), g),
            (e, URIRef(f"{KG}hasKGEntityType"), URIRef(ETYPE), g),
            (e, URIRef(f"{CORE}hasName"), Literal(n), g),
        ]
    return out


async def _marker(pg_pool, space):
    async with pg_pool.acquire() as conn:
        return await conn.fetch(
            "SELECT entity_type_uuid, entities_in_table, entities_of_type, complete"
            "  FROM prop_sort_coverage WHERE space_id = $1", space)


async def test_a_complete_type_is_recorded_and_unblocked(
        test_space, space_impl, pg_pool):
    from vitalgraph.db.sparql_sql.fast_prop_sort import record_prop_sort_coverage
    from vitalgraph.db.sparql_sql.sync_entity_prop_sort import entity_prop_sort_coverage

    await space_impl.add_rdf_quads_batch(test_space, _quads())

    async with pg_pool.acquire() as conn:
        covs = await entity_prop_sort_coverage(conn, test_space, limit=50,
                                               only_gaps=False)
        assert covs, "the all-types probe reported nothing to record"
        for cov in covs:
            await record_prop_sort_coverage(
                conn, test_space, cov["entity_type_uuid"],
                cov["in_table"], cov["of_type"])

    rows = await _marker(pg_pool, test_space)
    assert rows, (
        "nothing was recorded — this is the exact state production was found "
        "in, where an empty table read as a missing signal")
    assert all(r["complete"] for r in rows), f"expected all complete: {rows}"

    async with pg_pool.acquire() as conn:
        blocked = await conn.fetch(
            "SELECT 1 FROM prop_sort_block WHERE space_id = $1", test_space)
    assert not blocked, "a complete type left a block behind"


async def test_a_short_type_records_incomplete_and_takes_a_block(
        test_space, space_impl, pg_pool):
    """The direction that matters: short must gate, not just report."""
    from vitalgraph.db.sparql_sql.fast_prop_sort import record_prop_sort_coverage

    await space_impl.add_rdf_quads_batch(test_space, _quads())
    from vitalgraph.db.sparql_sql.sync_entity_prop_sort import _u

    ty = _u(ETYPE)
    async with pg_pool.acquire() as conn:
        await record_prop_sort_coverage(conn, test_space, ty, 1, 3)
    try:
        rows = [r for r in await _marker(pg_pool, test_space)
                if r["entity_type_uuid"] == ty]
        assert rows and rows[0]["complete"] is False, f"not recorded short: {rows}"

        async with pg_pool.acquire() as conn:
            blocked = await conn.fetchrow(
                "SELECT reason FROM prop_sort_block WHERE space_id = $1"
                "  AND entity_type_uuid = $2", test_space, ty)
        assert blocked is not None, (
            "a short type did not take a block — it would keep being served "
            "from a table known to be missing rows")
        assert "1/3" in blocked["reason"], blocked["reason"]

        # And recording it complete again must RELEASE it.
        async with pg_pool.acquire() as conn:
            await record_prop_sort_coverage(conn, test_space, ty, 3, 3)
            still = await conn.fetchrow(
                "SELECT 1 FROM prop_sort_block WHERE space_id = $1"
                "  AND entity_type_uuid = $2", test_space, ty)
        assert still is None, "converging did not clear the block"
    finally:
        async with pg_pool.acquire() as conn:
            await conn.execute("DELETE FROM prop_sort_block WHERE space_id = $1",
                               test_space)
            await conn.execute("DELETE FROM prop_sort_coverage WHERE space_id = $1",
                               test_space)


def test_the_maintenance_job_actually_calls_the_recorder():
    """A recorder nothing calls is the bug this file exists for."""
    import inspect
    from vitalgraph.process import maintenance_job as m

    src = inspect.getsource(m)
    assert "_run_prop_sort_coverage" in src, "no prop-sort coverage phase exists"
    assert '("prop_sort_coverage", self._run_prop_sort_coverage)' in src, (
        "the phase exists but is not registered in the maintenance cycle, so it "
        "never runs — which is how the table came to be empty in the first place")
    assert "record_prop_sort_coverage" in src, (
        "the phase does not call the recorder")

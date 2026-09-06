"""A load run must leave the dataset as it found it, provably.

`issues/171` Part 3. The concurrent load test writes into a 53M-quad space, so
cleanup has to be (a) proportional to what the run wrote, not to the space, and
(b) VERIFIED rather than assumed.

Verified is the load-bearing word. A cleanup that removes the quads and strands
rows in `entity_slot_sort` looks identical to a correct one from the outside:
the next run still passes, the space slowly fills with orphans, and the first
symptom is a coverage shortfall attributed to something else entirely.

These tests use a small space. What they pin is the CONTRACT — write into a
dedicated graph, remove by context, compare against the snapshot — which is what
makes the same code safe on the large one.
"""
# pyright: reportArgumentType=false

from __future__ import annotations

import uuid

import pytest

from tests.load.run_scoped_data import (
    RunScope, cleanup, resolve_context, snapshot, verify_clean)

pytestmark = pytest.mark.asyncio(loop_scope="session")

_VITALTYPE = "http://vital.ai/ontology/vital-core#vitaltype"


async def _write_run_data(conn, space_id, scope, n=25):
    """Quads in the run's own graph, as a load run would write them."""
    g = uuid.uuid4()
    await conn.execute(
        f"INSERT INTO {space_id}_term (term_uuid, term_text, term_type) "
        f"VALUES ($1,$2,'U') ON CONFLICT (term_uuid) DO NOTHING",
        g, scope.graph_uri)
    pred, typ = uuid.uuid4(), uuid.uuid4()
    for tid, text in ((pred, _VITALTYPE), (typ, f"urn:loadtest:{scope.run_id}")):
        await conn.execute(
            f"INSERT INTO {space_id}_term (term_uuid, term_text, term_type) "
            f"VALUES ($1,$2,'U') ON CONFLICT (term_uuid) DO NOTHING", tid, text)
    await conn.executemany(
        f"INSERT INTO {space_id}_rdf_quad (subject_uuid, predicate_uuid,"
        f" object_uuid, context_uuid) VALUES ($1,$2,$3,$4) "
        f"ON CONFLICT DO NOTHING",
        [(uuid.uuid4(), pred, typ, g) for _ in range(n)])
    return g


async def test_cleanup_removes_everything_the_run_wrote(pg_conn, test_space):
    sp = test_space
    scope = RunScope.new(sp)
    await snapshot(pg_conn, scope)

    await _write_run_data(pg_conn, sp, scope, n=25)
    assert await resolve_context(pg_conn, scope) is not None

    await cleanup(pg_conn, scope)

    findings = await verify_clean(pg_conn, scope)
    assert findings == [], f"cleanup left residue: {findings}"


async def test_verification_reports_residue_rather_than_passing(
        pg_conn, test_space):
    """The test that makes the other one worth having.

    If `verify_clean` cannot detect a partial cleanup it is decoration, and
    every future run would report success while the space accumulated orphans.
    Here the quads are removed by hand and the graph row left behind — the
    cleanup is deliberately NOT called.
    """
    sp = test_space
    scope = RunScope.new(sp)
    await snapshot(pg_conn, scope)
    await _write_run_data(pg_conn, sp, scope, n=25)

    findings = await verify_clean(pg_conn, scope)

    assert findings, (
        "verify_clean passed with 25 un-removed quads still in the run's "
        "graph — it cannot detect a partial cleanup and is worthless")
    assert any("still in the run" in f or "quads" in f for f in findings)

    await cleanup(pg_conn, scope)          # leave the space as found
    assert await verify_clean(pg_conn, scope) == []


async def test_cleanup_is_scoped_to_the_run(pg_conn, test_space):
    """Data outside the run's graph must survive it.

    The whole design rests on removal being bounded by context. A cleanup that
    over-reaches on a 53M-quad shared dataset is far worse than one that
    under-reaches.
    """
    sp = test_space
    other_ctx = uuid.uuid4()
    await pg_conn.execute(
        f"INSERT INTO {sp}_rdf_quad (subject_uuid, predicate_uuid,"
        f" object_uuid, context_uuid) VALUES ($1,$2,$3,$4) "
        f"ON CONFLICT DO NOTHING",
        uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), other_ctx)
    before_other = await pg_conn.fetchval(
        f"SELECT count(*) FROM {sp}_rdf_quad WHERE context_uuid = $1", other_ctx)

    scope = RunScope.new(sp)
    await snapshot(pg_conn, scope)
    await _write_run_data(pg_conn, sp, scope, n=10)
    await cleanup(pg_conn, scope)

    after_other = await pg_conn.fetchval(
        f"SELECT count(*) FROM {sp}_rdf_quad WHERE context_uuid = $1", other_ctx)
    assert after_other == before_other == 1, (
        "cleanup removed quads outside the run's graph")

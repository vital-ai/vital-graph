"""Integration: a bulk import that does not finish must not leave a space unindexed.

`issues/156`. `import_ntriples_bulk` drops the space's term and quad secondary
indexes before COPY. It recreated them only on the success path, from a list held
in its own memory, so a CANCEL (which returned early), an exception, or a killed
process left the space on primary keys only — correct answers, every query a
scan, nothing reporting it. Measured on a 50.3M-quad space: an exact term lookup
2,110 ms, an entity query timing out.

Covered here: the cancel path and the exception path restore every index; the
schema-based restore puts back indexes the process never saw; and the
maintenance check reports a space left without them (the kill -9 case, which no
`finally` can reach).
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

NT = "\n".join(
    f"<urn:t156:s{i}> <urn:t156:p> \"value {i}\" ." for i in range(50)) + "\n"


async def _complete(conn, space_id) -> set:
    """The space's secondary indexes, after asserting none is missing.

    Without this, a test running after one that stripped the shared fixture
    space compares an empty set with an empty set and passes vacuously — which
    the first version of this file did against the unfixed code.
    """
    from vitalgraph.db.sparql_sql.space_indexes import missing_space_indexes
    assert await missing_space_indexes(conn, space_id, [
        f"{space_id}_term", f"{space_id}_rdf_quad"]) == [], (
        "the fixture space is already missing indexes; this test would prove nothing")
    names = await _index_names(conn, space_id)
    assert names
    return names


async def _index_names(conn, space_id) -> set:
    return {r["indexname"] for r in await conn.fetch(
        "SELECT indexname FROM pg_indexes WHERE tablename = ANY($1::text[]) "
        "AND indexname NOT LIKE '%_pkey'",
        [f"{space_id}_term", f"{space_id}_rdf_quad"])}


@pytest.fixture
def nt_file(tmp_path):
    p = tmp_path / "t156.nt"
    p.write_text(NT)
    return str(p)


async def test_a_cancelled_bulk_import_restores_every_index(
        test_space, pg_pool, pg_conn, nt_file):
    from vitalgraph.endpoint.impl.data_import_impl import ImportEngine
    before = await _complete(pg_conn, test_space)

    cancel = asyncio.Event()
    cancel.set()                       # cancelled before the first COPY
    result = await ImportEngine(pg_pool).import_ntriples_bulk(
        test_space, "urn:t156:g", nt_file, force=True, cancel_event=cancel)

    assert result.get("cancelled") is True
    after = await _index_names(pg_conn, test_space)
    assert after == before, (
        f"a cancelled import left {sorted(before - after)} dropped — the cancel "
        f"path returned past the recreate (issues/156)")


async def test_a_failed_bulk_import_restores_every_index(
        test_space, pg_pool, pg_conn, nt_file, monkeypatch):
    from vitalgraph.endpoint.impl.data_import_impl import ImportEngine
    before = await _complete(pg_conn, test_space)
    engine = ImportEngine(pg_pool)

    def boom(*_a, **_k):
        raise RuntimeError("simulated failure mid-import")
    monkeypatch.setattr(engine, "_parse_ntriples_terms", boom)

    with pytest.raises(RuntimeError, match="simulated failure"):
        await engine.import_ntriples_bulk(test_space, "urn:t156:g", nt_file, force=True)
    assert await _index_names(pg_conn, test_space) == before


async def test_the_schema_restore_needs_no_memory_of_what_was_dropped(
        test_space, pg_conn):
    """The kill -9 case: the dropping process is gone, so restore from the
    schema. Rerunning the import is then self-healing."""
    from vitalgraph.db.sparql_sql.space_indexes import (
        missing_space_indexes, restore_space_indexes)
    before = await _complete(pg_conn, test_space)
    victims = sorted(n for n in before if n.startswith(f"idx_{test_space}"))[:3] \
        or sorted(before)[:3]
    for name in victims:
        await pg_conn.execute(f"DROP INDEX {name}")

    missing = {n for n, _ in await missing_space_indexes(pg_conn, test_space)}
    assert set(victims) <= missing, "the check did not see the dropped indexes"

    created = await restore_space_indexes(pg_conn, test_space)
    assert set(victims) <= set(created)
    assert await missing_space_indexes(pg_conn, test_space) == []
    assert await _index_names(pg_conn, test_space) == before


async def test_maintenance_reports_a_space_missing_indexes(
        test_space, pg_pool, pg_conn, caplog):
    from vitalgraph.process import maintenance_job as M
    victim = sorted(await _index_names(pg_conn, test_space))[0]
    await pg_conn.execute(f"DROP INDEX {victim}")
    try:
        M.reset_watch_schedule()
        with caplog.at_level(logging.WARNING, logger="vitalgraph.process.maintenance_job"):
            result = await M.MaintenanceJob(pg_pool)._run_space_index_check([test_space])
        assert result and victim in result["spaces"][test_space]
        msg = " ".join(r.getMessage() for r in caplog.records)
        assert "MISSING" in msg and "ensure_space_indexes.py" in msg
    finally:
        from vitalgraph.db.sparql_sql.space_indexes import restore_space_indexes
        await restore_space_indexes(pg_conn, test_space)

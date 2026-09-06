"""A restore must not leave a marker vouching for the PREVIOUS contents.

`issues/168`. `import_space` TRUNCATEs and re-COPYs the core tables, so it is
designed to restore OVER an existing space. It rebuilt a HAND-PICKED list of
derived tables — edge, frame_entity, stats — and that list went stale when
`entity_slot_sort` was added: the slot-sort table was never rebuilt and
`slot_sort_coverage` was never cleared.

The consequence is a wrong answer, not a slow one. After a restore the quads
hold the NEW contents, the slot-sort table holds rows derived from the OLD ones,
and the marker still says complete — so `fast_slot_filter` serves a confident,
plausible result computed from data that is no longer there.

ASSERTED ON THE MARKER, not on query results. The wrong answer here is
plausible: a result-shaped assertion can pass by coincidence when the two
datasets happen to overlap, and the marker is the thing that decides whether the
stale table is trusted at all.

The same function already had this omission once — `graph_registry` records it
copying a whole space in and registering no graphs (`issues/116`). The fix is
structural (delegate to `resync_all_auxiliary_tables`), so the test covers the
PROPERTY "no derived artefact vouches for the previous contents" rather than
enumerating tables, which is what went stale before.
"""
# pyright: reportArgumentType=false

from __future__ import annotations

import uuid

import pytest

from vitalgraph.db.sparql_sql.fast_slot_filter import record_slot_sort_coverage

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _marker_rows(conn, space_id):
    return await conn.fetch(
        "SELECT entity_type_uuid, complete FROM slot_sort_coverage "
        " WHERE space_id = $1", space_id)


async def test_a_restore_does_not_leave_a_stale_complete_marker(
        pg_conn, test_space, tmp_path):
    """The bug: restore over a space with a complete marker, marker survives."""
    from vitalgraph.db.sparql_sql.bulk_export import export_space, import_space

    sp = test_space
    # A marker asserting a type is fully covered, as any served space would have.
    stale_type = uuid.uuid4()
    await record_slot_sort_coverage(pg_conn, sp, stale_type, 500, 500)
    before = await _marker_rows(pg_conn, sp)
    assert any(r["complete"] for r in before), "precondition: a complete marker"

    paths = await export_space(pg_conn, sp, str(tmp_path))
    await import_space(pg_conn, sp, paths)

    after = await _marker_rows(pg_conn, sp)
    stale = [r for r in after
             if r["entity_type_uuid"] == stale_type and r["complete"]]
    assert not stale, (
        "the restore left a marker asserting the PREVIOUS contents were fully "
        "covered — fast_slot_filter will serve rows for entities that no "
        "longer exist")


async def test_resync_false_clears_the_marker_rather_than_leaving_it(
        pg_conn, test_space, tmp_path):
    """Opting out of the rebuild is opting into an incomplete derived set.

    It must not also opt into a marker that keeps vouching for it — that is the
    combination that serves stale rows with no error.
    """
    from vitalgraph.db.sparql_sql.bulk_export import export_space, import_space

    sp = test_space
    stale_type = uuid.uuid4()
    await record_slot_sort_coverage(pg_conn, sp, stale_type, 500, 500)

    paths = await export_space(pg_conn, sp, str(tmp_path))
    await import_space(pg_conn, sp, paths, resync=False)

    after = await _marker_rows(pg_conn, sp)
    assert not [r for r in after if r["complete"]], (
        "resync=False left a complete marker over derived tables that describe "
        "the previous contents")

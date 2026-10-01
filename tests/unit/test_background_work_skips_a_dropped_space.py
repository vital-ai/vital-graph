"""Background work must not run against a space that has gone (`issues/253`).

A periodic probe or a scheduled task picks a space id, the space is dropped a
moment later, and the work then runs against a schema that is not there — logging
`relation "..." does not exist` once per table, per space, per cycle. PostgreSQL
records every failed statement server-side even though the client swallows it, so
the cost lands in the database log too.

Found during a routine API-suite teardown, which produced exactly that from
`maintenance_job`'s referential sweep and the server-property backfill.
`vectorization.auto_sync` had asked the same question privately since before this
issue; there is now one implementation and three callers.
"""
import pytest

from vitalgraph.db.sparql_sql.space_presence import space_tables_present


class FakeConn:
    def __init__(self, present=True, boom=False):
        self.present = present
        self.boom = boom
        self.asked = []

    async def fetchval(self, sql, *args):
        if self.boom:
            raise RuntimeError("connection gone")
        self.asked.append(args[0] if args else None)
        return self.present


class TestTheCheck:
    @pytest.mark.asyncio
    async def test_a_live_space_is_present(self):
        conn = FakeConn(present=True)
        assert await space_tables_present(conn, "sp") is True
        # Asks about the QUAD TABLE, not the `space` catalogue row: the work is
        # on the tables, and the two halves can be dropped independently from a
        # caller's point of view.
        assert conn.asked == ["sp_rdf_quad"]

    @pytest.mark.asyncio
    async def test_a_dropped_space_is_absent(self):
        assert await space_tables_present(FakeConn(present=False), "sp") is False

    @pytest.mark.asyncio
    async def test_a_broken_connection_does_not_masquerade_as_absent(self):
        # "I could not check" is not "it is gone". Answering False would make a
        # connection blip look like a deletion and silently skip real work.
        assert await space_tables_present(FakeConn(boom=True), "sp") is True


class TestTheCallersUseIt:
    def test_all_three_background_paths_check_before_working(self):
        import inspect

        from vitalgraph.process import maintenance_job
        from vitalgraph.tasks import backfill_server_properties_task
        from vitalgraph.vectorization import auto_sync

        for mod in (maintenance_job, backfill_server_properties_task, auto_sync):
            src = inspect.getsource(mod)
            assert "space_tables_present" in src, mod.__name__

    def test_auto_sync_does_not_keep_a_second_implementation(self):
        # It asked first and privately; a second copy is how two callers drift.
        import inspect

        from vitalgraph.vectorization import auto_sync

        src = inspect.getsource(auto_sync)
        assert "to_regclass" not in src

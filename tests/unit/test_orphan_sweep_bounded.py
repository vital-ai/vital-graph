"""`cleanup_orphan_edges` is bounded on the SCAN, not on the deletions.

`issues/079`. The previous form put `LIMIT` on the rows to delete, which bounds
nothing in the case that actually matters: when there is nothing to delete —
the healthy state, and the common one — PostgreSQL still has to probe every row
to establish that. Measured at 181,212 ms over 4,977,000 rows with zero orphans,
against a 60 s `command_timeout`, so it was cancelled every time and the cleanup
`issues/064` added never ran at all.

It also ran INLINE in the SPARQL UPDATE request path. It does not any more;
`MaintenanceJob` owns it, on a connection that is not answering a user.

These tests are about the CONTRACT — bounded window, rotation, priority signal.
The SQL itself is exercised against a real table in the integration path.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql import sync_edge_table as se


class TestTheSweepSignal:
    """A WHERE-bound delete records that a space needs sweeping, and no more."""

    def setup_method(self):
        se._sweep_pending.clear()

    def test_marking_then_taking_returns_the_space(self):
        se.mark_sweep_needed("sp_a")
        assert se.take_sweep_pending() == {"sp_a"}

    def test_taking_drains(self):
        se.mark_sweep_needed("sp_a")
        se.take_sweep_pending()
        assert se.take_sweep_pending() == set()

    def test_marking_is_idempotent(self):
        """An update storm on one space must not queue it a thousand times."""
        for _ in range(1000):
            se.mark_sweep_needed("sp_a")
        assert se.take_sweep_pending() == {"sp_a"}

    def test_several_spaces_are_kept_apart(self):
        se.mark_sweep_needed("sp_a")
        se.mark_sweep_needed("sp_b")
        assert se.take_sweep_pending() == {"sp_a", "sp_b"}


class TestTheScanIsBounded:
    """The window, not the delete count, is what must be limited."""

    def test_the_scan_bound_exists_and_is_finite(self):
        assert isinstance(se._SWEEP_SCAN_ROWS, int)
        assert 0 < se._SWEEP_SCAN_ROWS <= 1_000_000

    @pytest.mark.asyncio
    async def test_the_window_limit_is_on_the_scan_not_the_delete(self):
        """Pins the shape: LIMIT belongs to the row-selecting subquery.

        Regressing this is silent — the sweep still returns correct results and
        still deletes the right rows. It just takes three minutes instead of
        twelve seconds, and gets cancelled by a timeout that was never meant
        for it.
        """
        seen = {}

        class _Conn:
            async def fetch(self, sql, *args):
                seen["sql"] = sql
                return []

            async def execute(self, sql, *args):
                return "DELETE 0"

        await se.cleanup_orphan_edges(_Conn(), "sp_x", scan_rows=1234)
        sql = seen["sql"]
        assert "LIMIT 1234" in sql, "the scan window is not bounded"
        # The bound must sit with the row source, ahead of the anti-join.
        assert sql.index("LIMIT 1234") > sql.index("NOT EXISTS"), \
            "LIMIT is not inside the window subquery"

    @pytest.mark.asyncio
    async def test_an_empty_window_wraps_the_cursor(self):
        """Reaching the end must restart, or the tail is swept once and never again."""
        class _Conn:
            async def fetch(self, sql, *args):
                return []

            async def execute(self, sql, *args):
                return "DELETE 0"

        se._sweep_cursor["sp_wrap"] = "(999,9)"
        await se.cleanup_orphan_edges(_Conn(), "sp_wrap")
        assert se._sweep_cursor["sp_wrap"] is None, "cursor did not wrap"

    @pytest.mark.asyncio
    async def test_the_cursor_advances_to_the_last_row_seen(self):
        class _Conn:
            async def fetch(self, sql, *args):
                return [{"ctid": "(1,1)", "orphan": False},
                        {"ctid": "(4,7)", "orphan": False}]

            async def execute(self, sql, *args):
                return "DELETE 0"

        se._sweep_cursor.pop("sp_adv", None)
        await se.cleanup_orphan_edges(_Conn(), "sp_adv")
        assert se._sweep_cursor["sp_adv"] == "(4,7)"

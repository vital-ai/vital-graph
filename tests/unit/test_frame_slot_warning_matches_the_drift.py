"""The frame_slot integrity warning names the remedy for the drift it found — issue 268.

Production, 2026-10-12: five warnings in eight hours on the main KG space, every
one a SURPLUS (expected 3,044,768, has 3,044,798), each telling the operator that
"the frame_slot backfill repairs this". A backfill only inserts. The surplus was
also not real: the two counts were two statements, so writes landing during the
expected-count scan were counted by the second `count(*)` alone.
"""

from __future__ import annotations

import asyncio

from vitalgraph.db.sparql_sql import sync_frame_slot_table as fst
from vitalgraph.process.maintenance_job import frame_slot_repair_text


def test_missing_rows_go_to_the_backfill():
    text = frame_slot_repair_text("sp", expected=100, actual=90, orphan_rate=0.0)
    assert "Missing rows" in text and "backfill_frame_slot_table" in text


def test_a_surplus_is_not_sent_to_the_backfill():
    text = frame_slot_repair_text("sp", expected=3_044_768, actual=3_044_798, orphan_rate=0.0)
    assert "Missing rows" not in text
    assert "only inserts" in text and "cleanup_stale_frame_slot" in text


def test_orphans_go_to_the_rebuild():
    text = frame_slot_repair_text("sp", expected=100, actual=100, orphan_rate=0.02)
    assert "migrate_frame_slot_table.py --space sp --apply" in text


class _Conn:
    def __init__(self):
        self.calls = []

    async def fetchrow(self, sql, *args, timeout=None):
        self.calls.append(("fetchrow", timeout))
        return {"expected": 7, "actual": 9}

    async def fetchval(self, sql, *args, timeout=None):
        self.calls.append(("fetchval", timeout))
        return 0


def test_both_counts_come_from_one_statement_with_the_client_timeout():
    conn = _Conn()
    assert asyncio.run(fst.frame_slot_drift(conn, "sp", timeout=12.5)) == (7, 9)
    # one statement is one snapshot; two let concurrent writes skew the pair
    assert conn.calls == [("fetchrow", 12.5)]

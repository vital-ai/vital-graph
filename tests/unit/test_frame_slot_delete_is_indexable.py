"""The `frame_slot` pre-delete filter must stay indexable (`issues/253`).

`issues/238` established the mechanism on this table's twin: a BitmapOr can only
combine INDEXABLE conditions, a subquery arm compiles to a hashed SubPlan which
is not one, and a single unindexable arm forces the whole disjunction to a
SEQUENTIAL SCAN — giving a statement that deletes a handful of rows a cost
proportional to the size of the table. 238 fixed `entity_slot_sort` and left this
one behind; production logs on 2026-09-30 then measured it as 96.6% of the four
pre-delete scans on the write path.

Measured locally on a real 401,543-row `frame_slot` (474,031-row edge table),
realistic 15-subject write, 5 runs, both forms deleting the same 7 rows:

    OLD (subquery arm)   Seq Scan   37.0 / 38.0 / 348.3 ms   11,260 buffers
    eager resolve        Bitmap      0.040 / 0.054 / 0.068 ms   459 buffers
    NEW (two arrays)     Bitmap      0.033 / 0.045 / 4.457 ms   215 buffers

i.e. 384x including the resolve. Equivalence was checked on five input shapes —
frame only, slots only, edges only, a whole write, and unscoped — all agreeing
with the old form, which matters because the indirect arms are the reason the
filter is a disjunction at all.

THE SHAPE IS WHAT REGRESSES, so the shape is what these assert. The two forms
return identical rows, so nothing else in the system would notice the rewrite
being undone.
"""
import uuid

import pytest

from vitalgraph.db.sparql_sql import sync_frame_slot_table as mod
from vitalgraph.db.sparql_sql.sync_frame_slot_table import (
    _edge_source_nodes, sync_frame_slot_before_delete)


class FakeConn:
    """Records what the sync issues, in order."""

    def __init__(self, roots=()):
        self.statements = []
        self.fetches = []
        self._roots = list(roots)

    async def fetchval(self, sql, *args):
        # `_table_present` asks `to_regclass`; say the table exists.
        return "public.some_frame_slot"

    async def fetch(self, sql, *args):
        self.fetches.append((sql, args))
        return [{"source_node_uuid": r} for r in self._roots]

    async def execute(self, sql, *args):
        self.statements.append((sql, args))
        return "DELETE 3"

    def is_in_transaction(self):
        return True

    @property
    def deletes(self):
        return [(s, a) for s, a in self.statements if s.lstrip().startswith("DELETE")]


@pytest.fixture
def space(monkeypatch):
    # A fresh space id per test: `_table_present` memoises per space in a module
    # dict, and a shared id would leak one test's answer into another.
    name = f"sp_{uuid.uuid4().hex[:8]}"
    monkeypatch.setitem(mod._frame_slot_present, name, True)
    return name


SUBJECTS = [uuid.uuid4() for _ in range(4)]
CTX = uuid.uuid4()
ROOT = uuid.uuid4()


class TestTheDeleteFilter:
    @pytest.mark.asyncio
    async def test_it_contains_no_subquery(self, space):
        # The regression guard. One unindexable arm costs a whole table scan.
        conn = FakeConn(roots=[ROOT])
        await sync_frame_slot_before_delete(conn, space, SUBJECTS, context_uuid=CTX)
        sql, _ = conn.deletes[0]
        assert "SELECT" not in sql.upper(), sql

    @pytest.mark.asyncio
    async def test_both_arms_are_array_membership(self, space):
        conn = FakeConn(roots=[ROOT])
        await sync_frame_slot_before_delete(conn, space, SUBJECTS, context_uuid=CTX)
        sql, _ = conn.deletes[0]
        assert sql.count("= ANY(") == 2, sql

    @pytest.mark.asyncio
    async def test_the_roots_are_resolved_before_the_delete(self, space):
        # ORDER IS LOAD-BEARING: the resolve reads the edge rows the DELETE is
        # about to invalidate, so running it afterwards would find nothing and
        # silently stop deleting the indirect rows.
        conn = FakeConn(roots=[ROOT])
        await sync_frame_slot_before_delete(conn, space, SUBJECTS, context_uuid=CTX)
        assert len(conn.fetches) == 1
        resolve_sql = conn.fetches[0][0]
        assert "source_node_uuid" in resolve_sql
        assert conn.deletes, "no DELETE issued"

    @pytest.mark.asyncio
    async def test_the_resolved_roots_are_passed_as_the_second_array(self, space):
        conn = FakeConn(roots=[ROOT])
        await sync_frame_slot_before_delete(conn, space, SUBJECTS, context_uuid=CTX)
        _, args = conn.deletes[0]
        assert list(args[0]) == SUBJECTS
        assert list(args[1]) == [ROOT]
        assert args[2] == CTX

    @pytest.mark.asyncio
    async def test_the_unscoped_form_shifts_the_parameters(self, space):
        conn = FakeConn(roots=[ROOT])
        await sync_frame_slot_before_delete(conn, space, SUBJECTS, context_uuid=None)
        sql, args = conn.deletes[0]
        assert "context_uuid" not in sql
        assert len(args) == 2

    @pytest.mark.asyncio
    async def test_no_indirect_roots_is_an_empty_array_not_a_missing_arm(self, space):
        # `= ANY('{}')` matches nothing, which is the right answer. Dropping the
        # arm instead would change the SQL shape per call and defeat the plan
        # cache reasoning in `_forced`.
        conn = FakeConn(roots=[])
        await sync_frame_slot_before_delete(conn, space, SUBJECTS, context_uuid=CTX)
        sql, args = conn.deletes[0]
        assert sql.count("= ANY(") == 2
        assert list(args[1]) == []

    @pytest.mark.asyncio
    async def test_no_subjects_does_nothing_at_all(self, space):
        conn = FakeConn()
        assert await sync_frame_slot_before_delete(conn, space, [], context_uuid=CTX) == 0
        assert conn.statements == [] and conn.fetches == []


class TestTheEagerResolve:
    @pytest.mark.asyncio
    async def test_it_looks_up_both_indirections_indexably(self, space):
        # dest_node_uuid via idx_{space}_edge_dst_src, edge_uuid via
        # idx_{space}_edge_edge — the two the schema provides.
        conn = FakeConn(roots=[ROOT])
        await _edge_source_nodes(conn, space, SUBJECTS)
        sql, args = conn.fetches[0]
        assert "dest_node_uuid = ANY(" in sql
        assert "edge_uuid = ANY(" in sql
        assert "DISTINCT" in sql.upper()
        assert list(args[0]) == SUBJECTS

    @pytest.mark.asyncio
    async def test_empty_input_makes_no_round_trip(self, space):
        conn = FakeConn()
        assert await _edge_source_nodes(conn, space, []) == []
        assert conn.fetches == []

"""Incremental derived-table syncs probe by the write, not by the space — issues/273.

Profiled on a UW-sized space (200,880 edges), one 7k-quad decision write:

* `frame_slot`'s re-derive picked its frames with `IN (SELECT … FROM edge …)`
  and the planner hash-joined that against a SEQUENTIAL scan of the whole edge
  table: 62-72 ms for 372 rows. Resolving the frames first and probing by
  `= ANY` took it to ~12 ms.
* `entity_slot_sort`'s seeded walk was merge-joined against every slot edge of
  the space (149,251 rows, 128k buffers): 111-150 ms. A LATERAL lookup per walked
  frame took it to ~19-25 ms — but only with `OFFSET 0`, without which the planner
  pulls the subquery up and picks the same merge join.

These pin the shapes; the timings are in the issue.
"""

from __future__ import annotations

import inspect

from vitalgraph.db.sparql_sql import sync_entity_slot_sort as ESS
from vitalgraph.db.sparql_sql import sync_frame_slot_table as FS


def test_the_seeded_walk_looks_up_slot_edges_per_frame():
    sql = ESS._select_rows("sp", "TRUE", seed_param="$9")
    lateral = sql[sql.index("JOIN LATERAL"):]
    assert "OFFSET 0" in lateral[:lateral.index(") slot_e ON TRUE")], (
        "without OFFSET 0 the planner flattens the LATERAL back into a merge join")
    assert "se.edge_uuid" in lateral, "the incremental filter reads slot_e.edge_uuid"


def test_the_full_walk_keeps_the_set_based_join():
    sql = ESS._select_rows("sp", "TRUE")
    assert "JOIN LATERAL" not in sql
    assert "JOIN sp_edge slot_e" in sql


def test_frame_slot_resolves_its_frames_before_the_insert():
    src = inspect.getsource(FS.sync_frame_slot_after_edge_insert)
    assert "_edge_owners(conn, space_id, chunk)" in src
    insert = src[src.index("INSERT INTO"):]
    assert "emv.source_node_uuid = ANY($4::uuid[])" in insert
    assert "IN (" not in insert[:insert.index("ON CONFLICT")], (
        "a subquery here is hash-joined against a scan of the whole edge table")

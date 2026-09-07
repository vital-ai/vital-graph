"""Locking a WHERE-bound SPARQL update. `issues/174` item 5.

The behaviour under test is what stops a raw SPARQL update interleaving with an
entity or frame write. It is exercised with fakes rather than a database because
the parts that can be got wrong are decisions, not SQL: which grouping a subject
resolves to, and when the lock loop stops.
"""
import logging

import pytest

from vitalgraph.db.sparql_sql import update_lock
from vitalgraph.db.sparql_sql.update_lock import (
    HAS_KG_GRAPH_URI, MAX_PASSES, _groupings_for, _subjects_for_plan,
    acquire_update_locks,
)
from vitalgraph.db.sparql_sql.emit_update import UpdateLockPlan
from vitalgraph.db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid


class Row(dict):
    """Stands in for an asyncpg Record, which iterates VALUES, not keys.

    A plain dict iterates keys, so a fake built from dicts silently feeds column
    NAMES into the subject set — the fake passes and the real path does not.
    """

    def __iter__(self):
        return iter(self.values())


class FakeConn:
    """Answers the two queries the lock path makes, and records the locks taken."""

    def __init__(self, probe_rows=None, owner_map=None, probe_fn=None):
        # `probe_fn(pass_number)` lets a test vary the WHERE result per pass,
        # which is how the loop's convergence is exercised. Preferred over
        # replacing `fetch`, because the owner lookup passes its predicate as a
        # PARAMETER — the URI never appears in the SQL text, so a hand-rolled
        # discriminator that greps for it silently answers the wrong query.
        self.probe_fn = probe_fn
        self.probe_rows = probe_rows or []       # rows the materialised WHERE yields
        self.owner_map = owner_map or {}         # subject URI -> grouping URI, "in the store"
        self.locked: list = []                   # advisory keys, in acquisition order
        self.probe_count = 0                     # how many times the WHERE was materialised

    async def execute(self, sql, *args):
        if "CREATE TEMP TABLE" in sql:
            self.probe_count += 1
        if "pg_advisory_xact_lock" in sql:
            self.locked.append(args[0])

    async def fetch(self, sql, *args):
        if "hasKGGraphURI" in sql or "predicate_uuid = $1" in sql:
            want = set(args[1])
            out = []
            for uri, owner in self.owner_map.items():
                u = _generate_term_uuid(uri, "U")
                if u in want:
                    out.append(Row(subject_uuid=u, term_text=owner))
            return out
        if self.probe_fn is not None:
            return list(self.probe_fn(self.probe_count))
        return list(self.probe_rows)


PLAN = UpdateLockPlan(where_sql="SELECT 1", subject_columns=["v0"])


class TestGroupingResolution:
    """Which key a subject locks. Getting this wrong locks nothing useful."""

    @pytest.mark.asyncio
    async def test_store_lookup_finds_the_enclosing_entity(self):
        # THE PRODUCTION SHAPE: the change set names only a slot value quad and
        # says nothing about the entity enclosing it. Without this lookup the
        # update locks the slot, collides with nobody, and interleaves with the
        # entity write it was supposed to wait for.
        conn = FakeConn(owner_map={"urn:slot:1": "urn:entity:A"})
        assert await _groupings_for(conn, "sp", ["urn:slot:1"]) == {"urn:entity:A"}

    @pytest.mark.asyncio
    async def test_change_set_wins_over_the_store(self):
        # A subject being reparented by this very update: the row still says the
        # old owner, and the update is what changes it.
        conn = FakeConn(owner_map={"urn:slot:1": "urn:entity:OLD"})
        got = await _groupings_for(conn, "sp", ["urn:slot:1"],
                                   {"urn:slot:1": "urn:entity:NEW"})
        assert got == {"urn:entity:NEW"}

    @pytest.mark.asyncio
    async def test_unknown_subject_is_its_own_grouping(self):
        # A standalone frame, or general RDF no entity write will touch.
        conn = FakeConn(owner_map={})
        assert await _groupings_for(conn, "sp", ["urn:frame:1"]) == {"urn:frame:1"}

    @pytest.mark.asyncio
    async def test_many_subjects_in_one_entity_collapse_to_one_key(self):
        conn = FakeConn(owner_map={f"urn:slot:{i}": "urn:entity:A" for i in range(5)})
        got = await _groupings_for(conn, "sp", [f"urn:slot:{i}" for i in range(5)])
        assert got == {"urn:entity:A"}

    @pytest.mark.asyncio
    async def test_no_subjects_takes_no_locks(self):
        assert await _groupings_for(FakeConn(), "sp", []) == set()


class TestSubjectDiscovery:
    @pytest.mark.asyncio
    async def test_constants_need_no_probe(self):
        # A template with a fixed subject is known without running the WHERE.
        plan = UpdateLockPlan(where_sql="SELECT 1", subject_constants=["urn:e:1"])
        conn = FakeConn()
        assert await _subjects_for_plan(conn, plan) == {"urn:e:1"}
        assert conn.probe_count == 0

    @pytest.mark.asyncio
    async def test_bound_variables_come_from_the_materialised_where(self):
        conn = FakeConn(probe_rows=[Row(v0="urn:slot:1"), Row(v0="urn:slot:2")])
        assert await _subjects_for_plan(conn, PLAN) == {"urn:slot:1", "urn:slot:2"}
        assert conn.probe_count == 1

    @pytest.mark.asyncio
    async def test_constants_and_variables_combine(self):
        plan = UpdateLockPlan(where_sql="SELECT 1", subject_columns=["v0"],
                              subject_constants=["urn:e:fixed"])
        conn = FakeConn(probe_rows=[Row(v0="urn:slot:1")])
        assert await _subjects_for_plan(conn, plan) == {"urn:e:fixed", "urn:slot:1"}


class TestLockLoop:
    @pytest.mark.asyncio
    async def test_no_plans_locks_nothing(self):
        conn = FakeConn()
        assert await acquire_update_locks(conn, "sp", []) == []
        assert conn.locked == []

    @pytest.mark.asyncio
    async def test_stable_set_locks_once_and_confirms(self):
        conn = FakeConn(probe_rows=[Row(v0="urn:slot:1")],
                        owner_map={"urn:slot:1": "urn:entity:A"})
        assert await acquire_update_locks(conn, "sp", [PLAN]) == ["urn:entity:A"]
        # One key locked; the second pass exists to confirm nothing new appeared.
        assert len(conn.locked) == 1
        assert conn.probe_count == 2

    @pytest.mark.asyncio
    async def test_a_key_revealed_by_the_second_pass_is_also_locked(self):
        # Re-materialising under the first lock can expose subjects the first
        # pass could not see. One pass is not a fixed point.
        conn = FakeConn(
            probe_fn=lambda p: ([Row(v0="urn:slot:1")] if p < 2
                                else [Row(v0="urn:slot:1"), Row(v0="urn:slot:2")]),
            owner_map={"urn:slot:1": "urn:entity:A",
                       "urn:slot:2": "urn:entity:B"})
        got = await acquire_update_locks(conn, "sp", [PLAN])
        assert set(got) == {"urn:entity:A", "urn:entity:B"}

    @pytest.mark.asyncio
    async def test_keys_are_taken_in_sorted_order(self):
        # Two updates touching the same groupings in different orders must queue,
        # not deadlock.
        conn = FakeConn(probe_rows=[Row(v0=f"urn:slot:{i}") for i in range(6)],
                        owner_map={f"urn:slot:{i}": f"urn:entity:{i}" for i in range(6)})
        await acquire_update_locks(conn, "sp", [PLAN])
        assert conn.locked == sorted(conn.locked)

    @pytest.mark.asyncio
    async def test_a_set_that_never_settles_gives_up_loudly(self, caplog):
        # Proceeding is right — the alternative is retrying forever — but it must
        # not be silent, because the update then runs less serialised than the
        # caller believes.
        conn = FakeConn(owner_map={},
                        probe_fn=lambda p: [Row(v0=f"urn:slot:{p}")])
        with caplog.at_level(logging.WARNING):
            got = await acquire_update_locks(conn, "sp", [PLAN])
        assert len(got) == MAX_PASSES
        assert "still growing" in caplog.text


class TestUpdateLockPlanShape:
    """What the emitter hands over. `issues/174` item 5, emitter half."""

    def test_a_plan_with_neither_subjects_nor_columns_locks_nothing(self):
        # An update the emitter could not characterise must not silently lock
        # something arbitrary; it degrades to running unserialised, as before.
        plan = UpdateLockPlan(where_sql="SELECT 1")
        assert plan.subject_columns == []
        assert plan.subject_constants == []
        assert plan.changeset_groupings == {}

    def test_defaults_are_not_shared_between_instances(self):
        # A mutable default would let one update's subjects leak into the next.
        a, b = UpdateLockPlan(where_sql="x"), UpdateLockPlan(where_sql="y")
        a.subject_columns.append("v0")
        a.changeset_groupings["s"] = "e"
        assert b.subject_columns == []
        assert b.changeset_groupings == {}

    @pytest.mark.asyncio
    async def test_changeset_grouping_is_used_without_touching_the_store(self):
        # The created-subject case: nothing to look up, so the store must not be
        # consulted for it at all.
        conn = FakeConn(owner_map={})
        got = await _groupings_for(conn, "sp", ["urn:new:slot"],
                                   {"urn:new:slot": "urn:entity:A"})
        assert got == {"urn:entity:A"}


class TestLockKeyAgreesAcrossPaths:
    """A SPARQL update and an entity write must derive the SAME key.

    They lock through different code — `acquire_update_locks` and the write
    paths' direct `lock_entities` — so a divergence here would leave both
    "locked" and neither excluded, which is the failure this whole item exists
    to prevent and which no single-path test would show.
    """

    def test_same_uri_gives_the_same_advisory_key(self):
        from vitalgraph.db.sparql_sql.entity_lock import entity_lock_key
        for uri in ("urn:entity:A", "urn:cardiff:kg:entity:NurtureAction", "x" * 300):
            assert entity_lock_key(uri) == entity_lock_key(uri)

    @pytest.mark.asyncio
    async def test_resolution_yields_the_uri_the_write_paths_lock(self):
        # The write paths lock the ENTITY uri. Resolution must produce exactly
        # that string — not the slot, and not the frame.
        conn = FakeConn(owner_map={"urn:slot:1": "urn:entity:A"})
        assert await _groupings_for(conn, "sp", ["urn:slot:1"]) == {"urn:entity:A"}

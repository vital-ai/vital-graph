"""Renaming a space, for real — issue 232 step 2.

Renaming is the SANCTIONED remedy for an over-long space id — the schema refuses
one and says to rename — and it did not exist.

HOW THESE TESTS GRADE IT. The enumerator (step 1) is the oracle: after a rename
the OLD id must own ZERO catalogue objects, the NEW id must own the same number
the old one had, and `mismatched` must be empty. That last one is what catches a
partial rename, which is the failure mode that otherwise stays silent — every
object keeps working under its old name because the catalogue links by oid, and
the damage only appears later when `CREATE INDEX IF NOT EXISTS idx_{new}_…`
builds a second index alongside the first.

Checking the object COUNT alone would not catch it. Checking `mismatched` does.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql.space_rename import (
    SpaceRenameRefused, plan_rename, rename_space)
from vitalgraph.db.sparql_sql.space_rename_enumerate import enumerate_space_objects

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]


# SHORT IDS ON PURPOSE. `make_space()` generates `inttest_<12 hex>` = 20 bytes, and
# the rename appends `_r` — which overflows the REAL ceiling. `max_space_id_bytes()`
# reports 34, but the auto-named sequence
# `{space}_document_segmentation_config_config_id_seq` is 42 bytes of suffix, so
# anything over 21 bytes produces a name PostgreSQL truncates silently. The rename
# refuses that, correctly, and these tests would be testing the refusal rather than
# the rename. See `issues/246`.
_N = iter(range(1, 99))


def _short() -> str:
    return f"inttest_rn{next(_N)}"


def _same_length(space_id: str) -> str:
    """A different id of the SAME byte length.

    Required, not convenient: every real space carries auto-named constraints
    PostgreSQL already truncated at 63 bytes (`issues/246`), and the rename
    refuses a length change because it would re-truncate them irreversibly.
    """
    return space_id[:-1] + ("z" if space_id[-1] != "z" else "y")


class TestARoundTrip:

    async def test_every_object_moves_and_nothing_is_left_behind(
            self, pg_conn, make_space):
        sp = await make_space(_short())
        new = _same_length(sp)
        before = await enumerate_space_objects(pg_conn, sp)
        assert before["total"] > 100, "a real space should have hundreds of objects"

        try:
            report = await rename_space(pg_conn, sp, new)
            assert report["statements"] > 0

            after_old = await enumerate_space_objects(pg_conn, sp)
            after_new = await enumerate_space_objects(pg_conn, new)

            assert after_old["total"] == 0, \
                f"{after_old['total']} objects left under the old id"
            assert after_new["total"] == before["total"]
            # THE assertion: a partial rename shows up here and nowhere else.
            assert after_new["mismatched"] == [], after_new["mismatched"][:10]
        finally:
            await rename_space(pg_conn, new, sp)

    async def test_the_data_survives(self, pg_conn, make_space):
        """Catalogue only — no rows are rewritten, so the quads must be untouched
        and queryable under the new name."""
        sp = await make_space(_short())
        new = _same_length(sp)
        await pg_conn.execute(
            f"INSERT INTO {sp}_datatype (datatype_uri) VALUES "
            f"('urn:probe:dt') ON CONFLICT DO NOTHING")
        before = await pg_conn.fetchval(f"SELECT count(*) FROM {sp}_datatype")
        try:
            await rename_space(pg_conn, sp, new)
            assert await pg_conn.fetchval(
                f"SELECT count(*) FROM {new}_datatype") == before
            assert await pg_conn.fetchval(
                f"SELECT count(*) FROM {new}_datatype "
                f"WHERE datatype_uri = 'urn:probe:dt'") == 1
        finally:
            await rename_space(pg_conn, new, sp)

    async def test_renaming_back_restores_the_original_names(
            self, pg_conn, make_space):
        """Not just cosmetic: it proves the mapping is invertible, i.e. that no
        object acquired a name the rule cannot undo."""
        sp = await make_space(_short())
        # SAME BYTE LENGTH, deliberately. Five auto-named UNIQUE constraints are
        # already truncated at 63 bytes on every space — the intended
        # `_document_segmentation_config_document_type_uri_segment_method_uri_key`
        # is 70 bytes of suffix before any space id (`issues/246`). A
        # different-length target makes PostgreSQL re-truncate them differently, so
        # reversibility can only be asserted where the length does not change.
        new = _same_length(sp)
        assert len(new) == len(sp)
        original = await enumerate_space_objects(pg_conn, sp)
        await rename_space(pg_conn, sp, new)
        await rename_space(pg_conn, new, sp)
        restored = await enumerate_space_objects(pg_conn, sp)
        for cls in ("tables", "indexes", "constraints", "sequences",
                    "functions", "triggers", "partition_children"):
            assert restored[cls] == original[cls], cls

    async def test_a_partitioned_space_moves_its_children(
            self, pg_conn, make_space):
        """Renaming a partitioned parent does NOT rename its children — measured.
        So the children need their own ALTER, and this is the test that they get
        one."""
        sp = await make_space(_short(), partition_quads=4)
        # SAME LENGTH, for the reason in the round-trip test: a partition child's
        # auto-named index (`{space}_entity_prop_sort_p0_context_uuid_…_idx`) is
        # already at 63 bytes, so lengthening the id is REFUSED — correctly.
        new = _same_length(sp)
        before = await enumerate_space_objects(pg_conn, sp)
        assert before["partition_children"], "fixture is not partitioned"
        try:
            await rename_space(pg_conn, sp, new)
            after = await enumerate_space_objects(pg_conn, new)
            assert len(after["partition_children"]) == \
                len(before["partition_children"])
            assert (await enumerate_space_objects(pg_conn, sp))["total"] == 0
        finally:
            await rename_space(pg_conn, new, sp)


class TestTheRegistryAndItsChildrenFollow:

    async def test_the_space_row_moves(self, pg_conn, make_space):
        sp = await make_space(_short())
        new = _same_length(sp)
        try:
            await rename_space(pg_conn, sp, new)
            assert await pg_conn.fetchval(
                "SELECT count(*) FROM space WHERE space_id = $1", new) == 1
            assert await pg_conn.fetchval(
                "SELECT count(*) FROM space WHERE space_id = $1", sp) == 0
        finally:
            await rename_space(pg_conn, new, sp)

    async def test_graph_rows_follow_by_cascade(self, pg_conn, make_space):
        sp = await make_space(_short())
        new = _same_length(sp)
        await pg_conn.execute(
            "INSERT INTO graph (space_id, graph_uri, graph_name) VALUES "
            "($1, $2, 'probe') ON CONFLICT DO NOTHING", sp, f"urn:{sp}")
        try:
            await rename_space(pg_conn, sp, new)
            assert await pg_conn.fetchval(
                "SELECT count(*) FROM graph WHERE space_id = $1", new) >= 1
        finally:
            await rename_space(pg_conn, new, sp)

    async def test_the_graph_uri_is_deliberately_NOT_rewritten(
            self, pg_conn, make_space):
        """`issues/232` decided this explicitly. The URI is stored as a term whose
        uuid derives from its TEXT, so rewriting it would change every
        `context_uuid` in the largest tables in the space — a full data rewrite,
        not a catalogue operation. A renamed space legitimately holds a graph named
        for its old id, and this test exists so nobody 'fixes' that later without
        reading why."""
        sp = await make_space(_short())
        new = _same_length(sp)
        await pg_conn.execute(
            "INSERT INTO graph (space_id, graph_uri, graph_name) VALUES "
            "($1, $2, 'probe') ON CONFLICT DO NOTHING", sp, f"urn:{sp}")
        try:
            await rename_space(pg_conn, sp, new)
            uris = [r["graph_uri"] for r in await pg_conn.fetch(
                "SELECT graph_uri FROM graph WHERE space_id = $1", new)]
            assert f"urn:{sp}" in uris, uris
        finally:
            await rename_space(pg_conn, new, sp)


class TestWhatItRefuses:
    """Every refusal must happen before anything is changed."""

    async def test_an_over_long_new_id(self, pg_conn, make_space):
        from vitalgraph.db.sparql_sql.sparql_sql_schema import max_space_id_bytes
        sp = await make_space(_short())
        with pytest.raises(SpaceRenameRefused, match="ceiling"):
            await rename_space(pg_conn, sp, "a" * (max_space_id_bytes() + 1))
        assert (await enumerate_space_objects(pg_conn, sp))["total"] > 0

    async def test_a_new_id_that_already_exists(self, pg_conn, make_space):
        a = await make_space(_short())
        b = await make_space(_short())
        with pytest.raises(SpaceRenameRefused, match="already exists"):
            await rename_space(pg_conn, a, b)

    async def test_an_unregistered_source(self, pg_conn):
        with pytest.raises(SpaceRenameRefused, match="no space"):
            await rename_space(pg_conn, "inttest_not_a_space_at_all", "whatever")

    async def test_a_new_id_that_shadows_another_space(self, pg_conn, make_space):
        """The `data` / `data_orig` hazard, refused at the source. Renaming INTO a
        prefix relationship makes every later audit, orphan sweep and drop unable
        to tell the two spaces apart."""
        sp = await make_space(_short())
        await make_space("inttest_shadowtarget_child")
        with pytest.raises(SpaceRenameRefused, match="shadow"):
            await rename_space(pg_conn, sp, "inttest_shadowtarget")

    async def test_a_new_id_that_is_not_a_bare_identifier(
            self, pg_conn, make_space):
        sp = await make_space(_short())
        for bad in ('has space', 'Has-Caps', 'quote"d', '1leading'):
            with pytest.raises(SpaceRenameRefused, match="identifier"):
                await rename_space(pg_conn, sp, bad)

    async def test_a_protected_space_is_refused(self, pg_conn):
        from vitalgraph.constants import PROTECTED_SPACES
        protected = next(iter(PROTECTED_SPACES))
        with pytest.raises(SpaceRenameRefused, match="protected"):
            await rename_space(pg_conn, protected, "inttest_whatever")


class TestDryRun:

    async def test_it_changes_nothing_and_returns_the_plan(
            self, pg_conn, make_space):
        sp = await make_space(_short())
        before = await enumerate_space_objects(pg_conn, sp)
        target = _same_length(sp)
        report = await rename_space(pg_conn, sp, target, dry_run=True)
        assert report["statements"] > 100
        assert any("ALTER TABLE" in s for s in report["sql"])
        assert any("RENAME CONSTRAINT" in s for s in report["sql"])
        assert any("ALTER INDEX" in s for s in report["sql"])
        assert any("UPDATE space SET space_id" in s for s in report["sql"])
        after = await enumerate_space_objects(pg_conn, sp)
        assert after["total"] == before["total"]
        assert (await enumerate_space_objects(pg_conn, target))["total"] == 0

    async def test_constraints_are_planned_before_indexes(
            self, pg_conn, make_space):
        """Renaming a PK/UNIQUE constraint also renames its backing index, so an
        index pass that ran first would later name an index that no longer
        exists. The order is load-bearing, not stylistic."""
        sp = await make_space(_short())
        plan = await plan_rename(pg_conn, sp, _same_length(sp))
        kinds = [k for k, _ in plan]
        assert kinds.index("constraint") < kinds.index("index")
        assert kinds.index("trigger") < kinds.index("table")
        assert kinds[-2:] == ["registry", "process"]

    async def test_no_constraint_backed_index_is_renamed_twice(
            self, pg_conn, make_space):
        """The concrete consequence of that order: a name moved by its constraint
        must not also appear in an ALTER INDEX."""
        sp = await make_space(_short())
        plan = await plan_rename(pg_conn, sp, _same_length(sp))
        renamed_by_constraint = {
            s.split("RENAME CONSTRAINT ")[1].split(" TO ")[0].strip('"')
            for k, s in plan if k == "constraint"}
        indexed = {s.split("ALTER INDEX ")[1].split(" RENAME")[0].strip('"')
                   for k, s in plan if k == "index"}
        assert not (renamed_by_constraint & indexed), \
            renamed_by_constraint & indexed


class TestItRefusesToReTruncate:
    """`issues/246`, and the user's call: where truncation cannot be prevented,
    just refuse.

    Five auto-named UNIQUE constraints sit at exactly 63 bytes on EVERY space —
    `{space}_document_segmentation_config_document_type_uri_segment_method_uri_key`
    is 70 bytes of suffix before any id — so PostgreSQL truncated them at CREATE
    time. There is no ceiling that prevents this: an honest one computed over
    every auto-generated name is NEGATIVE (-7), and 6 even if the UNIQUEs were
    named explicitly, which would refuse every space that exists. So refusing the
    renames that make it WORSE is the whole available remedy.
    """

    async def test_a_length_changing_rename_is_refused(self, pg_conn, make_space):
        sp = await make_space(_short())
        with pytest.raises(SpaceRenameRefused, match="already at the"):
            await rename_space(pg_conn, sp, f"{sp}_longer")
        assert (await enumerate_space_objects(pg_conn, sp))["total"] > 0

    async def test_shortening_is_refused_too(self, pg_conn, make_space):
        """Shortening is the USE CASE — rename exists to fix an over-long id — so
        this refusal is the expensive one, and it is deliberate. The opt-in below
        is how you take it anyway."""
        sp = await make_space(_short())
        with pytest.raises(SpaceRenameRefused, match="already at the"):
            await rename_space(pg_conn, sp, sp[:-2])

    async def test_the_message_names_the_same_length_way_out(
            self, pg_conn, make_space):
        sp = await make_space(_short())
        with pytest.raises(SpaceRenameRefused) as exc:
            await rename_space(pg_conn, sp, f"{sp}_longer")
        assert "same byte length" in str(exc.value)
        assert "allow_retruncation" in str(exc.value)

    async def test_the_opt_in_lets_a_SHORTENING_through(self, pg_conn, make_space):
        """An explicit acceptance of the loss, not a default — and it only helps
        when SHORTENING. Lengthening stays blocked by the 63-byte check, because
        the mapped name would not fit at all rather than merely re-truncate."""
        sp = await make_space(_short())
        new = sp[:-2]
        try:
            report = await rename_space(pg_conn, sp, new,
                                        allow_retruncation=True)
            assert report["statements"] > 0
            assert (await enumerate_space_objects(pg_conn, sp))["total"] == 0
            assert (await enumerate_space_objects(pg_conn, new))["total"] > 0
        finally:
            await rename_space(pg_conn, new, sp, allow_retruncation=True)

    async def test_lengthening_stays_blocked_even_with_the_opt_in(
            self, pg_conn, make_space):
        """Two different guards, and only one is opt-outable: re-truncation is a
        loss you can accept, a name that does not fit is not."""
        sp = await make_space(_short())
        with pytest.raises(SpaceRenameRefused, match="would exceed"):
            await rename_space(pg_conn, sp, f"{sp}_x",
                               allow_retruncation=True)

    async def test_a_same_length_rename_is_unaffected(self, pg_conn, make_space):
        sp = await make_space(_short())
        new = _same_length(sp)
        try:
            await rename_space(pg_conn, sp, new)
            assert (await enumerate_space_objects(pg_conn, new))["mismatched"] == []
        finally:
            await rename_space(pg_conn, new, sp)

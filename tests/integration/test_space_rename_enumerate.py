"""Enumerating what names a space — issue 232 step 1.

A rename must cover four object classes, not one. `ALTER TABLE … RENAME TO`
renames the table and nothing it owns, and everything keeps WORKING because the
catalogue links by oid — so the names silently stop describing reality, and the
next `CREATE INDEX IF NOT EXISTS idx_{new}_…` finds nothing by that name and
builds a SECOND index alongside the old one.

So this enumerator is the audit that has to be right before anything writes.

TWO PROPERTIES CARRY THE WEIGHT
-------------------------------
**Prefix shadowing.** `data` is a prefix of `data_orig`, and renaming `data` to
`data_orig` is the issue's own example — so a rename of the shorter id must never
claim the longer one's objects. This is the failure that would DROP or rename
another space's tables, so it is tested from both directions.

**Completeness.** Anything the enumerator misses is an object a rename leaves
behind under the old name. There is no list to check against — the whole point is
that it is derived from the catalogue — so the tests assert the classes are all
non-empty on a real space and that a deliberately half-renamed space is detected.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql.space_rename_enumerate import (
    enumerate_space_objects, format_enumeration)

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

_CLASSES = ("tables", "indexes", "constraints", "sequences")


class TestItFindsEveryClass:

    async def test_a_real_space_has_objects_in_every_class(
            self, pg_conn, make_space):
        """Any class reading zero is a class a rename would silently skip."""
        sp = await make_space()
        r = await enumerate_space_objects(pg_conn, sp)
        for cls in _CLASSES:
            assert r[cls], f"{cls} came back empty"
        assert r["total"] == sum(
            len(r[k]) for k in ("tables", "partition_children", "indexes",
                                "constraints", "sequences", "functions",
                                "triggers"))

    async def test_the_core_tables_are_present(self, pg_conn, make_space):
        sp = await make_space()
        r = await enumerate_space_objects(pg_conn, sp)
        for suffix in ("term", "rdf_quad", "datatype", "search_mapping",
                       "vector_index", "fts_index"):
            assert f"{sp}_{suffix}" in r["tables"], suffix

    async def test_the_dynamic_vec_table_is_found(self, pg_conn, make_space):
        """A hardcoded list cannot know these names — every space has at least
        `_vec_document_segments` from bootstrap, and more are user-named."""
        sp = await make_space()
        r = await enumerate_space_objects(pg_conn, sp)
        assert any(t.startswith(f"{sp}_vec_") for t in r["tables"]), r["tables"]

    async def test_constraints_include_the_auto_named_ones(
            self, pg_conn, make_space):
        """Nothing in the schema names a constraint, so every one is auto-named
        from its table and every one needs renaming."""
        sp = await make_space()
        r = await enumerate_space_objects(pg_conn, sp)
        assert f"{sp}_term_pkey" in r["constraints"], \
            [c for c in r["constraints"] if "term" in c][:5]

    async def test_partition_children_are_reported_separately(
            self, pg_conn, make_space):
        """Measured: renaming a partitioned parent leaves the children behind, so
        they need their own ALTER and must not hide inside `tables`."""
        sp = await make_space(partition_quads=4)
        r = await enumerate_space_objects(pg_conn, sp)
        assert r["partition_children"], "a partitioned space reported no children"
        assert all(c not in r["tables"] for c in r["partition_children"])
        assert any(c.startswith(f"{sp}_rdf_quad_p")
                   for c in r["partition_children"]), r["partition_children"]


class TestPrefixShadowing:
    """The `data` / `data_orig` shape the issue calls precisely dangerous."""

    async def test_the_shorter_id_does_not_claim_the_longer_ones_objects(
            self, pg_conn, make_space):
        short = await make_space("inttest_shadow")
        long_ = await make_space("inttest_shadow_extra")

        r = await enumerate_space_objects(pg_conn, short)
        assert r["shadowed_by"] == [long_]
        leaked = [t for t in r["tables"] if t.startswith(f"{long_}_")]
        assert leaked == [], f"would have renamed another space's tables: {leaked}"
        assert f"{short}_term" in r["tables"]

    async def test_the_longer_id_is_unaffected(self, pg_conn, make_space):
        await make_space("inttest_shadow2")
        long_ = await make_space("inttest_shadow2_extra")
        r = await enumerate_space_objects(pg_conn, long_)
        assert r["shadowed_by"] == []
        assert f"{long_}_term" in r["tables"]

    async def test_no_index_of_the_longer_space_is_claimed(
            self, pg_conn, make_space):
        """Indexes are found via the owned TABLES, so a table-attribution bug
        would leak indexes too. Checked separately because that is the class a
        rename would duplicate rather than merely misname."""
        short = await make_space("inttest_shadow3")
        long_ = await make_space("inttest_shadow3_extra")
        r = await enumerate_space_objects(pg_conn, short)
        assert not any(long_ in name for name in r["indexes"])


class TestItDetectsAPreviousPartialRename:

    async def test_a_hand_renamed_table_leaves_mismatched_objects(
            self, pg_conn, make_space):
        """The damage this issue is about, reproduced: rename ONLY the table, as
        `ALTER TABLE` does, and the enumerator must report what was left behind.
        """
        sp = await make_space()
        # Rename the table the way a careless operator would — table only.
        await pg_conn.execute(
            f"ALTER TABLE {sp}_rdf_value_stats RENAME TO renamed_value_stats")
        try:
            r = await enumerate_space_objects(pg_conn, "renamed")
            # Its indexes and constraints still carry the OLD space id, so they
            # do not contain `renamed_`.
            assert r["mismatched"], (
                "a table renamed without its indexes reported no mismatch")
            assert any(sp in name for name in r["mismatched"]), r["mismatched"]
        finally:
            await pg_conn.execute(
                f"ALTER TABLE renamed_value_stats RENAME TO {sp}_rdf_value_stats")

    async def test_a_healthy_space_reports_no_mismatch(self, pg_conn, make_space):
        """The baseline that makes the check believable. An audit that fires on
        every space is an audit nobody runs — the first version of this rule used
        a prefix test and flagged all 105 indexes of every healthy space."""
        sp = await make_space()
        r = await enumerate_space_objects(pg_conn, sp)
        assert r["mismatched"] == [], r["mismatched"][:10]


class TestTheSummaryIsReadable:

    async def test_it_names_the_space_and_every_class(self, pg_conn, make_space):
        sp = await make_space()
        text = format_enumeration(await enumerate_space_objects(pg_conn, sp))
        assert sp in text
        for cls in _CLASSES:
            assert cls in text

    async def test_shadowing_is_called_out(self, pg_conn, make_space):
        short = await make_space("inttest_shadow4")
        await make_space("inttest_shadow4_extra")
        text = format_enumeration(await enumerate_space_objects(pg_conn, short))
        assert "prefix of" in text

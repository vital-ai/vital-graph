"""`SparqlSQLSchema.classify_space_table` is the single answer to "what is this table?".

`scripts/migrate_drop_retired_tables.py` used to carry its own copy of the
known suffixes, the dynamic `fts_`/`vec_` prefixes AND the retired names. A
duplicate is how a table comes to be retired in one place and live in another,
which is the defect class `issues/185` is about.

The prefix cases below are the ones a caller gets wrong on its own.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema


SPACES = ["cardiff_kg", "cardiff_kg_test", "lead_prod"]


def _c(table):
    return SparqlSQLSchema.classify_space_table(table, SPACES)


class TestAttribution:

    def test_a_longer_space_id_keeps_its_own_tables(self):
        """The bug this API exists to prevent.

        `LIKE '<space>\\_%'` matches every table of a space whose id merely
        EXTENDS this one, so `cardiff_kg` claimed all of `cardiff_kg_test`'s.
        The drop survived it, but the DRIFT REPORT did not — and that report is
        the input to the retired list, so a misattribution there is one step
        from dropping a live table of another space.
        """
        info = _c("cardiff_kg_test_rdf_quad")
        assert info["space_id"] == "cardiff_kg_test", (
            "attributed to the shorter prefix; a plain LIKE would do this")
        assert info["role"] == "schema"

    def test_the_shorter_space_still_gets_its_own(self):
        info = _c("cardiff_kg_rdf_quad")
        assert info["space_id"] == "cardiff_kg"
        assert info["role"] == "schema"

    def test_a_name_belonging_to_no_space_is_foreign(self):
        assert _c("some_other_table")["role"] == "foreign"


class TestRoles:

    def test_a_retired_table_reports_why(self):
        info = _c("cardiff_kg_frame_entity")
        assert info["role"] == "retired"
        assert info["reason"], "a retired verdict without a reason is not actionable"

    def test_a_user_named_index_is_not_drift(self):
        """One table per user-named index, so unrecognisable by construction.

        A sweep that dropped "anything not in the schema" would destroy these,
        which is why the retired list is explicit rather than inferred.
        """
        for name in ("cardiff_kg_fts_whatever", "cardiff_kg_vec_my_index_7f3a"):
            assert _c(name)["role"] == "dynamic_index", name

    def test_a_partition_child_is_attributed_to_its_parent(self):
        info = _c("cardiff_kg_rdf_quad_p3")
        assert info["suffix"] == "rdf_quad"
        assert info["role"] == "schema"

    def test_a_retired_name_that_prefixes_another_does_not_swallow_it(self):
        """`vector_mapping` is a prefix of `vector_mapping_property`.

        Matching partition children as `startswith(name + "_p")` made
        `vector_mapping_property` match the `vector_mapping` rule, reporting it
        twice and inflating a 34-table count to 51. The suffix after `_p` has
        to be digits.
        """
        assert _c("cardiff_kg_vector_mapping")["suffix"] == "vector_mapping"
        assert _c("cardiff_kg_vector_mapping_property")["suffix"] == \
            "vector_mapping_property"

    def test_an_unknown_table_is_reported_not_assumed(self):
        info = _c("cardiff_kg_something_nobody_knows")
        assert info["role"] == "unknown"
        assert info["space_id"] == "cardiff_kg"


class TestRetiredDropsComeFromOneList:

    def test_the_drop_list_covers_every_retired_table(self):
        """The schema's own teardown and the migration script must agree.

        `frame_entity` was dropped by one path and kept by another precisely
        because each named it separately.
        """
        stmts = " ".join(SparqlSQLSchema.retired_table_sql("sp"))
        assert "sp_frame_entity" in stmts
        assert "sp_vector_mapping" in stmts

    def test_drop_space_tables_includes_the_retired_ones(self):
        stmts = " ".join(SparqlSQLSchema().drop_space_tables_sql("sp"))
        assert "sp_frame_entity" in stmts, (
            "a space created before the retirement would leak the table")

    def test_no_retired_suffix_is_also_a_live_one(self):
        """A name cannot be both retired and created."""
        live = set(SparqlSQLSchema.get_table_names("X").keys())
        retired = set(SparqlSQLSchema._RETIRED_TABLE_SUFFIXES)
        assert not (live & retired), f"both live and retired: {live & retired}"

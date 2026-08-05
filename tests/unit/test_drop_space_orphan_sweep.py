"""
`drop_space` must remove every table named for the space — including ones nobody
remembered to add to the explicit drop list — without touching another space's.

Background: the drop path is a hand-maintained pile of special cases (a static
list of 18, a `_vec_%`/`_fts_%` sweep, plus one-off drops for
`segmentation_jobs` and legacy `vector_mapping`). `document_segmentation_config`
is created on demand and was never added, so every space ever created leaked one
table — 116 orphans (7.4 MB) on one local stack. A final sweep makes the drop
self-healing.

The sweep's risk is over-reach, which these tests pin: one space id can be a
prefix of another, and `_` is a LIKE wildcard in SQL.
"""

import pytest

from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema

orphans = SparqlSQLSchema.orphan_tables_for_space


class TestFindsWhatTheExplicitListMisses:
    def test_finds_the_table_that_leaked(self):
        tables = ["myspace_document_segmentation_config", "unrelated_table"]
        assert orphans(tables, "myspace", []) == ["myspace_document_segmentation_config"]

    def test_finds_any_future_on_demand_table(self):
        tables = ["myspace_some_new_feature_table"]
        assert orphans(tables, "myspace", []) == ["myspace_some_new_feature_table"]

    def test_ignores_tables_of_other_spaces(self):
        tables = ["other_rdf_quad", "myspace_term"]
        assert orphans(tables, "myspace", ["other"]) == ["myspace_term"]

    def test_ignores_shared_admin_tables(self):
        tables = ["space", "user", "install"]
        assert orphans(tables, "myspace", []) == []

    def test_empty_when_nothing_survived(self):
        assert orphans(["space", "other_term"], "myspace", ["other"]) == []


class TestDoesNotOverReach:
    """A space id can be a prefix of another space id."""

    def test_longer_space_name_is_protected(self):
        tables = [
            "e2e_test_term",             # ours
            "e2e_test_extra_term",       # belongs to 'e2e_test_extra'
            "e2e_test_extra_rdf_quad",
        ]
        assert orphans(tables, "e2e_test", ["e2e_test_extra"]) == ["e2e_test_term"]

    def test_multiple_shadowing_spaces(self):
        tables = ["s_a", "s_b_x", "s_b_c_y", "s_own_table"]
        result = orphans(tables, "s", ["s_b", "s_b_c"])
        assert "s_b_x" not in result
        assert "s_b_c_y" not in result
        assert "s_own_table" in result

    def test_unrelated_space_with_similar_name_is_untouched(self):
        # 'myspaceX_term' does not start with 'myspace_' — the underscore in the
        # prefix is literal here, unlike a SQL LIKE pattern where _ is a wildcard.
        tables = ["myspaceX_term", "myspace_term"]
        assert orphans(tables, "myspace", []) == ["myspace_term"]

    def test_space_id_alone_is_not_matched(self):
        # A table named exactly like the space id has no trailing underscore and
        # is not one of its per-space tables.
        assert orphans(["myspace"], "myspace", []) == []


class TestRealisticLeftovers:
    def test_the_actual_orphan_shape_from_the_test_stack(self):
        tables = [
            "apitest_8360d4c5_document_segmentation_config",
            "apitest_8360d4c5_segmentation_jobs",
            "e2e_test_space_term",
            "space",
        ]
        found = orphans(tables, "apitest_8360d4c5", ["e2e_test_space"])
        assert sorted(found) == [
            "apitest_8360d4c5_document_segmentation_config",
            "apitest_8360d4c5_segmentation_jobs",
        ]

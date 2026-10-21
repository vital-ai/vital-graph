"""The storage key's shape, and the rule that keeps space ids out of it.

A key and a space id must be disjoint sets. If an id could equal some space's
key, a call site that passed the id where the key belongs would reach THAT
space's objects instead of failing — silently, and on another tenant's data.
So the shape is reserved: ids may not have it, and the prefix builder refuses
anything without it.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql.space_names import (
    STORAGE_KEY_NAMESPACE, is_storage_key, key_shaped_id_problem,
    new_storage_key, storage_key_prefix)
from vitalgraph.db.sparql_sql.space_rekey import _map_prefix
from vitalgraph.db.sparql_sql.sparql_sql_schema import (
    STORAGE_KEY_COLUMN_SQL, SparqlSQLSchema)


class TestTheShape:

    @pytest.mark.parametrize("value", ["abcd2345", "zzzzzzzz", "a2b3c4d5"])
    def test_keys(self, value):
        assert is_storage_key(value)

    @pytest.mark.parametrize("value", [
        "abcd234", "abcd23456",        # wrong length
        "abcd2341", "abcd2348",        # 0, 1, 8, 9 are not base32
        "ABCD2345", "abcd_345", "",    # case, separator, empty
        None, 12345678,
    ])
    def test_not_keys(self, value):
        assert not is_storage_key(value)

    def test_generated_keys_have_the_shape_and_differ(self):
        keys = {new_storage_key() for _ in range(500)}
        assert all(is_storage_key(k) for k in keys)
        assert len(keys) == 500


class TestTheIdsAndKeysAreDisjoint:

    def test_a_key_shaped_id_is_refused(self):
        assert "storage key" in key_shaped_id_problem("abcd2345")

    @pytest.mark.parametrize("space_id", [
        "prod_kg", "lead_prod", "abcdefg", "abcdefghi", "abcd2341", "sp_kg_types"])
    def test_ordinary_ids_pass(self, space_id):
        assert key_shaped_id_problem(space_id) is None

    @pytest.mark.parametrize("space_id", ["prod_kg", "lead_prod", "x"])
    def test_an_id_cannot_be_used_as_a_key(self, space_id):
        with pytest.raises(ValueError, match="not a storage key"):
            storage_key_prefix(space_id)

    def test_the_prefix(self):
        assert storage_key_prefix("abcd2345") == "vgs_abcd2345"
        assert STORAGE_KEY_NAMESPACE == "vgs_"

    def test_no_admin_table_is_in_the_namespace(self):
        """`vgs_*` belongs to spaces alone; that is what makes a `vgs_` object
        with no matching key an orphan by definition."""
        assert not [t for t in SparqlSQLSchema.ADMIN_TABLE_NAMES
                    if t.startswith(STORAGE_KEY_NAMESPACE)]


class TestTheColumn:

    def test_fresh_installs_get_the_same_clause_the_migration_adds(self):
        space_ddl = dict(SparqlSQLSchema.ADMIN_TABLE_DDL)["space"]
        assert STORAGE_KEY_COLUMN_SQL in space_ddl

    def test_the_database_enforces_the_shape(self):
        assert "UNIQUE" in STORAGE_KEY_COLUMN_SQL
        assert "^[a-z2-7]{8}$" in STORAGE_KEY_COLUMN_SQL


class TestPrefixSubstitution:

    @pytest.mark.parametrize("name,expected", [
        ("x_rdf_quad", "vgs_abcd2345_rdf_quad"),
        ("idx_x_edge_ctx", "idx_vgs_abcd2345_edge_ctx"),
        ("trg_x_isq_ins", "trg_vgs_abcd2345_isq_ins"),
        ("ck_x_term_uri_len", "ck_vgs_abcd2345_term_uri_len"),
        ("x_rdf_quad_p3", "vgs_abcd2345_rdf_quad_p3"),
    ])
    def test_every_decorator(self, name, expected):
        assert _map_prefix(name, "x", "vgs_abcd2345") == expected

    def test_a_leading_token_not_a_substring(self):
        """`idx_x_…` for a space called `x`: the first `x` is inside `idx_`."""
        assert _map_prefix("idx_x_term_tt", "x", "y") == "idx_y_term_tt"

    def test_an_unrelated_name_is_not_mapped(self):
        assert _map_prefix("xy_rdf_quad", "x", "vgs_abcd2345") is None

    def test_and_back(self):
        assert _map_prefix("vgs_abcd2345_term", "vgs_abcd2345", "x") == "x_term"

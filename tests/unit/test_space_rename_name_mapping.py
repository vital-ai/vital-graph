"""Mapping an object name from one space id to another — issue 232 step 2.

Pure and fast, so the cases that matter can be enumerated rather than sampled.

THE TRAP THIS EXISTS FOR. The obvious implementation is
`name.replace(old, new, 1)`, and it is wrong: for a space called `x`, the first
`x` in `idx_x_edge_ctx` is inside `idx_`, so a first-occurrence replace produces
`idy__x_edge_ctx`. The rule has to match `{decorator}{space_id}` as a whole
leading token.

AND WHY None MATTERS MORE THAN THE MAPPING. A name the rename cannot map must be
a HARD FAILURE, never a skip — a skipped object is an orphan under the old id,
which is the entire defect `issues/232` is about. So `None` is the signal that
stops a rename, and these tests pin which names produce it.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql.space_rename import _map_name

pytestmark = [pytest.mark.unit]


class TestTheShapesARealSpaceProduces:

    @pytest.mark.parametrize("name,expected", [
        # tables
        ("data_term", "data_orig_term"),
        ("data_rdf_quad", "data_orig_rdf_quad"),
        ("data_vec_document_segments", "data_orig_vec_document_segments"),
        ("data_fts_message_content", "data_orig_fts_message_content"),
        # partition children — renaming the parent does NOT move these
        ("data_rdf_quad_p0", "data_orig_rdf_quad_p0"),
        ("data_entity_slot_sort_p15", "data_orig_entity_slot_sort_p15"),
        # explicitly named indexes
        ("idx_data_edge_ctx", "idx_data_orig_edge_ctx"),
        ("idx_data_eps_dt_desc", "idx_data_orig_eps_dt_desc"),
        # auto-named constraints, including PG18's NOT NULL ones
        ("data_term_pkey", "data_orig_term_pkey"),
        ("data_datatype_datatype_uri_key", "data_orig_datatype_datatype_uri_key"),
        ("data_term_ctx_not_null", "data_orig_term_ctx_not_null"),
        ("data_search_mapping_property_mapping_id_fkey",
         "data_orig_search_mapping_property_mapping_id_fkey"),
        # sequences
        ("data_datatype_datatype_id_seq", "data_orig_datatype_datatype_id_seq"),
        # trigger and its function
        ("trg_data_fts_content_tsv", "trg_data_orig_fts_content_tsv"),
        ("data_fts_content_tsv_trigger", "data_orig_fts_content_tsv_trigger"),
    ])
    def test_it_maps(self, name, expected):
        assert _map_name(name, "data", "data_orig") == expected


class TestTheSubstringTrap:
    """A first-occurrence replace passes every test above and fails these."""

    def test_a_single_letter_space_id_inside_a_decorator(self):
        """`idx_` contains an `x`, so for space `x` the first occurrence of the id
        is not the id."""
        assert _map_name("idx_x_edge_ctx", "x", "y") == "idx_y_edge_ctx"

    def test_an_id_that_also_appears_in_the_suffix(self):
        """Space `term` owns `term_term`; only the LEADING token is the space."""
        assert _map_name("term_term", "term", "renamed") == "renamed_term"

    def test_an_id_that_appears_twice(self):
        assert _map_name("data_data_stats", "data", "new") == "new_data_stats"


class TestWhatItRefusesToMap:
    """None stops a rename. Each of these being mapped instead would rename or
    orphan an object belonging to something else."""

    @pytest.mark.parametrize("name", [
        "other_term",                  # a different space
        "idx_other_term",              # a different space's index
        "space",                       # the shared registry table
        "user_space_access",
        "datax_term",                  # id is a prefix but not a token
        "idx_datax_term",
        "",
    ])
    def test_it_returns_none(self, name):
        assert _map_name(name, "data", "data_orig") is None

    def test_a_longer_space_id_is_not_claimed(self):
        """The `data` / `data_orig` hazard at the NAME level: renaming `data` must
        not map `data_orig`'s own objects."""
        assert _map_name("data_orig_term", "data", "data2") == "data2_orig_term"
        # …which is why attribution happens FIRST, by longest prefix, and this
        # function only ever sees names the enumerator already assigned. The
        # mapping alone cannot tell these apart, and that is the reason the
        # enumerator's shadowing rule is load-bearing rather than tidy.


class TestExactMatches:

    def test_the_bare_space_id_maps(self):
        assert _map_name("data", "data", "data_orig") == "data_orig"

    def test_a_decorated_bare_id_maps(self):
        assert _map_name("idx_data", "data", "data_orig") == "idx_data_orig"

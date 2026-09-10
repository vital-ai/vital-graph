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


SPACES = ["prod_kg", "prod_kg_test", "other_space"]


def _c(table):
    return SparqlSQLSchema.classify_space_table(table, SPACES)


class TestAttribution:

    def test_a_longer_space_id_keeps_its_own_tables(self):
        """The bug this API exists to prevent.

        `LIKE '<space>\\_%'` matches every table of a space whose id merely
        EXTENDS this one, so `prod_kg` claimed all of `prod_kg_test`'s.
        The drop survived it, but the DRIFT REPORT did not — and that report is
        the input to the retired list, so a misattribution there is one step
        from dropping a live table of another space.
        """
        info = _c("prod_kg_test_rdf_quad")
        assert info["space_id"] == "prod_kg_test", (
            "attributed to the shorter prefix; a plain LIKE would do this")
        assert info["role"] == "schema"

    def test_the_shorter_space_still_gets_its_own(self):
        info = _c("prod_kg_rdf_quad")
        assert info["space_id"] == "prod_kg"
        assert info["role"] == "schema"

    def test_a_name_belonging_to_no_space_is_foreign(self):
        assert _c("some_other_table")["role"] == "foreign"


class TestRoles:

    def test_a_retired_table_reports_why(self):
        info = _c("prod_kg_frame_entity")
        assert info["role"] == "retired"
        assert info["reason"], "a retired verdict without a reason is not actionable"

    def test_a_user_named_index_is_not_drift(self):
        """One table per user-named index, so unrecognisable by construction.

        A sweep that dropped "anything not in the schema" would destroy these,
        which is why the retired list is explicit rather than inferred.
        """
        for name in ("prod_kg_fts_whatever", "prod_kg_vec_my_index_7f3a"):
            assert _c(name)["role"] == "dynamic_index", name

    def test_a_partition_child_is_attributed_to_its_parent(self):
        info = _c("prod_kg_rdf_quad_p3")
        assert info["suffix"] == "rdf_quad"
        assert info["role"] == "schema"

    def test_a_retired_name_that_prefixes_another_does_not_swallow_it(self):
        """`vector_mapping` is a prefix of `vector_mapping_property`.

        Matching partition children as `startswith(name + "_p")` made
        `vector_mapping_property` match the `vector_mapping` rule, reporting it
        twice and inflating a 34-table count to 51. The suffix after `_p` has
        to be digits.
        """
        assert _c("prod_kg_vector_mapping")["suffix"] == "vector_mapping"
        assert _c("prod_kg_vector_mapping_property")["suffix"] == \
            "vector_mapping_property"

    def test_an_unknown_table_is_reported_not_assumed(self):
        info = _c("prod_kg_something_nobody_knows")
        assert info["role"] == "unknown"
        assert info["space_id"] == "prod_kg"


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


class TestNoCodeIndexesARetiredKey:
    """`get_table_names(...)['x']` with a retired key is a runtime KeyError.

    Removing `frame_entity` from that map turned three existing lookups into
    landmines. One of them, in `_maybe_analyze_aux_tables`, built its table list
    as

        tables = [t['rdf_pred_stats'], t['rdf_stats'], t['datatype'],
                  t['edge'], t['frame_entity']]

    so the KeyError fired while BUILDING the list, before any ANALYZE ran — and
    the caller logs it as non-fatal. The result was not "one stale table is
    skipped" but ALL FIVE silently skipped on every bulk write in production,
    visible only as `ANALYZE after bulk insert failed (non-fatal):
    'frame_entity'` in the logs.

    A retirement removes a key; nothing failed at import, and nothing failed
    loudly at runtime either. Hence a static check.
    """

    def _lookup_keys(self):
        """(file, key) for every subscript of a `get_table_names` result.

        AST, scoped PER FUNCTION. Two cruder versions produced false positives:
        matching any variable named `t` caught unrelated dicts, and scoping by
        FILE still caught them, because the same short name is reused for a
        different dict elsewhere in the same module.
        """
        import ast, pathlib
        root = pathlib.Path(__file__).resolve().parents[3]
        found = []
        for f in list((root / "vitalgraph").rglob("*.py")) + \
                 list((root / "scripts").rglob("*.py")):
            try:
                tree = ast.parse(f.read_text())
            except Exception:
                continue
            for fn in ast.walk(tree):
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                names = set()
                for node in ast.walk(fn):
                    if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
                        continue
                    fname = node.value.func
                    label = getattr(fname, "attr", None) or getattr(fname, "id", None)
                    if label != "get_table_names":
                        continue
                    for tgt in node.targets:
                        if isinstance(tgt, ast.Name):
                            names.add(tgt.id)
                if not names:
                    continue
                for node in ast.walk(fn):
                    if (isinstance(node, ast.Subscript)
                            and isinstance(node.value, ast.Name)
                            and node.value.id in names
                            and isinstance(node.slice, ast.Constant)
                            and isinstance(node.slice.value, str)):
                        found.append((f.relative_to(root), node.slice.value))
        return found

    def test_every_indexed_key_exists(self):
        live = set(SparqlSQLSchema.get_table_names("X"))
        bad = [(f, k) for f, k in self._lookup_keys() if k not in live]
        assert not bad, (
            "these index get_table_names with a key it no longer defines, "
            f"which is a runtime KeyError: {bad}")

    def test_the_check_can_see_something(self):
        """Guard the guard: a regex that matches nothing would pass forever."""
        assert self._lookup_keys(), "found no lookups at all — the pattern broke"

"""FTS index languages: one builder per side, and nothing unchecked reaches SQL.

`issues/333`. Five hand-written copies turned an index's `languages` into SQL.
They drifted (the fast path used only the first language), none checked the
name before pasting it unquoted into DDL run over the simple-query protocol
(SQL injection for a space writer), and an unknown name was accepted at index
creation and then failed every write into the index inside auto-sync, which
only logs.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql.fts_languages import (
    InvalidFtsLanguages, check_language_name, tsquery_expr, tsvector_expr,
    validate_fts_languages,
)
from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
from vitalgraph.db.sparql_sql.vg_functions import _build_tsquery_expr

INJECTION = "english'::regconfig, ''); DROP TABLE x; --"


# The builders as they were before `issues/333`, verbatim, so the SQL for every
# valid list is pinned byte-identical: recorded plans and baselines stay
# comparable.
def _old_trigger_expr(languages):
    languages = languages or ["english"]
    return "\n         || ".join(
        f"to_tsvector('{lang}'::regconfig, COALESCE(NEW.search_text, ''))"
        for lang in languages)


def _old_batch_expr(languages, text_col="search_text"):
    languages = languages or ["english"]
    return " || ".join(
        f"to_tsvector('{lang}'::regconfig, COALESCE({text_col}, ''))"
        for lang in languages)


def _old_tsquery_expr(languages, safe_text):
    parts = [f"websearch_to_tsquery('{lang}'::regconfig, '{safe_text}')"
             for lang in languages]
    return parts[0] if len(parts) == 1 else "(" + " || ".join(parts) + ")"


LISTS = [["english"], ["english", "spanish"], ["simple"],
         ["english", "spanish", "french"]]


class TestTheSqlIsUnchanged:
    @pytest.mark.parametrize("langs", LISTS + [[]])
    def test_trigger_expression(self, langs):
        assert SparqlSQLSchema._build_tsv_concat_expr(langs) == _old_trigger_expr(langs)

    @pytest.mark.parametrize("langs", LISTS + [[]])
    def test_batch_expression(self, langs):
        assert SparqlSQLSchema.build_tsv_batch_expr(langs) == _old_batch_expr(langs)
        assert (SparqlSQLSchema.build_tsv_batch_expr(langs, "t.txt")
                == _old_batch_expr(langs, "t.txt"))

    @pytest.mark.parametrize("langs", LISTS)
    def test_query_expression(self, langs):
        assert (_build_tsquery_expr(langs, "don''t stop")
                == _old_tsquery_expr(langs, "don''t stop"))

    def test_a_parameter_is_accepted_as_the_text(self):
        assert (tsquery_expr(["english", "spanish"], "$1")
                == "(websearch_to_tsquery('english'::regconfig, $1) "
                   "|| websearch_to_tsquery('spanish'::regconfig, $1))")

    def test_no_languages_means_english(self):
        assert tsquery_expr([], "$1") == "websearch_to_tsquery('english'::regconfig, $1)"
        assert tsvector_expr(None, "t") == "to_tsvector('english'::regconfig, t)"


class TestNothingUncheckedReachesSql:
    """The query builders read languages from the REGISTRY, which predates
    validation, so they refuse a bad stored name rather than interpolate it."""

    @pytest.mark.parametrize("bad", [
        INJECTION, "English", "pg_catalog.english", "eng lish", "", "1english",
        "e" * 64, None, 3,
    ])
    def test_every_builder_refuses(self, bad):
        with pytest.raises(InvalidFtsLanguages):
            check_language_name(bad)
        with pytest.raises(InvalidFtsLanguages):
            tsvector_expr(["english", bad], "t")
        with pytest.raises(InvalidFtsLanguages):
            tsquery_expr(["english", bad], "$1")
        with pytest.raises(InvalidFtsLanguages):
            SparqlSQLSchema().create_fts_data_table_sql("sp", "idx", [bad])
        with pytest.raises(InvalidFtsLanguages):
            _build_tsquery_expr([bad], "x")

    def test_it_is_a_value_error(self):
        # So existing `except ValueError` handlers still see it as bad input.
        assert issubclass(InvalidFtsLanguages, ValueError)


class _Conn:
    """`pg_ts_config` as a database with these configurations visible, and
    the `cjk` functions installed or not."""

    def __init__(self, configs=("english", "spanish", "simple", "french"),
                 cjk_installed=True):
        self.configs = set(configs)
        self.cjk_installed = cjk_installed
        self.queries = 0

    async def fetch(self, sql, names):
        self.queries += 1
        if "to_regprocedure" in sql:
            return [] if self.cjk_installed else [{"sig": n} for n in names]
        assert "pg_ts_config_is_visible" in sql
        assert "cjk" not in names, "a pseudo-language is not a pg_ts_config"
        return [{"cfgname": n} for n in names if n in self.configs]


class TestValidation:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("langs", LISTS)
    async def test_known_configurations_pass(self, langs):
        assert await validate_fts_languages(_Conn(), langs) is None

    @pytest.mark.asyncio
    async def test_an_unknown_configuration_is_named(self):
        reason = await validate_fts_languages(_Conn(), ["english", "klingon"])
        assert reason and "klingon" in reason and "english" not in reason.split(":")[1]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("langs,expect", [
        ([], "non-empty"),
        (None, "non-empty"),
        ("english", "not a string"),
        (["english", "english"], "duplicate"),
        ([INJECTION], "invalid language name"),
        (["English"], "invalid language name"),
    ])
    async def test_shape_is_refused_without_a_query(self, langs, expect):
        conn = _Conn()
        reason = await validate_fts_languages(conn, langs)
        assert reason and expect in reason
        assert conn.queries == 0, "a malformed list must not reach the database"


class TestCjk:
    """`cjk` is a pseudo-language served by the `vitalgraph_cjk_*` functions."""

    def test_index_side(self):
        assert (tsvector_expr(["english", "cjk"], "t")
                == "to_tsvector('english'::regconfig, t) || vitalgraph_cjk_tsvector(t)")
        assert tsvector_expr(["cjk"], "t") == "vitalgraph_cjk_tsvector(t)"

    def test_query_side_coalesces_the_null_arm(self):
        """`vitalgraph_cjk_tsquery` is NULL for a query with no positive CJK,
        and `tsquery || NULL` is NULL, so the other arms are the fallback."""
        en = "websearch_to_tsquery('english'::regconfig, $1)"
        assert (tsquery_expr(["english", "cjk"], "$1")
                == f"COALESCE({en} || vitalgraph_cjk_tsquery($1), {en})")
        both = ("(websearch_to_tsquery('english'::regconfig, $1) || "
                "websearch_to_tsquery('spanish'::regconfig, $1))")
        assert (tsquery_expr(["english", "spanish", "cjk"], "$1")
                == f"COALESCE({both} || vitalgraph_cjk_tsquery($1), {both})")

    def test_cjk_alone_is_the_bare_arm(self):
        # NULL there means "matches nothing", which every consumer reads so.
        assert tsquery_expr(["cjk"], "$1") == "vitalgraph_cjk_tsquery($1)"

    def test_order_does_not_matter(self):
        assert (tsquery_expr(["cjk", "english"], "$1")
                == tsquery_expr(["english", "cjk"], "$1"))

    def test_the_trigger_and_batch_carry_it(self):
        assert "vitalgraph_cjk_tsvector(COALESCE(NEW.search_text, ''))" in (
            SparqlSQLSchema._build_tsv_concat_expr(["english", "cjk"]))
        assert "vitalgraph_cjk_tsvector(COALESCE(search_text, ''))" in (
            SparqlSQLSchema.build_tsv_batch_expr(["english", "cjk"]))

    @pytest.mark.asyncio
    async def test_it_validates_when_the_functions_are_installed(self):
        assert await validate_fts_languages(_Conn(), ["english", "cjk"]) is None
        assert await validate_fts_languages(_Conn(), ["cjk"]) is None

    @pytest.mark.asyncio
    async def test_it_is_refused_until_the_pre_deploy_step_runs(self):
        reason = await validate_fts_languages(_Conn(cjk_installed=False),
                                              ["english", "cjk"])
        assert reason and "install_sql_functions.py" in reason
        assert "vitalgraph_cjk_tsvector(text)" in reason

    @pytest.mark.asyncio
    async def test_an_unknown_name_is_still_refused_beside_it(self):
        reason = await validate_fts_languages(_Conn(), ["cjk", "klingon"])
        assert reason and "klingon" in reason

    def test_every_cjk_function_is_installed_by_both_installers(self):
        from vitalgraph.db.sparql_sql.sparql_sql_admin import (
            CJK_FUNCTION_SIGNATURES, FUNCTION_DDL, FUNCTIONS)
        assert set(CJK_FUNCTION_SIGNATURES) == {
            "vitalgraph_cjk_runs(text)", "vitalgraph_cjk_index_text(text)",
            "vitalgraph_cjk_tsvector(text)", "vitalgraph_cjk_tsquery(text)",
            "vitalgraph_cjk_query_terms(text)"}
        assert FUNCTION_DDL == tuple(ddl for _, ddl in FUNCTIONS)
        names = [sig.split("(")[0] for sig, _ in FUNCTIONS]
        for (sig, ddl) in FUNCTIONS:
            assert f"FUNCTION {sig.split('(')[0]}(" in ddl, sig
        # LANGUAGE sql bodies are checked at CREATE: callees come first.
        assert names.index("vitalgraph_cjk_runs") < names.index("vitalgraph_cjk_index_text")
        assert names.index("vitalgraph_cjk_index_text") < names.index("vitalgraph_cjk_tsvector")

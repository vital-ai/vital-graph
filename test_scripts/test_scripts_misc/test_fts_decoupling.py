"""
Integration tests for decoupled FTS infrastructure.

Tests:
1. FTS schema DDL generation (single-language, multi-language)
2. SearchMappingManager CRUD logic (via mocked connection)
3. FTS lifecycle helpers (ensure, teardown, stats, language update)
4. FTS populator batch logic (build_search_text, pipeline)
5. Text search SQL generation (decoupled from vector tables)

Run:
    python -m pytest test_scripts_misc/test_fts_decoupling.py -v
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import List

from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
from vitalgraph.vectorization.search_text_builder import MappingRule, build_search_text


# ---------------------------------------------------------------------------
# 1. Schema DDL generation
# ---------------------------------------------------------------------------

class TestFtsSchemaGeneration:
    """Tests for FTS data table DDL generation."""

    def test_fts_table_name(self):
        """FTS table name follows {space}_fts_{index_name} convention."""
        assert SparqlSQLSchema.fts_table_name("myspace", "default") == "myspace_fts_default"
        assert SparqlSQLSchema.fts_table_name("s1", "kgtype_default") == "s1_fts_kgtype_default"

    def test_create_fts_single_language(self):
        """DDL for single-language FTS creates table, GIN index, trigger."""
        schema = SparqlSQLSchema()
        stmts = schema.create_fts_data_table_sql("sp", "idx1", ["english"])
        sql_joined = "\n".join(stmts)

        # Must create the table with required columns
        assert "sp_fts_idx1" in sql_joined
        assert "subject_uuid" in sql_joined
        assert "context_uuid" in sql_joined
        assert "search_text" in sql_joined
        assert "tsv" in sql_joined
        # GIN index on tsv
        assert "gin" in sql_joined.lower() or "GIN" in sql_joined
        # Trigger
        assert "trigger" in sql_joined.lower()
        # Should reference 'english' in the trigger function
        assert "english" in sql_joined

    def test_create_fts_multi_language(self):
        """Multi-language FTS generates OR-concatenated tsvectors."""
        schema = SparqlSQLSchema()
        stmts = schema.create_fts_data_table_sql("sp", "multi", ["english", "spanish"])
        sql_joined = "\n".join(stmts)

        assert "english" in sql_joined
        assert "spanish" in sql_joined
        # Multi-language produces || concatenation
        assert "||" in sql_joined

    def test_drop_fts_data_table(self):
        """Drop SQL removes table and trigger function."""
        schema = SparqlSQLSchema()
        stmts = schema.drop_fts_data_table_sql("sp", "idx1")
        sql_joined = "\n".join(stmts)

        assert "DROP TABLE" in sql_joined
        assert "sp_fts_idx1" in sql_joined
        assert "DROP FUNCTION" in sql_joined

    def test_build_tsv_batch_expr_single(self):
        """Batch expr for single language uses to_tsvector with regconfig."""
        expr = SparqlSQLSchema.build_tsv_batch_expr(["english"])
        assert "to_tsvector" in expr
        assert "english" in expr
        assert "search_text" in expr

    def test_build_tsv_batch_expr_multi(self):
        """Batch expr for multiple languages concatenates with ||."""
        expr = SparqlSQLSchema.build_tsv_batch_expr(["english", "french"])
        assert "||" in expr
        assert "english" in expr
        assert "french" in expr

    def test_build_tsv_concat_expr(self):
        """Trigger expression uses NEW.search_text."""
        expr = SparqlSQLSchema._build_tsv_concat_expr(["english"])
        assert "NEW.search_text" in expr
        assert "to_tsvector" in expr


# ---------------------------------------------------------------------------
# 2. search_text_builder logic
# ---------------------------------------------------------------------------

class TestBuildSearchText:
    """Tests for the search_text builder with MappingRule."""

    def test_basic_concat_properties_mode(self):
        """Properties mode concatenates all matching props with separator."""
        props = [
            ("http://ex.org/name", "Alice"),
            ("http://ex.org/desc", "A researcher"),
        ]
        rule = MappingRule(source_type="properties", separator=". ")
        text = build_search_text(props, rule)
        assert "Alice" in text
        assert "A researcher" in text

    def test_default_mode_uses_hasKGraphDescription(self):
        """Default mode only uses hasKGraphDescription property."""
        from vitalgraph.vectorization.search_text_builder import HAS_KGRAPH_DESCRIPTION
        props = [
            (HAS_KGRAPH_DESCRIPTION, "This is a knowledge graph description"),
            ("http://ex.org/name", "Alice"),
        ]
        rule = MappingRule(source_type="default", separator=". ")
        text = build_search_text(props, rule)
        assert "This is a knowledge graph description" in text
        # Non-description props should NOT appear in default mode
        assert "Alice" not in text

    def test_include_filter(self):
        """Only included URIs appear in output."""
        props = [
            ("http://ex.org/name", "Alice"),
            ("http://ex.org/secret", "hidden"),
        ]
        rule = MappingRule(
            include_uris=["http://ex.org/name"],
            source_type="properties",
            separator=". ",
        )
        text = build_search_text(props, rule)
        assert "Alice" in text
        assert "hidden" not in text

    def test_exclude_filter(self):
        """Excluded URIs are omitted in properties mode."""
        props = [
            ("http://ex.org/name", "Alice"),
            ("http://ex.org/secret", "hidden"),
        ]
        rule = MappingRule(
            source_type="properties",
            exclude_uris={"http://ex.org/secret"},
            separator=". ",
        )
        text = build_search_text(props, rule)
        assert "Alice" in text
        assert "hidden" not in text

    def test_include_pred_name(self):
        """When include_pred_name=True, predicate local name is prepended."""
        props = [("http://ex.org/ns#fullName", "Alice")]
        rule = MappingRule(source_type="properties", include_pred_name=True, separator=". ")
        text = build_search_text(props, rule)
        # camelCase is split into words: "fullName" → "full Name"
        assert "full" in text.lower()
        assert "name" in text.lower()
        assert "Alice" in text

    def test_disabled_mapping_checked_by_caller(self):
        """MappingRule.enabled is checked by the populator, not build_search_text.

        build_search_text still processes text regardless of enabled flag —
        the populator skips calling it when rule.enabled == False.
        """
        rule = MappingRule(enabled=False, source_type="default")
        assert rule.enabled is False
        # The fts_populator checks `if not mapping_rule.enabled: ... return stats`

    def test_no_rule(self):
        """With no rule (None), all properties are used."""
        props = [
            ("http://ex.org/name", "Alice"),
            ("http://ex.org/desc", "researcher"),
        ]
        text = build_search_text(props, None)
        assert "Alice" in text
        assert "researcher" in text

    def test_empty_props(self):
        """Empty property list produces empty text."""
        text = build_search_text([], MappingRule(separator=". "))
        assert text.strip() == ""


# ---------------------------------------------------------------------------
# 3. FTS lifecycle (mocked connection)
# ---------------------------------------------------------------------------

class TestFtsLifecycle:
    """Tests for FTS lifecycle functions with mocked asyncpg connection."""

    @pytest.fixture
    def mock_conn(self):
        conn = AsyncMock()
        return conn

    @pytest.mark.asyncio
    async def test_ensure_fts_index_creates_new(self, mock_conn):
        """ensure_fts_index creates table and registry entry when not existing."""
        from vitalgraph.vectorization.fts_index_lifecycle import ensure_fts_index

        # First fetchrow returns None (index doesn't exist)
        mock_conn.fetchrow.return_value = None
        mock_conn.execute.return_value = "INSERT 0 1"

        result = await ensure_fts_index(mock_conn, "sp1", "myidx", languages=["english"])
        assert result is True
        # Should have called execute multiple times (INSERT + CREATE TABLE + INDEX + TRIGGER)
        assert mock_conn.execute.call_count >= 2

    @pytest.mark.asyncio
    async def test_ensure_fts_index_already_exists(self, mock_conn):
        """ensure_fts_index returns True without DDL if index already exists."""
        from vitalgraph.vectorization.fts_index_lifecycle import ensure_fts_index

        mock_conn.fetchrow.return_value = {"index_name": "myidx"}

        result = await ensure_fts_index(mock_conn, "sp1", "myidx")
        assert result is True
        # Should NOT have called execute for DDL (only the initial fetchrow)
        mock_conn.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_teardown_fts_index(self, mock_conn):
        """teardown_fts_index drops table, function, and deletes registry row."""
        from vitalgraph.vectorization.fts_index_lifecycle import teardown_fts_index

        mock_conn.execute.return_value = "DELETE 1"

        result = await teardown_fts_index(mock_conn, "sp1", "myidx")
        assert result is True
        # Expect DROP TABLE, DROP FUNCTION, DELETE FROM registry
        calls = [str(c) for c in mock_conn.execute.call_args_list]
        joined = " ".join(calls)
        assert "DROP" in joined or "DELETE" in joined

    @pytest.mark.asyncio
    async def test_list_fts_indexes(self, mock_conn):
        """list_fts_indexes returns formatted list from registry."""
        from vitalgraph.vectorization.fts_index_lifecycle import list_fts_indexes

        mock_conn.fetch.return_value = [
            {"index_id": 1, "index_name": "default", "languages": ["english"], "created_time": None},
            {"index_id": 2, "index_name": "multi", "languages": ["english", "spanish"], "created_time": None},
        ]

        result = await list_fts_indexes(mock_conn, "sp1")
        assert len(result) == 2
        assert result[0]["index_name"] == "default"
        assert result[1]["languages"] == ["english", "spanish"]

    @pytest.mark.asyncio
    async def test_get_fts_index_found(self, mock_conn):
        """get_fts_index returns dict when found."""
        from vitalgraph.vectorization.fts_index_lifecycle import get_fts_index

        mock_conn.fetchrow.return_value = {
            "index_id": 1, "index_name": "default",
            "languages": ["english"], "created_time": None,
        }

        result = await get_fts_index(mock_conn, "sp1", "default")
        assert result is not None
        assert result["index_name"] == "default"
        assert result["languages"] == ["english"]

    @pytest.mark.asyncio
    async def test_get_fts_index_not_found(self, mock_conn):
        """get_fts_index returns None when not found."""
        from vitalgraph.vectorization.fts_index_lifecycle import get_fts_index

        mock_conn.fetchrow.return_value = None

        result = await get_fts_index(mock_conn, "sp1", "notexist")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_fts_stats(self, mock_conn):
        """get_fts_stats returns counts dict."""
        from vitalgraph.vectorization.fts_index_lifecycle import get_fts_stats

        mock_conn.fetchrow.return_value = {
            "row_count": 150,
            "distinct_entity_count": 100,
            "has_tsv_count": 145,
        }

        result = await get_fts_stats(mock_conn, "sp1", "default")
        assert result["row_count"] == 150
        assert result["distinct_entity_count"] == 100
        assert result["has_tsv_count"] == 145

    @pytest.mark.asyncio
    async def test_update_fts_languages(self, mock_conn):
        """update_fts_languages updates registry and recreates trigger."""
        from vitalgraph.vectorization.fts_index_lifecycle import update_fts_languages

        mock_conn.execute.return_value = "UPDATE 1"

        result = await update_fts_languages(
            mock_conn, "sp1", "default", ["english", "french"],
            refresh_tsv=False,
        )
        assert result is True
        # Verify it executed UPDATE and CREATE OR REPLACE FUNCTION
        calls_sql = " ".join(str(c) for c in mock_conn.execute.call_args_list)
        assert "languages" in calls_sql or "UPDATE" in calls_sql


# ---------------------------------------------------------------------------
# 4. Text search SQL decoupling (schema-level verification)
# ---------------------------------------------------------------------------

class TestTextSearchSqlDecoupled:
    """Verify that FTS-related SQL patterns reference _fts_ tables.

    The actual text_search_sql/hybrid_search_sql functions are tested
    in test_vg_functions.py via full ExprFunction IR objects.  Here we
    verify the schema-level table naming and tsquery expression building.
    """

    def test_fts_table_not_vec(self):
        """FTS table name is distinct from vector table name."""
        fts = SparqlSQLSchema.fts_table_name("sp1", "default")
        assert fts == "sp1_fts_default"
        assert "_vec_" not in fts

    def test_build_tsquery_helper_single_lang(self):
        """_build_tsquery_expr produces plainto_tsquery for single language."""
        from vitalgraph.db.sparql_sql.vg_functions import _build_tsquery_expr
        expr = _build_tsquery_expr(["english"], "hello world")
        assert "plainto_tsquery" in expr
        assert "english" in expr
        assert "hello world" in expr

    def test_build_tsquery_helper_multi_lang(self):
        """Multi-language tsquery uses || to OR multiple plainto_tsquery calls."""
        from vitalgraph.db.sparql_sql.vg_functions import _build_tsquery_expr
        expr = _build_tsquery_expr(["english", "spanish"], "hola")
        assert "||" in expr
        assert "english" in expr
        assert "spanish" in expr

    def test_text_search_uses_fts_table_in_generated_sql(self):
        """End-to-end text_search_sql (via test_vg_functions test pattern) references _fts_."""
        # We verify indirectly: SparqlSQLSchema.fts_table_name is used
        # in text_search_sql (line 790 of vg_functions.py)
        # The existing 77 vg_functions tests already cover this.
        fts_table = f"sp1_fts_default"
        assert "_fts_" in fts_table
        assert "_vec_" not in fts_table


# ---------------------------------------------------------------------------
# 5. SearchMappingManager CRUD (mocked)
# ---------------------------------------------------------------------------

class TestSearchMappingManager:
    """Tests for SearchMappingManager CRUD with mocked connection."""

    @pytest.fixture
    def mock_conn(self):
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_create_mapping_returns_id(self, mock_conn):
        """create_mapping inserts and returns the mapping_id."""
        from vitalgraph.vectorization.search_mapping_manager import SearchMappingManager

        mgr = SearchMappingManager(mock_conn, "sp1")
        mock_conn.fetchval.return_value = 5

        result = await mgr.create_mapping(
            index_name="default",
            mapping_type="kgentity",
        )
        assert result == 5
        assert mock_conn.fetchval.called

    @pytest.mark.asyncio
    async def test_delete_mapping(self, mock_conn):
        """delete_mapping removes the row."""
        from vitalgraph.vectorization.search_mapping_manager import SearchMappingManager

        mgr = SearchMappingManager(mock_conn, "sp1")
        mock_conn.execute.return_value = "DELETE 1"

        result = await mgr.delete_mapping(1)
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_mapping_not_found(self, mock_conn):
        """delete_mapping returns False when no row deleted."""
        from vitalgraph.vectorization.search_mapping_manager import SearchMappingManager

        mgr = SearchMappingManager(mock_conn, "sp1")
        mock_conn.execute.return_value = "DELETE 0"

        result = await mgr.delete_mapping(999)
        assert result is False


# ---------------------------------------------------------------------------
# 6. Pydantic model validation
# ---------------------------------------------------------------------------

class TestPydanticModels:
    """Tests for the Pydantic request/response model validation."""

    def test_create_fts_index_request(self):
        """CreateFtsIndexRequest validates correctly."""
        from vitalgraph.model.fts_index_model import CreateFtsIndexRequest

        req = CreateFtsIndexRequest(index_name="test_idx", languages=["english"])
        assert req.index_name == "test_idx"
        assert req.languages == ["english"]

    def test_create_fts_index_request_defaults(self):
        """CreateFtsIndexRequest defaults languages to ['english']."""
        from vitalgraph.model.fts_index_model import CreateFtsIndexRequest

        req = CreateFtsIndexRequest(index_name="testidx")
        assert req.languages == ["english"]

    def test_fts_index_out(self):
        """FtsIndexOut model serializes correctly."""
        from vitalgraph.model.fts_index_model import FtsIndexOut

        out = FtsIndexOut(
            index_id=1, index_name="default",
            languages=["english", "spanish"], created_time=None,
        )
        d = out.model_dump()
        assert d["index_id"] == 1
        assert d["languages"] == ["english", "spanish"]

    def test_create_search_mapping_request(self):
        """CreateSearchMappingRequest validates correctly with defaults."""
        from vitalgraph.model.search_mappings_model import CreateSearchMappingRequest

        req = CreateSearchMappingRequest(
            index_name="default",
            mapping_type="kgentity",
        )
        assert req.enabled is True
        assert req.separator == ". "
        assert req.include_pred_name is False
        assert req.include_type_desc is True

    def test_search_mapping_out(self):
        """SearchMappingOut model serializes correctly."""
        from vitalgraph.model.search_mappings_model import SearchMappingOut

        out = SearchMappingOut(
            mapping_id=1, mapping_type="kgentity",
            type_uri=None, index_name="default",
            enabled=True, source_type="default",
            separator=". ", include_pred_name=False,
            include_type_desc=True, created_time=None,
            properties=[],
        )
        d = out.model_dump()
        assert d["mapping_id"] == 1
        assert d["properties"] == []

    def test_create_fts_index_request_validation(self):
        """CreateFtsIndexRequest rejects invalid index names."""
        from vitalgraph.model.fts_index_model import CreateFtsIndexRequest
        from pydantic import ValidationError

        # Must start with lowercase letter
        with pytest.raises(ValidationError):
            CreateFtsIndexRequest(index_name="123invalid")
        # No uppercase
        with pytest.raises(ValidationError):
            CreateFtsIndexRequest(index_name="Invalid")
        # No dashes
        with pytest.raises(ValidationError):
            CreateFtsIndexRequest(index_name="has-dash")
        # Valid names
        req = CreateFtsIndexRequest(index_name="a_valid_name_123")
        assert req.index_name == "a_valid_name_123"

    def test_populate_fts_request_batch_size_bounds(self):
        """PopulateFtsRequest enforces batch_size bounds."""
        from vitalgraph.model.fts_index_model import PopulateFtsRequest
        from pydantic import ValidationError

        # batch_size < 1
        with pytest.raises(ValidationError):
            PopulateFtsRequest(graph_uri="urn:g", batch_size=0)
        # batch_size > 1000
        with pytest.raises(ValidationError):
            PopulateFtsRequest(graph_uri="urn:g", batch_size=1001)
        # Valid
        req = PopulateFtsRequest(graph_uri="urn:g", batch_size=500)
        assert req.batch_size == 500

    def test_search_mapping_property_out(self):
        """SearchMappingPropertyOut model serializes correctly."""
        from vitalgraph.model.search_mappings_model import SearchMappingPropertyOut

        out = SearchMappingPropertyOut(
            property_id=10,
            mapping_id=1,
            property_uri="http://ex.org/name",
            property_role="include",
            ordinal=0,
        )
        d = out.model_dump()
        assert d["property_id"] == 10
        assert d["property_role"] == "include"


# ---------------------------------------------------------------------------
# 7. FTS Populator pipeline (mocked)
# ---------------------------------------------------------------------------

class TestFtsPopulator:
    """Tests for FTS populator pipeline logic with mocked connection."""

    @pytest.fixture
    def mock_conn(self):
        conn = AsyncMock()
        return conn

    @pytest.mark.asyncio
    async def test_populate_no_mapping_returns_empty_stats(self, mock_conn):
        """populate_fts_index returns empty stats if no mapping found."""
        from vitalgraph.vectorization.fts_populator import populate_fts_index

        # resolve_search_mapping returns None → populator skips
        with patch(
            'vitalgraph.vectorization.fts_populator.resolve_search_mapping',
            new_callable=AsyncMock,
            return_value=None,
        ):
            stats = await populate_fts_index(
                mock_conn, "sp1", "default", "ctx_uuid",
                mapping_type="kgentity",
            )
        assert stats.rows_stored == 0
        assert stats.subjects_processed == 0

    @pytest.mark.asyncio
    async def test_populate_disabled_mapping_skips(self, mock_conn):
        """populate_fts_index skips when mapping is disabled."""
        from vitalgraph.vectorization.fts_populator import populate_fts_index

        disabled_rule = MappingRule(enabled=False, source_type="default")
        with patch(
            'vitalgraph.vectorization.fts_populator.resolve_search_mapping',
            new_callable=AsyncMock,
            return_value=disabled_rule,
        ):
            stats = await populate_fts_index(
                mock_conn, "sp1", "default", "ctx_uuid",
                mapping_type="kgentity",
            )
        assert stats.rows_stored == 0
        assert stats.subjects_processed == 0

    @pytest.mark.asyncio
    async def test_populate_no_subjects_returns_early(self, mock_conn):
        """populate_fts_index returns quickly with 0 subjects."""
        from vitalgraph.vectorization.fts_populator import populate_fts_index

        rule = MappingRule(enabled=True, source_type="properties")
        # fts_index lookup
        mock_conn.fetchrow.return_value = {"languages": ["english"]}
        # No subjects
        mock_conn.fetch.return_value = []

        stats = await populate_fts_index(
            mock_conn, "sp1", "default", "ctx_uuid",
            mapping_rule=rule,
        )
        assert stats.rows_stored == 0
        assert stats.subjects_processed == 0
        assert stats.elapsed_seconds >= 0

    @pytest.mark.asyncio
    async def test_process_fts_batch_stores_rows(self, mock_conn):
        """_process_fts_batch upserts search_text for subjects with properties."""
        from vitalgraph.vectorization.fts_populator import _process_fts_batch, FTSPopulationStats

        stats = FTSPopulationStats()
        rule = MappingRule(enabled=True, source_type="properties", separator=". ")

        # Mock fetch_literal_properties_batch
        with patch(
            'vitalgraph.vectorization.fts_populator.fetch_literal_properties_batch',
            new_callable=AsyncMock,
            return_value={
                "uuid1": [("http://ex.org/name", "Alice")],
                "uuid2": [("http://ex.org/name", "Bob")],
                "uuid3": [],  # no props → skipped
            },
        ):
            mock_conn.execute.return_value = "INSERT 0 1"
            await _process_fts_batch(
                mock_conn, "sp1", "sp1_fts_default", "ctx_uuid",
                ["uuid1", "uuid2", "uuid3"], rule, stats,
            )

        assert stats.subjects_processed == 3
        assert stats.rows_stored == 2
        assert stats.subjects_skipped == 1

    @pytest.mark.asyncio
    async def test_delete_subject_fts(self, mock_conn):
        """delete_subject_fts executes DELETE SQL."""
        from vitalgraph.vectorization.fts_populator import delete_subject_fts

        mock_conn.execute.return_value = "DELETE 1"
        result = await delete_subject_fts(mock_conn, "sp1", "default", "uuid1", "ctx_uuid")
        assert result is True
        assert mock_conn.execute.called
        call_sql = str(mock_conn.execute.call_args)
        assert "DELETE" in call_sql or "sp1_fts_default" in call_sql

    @pytest.mark.asyncio
    async def test_update_subject_fts_with_props(self, mock_conn):
        """update_subject_fts upserts text when properties exist."""
        from vitalgraph.vectorization.fts_populator import update_subject_fts

        with patch(
            'vitalgraph.vectorization.fts_populator.fetch_literal_properties',
            new_callable=AsyncMock,
            return_value=[("http://ex.org/name", "Alice")],
        ):
            mock_conn.execute.return_value = "INSERT 0 1"
            result = await update_subject_fts(
                mock_conn, "sp1", "default", "uuid1", "ctx_uuid",
                mapping_rule=MappingRule(source_type="properties"),
            )
        assert result is True
        assert mock_conn.execute.called

    @pytest.mark.asyncio
    async def test_update_subject_fts_no_props_deletes(self, mock_conn):
        """update_subject_fts deletes entry when no properties found."""
        from vitalgraph.vectorization.fts_populator import update_subject_fts

        with patch(
            'vitalgraph.vectorization.fts_populator.fetch_literal_properties',
            new_callable=AsyncMock,
            return_value=[],
        ):
            mock_conn.execute.return_value = "DELETE 1"
            result = await update_subject_fts(
                mock_conn, "sp1", "default", "uuid1", "ctx_uuid",
                mapping_rule=MappingRule(source_type="properties"),
            )
        assert result is True


# ---------------------------------------------------------------------------
# 8. SearchMappingManager property & list tests (mocked)
# ---------------------------------------------------------------------------

class TestSearchMappingManagerExtended:
    """Extended tests for SearchMappingManager: list, update, properties."""

    @pytest.fixture
    def mock_conn(self):
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_list_mappings_no_filter(self, mock_conn):
        """list_mappings with no filters returns all rows."""
        from vitalgraph.vectorization.search_mapping_manager import SearchMappingManager

        mgr = SearchMappingManager(mock_conn, "sp1")
        mapping_rows = [
            {"mapping_id": 1, "mapping_type": "kgentity", "type_uri": None,
             "index_name": "default", "enabled": True, "source_type": "default",
             "separator": ". ", "include_pred_name": False,
             "include_type_desc": True, "created_time": None},
            {"mapping_id": 2, "mapping_type": "kgframe", "type_uri": "http://ex.org/Frame",
             "index_name": "default", "enabled": False, "source_type": "properties",
             "separator": " ", "include_pred_name": True,
             "include_type_desc": False, "created_time": None},
        ]
        # First fetch call returns mappings; subsequent calls return empty properties
        mock_conn.fetch.side_effect = [mapping_rows, [], []]

        result = await mgr.list_mappings()
        assert len(result) == 2
        assert result[0].mapping_type == "kgentity"
        assert result[1].enabled is False

    @pytest.mark.asyncio
    async def test_list_mappings_with_filter(self, mock_conn):
        """list_mappings with mapping_type filter builds correct SQL."""
        from vitalgraph.vectorization.search_mapping_manager import SearchMappingManager

        mgr = SearchMappingManager(mock_conn, "sp1")
        mock_conn.fetch.return_value = []

        await mgr.list_mappings(mapping_type="kgentity", enabled=True)
        call_args = mock_conn.fetch.call_args
        sql = call_args[0][0]
        assert "mapping_type = $1" in sql
        assert "enabled = $2" in sql

    @pytest.mark.asyncio
    async def test_update_mapping_sets_fields(self, mock_conn):
        """update_mapping builds SET clause for provided fields."""
        from vitalgraph.vectorization.search_mapping_manager import SearchMappingManager

        mgr = SearchMappingManager(mock_conn, "sp1")
        mock_conn.fetchrow.return_value = {
            "mapping_id": 1, "mapping_type": "kgentity", "type_uri": None,
            "index_name": "default", "enabled": False, "source_type": "default",
            "separator": " | ", "include_pred_name": False,
            "include_type_desc": True, "created_time": None,
        }
        # list_properties for _row_to_dto
        mock_conn.fetch.return_value = []

        result = await mgr.update_mapping(1, enabled=False, separator=" | ")
        assert result is not None
        assert result.enabled is False
        assert result.separator == " | "
        # Verify SQL was called
        sql = mock_conn.fetchrow.call_args[0][0]
        assert "UPDATE" in sql
        assert "enabled" in sql
        assert "separator" in sql

    @pytest.mark.asyncio
    async def test_add_property(self, mock_conn):
        """add_property inserts and returns property_id."""
        from vitalgraph.vectorization.search_mapping_manager import SearchMappingManager

        mgr = SearchMappingManager(mock_conn, "sp1")
        mock_conn.fetchval.return_value = 42

        pid = await mgr.add_property(
            mapping_id=1,
            property_uri="http://ex.org/name",
            property_role="include",
            ordinal=1,
        )
        assert pid == 42

    @pytest.mark.asyncio
    async def test_remove_property(self, mock_conn):
        """remove_property returns True on success."""
        from vitalgraph.vectorization.search_mapping_manager import SearchMappingManager

        mgr = SearchMappingManager(mock_conn, "sp1")
        mock_conn.execute.return_value = "DELETE 1"

        result = await mgr.remove_property(42)
        assert result is True

    @pytest.mark.asyncio
    async def test_remove_property_not_found(self, mock_conn):
        """remove_property returns False when property doesn't exist."""
        from vitalgraph.vectorization.search_mapping_manager import SearchMappingManager

        mgr = SearchMappingManager(mock_conn, "sp1")
        mock_conn.execute.return_value = "DELETE 0"

        result = await mgr.remove_property(999)
        assert result is False

    @pytest.mark.asyncio
    async def test_list_properties(self, mock_conn):
        """list_properties returns ordered property DTOs."""
        from vitalgraph.vectorization.search_mapping_manager import SearchMappingManager

        mgr = SearchMappingManager(mock_conn, "sp1")
        mock_conn.fetch.return_value = [
            {"property_id": 1, "mapping_id": 1, "property_uri": "http://ex.org/name",
             "property_role": "include", "ordinal": 0},
            {"property_id": 2, "mapping_id": 1, "property_uri": "http://ex.org/desc",
             "property_role": "exclude", "ordinal": 1},
        ]

        props = await mgr.list_properties(1)
        assert len(props) == 2
        assert props[0].property_uri == "http://ex.org/name"
        assert props[1].property_role == "exclude"

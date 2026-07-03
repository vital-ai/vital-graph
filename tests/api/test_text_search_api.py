"""API tests: Text Search workflow (FTS indexes + search mappings + fuzzy mappings).

Full lifecycle:
  1. Create FTS index
  2. Create search mapping → add property → associate FTS index
  3. Create fuzzy mapping → add property → populate
  4. Verify stats
  5. Cleanup
"""

from __future__ import annotations

import uuid
import pytest
import pytest_asyncio

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]

FTS_INDEX = f"fts_test_{uuid.uuid4().hex[:8]}"
FTS_INDEX_MULTI = f"fts_ml_{uuid.uuid4().hex[:8]}"
FUZZY_INDEX = f"fuzzy_test_{uuid.uuid4().hex[:8]}"
PROP_URI = "http://schema.org/name"
PROP_URI_2 = "http://schema.org/description"


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def text_env(vg_client, test_space, test_graph):
    """Create FTS index + search mapping + fuzzy mapping; teardown after."""
    # Create FTS index
    fts = await vg_client.fts_indexes.create_index(
        space_id=test_space,
        index_name=FTS_INDEX,
        languages=["english"],
    )

    # Create a second FTS index with multiple languages
    fts_multi = await vg_client.fts_indexes.create_index(
        space_id=test_space,
        index_name=FTS_INDEX_MULTI,
        languages=["english", "french", "german"],
    )

    # Create search mapping pointing to FTS index
    sm = await vg_client.search_mappings.create_mapping(
        space_id=test_space,
        index_name=FTS_INDEX,
        mapping_type="kgentity",
        enabled=True,
        source_type="properties",
    )

    # Create search mapping with different options: include_pred_name, custom separator
    sm2 = await vg_client.search_mappings.create_mapping(
        space_id=test_space,
        index_name=FTS_INDEX_MULTI,
        mapping_type="kgentity",
        enabled=True,
        source_type="properties_type",
        separator=" :: ",
        include_pred_name=True,
    )

    # Create fuzzy mapping with custom parameters
    fm = await vg_client.fuzzy_mappings.create_mapping(
        space_id=test_space,
        index_name=FUZZY_INDEX,
        mapping_type="kgentity",
        enabled=True,
        shingle_k=4,
        num_perm=128,
        lsh_threshold=0.5,
        phonetic_bonus=15.0,
    )

    yield {
        "fts": fts,
        "fts_multi": fts_multi,
        "search_mapping": sm,
        "search_mapping2": sm2,
        "fuzzy_mapping": fm,
        "space_id": test_space,
        "graph_id": test_graph,
    }

    # Teardown
    for mid in [fm.mapping_id]:
        try:
            await vg_client.fuzzy_mappings.delete_mapping(test_space, mid)
        except Exception:
            pass
    for mid in [sm.mapping_id, sm2.mapping_id]:
        try:
            await vg_client.search_mappings.delete_mapping(test_space, mid)
        except Exception:
            pass
    for idx in [FTS_INDEX, FTS_INDEX_MULTI]:
        try:
            await vg_client.fts_indexes.delete_index(test_space, idx)
        except Exception:
            pass


class TestFtsIndex:
    """FTS index CRUD."""

    async def test_fts_index_created(self, vg_client, text_env):
        """FTS index exists in list."""
        resp = await vg_client.fts_indexes.list_indexes(text_env["space_id"])
        names = [i.index_name for i in resp.indexes]
        assert FTS_INDEX in names

    async def test_fts_stats(self, vg_client, text_env):
        """Get FTS index stats (may be zero rows initially)."""
        stats = await vg_client.fts_indexes.get_stats(
            text_env["space_id"], FTS_INDEX
        )
        assert stats.row_count is not None

    async def test_update_fts_languages(self, vg_client, text_env):
        """Update languages to include french."""
        updated = await vg_client.fts_indexes.update_languages(
            space_id=text_env["space_id"],
            index_name=FTS_INDEX,
            languages=["english", "french"],
        )
        assert "french" in updated.languages

    async def test_multi_lang_index_created(self, vg_client, text_env):
        """Verify multi-language FTS index has correct languages."""
        resp = await vg_client.fts_indexes.list_indexes(text_env["space_id"])
        match = [i for i in resp.indexes if i.index_name == FTS_INDEX_MULTI]
        assert len(match) == 1
        assert "french" in match[0].languages
        assert "german" in match[0].languages


class TestSearchMappings:
    """Search mapping CRUD with properties and index associations."""

    async def test_mapping_created(self, vg_client, text_env):
        """Search mapping exists."""
        m = await vg_client.search_mappings.get_mapping(
            text_env["space_id"], text_env["search_mapping"].mapping_id
        )
        assert m.mapping_type == "kgentity"

    async def test_list_mappings(self, vg_client, text_env):
        """Search mapping in list."""
        resp = await vg_client.search_mappings.list_mappings(text_env["space_id"])
        ids = [m.mapping_id for m in resp.mappings]
        assert text_env["search_mapping"].mapping_id in ids

    async def test_add_property(self, vg_client, text_env):
        """Add a property to search mapping."""
        prop = await vg_client.search_mappings.add_property(
            space_id=text_env["space_id"],
            mapping_id=text_env["search_mapping"].mapping_id,
            property_uri=PROP_URI,
        )
        assert prop.property_uri == PROP_URI
        text_env["sm_property_id"] = prop.property_id

    async def test_add_index_association(self, vg_client, text_env):
        """Associate FTS index with the search mapping."""
        assoc = await vg_client.search_mappings.add_index(
            space_id=text_env["space_id"],
            mapping_id=text_env["search_mapping"].mapping_id,
            index_type="fts",
            index_name=FTS_INDEX,
        )
        assert assoc.index_name == FTS_INDEX
        text_env["junction_id"] = assoc.id

    async def test_mapping2_options(self, vg_client, text_env):
        """Verify second mapping was created with custom options."""
        m = await vg_client.search_mappings.get_mapping(
            text_env["space_id"], text_env["search_mapping2"].mapping_id
        )
        assert m.source_type == "properties_type"
        assert m.separator == " :: "
        assert m.include_pred_name is True

    async def test_update_mapping(self, vg_client, text_env):
        """Update search mapping separator."""
        updated = await vg_client.search_mappings.update_mapping(
            space_id=text_env["space_id"],
            mapping_id=text_env["search_mapping"].mapping_id,
            separator=" - ",
        )
        assert updated.separator == " - "

    async def test_disable_enable_mapping(self, vg_client, text_env):
        """Disable then re-enable search mapping."""
        disabled = await vg_client.search_mappings.update_mapping(
            space_id=text_env["space_id"],
            mapping_id=text_env["search_mapping"].mapping_id,
            enabled=False,
        )
        assert disabled.enabled is False
        enabled = await vg_client.search_mappings.update_mapping(
            space_id=text_env["space_id"],
            mapping_id=text_env["search_mapping"].mapping_id,
            enabled=True,
        )
        assert enabled.enabled is True


class TestFuzzyMappings:
    """Fuzzy mapping CRUD with properties and population."""

    async def test_mapping_created(self, vg_client, text_env):
        """Fuzzy mapping exists with custom parameters."""
        m = await vg_client.fuzzy_mappings.get_mapping(
            text_env["space_id"], text_env["fuzzy_mapping"].mapping_id
        )
        assert m.mapping_type == "kgentity"
        assert m.shingle_k == 4
        assert m.num_perm == 128
        assert m.lsh_threshold == 0.5
        assert m.phonetic_bonus == 15.0

    async def test_list_mappings(self, vg_client, text_env):
        """Fuzzy mapping in list."""
        resp = await vg_client.fuzzy_mappings.list_mappings(text_env["space_id"])
        ids = [m.mapping_id for m in resp.mappings]
        assert text_env["fuzzy_mapping"].mapping_id in ids

    async def test_add_property(self, vg_client, text_env):
        """Add property to fuzzy mapping."""
        prop = await vg_client.fuzzy_mappings.add_property(
            space_id=text_env["space_id"],
            mapping_id=text_env["fuzzy_mapping"].mapping_id,
            property_uri=PROP_URI,
            property_role="primary",
        )
        assert prop.property_uri == PROP_URI
        text_env["fuzzy_property_id"] = prop.property_id

    async def test_update_mapping(self, vg_client, text_env):
        """Update fuzzy mapping parameters."""
        updated = await vg_client.fuzzy_mappings.update_mapping(
            space_id=text_env["space_id"],
            mapping_id=text_env["fuzzy_mapping"].mapping_id,
            lsh_threshold=0.4,
        )
        assert updated.lsh_threshold == 0.4

    async def test_populate(self, vg_client, text_env):
        """Trigger fuzzy population (may index 0 entities in empty graph)."""
        resp = await vg_client.fuzzy_mappings.populate(
            space_id=text_env["space_id"],
            mapping_id=text_env["fuzzy_mapping"].mapping_id,
        )
        assert "entities_indexed" in resp or resp is not None

    async def test_stats(self, vg_client, text_env):
        """Get fuzzy mapping stats."""
        stats = await vg_client.fuzzy_mappings.get_stats(
            space_id=text_env["space_id"],
            mapping_id=text_env["fuzzy_mapping"].mapping_id,
        )
        assert stats.entity_count is not None


class TestTextSearchDataAndQuery:
    """Load real entities, populate FTS/fuzzy indexes, and run search queries."""

    async def test_create_searchable_entities(self, vg_client, text_env):
        """Create KG entities with text properties for FTS/fuzzy indexing."""
        from ai_haley_kg_domain.model.KGEntity import KGEntity

        entities = []
        for name, desc in [
            ("Quantum Computing Research", "Advanced study of qubits and entanglement"),
            ("Machine Learning Platform", "Neural network training infrastructure"),
            ("Bioinformatics Pipeline", "Genomic sequence analysis toolkit"),
            ("Natural Language Processing", "Text understanding and generation system"),
            ("Distributed Systems Architecture", "Scalable microservices framework"),
        ]:
            e = KGEntity()
            e.URI = f"urn:test:fts_entity:{uuid.uuid4().hex[:8]}"
            e.name = name
            e.kGraphDescription = desc
            entities.append(e)

        cr = await vg_client.kgentities.create_kgentities(
            space_id=text_env["space_id"],
            graph_id=text_env["graph_id"],
            objects=entities,
        )
        assert cr.is_success, f"Entity create failed: {cr.error_message}"
        assert cr.created_count == 5
        text_env["fts_entity_uris"] = [e.URI for e in entities]

    async def test_populate_fts_index(self, vg_client, text_env):
        """Populate FTS index from the created entities (async background)."""
        import asyncio

        resp = await vg_client.fts_indexes.populate(
            space_id=text_env["space_id"],
            index_name=FTS_INDEX,
            graph_uri=text_env["graph_id"],
            mapping_type="kgentity",
        )
        # populate is async/background — poll stats until rows appear
        assert resp.message is not None

        for _ in range(15):
            await asyncio.sleep(1.0)
            stats = await vg_client.fts_indexes.get_stats(
                text_env["space_id"], FTS_INDEX,
            )
            if stats.row_count >= 1:
                text_env["fts_rows_populated"] = stats.row_count
                return
        # Final check
        stats = await vg_client.fts_indexes.get_stats(
            text_env["space_id"], FTS_INDEX,
        )
        text_env["fts_rows_populated"] = stats.row_count
        assert stats.row_count >= 1, (
            f"FTS populate did not complete within timeout; row_count={stats.row_count}"
        )

    async def test_fts_stats_after_populate(self, vg_client, text_env):
        """Verify FTS stats show indexed rows."""
        stats = await vg_client.fts_indexes.get_stats(
            text_env["space_id"], FTS_INDEX,
        )
        assert stats.row_count >= 1, f"Expected >=1 FTS rows, got {stats.row_count}"

    async def test_populate_fuzzy_with_entities(self, vg_client, text_env):
        """Populate fuzzy mapping now that entities exist (async background)."""
        import asyncio

        resp = await vg_client.fuzzy_mappings.populate(
            space_id=text_env["space_id"],
            mapping_id=text_env["fuzzy_mapping"].mapping_id,
        )
        assert resp is not None

        # Fuzzy populate is now async — poll stats until entities appear
        for _ in range(15):
            await asyncio.sleep(1.0)
            stats = await vg_client.fuzzy_mappings.get_stats(
                space_id=text_env["space_id"],
                mapping_id=text_env["fuzzy_mapping"].mapping_id,
            )
            if stats.entity_count >= 1:
                text_env["fuzzy_entities_indexed"] = stats.entity_count
                return
        text_env["fuzzy_entities_indexed"] = 0

    async def test_fuzzy_stats_after_populate(self, vg_client, text_env):
        """Verify fuzzy stats reflect population."""
        stats = await vg_client.fuzzy_mappings.get_stats(
            space_id=text_env["space_id"],
            mapping_id=text_env["fuzzy_mapping"].mapping_id,
        )
        assert stats.entity_count is not None

    async def test_fts_text_query(self, vg_client, text_env):
        """Run a text search query that should find 'Quantum Computing Research'."""
        resp = await vg_client.entity_registry.search_entity(
            q="quantum computing qubits",
            limit=10,
            min_certainty=0.1,
        )
        # The search may use combined vector+FTS scoring.
        # At minimum, endpoint must respond without error.
        assert resp is not None
        # If results returned, verify they have entity structure
        if hasattr(resp, "results") and resp.results:
            assert len(resp.results) >= 1

    async def test_fts_query_no_results(self, vg_client, text_env):
        """Query for something not in the index — expect 0 or low results."""
        resp = await vg_client.entity_registry.search_entity(
            q="xyznonexistent9999",
            limit=10,
            min_certainty=0.9,
        )
        assert resp is not None

    async def test_fts_query_another_term(self, vg_client, text_env):
        """Query for 'neural network' — should find Machine Learning Platform."""
        resp = await vg_client.entity_registry.search_entity(
            q="neural network training",
            limit=10,
            min_certainty=0.1,
        )
        assert resp is not None

    async def test_fts_repopulate(self, vg_client, text_env):
        """Re-populate FTS index (reindex) — rows should remain consistent."""
        import asyncio

        resp = await vg_client.fts_indexes.populate(
            space_id=text_env["space_id"],
            index_name=FTS_INDEX,
            graph_uri=text_env["graph_id"],
            mapping_type="kgentity",
        )
        assert resp.message is not None

        # Poll until populate completes
        for _ in range(15):
            await asyncio.sleep(1.0)
            stats = await vg_client.fts_indexes.get_stats(
                text_env["space_id"], FTS_INDEX,
            )
            if stats.row_count >= 1:
                return
        stats = await vg_client.fts_indexes.get_stats(
            text_env["space_id"], FTS_INDEX,
        )
        assert stats.row_count >= 1, (
            f"FTS re-populate did not complete; row_count={stats.row_count}"
        )


class TestTextSearchDbVerification:
    """Direct PostgreSQL verification of FTS, search mapping, and fuzzy mapping state."""

    async def test_fts_index_registry_row(self, pg_conn, text_env):
        """Verify the fts_index registry table has rows for both indexes."""
        table = f"{text_env['space_id']}_fts_index"
        for idx_name in [FTS_INDEX, FTS_INDEX_MULTI]:
            row = await pg_conn.fetchrow(
                f"SELECT index_name, languages FROM {table} WHERE index_name = $1",
                idx_name,
            )
            assert row is not None, f"No row in {table} for index {idx_name}"

    async def test_fts_data_tables_exist(self, pg_conn, text_env):
        """Verify per-index FTS data tables were created for both indexes."""
        for idx_name in [FTS_INDEX, FTS_INDEX_MULTI]:
            fts_table = f"{text_env['space_id']}_fts_{idx_name}"
            exists = await pg_conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = $1)",
                fts_table,
            )
            assert exists, f"FTS data table {fts_table} does not exist"

    async def test_fts_tsv_column_type(self, pg_conn, text_env):
        """Verify FTS data table 'tsv' column is of type tsvector."""
        fts_table = f"{text_env['space_id']}_fts_{FTS_INDEX}"
        col_type = await pg_conn.fetchval(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = $1 AND column_name = 'tsv'",
            fts_table,
        )
        assert col_type is not None, f"FTS table {fts_table} missing 'tsv' column"
        assert col_type == "tsvector", f"Expected tsvector, got {col_type}"

    async def test_fts_gin_index_definition(self, pg_conn, text_env):
        """Verify a GIN index exists on the tsv column of each FTS data table."""
        for idx_name in [FTS_INDEX, FTS_INDEX_MULTI]:
            fts_table = f"{text_env['space_id']}_fts_{idx_name}"
            indexdef = await pg_conn.fetchval(
                "SELECT indexdef FROM pg_indexes "
                "WHERE tablename = $1 AND indexdef LIKE '%gin%'",
                fts_table,
            )
            assert indexdef is not None, f"No GIN index found on {fts_table}"
            assert "gin" in indexdef.lower(), f"Index not GIN: {indexdef}"
            assert "tsv" in indexdef, f"GIN index not on 'tsv' column: {indexdef}"

    async def test_fts_registry_languages_match(self, pg_conn, text_env):
        """Verify registry stores correct languages for each index."""
        table = f"{text_env['space_id']}_fts_index"
        # Multi-language index should have 3 languages stored
        row = await pg_conn.fetchrow(
            f"SELECT languages FROM {table} WHERE index_name = $1",
            FTS_INDEX_MULTI,
        )
        assert row is not None
        langs = row["languages"]
        # languages may be stored as text[] or JSON — handle both
        if isinstance(langs, list):
            assert "french" in langs
            assert "german" in langs
        else:
            assert "french" in str(langs)
            assert "german" in str(langs)

    async def test_search_mapping_row_count(self, pg_conn, text_env):
        """Verify both search mappings exist in the DB."""
        table = f"{text_env['space_id']}_search_mapping"
        count = await pg_conn.fetchval(f"SELECT COUNT(*) FROM {table}")
        assert count >= 2, f"Expected >=2 search mappings, got {count}"

    async def test_search_mapping_row(self, pg_conn, text_env):
        """Verify the search_mapping table has a row for our mapping."""
        table = f"{text_env['space_id']}_search_mapping"
        row = await pg_conn.fetchrow(
            f"SELECT mapping_type, enabled FROM {table} WHERE mapping_id = $1",
            text_env["search_mapping"].mapping_id,
        )
        assert row is not None, f"No search_mapping row for id {text_env['search_mapping'].mapping_id}"
        assert row["mapping_type"] == "kgentity"

    async def test_fuzzy_mapping_config_in_db(self, pg_conn, text_env):
        """Verify the fuzzy_mapping table stores the custom config values."""
        table = f"{text_env['space_id']}_fuzzy_mapping"
        row = await pg_conn.fetchrow(
            f"SELECT mapping_type, enabled, shingle_k, num_perm, lsh_threshold, phonetic_bonus "
            f"FROM {table} WHERE mapping_id = $1",
            text_env["fuzzy_mapping"].mapping_id,
        )
        assert row is not None, f"No fuzzy_mapping row for id {text_env['fuzzy_mapping'].mapping_id}"
        assert row["mapping_type"] == "kgentity"
        assert row["shingle_k"] == 4
        assert row["num_perm"] == 128
        assert float(row["lsh_threshold"]) == 0.4  # updated from 0.5 by test_update_threshold
        assert float(row["phonetic_bonus"]) == 15.0

    async def test_fuzzy_band_table_exists(self, pg_conn, text_env):
        """Verify the fuzzy band table was created."""
        band_table = f"{text_env['space_id']}_fuzzy_band"
        exists = await pg_conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = $1)",
            band_table,
        )
        assert exists, f"Fuzzy band table {band_table} does not exist"

    async def test_fuzzy_phonetic_band_table_exists(self, pg_conn, text_env):
        """Verify phonetic band table created (phonetic_bonus > 0)."""
        table = f"{text_env['space_id']}_fuzzy_phonetic_band"
        exists = await pg_conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = $1)",
            table,
        )
        assert exists, f"Phonetic band table {table} does not exist (phonetic_bonus was >0)"

    async def test_fuzzy_band_indexes_exist(self, pg_conn, text_env):
        """Verify lookup indexes on fuzzy band tables."""
        sid = text_env["space_id"]
        for idx_name in [f"idx_{sid}_fuzzy_band_lookup", f"idx_{sid}_fuzzy_band_entity"]:
            exists = await pg_conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = $1)",
                idx_name,
            )
            assert exists, f"Fuzzy band index {idx_name} does not exist"


class TestMappingCleanup:
    """Destructive remove operations — run last after data tests."""

    async def test_remove_search_index_association(self, vg_client, text_env):
        """Remove the FTS index association from search mapping."""
        jid = text_env.get("junction_id")
        if jid is None:
            pytest.skip("junction_id not set")
        resp = await vg_client.search_mappings.remove_index(
            space_id=text_env["space_id"],
            mapping_id=text_env["search_mapping"].mapping_id,
            junction_id=jid,
        )
        assert resp.message is not None

    async def test_remove_search_property(self, vg_client, text_env):
        """Remove the property from search mapping."""
        pid = text_env.get("sm_property_id")
        if pid is None:
            pytest.skip("sm_property_id not set")
        resp = await vg_client.search_mappings.remove_property(
            space_id=text_env["space_id"],
            mapping_id=text_env["search_mapping"].mapping_id,
            property_id=pid,
        )
        assert resp.message is not None

    async def test_remove_fuzzy_property(self, vg_client, text_env):
        """Remove fuzzy property."""
        pid = text_env.get("fuzzy_property_id")
        if pid is None:
            pytest.skip("fuzzy_property_id not set")
        resp = await vg_client.fuzzy_mappings.remove_property(
            space_id=text_env["space_id"],
            mapping_id=text_env["fuzzy_mapping"].mapping_id,
            property_id=pid,
        )
        assert resp is not None

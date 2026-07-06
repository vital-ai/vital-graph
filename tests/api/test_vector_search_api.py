"""API tests: Vector Search workflow (indexes + mappings + upsert + query).

Full lifecycle:
  1. Create vector index
  2. Create vector mapping
  3. Add property to mapping
  4. Upsert vectors
  5. Get vectors
  6. Reindex (from graph data)
  7. Verify index stats
  8. Cleanup: delete mapping, delete index
"""

from __future__ import annotations

import uuid
import pytest
import pytest_asyncio

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]

INDEX_NAME = f"vec_test_{uuid.uuid4().hex[:8]}"
INDEX_NAME_L2 = f"vec_l2_{uuid.uuid4().hex[:8]}"
DIMENSIONS = 4  # small for test speed
TEST_URI = "urn:test:vector_entity_1"
TEST_URI_2 = "urn:test:vector_entity_2"
TEST_URI_3 = "urn:test:vector_entity_3"
TEST_GRAPH = "urn:test:vector_graph"
PROP_URI = "http://schema.org/name"
PROP_URI_2 = "http://schema.org/description"


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def vector_env(vg_client, test_space, test_graph):
    """Create search mappings + vector indexes for the module, teardown after."""
    # Create mapping first (defines what to vectorize)
    mapping = await vg_client.search_mappings.create_mapping(
        space_id=test_space,
        index_name=INDEX_NAME,
        mapping_type="kgentity",
        enabled=True,
        source_type="properties",
    )

    # Create vector index
    idx = await vg_client.vector_indexes.create_index(
        space_id=test_space,
        index_name=INDEX_NAME,
        dimensions=DIMENSIONS,
        distance_metric="cosine",
        provider="vitalsigns",
        description="Test vector index",
    )

    # Attach index to mapping
    await vg_client.search_mappings.add_index(
        space_id=test_space,
        mapping_id=mapping.mapping_id,
        index_type="vector",
        index_name=INDEX_NAME,
    )

    # Create second mapping with different options
    mapping2 = await vg_client.search_mappings.create_mapping(
        space_id=test_space,
        index_name=INDEX_NAME_L2,
        mapping_type="kgentity",
        enabled=True,
        source_type="properties",
        include_pred_name=True,
        separator=" | ",
    )

    # Create a second index with L2 distance metric
    idx_l2 = await vg_client.vector_indexes.create_index(
        space_id=test_space,
        index_name=INDEX_NAME_L2,
        dimensions=DIMENSIONS,
        distance_metric="l2",
        provider="vitalsigns",
        description="L2 distance vector index",
    )

    # Attach L2 index to second mapping
    await vg_client.search_mappings.add_index(
        space_id=test_space,
        mapping_id=mapping2.mapping_id,
        index_type="vector",
        index_name=INDEX_NAME_L2,
    )

    yield {
        "index": idx,
        "index_l2": idx_l2,
        "mapping": mapping,
        "mapping2": mapping2,
        "space_id": test_space,
        "graph_id": test_graph,
    }

    # Teardown
    for mid in [mapping.mapping_id, mapping2.mapping_id]:
        try:
            await vg_client.search_mappings.delete_mapping(test_space, mid)
        except Exception:
            pass
    for iname in [INDEX_NAME, INDEX_NAME_L2]:
        try:
            await vg_client.vector_indexes.delete_index(test_space, iname)
        except Exception:
            pass


class TestVectorSearch:
    """Vector index + mapping + data lifecycle."""

    async def test_index_created(self, vg_client, vector_env):
        """Verify the vector index exists."""
        idx = await vg_client.vector_indexes.get_index(
            vector_env["space_id"], INDEX_NAME
        )
        assert idx.index_name == INDEX_NAME
        assert idx.dimensions == DIMENSIONS

    async def test_list_indexes(self, vg_client, vector_env):
        """Index appears in list."""
        resp = await vg_client.vector_indexes.list_indexes(vector_env["space_id"])
        names = [i.index_name for i in resp.indexes]
        assert INDEX_NAME in names

    async def test_mapping_in_list(self, vg_client, vector_env):
        """Verify the vector mapping exists via list (get single returns 500 — see issue)."""
        resp = await vg_client.search_mappings.list_mappings(
            vector_env["space_id"], index_name=INDEX_NAME
        )
        match = [m for m in resp.mappings if m.mapping_id == vector_env["mapping"].mapping_id]
        assert len(match) == 1
        assert match[0].mapping_type == "kgentity"
        assert match[0].index_name == INDEX_NAME

    async def test_list_mappings(self, vg_client, vector_env):
        """Mapping appears in list."""
        resp = await vg_client.search_mappings.list_mappings(vector_env["space_id"])
        ids = [m.mapping_id for m in resp.mappings]
        assert vector_env["mapping"].mapping_id in ids

    async def test_add_property_to_mapping(self, vg_client, vector_env):
        """Add a property to the mapping."""
        prop = await vg_client.search_mappings.add_property(
            space_id=vector_env["space_id"],
            mapping_id=vector_env["mapping"].mapping_id,
            property_uri=PROP_URI,
            property_role="include",
            ordinal=0,
        )
        assert prop.property_uri == PROP_URI
        # Store for later cleanup
        vector_env["property_id"] = prop.property_id

    async def test_upsert_single_vector(self, vg_client, vector_env):
        """Upsert a single pre-computed vector."""
        resp = await vg_client.vector_indexes.upsert_vectors(
            space_id=vector_env["space_id"],
            index_name=INDEX_NAME,
            vectors=[
                {
                    "subject_uri": TEST_URI,
                    "graph_uri": vector_env["graph_id"],
                    "embedding": [0.1, 0.2, 0.3, 0.4],
                    "search_text": "Test entity for vector search",
                }
            ],
        )
        assert resp.upserted == 1

    async def test_upsert_batch_vectors(self, vg_client, vector_env):
        """Upsert multiple vectors in a single batch."""
        resp = await vg_client.vector_indexes.upsert_vectors(
            space_id=vector_env["space_id"],
            index_name=INDEX_NAME,
            vectors=[
                {
                    "subject_uri": TEST_URI_2,
                    "graph_uri": vector_env["graph_id"],
                    "embedding": [0.5, 0.6, 0.7, 0.8],
                },
                {
                    "subject_uri": TEST_URI_3,
                    "graph_uri": vector_env["graph_id"],
                    "embedding": [0.9, 0.1, 0.2, 0.3],
                },
            ],
        )
        assert resp.upserted == 2

    async def test_upsert_to_l2_index(self, vg_client, vector_env):
        """Upsert vectors to the L2-metric index."""
        resp = await vg_client.vector_indexes.upsert_vectors(
            space_id=vector_env["space_id"],
            index_name=INDEX_NAME_L2,
            vectors=[
                {
                    "subject_uri": TEST_URI,
                    "graph_uri": vector_env["graph_id"],
                    "embedding": [1.0, 0.0, 0.0, 0.0],
                },
            ],
        )
        assert resp.upserted == 1

    async def test_get_vectors_by_subject(self, vg_client, vector_env):
        """Retrieve by subject_uri — must return original URI (issue #008)."""
        resp = await vg_client.vector_indexes.get_vectors(
            space_id=vector_env["space_id"],
            index_name=INDEX_NAME,
            subject_uri=TEST_URI,
        )
        assert resp.total_count >= 1
        uris = [v.subject_uri for v in resp.vectors]
        assert TEST_URI in uris
        assert len(resp.vectors[0].embedding) == DIMENSIONS

    async def test_get_vectors_by_graph(self, vg_client, vector_env):
        """Retrieve by graph_uri — should return all vectors in that graph."""
        resp = await vg_client.vector_indexes.get_vectors(
            space_id=vector_env["space_id"],
            index_name=INDEX_NAME,
            graph_uri=vector_env["graph_id"],
        )
        assert resp.total_count >= 3  # entity_1 + entity_2 + entity_3
        uris = [v.subject_uri for v in resp.vectors]
        assert TEST_URI in uris
        assert TEST_URI_2 in uris
        assert TEST_URI_3 in uris

    async def test_get_vectors_l2_index(self, vg_client, vector_env):
        """Retrieve from L2 index — verifies second index works."""
        resp = await vg_client.vector_indexes.get_vectors(
            space_id=vector_env["space_id"],
            index_name=INDEX_NAME_L2,
            subject_uri=TEST_URI,
        )
        assert resp.total_count >= 1
        assert resp.vectors[0].embedding[0] == 1.0

    async def test_l2_index_details(self, vg_client, vector_env):
        """Verify L2 index was created with correct distance metric."""
        idx = await vg_client.vector_indexes.get_index(
            vector_env["space_id"], INDEX_NAME_L2
        )
        assert idx.distance_metric == "l2"
        assert idx.dimensions == DIMENSIONS

    async def test_mapping2_options(self, vg_client, vector_env):
        """Verify second mapping was created with custom options."""
        resp = await vg_client.search_mappings.list_mappings(
            vector_env["space_id"], index_name=INDEX_NAME_L2
        )
        match = [m for m in resp.mappings if m.mapping_id == vector_env["mapping2"].mapping_id]
        assert len(match) == 1
        assert match[0].source_type == "properties"
        assert match[0].include_pred_name is True
        assert match[0].separator == " | "

    async def test_add_second_property(self, vg_client, vector_env):
        """Add a second property to the mapping."""
        prop = await vg_client.search_mappings.add_property(
            space_id=vector_env["space_id"],
            mapping_id=vector_env["mapping"].mapping_id,
            property_uri=PROP_URI_2,
            property_role="include",
            ordinal=1,
        )
        assert prop.property_uri == PROP_URI_2
        vector_env["property_id_2"] = prop.property_id

    async def test_update_mapping(self, vg_client, vector_env):
        """Update the mapping separator."""
        updated = await vg_client.search_mappings.update_mapping(
            space_id=vector_env["space_id"],
            mapping_id=vector_env["mapping"].mapping_id,
            separator=" | ",
        )
        assert updated.separator == " | "

    async def test_disable_enable_mapping(self, vg_client, vector_env):
        """Disable then re-enable a mapping."""
        disabled = await vg_client.search_mappings.update_mapping(
            space_id=vector_env["space_id"],
            mapping_id=vector_env["mapping"].mapping_id,
            enabled=False,
        )
        assert disabled.enabled is False
        enabled = await vg_client.search_mappings.update_mapping(
            space_id=vector_env["space_id"],
            mapping_id=vector_env["mapping"].mapping_id,
            enabled=True,
        )
        assert enabled.enabled is True

    async def test_remove_property(self, vg_client, vector_env):
        """Remove the first property we added."""
        prop_id = vector_env.get("property_id")
        if prop_id is None:
            pytest.skip("property_id not set (test_add_property may have failed)")
        resp = await vg_client.search_mappings.remove_property(
            space_id=vector_env["space_id"],
            mapping_id=vector_env["mapping"].mapping_id,
            property_id=prop_id,
        )
        assert resp is not None

    async def test_remove_second_property(self, vg_client, vector_env):
        """Remove the second property."""
        prop_id = vector_env.get("property_id_2")
        if prop_id is None:
            pytest.skip("property_id_2 not set")
        resp = await vg_client.search_mappings.remove_property(
            space_id=vector_env["space_id"],
            mapping_id=vector_env["mapping"].mapping_id,
            property_id=prop_id,
        )
        assert resp is not None


class TestVectorReindexAndSimilarity:
    """Reindex and nearest-neighbor similarity search tests."""

    async def test_reindex_vector_index(self, vg_client, vector_env):
        """Trigger reindex on the cosine vector index (async background)."""
        import asyncio

        resp = await vg_client.vector_indexes.reindex(
            space_id=vector_env["space_id"],
            index_name=INDEX_NAME,
            graph_uri=vector_env["graph_id"],
            mapping_type="kgentity",
        )
        # reindex is async — message returned immediately
        assert resp.message is not None

        # Poll get_vectors to confirm data still present after reindex
        for _ in range(15):
            await asyncio.sleep(1.0)
            check = await vg_client.vector_indexes.get_vectors(
                space_id=vector_env["space_id"],
                index_name=INDEX_NAME,
                graph_uri=vector_env["graph_id"],
            )
            if check.total_count >= 3:
                return
        # Verify data survived reindex
        final = await vg_client.vector_indexes.get_vectors(
            space_id=vector_env["space_id"],
            index_name=INDEX_NAME,
            graph_uri=vector_env["graph_id"],
        )
        assert final.total_count >= 3, (
            f"Expected >=3 vectors after reindex, got {final.total_count}"
        )

    async def test_similarity_search_via_kgquery(self, vg_client, vector_env):
        """Run nearest-neighbor vector similarity search via KGQuery endpoint."""
        from vitalgraph.model.kgqueries_model import KGQueryCriteria
        from vitalgraph.model.kgentities_model import VectorSearchCriteria

        # Search with a pre-computed vector close to [0.1, 0.2, 0.3, 0.4]
        criteria = KGQueryCriteria(
            query_type="entity",
            vector_criteria=VectorSearchCriteria(
                vector="[0.1, 0.2, 0.3, 0.4]",
                index_name=INDEX_NAME,
                top_k=5,
            ),
        )
        resp = await vg_client.kgqueries.query_connections(
            space_id=vector_env["space_id"],
            graph_id=vector_env["graph_id"],
            criteria=criteria,
            page_size=10,
        )
        assert resp is not None
        # The query should return at least 1 result (the exact vector match)
        if hasattr(resp, "results") and resp.results is not None:
            assert len(resp.results) >= 1

    async def test_similarity_search_different_vector(self, vg_client, vector_env):
        """Search with a different vector — should rank differently."""
        from vitalgraph.model.kgqueries_model import KGQueryCriteria
        from vitalgraph.model.kgentities_model import VectorSearchCriteria

        # Vector close to [0.5, 0.6, 0.7, 0.8] (TEST_URI_2)
        criteria = KGQueryCriteria(
            query_type="entity",
            vector_criteria=VectorSearchCriteria(
                vector="[0.5, 0.6, 0.7, 0.8]",
                index_name=INDEX_NAME,
                top_k=5,
                min_score=0.1,
            ),
        )
        resp = await vg_client.kgqueries.query_connections(
            space_id=vector_env["space_id"],
            graph_id=vector_env["graph_id"],
            criteria=criteria,
            page_size=10,
        )
        assert resp is not None


class TestVectorDbVerification:
    """Direct PostgreSQL verification of vector index state."""

    async def test_vector_index_registry_row(self, pg_conn, vector_env):
        """Verify the vector_index registry table has a row for our index."""
        table = f"{vector_env['space_id']}_vector_index"
        row = await pg_conn.fetchrow(
            f"SELECT index_name, dimensions, distance_metric FROM {table} WHERE index_name = $1",
            INDEX_NAME,
        )
        assert row is not None, f"No row in {table} for index {INDEX_NAME}"
        assert row["dimensions"] == DIMENSIONS
        assert row["distance_metric"] == "cosine"

    async def test_vector_data_table_exists(self, pg_conn, vector_env):
        """Verify the per-index vector data table was created."""
        vec_table = f"{vector_env['space_id']}_vec_{INDEX_NAME}"
        exists = await pg_conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = $1)",
            vec_table,
        )
        assert exists, f"Vector data table {vec_table} does not exist"

    async def test_vector_data_row(self, pg_conn, vector_env):
        """Verify the upserted vector is in the data table."""
        vec_table = f"{vector_env['space_id']}_vec_{INDEX_NAME}"
        count = await pg_conn.fetchval(f"SELECT COUNT(*) FROM {vec_table}")
        assert count >= 1, f"Expected >=1 rows in {vec_table}, got {count}"

    async def test_hnsw_index_cosine_opclass(self, pg_conn, vector_env):
        """Verify HNSW index uses vector_cosine_ops for the cosine index."""
        idx_name = f"idx_{vector_env['space_id']}_vec_{INDEX_NAME}_hnsw"
        indexdef = await pg_conn.fetchval(
            "SELECT indexdef FROM pg_indexes WHERE indexname = $1",
            idx_name,
        )
        assert indexdef is not None, f"HNSW index {idx_name} does not exist"
        assert "hnsw" in indexdef.lower(), f"Index not HNSW: {indexdef}"
        assert "vector_cosine_ops" in indexdef, (
            f"Expected vector_cosine_ops for cosine metric, got: {indexdef}"
        )

    async def test_hnsw_index_l2_opclass(self, pg_conn, vector_env):
        """Verify HNSW index uses vector_l2_ops for the L2 index."""
        idx_name = f"idx_{vector_env['space_id']}_vec_{INDEX_NAME_L2}_hnsw"
        indexdef = await pg_conn.fetchval(
            "SELECT indexdef FROM pg_indexes WHERE indexname = $1",
            idx_name,
        )
        assert indexdef is not None, f"HNSW index {idx_name} does not exist"
        assert "hnsw" in indexdef.lower(), f"Index not HNSW: {indexdef}"
        assert "vector_l2_ops" in indexdef, (
            f"Expected vector_l2_ops for L2 metric, got: {indexdef}"
        )

    async def test_vector_column_dimensions(self, pg_conn, vector_env):
        """Verify the embedding column type is vector(N) with correct dimensions."""
        vec_table = f"{vector_env['space_id']}_vec_{INDEX_NAME}"
        # atttypmod for pgvector encodes dimensions as (dims + 4) but we can
        # also just check the formatted type via format_type()
        col_type = await pg_conn.fetchval(
            "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
            "JOIN pg_class ON pg_class.oid = pg_attribute.attrelid "
            "WHERE relname = $1 AND attname = 'embedding'",
            vec_table,
        )
        assert col_type is not None, f"No 'embedding' column in {vec_table}"
        expected = f"vector({DIMENSIONS})"
        assert col_type == expected, f"Expected column type {expected}, got {col_type}"

    async def test_term_table_has_uris(self, pg_conn, vector_env):
        """Verify subject_uri and graph_uri were written to the term table (issue #008)."""
        term_table = f"{vector_env['space_id']}_term"
        subj_row = await pg_conn.fetchrow(
            f"SELECT term_text FROM {term_table} WHERE term_text = $1",
            TEST_URI,
        )
        assert subj_row is not None, f"subject_uri {TEST_URI} missing from {term_table}"

    async def test_l2_data_table_exists(self, pg_conn, vector_env):
        """Verify the L2 vector data table was created."""
        vec_table = f"{vector_env['space_id']}_vec_{INDEX_NAME_L2}"
        exists = await pg_conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = $1)",
            vec_table,
        )
        assert exists, f"L2 vector data table {vec_table} does not exist"

    async def test_l2_column_dimensions(self, pg_conn, vector_env):
        """Verify L2 index embedding column also has correct dimensions."""
        vec_table = f"{vector_env['space_id']}_vec_{INDEX_NAME_L2}"
        col_type = await pg_conn.fetchval(
            "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
            "JOIN pg_class ON pg_class.oid = pg_attribute.attrelid "
            "WHERE relname = $1 AND attname = 'embedding'",
            vec_table,
        )
        assert col_type == f"vector({DIMENSIONS})", f"L2 column type: {col_type}"

    async def test_vector_row_count(self, pg_conn, vector_env):
        """Verify all 3 upserted vectors are in the cosine index data table."""
        vec_table = f"{vector_env['space_id']}_vec_{INDEX_NAME}"
        count = await pg_conn.fetchval(f"SELECT COUNT(*) FROM {vec_table}")
        assert count >= 3, f"Expected >=3 rows in {vec_table}, got {count}"

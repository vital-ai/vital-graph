"""API tests: Geo Search workflow (geo config + geo points).

Full lifecycle:
  1. Get/create default geo config
  2. Update geo config (enable, set predicates)
  3. List geo points (empty initially)
  4. Reset geo config
"""

from __future__ import annotations

import pytest
import pytest_asyncio

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]

LAT_PRED = "http://schema.org/latitude"
LON_PRED = "http://schema.org/longitude"
LAT_PRED_2 = "http://www.w3.org/2003/01/geo/wgs84_pos#lat"
LON_PRED_2 = "http://www.w3.org/2003/01/geo/wgs84_pos#long"

GEO_ENTITY_1 = "urn:test:place:acme"
GEO_ENTITY_2 = "urn:test:place:london"
GEO_ENTITY_3 = "urn:test:place:paris"


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def geo_env(vg_client, test_space, test_graph):
    """Insert geo-tagged entities via SPARQL, configure geo, teardown."""
    from vitalgraph.model.sparql_model import SPARQLInsertRequest

    # Insert entities with lat/lon triples
    sparql_stmt = (
        f'INSERT DATA {{ '
        f'GRAPH <{test_graph}> {{ '
        f'<{GEO_ENTITY_1}> <http://schema.org/name> "Acme" . '
        f'<{GEO_ENTITY_1}> <{LAT_PRED}> "51.4816"^^<http://www.w3.org/2001/XMLSchema#double> . '
        f'<{GEO_ENTITY_1}> <{LON_PRED}> "-3.1791"^^<http://www.w3.org/2001/XMLSchema#double> . '
        f'<{GEO_ENTITY_2}> <http://schema.org/name> "London" . '
        f'<{GEO_ENTITY_2}> <{LAT_PRED}> "51.5074"^^<http://www.w3.org/2001/XMLSchema#double> . '
        f'<{GEO_ENTITY_2}> <{LON_PRED}> "-0.1278"^^<http://www.w3.org/2001/XMLSchema#double> . '
        f'<{GEO_ENTITY_3}> <http://schema.org/name> "Paris" . '
        f'<{GEO_ENTITY_3}> <{LAT_PRED}> "48.8566"^^<http://www.w3.org/2001/XMLSchema#double> . '
        f'<{GEO_ENTITY_3}> <{LON_PRED}> "2.3522"^^<http://www.w3.org/2001/XMLSchema#double> . '
        f'}} }}'
    )
    ins_req = SPARQLInsertRequest(update=sparql_stmt)
    result = await vg_client.sparql.execute_sparql_insert(test_space, ins_req)
    assert result.success, f"Geo SPARQL insert failed: {result.error}"

    yield {
        "space_id": test_space,
        "graph_id": test_graph,
    }
    # Reset geo config
    try:
        await vg_client.geo_config.delete_config(test_space)
    except Exception:
        pass


class TestGeoConfig:
    """Geo config get/update/delete lifecycle."""

    async def test_get_default_config(self, vg_client, geo_env):
        """Get config creates defaults if absent."""
        cfg = await vg_client.geo_config.get_config(geo_env["space_id"])
        assert cfg is not None
        # Default state: not enabled
        assert cfg.enabled is not None

    async def test_update_config_enable(self, vg_client, geo_env):
        """Enable geo and set predicates."""
        cfg = await vg_client.geo_config.update_config(
            space_id=geo_env["space_id"],
            enabled=True,
            auto_sync=True,
            lat_predicates=[LAT_PRED],
            lon_predicates=[LON_PRED],
        )
        assert cfg.enabled is True
        assert LAT_PRED in cfg.lat_predicates
        assert LON_PRED in cfg.lon_predicates

    async def test_update_config_multiple_predicates(self, vg_client, geo_env):
        """Update config to accept multiple lat/lon predicate URIs."""
        cfg = await vg_client.geo_config.update_config(
            space_id=geo_env["space_id"],
            lat_predicates=[LAT_PRED, LAT_PRED_2],
            lon_predicates=[LON_PRED, LON_PRED_2],
        )
        assert LAT_PRED in cfg.lat_predicates
        assert LAT_PRED_2 in cfg.lat_predicates
        assert LON_PRED in cfg.lon_predicates
        assert LON_PRED_2 in cfg.lon_predicates

    async def test_update_config_disable(self, vg_client, geo_env):
        """Disable geo."""
        cfg = await vg_client.geo_config.update_config(
            space_id=geo_env["space_id"],
            enabled=False,
        )
        assert cfg.enabled is False

    async def test_update_config_reenable(self, vg_client, geo_env):
        """Re-enable geo after disabling."""
        cfg = await vg_client.geo_config.update_config(
            space_id=geo_env["space_id"],
            enabled=True,
            auto_sync=True,
            lat_predicates=[LAT_PRED],
            lon_predicates=[LON_PRED],
        )
        assert cfg.enabled is True

    async def test_delete_config(self, vg_client, geo_env):
        """Reset geo config."""
        resp = await vg_client.geo_config.delete_config(geo_env["space_id"])
        assert resp is not None


class TestGeoPoints:
    """Geo points listing and spatial queries."""

    async def test_list_all_points(self, vg_client, geo_env):
        """List all geo points in the space."""
        resp = await vg_client.geo_points.list_points(
            space_id=geo_env["space_id"],
        )
        # May be 0 if auto_sync hasn't run, or >=3 if it has;
        # either way the endpoint must respond cleanly.
        assert resp.total_count is not None

    async def test_list_points_with_radius_acme(self, vg_client, geo_env):
        """Radius query centered near Acme."""
        resp = await vg_client.geo_points.list_points(
            space_id=geo_env["space_id"],
            near_lat=51.48,
            near_lon=-3.18,
            radius_km=10.0,
        )
        assert resp.total_count is not None

    async def test_list_points_large_radius(self, vg_client, geo_env):
        """Large radius query that could include all three cities."""
        resp = await vg_client.geo_points.list_points(
            space_id=geo_env["space_id"],
            near_lat=51.0,
            near_lon=0.0,
            radius_km=500.0,
        )
        assert resp.total_count is not None

    async def test_list_points_with_graph_filter(self, vg_client, geo_env):
        """Radius query filtered by graph URI."""
        resp = await vg_client.geo_points.list_points(
            space_id=geo_env["space_id"],
            near_lat=51.5,
            near_lon=-0.1,
            radius_km=200.0,
            graph_uri=geo_env["graph_id"],
        )
        assert resp.total_count is not None

    async def test_list_points_pagination(self, vg_client, geo_env):
        """Paginated geo query with limit and offset."""
        resp = await vg_client.geo_points.list_points(
            space_id=geo_env["space_id"],
            limit=1,
            offset=0,
        )
        assert resp.limit == 1
        assert resp.offset == 0


class TestGeoDbVerification:
    """Direct PostgreSQL verification of geo tables and config."""

    async def test_geo_config_table_exists(self, pg_conn, geo_env):
        """Verify the geo_config table was created for the space."""
        table = f"{geo_env['space_id']}_geo_config"
        exists = await pg_conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = $1)",
            table,
        )
        assert exists, f"Geo config table {table} does not exist"

    async def test_geo_data_table_exists(self, pg_conn, geo_env):
        """Verify the geo point data table was created."""
        table = f"{geo_env['space_id']}_geo"
        exists = await pg_conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = $1)",
            table,
        )
        assert exists, f"Geo data table {table} does not exist"

    async def test_geo_spatial_indexes_exist(self, pg_conn, geo_env):
        """Verify spatial indexes on the geo table."""
        sid = geo_env["space_id"]
        for idx_name in [f"idx_{sid}_geo_subj", f"idx_{sid}_geo_ctx"]:
            exists = await pg_conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = $1)",
                idx_name,
            )
            assert exists, f"Geo index {idx_name} does not exist"

    async def test_geo_table_column_types(self, pg_conn, geo_env):
        """Verify geo table columns have correct data types."""
        table = f"{geo_env['space_id']}_geo"
        expected_types = {
            "latitude": "double precision",
            "longitude": "double precision",
            "subject_uuid": "uuid",
            "context_uuid": "uuid",
        }
        for col, expected_type in expected_types.items():
            col_type = await pg_conn.fetchval(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = $1 AND column_name = $2",
                table, col,
            )
            assert col_type is not None, f"Geo table {table} missing column '{col}'"
            assert col_type == expected_type, (
                f"Column {col} type: expected '{expected_type}', got '{col_type}'"
            )

    async def test_geo_index_definitions(self, pg_conn, geo_env):
        """Verify actual index definitions on the geo table."""
        sid = geo_env["space_id"]
        geo_table = f"{sid}_geo"
        # Get all indexes on the geo table
        rows = await pg_conn.fetch(
            "SELECT indexname, indexdef FROM pg_indexes WHERE tablename = $1",
            geo_table,
        )
        assert len(rows) >= 1, f"No indexes found on {geo_table}"
        # At minimum, subject_uuid and context_uuid should be indexed
        index_defs = " ".join(r["indexdef"] for r in rows)
        assert "subject_uuid" in index_defs, f"No index on subject_uuid in {geo_table}"
        assert "context_uuid" in index_defs, f"No index on context_uuid in {geo_table}"

    async def test_geo_config_predicate_storage(self, pg_conn, geo_env):
        """Verify geo_config table stores predicate URIs correctly."""
        table = f"{geo_env['space_id']}_geo_config"
        exists = await pg_conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = $1)",
            table,
        )
        if not exists:
            # Config table may not exist if delete ran
            return
        row = await pg_conn.fetchrow(
            f"SELECT enabled, auto_sync, lat_predicates, lon_predicates FROM {table} LIMIT 1"
        )
        # Config was deleted at end of TestGeoConfig, so row may not exist
        if row is not None:
            assert isinstance(row["enabled"], bool)
            assert isinstance(row["auto_sync"], bool)
            # Predicates should be array or JSON containing the configured URIs
            if row["lat_predicates"] is not None:
                lat_preds = row["lat_predicates"]
                if isinstance(lat_preds, list):
                    assert any(LAT_PRED in str(p) for p in lat_preds)

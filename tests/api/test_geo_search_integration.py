"""API tests: Geo Search End-to-End integration via KGQuery geo_criteria.

Verifies the full geo pipeline: entity creation with KGGeoLocationSlot →
auto_sync geo population → KGQuery with geo_criteria using
vg:geoDistance / vg:withinRadius SPARQL functions.

Flow under test:
  1. Enable geo config with auto_sync=True
  2. Create 4 KGEntities at known locations (Bristol, London, Paris, New York)
     each with a KGGeoLocationSlot containing a WKT POINT value
  3. Wait for auto_sync to populate the geo table
  4. Verify geo points populated via list_points (sanity check)
  5. KGQuery entity queries with geo_criteria at increasing radii
  6. Verify distance ordering (nearest first) via sort_by_distance
  7. Cleanup

Known distances (approximate):
  - Bristol → London: ~190 km
  - Bristol → Paris:  ~470 km
  - Bristol → New York: ~5,300 km
  - London → Paris:  ~340 km
"""

from __future__ import annotations

import asyncio
import uuid
from typing import List

import pytest
import pytest_asyncio

from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGGeoLocationSlot import KGGeoLocationSlot
from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot

from vitalgraph.model.kgqueries_model import KGQueryCriteria
from vitalgraph.model.kgentities_model import GeoSearchCriteria

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]

NS = "urn:test:geo_integration:"

# Test locations with known coordinates
LOCATIONS = [
    {"name": "Bristol", "lat": 51.4545, "lon": -2.5879},
    {"name": "London", "lat": 51.5074, "lon": -0.1278},
    {"name": "Paris", "lat": 48.8566, "lon": 2.3522},
    {"name": "New York", "lat": 40.7128, "lon": -74.0060},
]

# Bristol center for radius searches
BRISTOL_LAT = 51.45
BRISTOL_LON = -2.59


def _create_entity_with_geo(name: str, lat: float, lon: float) -> List:
    """Create a KGEntity with a KGGeoLocationSlot containing WKT geo value.

    Returns [entity, frame, slot, entity→frame edge, frame→slot edge].
    """
    slug = name.lower().replace(" ", "_")
    suffix = uuid.uuid4().hex[:8]

    entity = KGEntity()
    entity.URI = f"{NS}entity/{slug}_{suffix}"
    entity.name = name

    frame = KGFrame()
    frame.URI = f"{NS}frame/{slug}_geo_{suffix}"

    slot = KGGeoLocationSlot()
    slot.URI = f"{NS}slot/{slug}_location_{suffix}"
    slot['http://vital.ai/ontology/haley-ai-kg#hasKGSlotType'] = \
        "http://vital.ai/ontology/haley-ai-kg#KGGeoLocationSlot"
    # WKT: POINT(longitude latitude) — standard WKT order
    wkt_value = f"POINT({lon} {lat})"
    slot['http://vital.ai/ontology/haley-ai-kg#hasGeoLocationSlotValue'] = wkt_value

    entity_frame_edge = Edge_hasEntityKGFrame()
    entity_frame_edge.URI = f"{NS}edge/{slug}_entity_frame_{suffix}"
    entity_frame_edge.edgeSource = entity.URI
    entity_frame_edge.edgeDestination = frame.URI

    frame_slot_edge = Edge_hasKGSlot()
    frame_slot_edge.URI = f"{NS}edge/{slug}_frame_slot_{suffix}"
    frame_slot_edge.edgeSource = frame.URI
    frame_slot_edge.edgeDestination = slot.URI

    return [entity, frame, slot, entity_frame_edge, frame_slot_edge]


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def geo_int_env(vg_client, test_space, test_graph):
    """Enable geo, create entities with geo slots, wait for population."""

    # ── 1. Enable geo config ─────────────────────────────────────────
    await vg_client.geo_config.update_config(
        space_id=test_space,
        enabled=True,
        auto_sync=True,
    )

    # ── 2. Create entities with geo slots ────────────────────────────
    all_objects = []
    entities = []
    for loc in LOCATIONS:
        objects = _create_entity_with_geo(loc["name"], loc["lat"], loc["lon"])
        entities.append(objects[0])  # keep the KGEntity ref
        all_objects.extend(objects)

    resp = await vg_client.kgentities.create_kgentities(
        test_space, test_graph, all_objects,
    )
    assert resp.is_success, f"Failed to create geo entities: {resp.error_message}"

    # ── 3. Wait for auto_sync to populate geo table ──────────────────
    for _ in range(20):
        await asyncio.sleep(1.5)
        check = await vg_client.geo_points.list_points(
            space_id=test_space,
            graph_uri=test_graph,
        )
        if check.total_count >= len(LOCATIONS):
            break

    yield {
        "space_id": test_space,
        "graph_id": test_graph,
        "entities": entities,
        "locations": LOCATIONS,
    }

    # ── Teardown ─────────────────────────────────────────────────────
    try:
        await vg_client.geo_config.delete_config(test_space)
    except Exception:
        pass


# ── Helpers ──────────────────────────────────────────────────────────

def _geo_entity_criteria(lat: float, lon: float, radius_km: float,
                         sort_by_distance: bool = False,
                         top_k: int = 20) -> KGQueryCriteria:
    """Build a KGQueryCriteria for entity query with geo_criteria."""
    return KGQueryCriteria(
        query_type="entity",
        geo_criteria=GeoSearchCriteria(
            latitude=lat,
            longitude=lon,
            radius_m=radius_km * 1000.0,
            sort_by_distance=sort_by_distance,
            top_k=top_k,
        ),
    )


class TestGeoPopulation:
    """Verify geo auto_sync populates points from KGGeoLocationSlots."""

    async def test_geo_points_populated(self, vg_client, geo_int_env):
        """After entity creation + auto_sync, all 4 locations should have geo points."""
        resp = await vg_client.geo_points.list_points(
            space_id=geo_int_env["space_id"],
            graph_uri=geo_int_env["graph_id"],
        )
        assert resp.total_count >= len(LOCATIONS), (
            f"Expected >={len(LOCATIONS)} geo points, got {resp.total_count}"
        )

    async def test_geo_points_have_coordinates(self, vg_client, geo_int_env):
        """Each geo point should have valid lat/lon values."""
        resp = await vg_client.geo_points.list_points(
            space_id=geo_int_env["space_id"],
            graph_uri=geo_int_env["graph_id"],
        )
        for pt in resp.points:
            assert -90 <= pt.latitude <= 90, f"Invalid latitude: {pt.latitude}"
            assert -180 <= pt.longitude <= 180, f"Invalid longitude: {pt.longitude}"


class TestGeoKGQuery:
    """KGQuery entity queries with geo_criteria (vg:withinRadius / vg:geoDistance)."""

    async def test_10km_from_bristol_finds_only_bristol(self, vg_client, geo_int_env):
        """10km radius from Bristol — only Bristol should be returned."""
        criteria = _geo_entity_criteria(BRISTOL_LAT, BRISTOL_LON, 10.0)
        resp = await vg_client.kgqueries.query_connections(
            space_id=geo_int_env["space_id"],
            graph_id=geo_int_env["graph_id"],
            criteria=criteria,
            page_size=20,
        )
        uris = resp.entity_uris or []
        bristol_uri = str(geo_int_env["entities"][0].URI)
        london_uri = str(geo_int_env["entities"][1].URI)

        assert bristol_uri in uris, (
            f"Expected Bristol entity in 10km results. Got: {uris}"
        )
        assert london_uri not in uris, "London should not be within 10km of Bristol"

    async def test_200km_from_bristol_finds_bristol_and_london(self, vg_client, geo_int_env):
        """200km radius from Bristol — Bristol + London, not Paris or NY."""
        criteria = _geo_entity_criteria(BRISTOL_LAT, BRISTOL_LON, 200.0)
        resp = await vg_client.kgqueries.query_connections(
            space_id=geo_int_env["space_id"],
            graph_id=geo_int_env["graph_id"],
            criteria=criteria,
            page_size=20,
        )
        uris = resp.entity_uris or []

        bristol_uri = str(geo_int_env["entities"][0].URI)
        london_uri = str(geo_int_env["entities"][1].URI)
        paris_uri = str(geo_int_env["entities"][2].URI)
        ny_uri = str(geo_int_env["entities"][3].URI)

        assert bristol_uri in uris, "Bristol should be within 200km"
        assert london_uri in uris, "London (~190km) should be within 200km"
        assert paris_uri not in uris, "Paris (~470km) should NOT be within 200km"
        assert ny_uri not in uris, "New York (~5300km) should NOT be within 200km"

    async def test_400km_from_channel_finds_three(self, vg_client, geo_int_env):
        """400km radius from English Channel — Bristol, London, Paris all within."""
        criteria = _geo_entity_criteria(50.0, 1.0, 400.0)
        resp = await vg_client.kgqueries.query_connections(
            space_id=geo_int_env["space_id"],
            graph_id=geo_int_env["graph_id"],
            criteria=criteria,
            page_size=20,
        )
        uris = resp.entity_uris or []

        bristol_uri = str(geo_int_env["entities"][0].URI)
        london_uri = str(geo_int_env["entities"][1].URI)
        paris_uri = str(geo_int_env["entities"][2].URI)
        ny_uri = str(geo_int_env["entities"][3].URI)

        assert bristol_uri in uris, "Bristol should be within 400km of Channel"
        assert london_uri in uris, "London should be within 400km of Channel"
        assert paris_uri in uris, "Paris should be within 400km of Channel"
        assert ny_uri not in uris, "New York should NOT be within 400km of Channel"

    async def test_6000km_finds_all(self, vg_client, geo_int_env):
        """6000km radius from Bristol — all 4 locations should be returned."""
        criteria = _geo_entity_criteria(BRISTOL_LAT, BRISTOL_LON, 6000.0)
        resp = await vg_client.kgqueries.query_connections(
            space_id=geo_int_env["space_id"],
            graph_id=geo_int_env["graph_id"],
            criteria=criteria,
            page_size=20,
        )
        uris = resp.entity_uris or []
        for i, loc in enumerate(LOCATIONS):
            entity_uri = str(geo_int_env["entities"][i].URI)
            assert entity_uri in uris, (
                f"{loc['name']} should be within 6000km, not found in results"
            )

    async def test_distance_ordering(self, vg_client, geo_int_env):
        """sort_by_distance=True should return entities nearest-first."""
        criteria = _geo_entity_criteria(
            BRISTOL_LAT, BRISTOL_LON, 6000.0, sort_by_distance=True,
        )
        resp = await vg_client.kgqueries.query_connections(
            space_id=geo_int_env["space_id"],
            graph_id=geo_int_env["graph_id"],
            criteria=criteria,
            page_size=20,
        )
        uris = resp.entity_uris or []
        assert len(uris) >= len(LOCATIONS), (
            f"Expected >={len(LOCATIONS)} entities, got {len(uris)}"
        )

        # Bristol should be first (nearest to search center)
        bristol_uri = str(geo_int_env["entities"][0].URI)
        assert uris[0] == bristol_uri, (
            f"Expected Bristol first (nearest), got {uris[0]}"
        )

        # New York should be last (farthest)
        ny_uri = str(geo_int_env["entities"][3].URI)
        test_uris = {str(e.URI) for e in geo_int_env["entities"]}
        test_results = [u for u in uris if u in test_uris]
        assert test_results[-1] == ny_uri, (
            f"Expected New York last (farthest), got {test_results[-1]}"
        )

    async def test_no_radius_returns_all_with_distance(self, vg_client, geo_int_env):
        """geo_criteria without radius_m computes distance but doesn't filter."""
        criteria = KGQueryCriteria(
            query_type="entity",
            geo_criteria=GeoSearchCriteria(
                latitude=BRISTOL_LAT,
                longitude=BRISTOL_LON,
                sort_by_distance=True,
                top_k=20,
            ),
        )
        resp = await vg_client.kgqueries.query_connections(
            space_id=geo_int_env["space_id"],
            graph_id=geo_int_env["graph_id"],
            criteria=criteria,
            page_size=20,
        )
        uris = resp.entity_uris or []
        # Without radius filter, all entities with geo data should appear
        assert len(uris) >= len(LOCATIONS), (
            f"Expected >={len(LOCATIONS)} entities without radius filter, got {len(uris)}"
        )

    async def test_count_only_with_geo(self, vg_client, geo_int_env):
        """count_only with geo_criteria returns correct total without URIs."""
        criteria = _geo_entity_criteria(BRISTOL_LAT, BRISTOL_LON, 200.0)
        resp = await vg_client.kgqueries.query_connections(
            space_id=geo_int_env["space_id"],
            graph_id=geo_int_env["graph_id"],
            criteria=criteria,
            page_size=20,
            count_only=True,
        )
        # Bristol + London within 200km
        assert resp.total_count >= 2, (
            f"Expected >=2 in count_only within 200km, got {resp.total_count}"
        )
        assert resp.entity_uris == [] or resp.entity_uris is None


class TestGeoSlotTarget:
    """KGQuery with geo_target='slot' + frame_criteria (slot-level geo path).

    This exercises the full entity→frame→slot traversal combined with
    vg:geoDistance(?slot_0_0, lat, lon) binding against the slot-keyed
    row in the geo table.
    """

    async def test_slot_target_with_frame_criteria(self, vg_client, geo_int_env):
        """geo_target='slot' + frame_criteria with KGGeoLocationSlot should find entities."""
        from vitalgraph.model.kgentities_model import FrameCriteria, SlotCriteria

        criteria = KGQueryCriteria(
            query_type="entity",
            frame_criteria=[
                FrameCriteria(
                    slot_criteria=[
                        SlotCriteria(
                            slot_type="http://vital.ai/ontology/haley-ai-kg#KGGeoLocationSlot",
                        ),
                    ],
                ),
            ],
            geo_criteria=GeoSearchCriteria(
                latitude=BRISTOL_LAT,
                longitude=BRISTOL_LON,
                radius_m=200_000.0,
                sort_by_distance=True,
                geo_target="slot",
            ),
        )
        resp = await vg_client.kgqueries.query_connections(
            space_id=geo_int_env["space_id"],
            graph_id=geo_int_env["graph_id"],
            criteria=criteria,
            page_size=20,
        )
        uris = resp.entity_uris or []
        bristol_uri = str(geo_int_env["entities"][0].URI)
        london_uri = str(geo_int_env["entities"][1].URI)

        assert bristol_uri in uris, (
            f"Expected Bristol in slot-level 200km results. Got: {uris}"
        )
        assert london_uri in uris, (
            f"Expected London in slot-level 200km results. Got: {uris}"
        )

    async def test_slot_target_distance_ordering(self, vg_client, geo_int_env):
        """geo_target='slot' with sort_by_distance should order correctly."""
        from vitalgraph.model.kgentities_model import FrameCriteria, SlotCriteria

        criteria = KGQueryCriteria(
            query_type="entity",
            frame_criteria=[
                FrameCriteria(
                    slot_criteria=[
                        SlotCriteria(
                            slot_type="http://vital.ai/ontology/haley-ai-kg#KGGeoLocationSlot",
                        ),
                    ],
                ),
            ],
            geo_criteria=GeoSearchCriteria(
                latitude=BRISTOL_LAT,
                longitude=BRISTOL_LON,
                radius_m=6_000_000.0,
                sort_by_distance=True,
                geo_target="slot",
            ),
        )
        resp = await vg_client.kgqueries.query_connections(
            space_id=geo_int_env["space_id"],
            graph_id=geo_int_env["graph_id"],
            criteria=criteria,
            page_size=20,
        )
        uris = resp.entity_uris or []
        assert len(uris) >= len(LOCATIONS), (
            f"Expected >={len(LOCATIONS)} entities in 6000km slot query, got {len(uris)}"
        )

        # Bristol should be first (nearest to search center)
        bristol_uri = str(geo_int_env["entities"][0].URI)
        assert uris[0] == bristol_uri, (
            f"Expected Bristol first (nearest) in slot-target query, got {uris[0]}"
        )

    async def test_entity_target_backward_compat(self, vg_client, geo_int_env):
        """geo_target='entity' (explicit) still works as before."""
        criteria = KGQueryCriteria(
            query_type="entity",
            geo_criteria=GeoSearchCriteria(
                latitude=BRISTOL_LAT,
                longitude=BRISTOL_LON,
                radius_m=200_000.0,
                sort_by_distance=True,
                geo_target="entity",
            ),
        )
        resp = await vg_client.kgqueries.query_connections(
            space_id=geo_int_env["space_id"],
            graph_id=geo_int_env["graph_id"],
            criteria=criteria,
            page_size=20,
        )
        uris = resp.entity_uris or []
        bristol_uri = str(geo_int_env["entities"][0].URI)
        assert bristol_uri in uris, (
            f"Expected Bristol with explicit entity geo_target. Got: {uris}"
        )


class TestGeoDualEntry:
    """Verify dual-entry in geo table: both slot-keyed and entity-keyed rows."""

    async def test_geo_table_has_dual_entries(self, vg_client, geo_int_env):
        """After auto_sync, each geo slot should produce 2 rows in geo table.

        With 4 entities * 1 geo slot each = 4 slot rows + 4 entity rows = 8 total.
        """
        resp = await vg_client.geo_points.list_points(
            space_id=geo_int_env["space_id"],
            graph_uri=geo_int_env["graph_id"],
            limit=50,
        )
        # Dual-entry: each entity has 1 slot → 2 rows per entity = 8 total
        assert resp.total_count >= len(LOCATIONS) * 2, (
            f"Expected >={len(LOCATIONS) * 2} geo rows (dual-entry), got {resp.total_count}"
        )

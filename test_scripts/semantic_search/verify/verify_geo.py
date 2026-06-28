"""Geo search verification via REST API and SPARQL."""

from test_scripts.semantic_search.config import TEST_SPACE_ID
from test_scripts.semantic_search.verify import SearchVerifier


async def test_geo_search(v: SearchVerifier):
    """Execute geo searches via SPARQL and REST API."""
    print("\n  --- Geo Search ---")
    client = v.client

    # REST API geo points list
    resp = await client.geo_points.list_points(space_id=TEST_SPACE_ID, limit=100)
    v.check("Geo points list returns results", resp.total_count >= 0)
    v.check("Geo point count >= 16", resp.total_count >= 16,
            f"total={resp.total_count}")

    # Radius search near NYC (REST API)
    resp2 = await client.geo_points.list_points(
        space_id=TEST_SPACE_ID,
        near_lat=40.73, near_lon=-74.00, radius_km=20)
    v.check("NYC radius search finds entities",
            resp2.total_count >= 3, f"count={resp2.total_count}")

    # Radius search near London (REST API)
    resp3 = await client.geo_points.list_points(
        space_id=TEST_SPACE_ID,
        near_lat=51.51, near_lon=-0.13, radius_km=20)
    v.check("London radius search finds entities",
            resp3.total_count >= 2, f"count={resp3.total_count}")

    # Radius search near Tokyo (REST API)
    resp4 = await client.geo_points.list_points(
        space_id=TEST_SPACE_ID,
        near_lat=35.68, near_lon=139.76, radius_km=20)
    v.check("Tokyo radius search finds entities",
            resp4.total_count >= 1, f"count={resp4.total_count}")

    # SPARQL geo search — radius near NYC (20km = 20000 meters)
    query = """PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
PREFIX core: <http://vital.ai/ontology/vital-core#>
SELECT ?entity ?name ?distance
WHERE {
  OPTIONAL { ?entity core:hasName ?name }
  BIND(vg:geoDistance(?entity, 40.73, -74.00) AS ?distance)
  FILTER(vg:withinRadius(?entity, 40.73, -74.00, 20000))
}
ORDER BY ?distance
LIMIT 10"""
    try:
        resp = await v.sparql(query)
        bindings = resp.results.get("bindings", []) if resp.results else []
        v.check("SPARQL geo radius NYC returns results",
                len(bindings) > 0, f"count={len(bindings)}")
    except Exception as e:
        v.check("SPARQL geo radius NYC", False, str(e))

    # Remote location (0,0) — should be empty
    resp5 = await client.geo_points.list_points(
        space_id=TEST_SPACE_ID, near_lat=0.0, near_lon=0.0, radius_km=1)
    v.check("Remote location (0,0) returns no results",
            resp5.total_count == 0, f"count={resp5.total_count}")

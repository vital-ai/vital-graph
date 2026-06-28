"""Entity Registry search verification — keyword, vector, geo, fuzzy."""

from test_scripts.semantic_search.config import (
    ER_ENTITY_TYPE_KEY, ER_ENTITIES,
)
from test_scripts.semantic_search.verify import SearchVerifier


async def test_entity_registry_search(v: SearchVerifier):
    """Test entity registry across all search modes."""
    print("\n  --- Entity Registry Search ---")
    reg = v.client.entity_registry

    # Keyword: list by type
    try:
        list_resp = await reg.search_entities(
            type_key=ER_ENTITY_TYPE_KEY, page_size=20)
        v.check("ER keyword: list by type succeeds",
                list_resp.success is True)
        v.check("ER keyword: has 3 test entities",
                len(list_resp.entities) >= len(ER_ENTITIES),
                f"count={len(list_resp.entities)}, expected>={len(ER_ENTITIES)}")
    except Exception as e:
        v.check("ER keyword: list by type", False, str(e))

    # Keyword: search by query string
    try:
        list_resp = await reg.search_entities(query="bakery", page_size=20)
        v.check("ER keyword: search 'bakery' succeeds",
                list_resp.success is True)
        v.check("ER keyword: 'bakery' finds results",
                len(list_resp.entities) > 0,
                f"count={len(list_resp.entities)}")
    except Exception as e:
        v.check("ER keyword: search 'bakery'", False, str(e))

    # Vector (semantic) search — "sourdough artisan bread"
    try:
        resp = await reg.search_entity(
            q="sourdough artisan bread", min_certainty=0.3, limit=10)
        v.check("ER vector: semantic search succeeds",
                resp.success is True)
        v.check("ER vector: finds bakery",
                len(resp.results) > 0, f"count={len(resp.results)}")
        if resp.results:
            names = [r.primary_name for r in resp.results]
            v.check("ER vector: top result is 'Sunrise Bakery'",
                    any("Sunrise" in n or "Bakery" in n for n in names),
                    f"names={names[:3]}")
    except Exception as e:
        v.check("ER vector: semantic search", False, str(e))

    # Vector search — "Japanese ramen noodles"
    try:
        resp = await reg.search_entity(
            q="Japanese ramen noodles", min_certainty=0.3, limit=10)
        v.check("ER vector: 'ramen noodles' succeeds",
                resp.success is True)
        v.check("ER vector: finds Tokyo Ramen",
                len(resp.results) > 0, f"count={len(resp.results)}")
    except Exception as e:
        v.check("ER vector: 'ramen noodles'", False, str(e))

    # Geo search near Brooklyn (40.68, -73.94)
    try:
        resp = await reg.search_entity(
            latitude=40.68, longitude=-73.94, radius_km=10, limit=10)
        v.check("ER geo: Brooklyn search succeeds",
                resp.success is True)
        v.check("ER geo: Brooklyn finds results",
                len(resp.results) > 0, f"count={len(resp.results)}")
    except Exception as e:
        v.check("ER geo: Brooklyn search", False, str(e))

    # Geo search near Tokyo (35.66, 139.70)
    try:
        resp = await reg.search_entity(
            latitude=35.66, longitude=139.70, radius_km=10, limit=10)
        v.check("ER geo: Tokyo search succeeds",
                resp.success is True)
        v.check("ER geo: Tokyo finds results",
                len(resp.results) > 0, f"count={len(resp.results)}")
    except Exception as e:
        v.check("ER geo: Tokyo search", False, str(e))

    # Combined semantic + geo — "fintech" near London
    try:
        resp = await reg.search_entity(
            q="fintech payment processing", latitude=51.52, longitude=-0.09,
            radius_km=10, min_certainty=0.1, limit=10)
        v.check("ER hybrid: semantic+geo London succeeds",
                resp.success is True)
        v.check("ER hybrid: London finds results",
                len(resp.results) > 0, f"count={len(resp.results)}")
    except Exception as e:
        v.check("ER hybrid: semantic+geo London", False, str(e))

    # Fuzzy search — "Sunris Bakry" (misspelled)
    try:
        resp = await reg.find_similar(
            name="Sunris Bakry", min_score=30.0, limit=10)
        v.check("ER fuzzy: 'Sunris Bakry' succeeds",
                resp.success is True)
        v.check("ER fuzzy: finds similar entities",
                len(resp.candidates) > 0, f"count={len(resp.candidates)}")
        if resp.candidates:
            top = resp.candidates[0]
            v.check("ER fuzzy: top result is relevant",
                    "sunrise" in top.primary_name.lower() or "bakery" in top.primary_name.lower(),
                    f"name={top.primary_name}")
    except Exception as e:
        v.check("ER fuzzy: 'Sunris Bakry'", False, str(e))

    # Fuzzy search — "Tokio Ramen" (misspelled)
    try:
        resp = await reg.find_similar(
            name="Tokio Ramen", min_score=20.0, limit=10)
        v.check("ER fuzzy: 'Tokio Ramen' succeeds",
                resp.success is True)
        v.check("ER fuzzy: finds Tokyo Ramen",
                len(resp.candidates) > 0, f"count={len(resp.candidates)}")
    except Exception as e:
        v.check("ER fuzzy: 'Tokio Raman'", False, str(e))

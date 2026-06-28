"""Keyword search & list verification for KG entities."""

from test_scripts.semantic_search.config import (
    TEST_SPACE_ID, TEST_GRAPH_ID,
    ENTITY_TYPE_RESTAURANT, ENTITY_TYPE_LANDMARK, ENTITY_TYPE_ARTICLE,
)
from test_scripts.semantic_search.verify import SearchVerifier


async def test_kgentities_list(v: SearchVerifier):
    """Verify loaded KG entities via list/search/filter."""
    print("\n  --- KGEntities: List & Keyword ---")
    client = v.client

    # List all entities (8 restaurants + 8 landmarks + 6 articles = 22)
    resp = await client.kgentities.list_kgentities(
        space_id=TEST_SPACE_ID, graph_id=TEST_GRAPH_ID, page_size=50)
    v.check("List all entities returns success", resp.is_success)
    v.check("Entity count >= 22", resp.total_count >= 22,
            f"total={resp.total_count}")

    # Keyword search by name
    resp2 = await client.kgentities.list_kgentities(
        space_id=TEST_SPACE_ID, graph_id=TEST_GRAPH_ID, search="pizza")
    v.check("Keyword search 'pizza' returns results",
            resp2.is_success and resp2.total_count > 0,
            f"total={resp2.total_count}")

    # Filter by entity type — restaurants
    resp3 = await client.kgentities.list_kgentities(
        space_id=TEST_SPACE_ID, graph_id=TEST_GRAPH_ID,
        entity_type_uri=ENTITY_TYPE_RESTAURANT, page_size=50)
    v.check("Filter by RestaurantEntity", resp3.total_count == 8,
            f"total={resp3.total_count}, expected=8")

    # Filter by entity type — landmarks
    resp4 = await client.kgentities.list_kgentities(
        space_id=TEST_SPACE_ID, graph_id=TEST_GRAPH_ID,
        entity_type_uri=ENTITY_TYPE_LANDMARK, page_size=50)
    v.check("Filter by LandmarkEntity", resp4.total_count == 8,
            f"total={resp4.total_count}, expected=8")

    # Filter by entity type — articles
    resp5 = await client.kgentities.list_kgentities(
        space_id=TEST_SPACE_ID, graph_id=TEST_GRAPH_ID,
        entity_type_uri=ENTITY_TYPE_ARTICLE, page_size=50)
    v.check("Filter by ArticleEntity", resp5.total_count == 6,
            f"total={resp5.total_count}, expected=6")

"""
Shared configuration for semantic search test scripts.
"""

TEST_SPACE_ID = "sp_semantic_search_test"
TEST_SPACE_NAME = "Semantic Search Test Space"
TEST_GRAPH_ID = "urn:semantic_search_test"

# Index names
VECTOR_INDEX_NAME = "entity_vector"
FTS_INDEX_NAME = "entity_fts"
FUZZY_INDEX_NAME = "entity_fuzzy"
HYBRID_INDEX_NAME = "entity_hybrid"

# Property URIs used in mappings
PROP_NAME = "http://vital.ai/ontology/vital-core#hasName"
PROP_DESCRIPTION = "http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription"
PROP_GEO_LOCATION = "http://vital.ai/ontology/haley-ai-kg#hasGeoLocationSlotValue"
PROP_TEXT_SLOT = "http://vital.ai/ontology/haley-ai-kg#hasTextSlotValue"

# Geo datatypes (used by geo populator for auto-detection)
GEO_DATATYPE_GEOLOCATION = "http://vital.ai/ontology/vital-core#geoLocation"
GEO_DATATYPE_WKT = "http://www.opengis.net/ont/geosparql#wktLiteral"

# KG Type URIs (stable, not random)
ENTITY_TYPE_RESTAURANT = "http://vital.ai/test/semantic/RestaurantEntity"
ENTITY_TYPE_LANDMARK = "http://vital.ai/test/semantic/LandmarkEntity"
ENTITY_TYPE_ARTICLE = "http://vital.ai/test/semantic/ArticleEntity"
FRAME_TYPE_LOCATION = "http://vital.ai/test/semantic/LocationFrame"
FRAME_TYPE_DESCRIPTION = "http://vital.ai/test/semantic/DescriptionFrame"
FRAME_TYPE_METADATA = "http://vital.ai/test/semantic/MetadataFrame"
SLOT_TYPE_CITY = "http://vital.ai/test/semantic/CitySlot"
SLOT_TYPE_COUNTRY = "http://vital.ai/test/semantic/CountrySlot"
SLOT_TYPE_SUMMARY = "http://vital.ai/test/semantic/SummarySlot"
SLOT_TYPE_CATEGORY = "http://vital.ai/test/semantic/CategorySlot"
SLOT_TYPE_YEAR = "http://vital.ai/test/semantic/YearSlot"
RELATION_TYPE_NEAR = "http://vital.ai/test/semantic/NearRelation"
RELATION_TYPE_MENTIONS = "http://vital.ai/test/semantic/MentionsRelation"

# KGDocument constants
DOCUMENT_TYPE_ARTICLE = "http://vital.ai/test/semantic/ArticleDocument"
DOCUMENT_SEGMENTS_INDEX = "document_segments"

# Test documents (inserted in step_03)
TEST_DOCUMENTS = [
    {
        "uri": "urn:semantic_test:doc:tokyo_food_guide",
        "name": "Tokyo Street Food Guide",
        "headline": "A Complete Guide to Tokyo Street Food",
        "content": (
            "# Introduction\n\n"
            "Tokyo is a paradise for food lovers. From ramen shops to sushi bars, "
            "the city offers an incredible variety of culinary experiences.\n\n"
            "## Ramen Culture\n\n"
            "Tonkotsu ramen is the most popular style in Tokyo. The rich pork bone "
            "broth is simmered for hours to achieve its creamy texture. Popular shops "
            "include Ichiran, Fuunji, and Afuri.\n\n"
            "## Sushi and Sashimi\n\n"
            "Tsukiji Outer Market remains a top destination for fresh sushi. "
            "Conveyor belt sushi (kaiten-zushi) offers affordable options for visitors.\n\n"
            "## Street Snacks\n\n"
            "Takoyaki (octopus balls), yakitori (grilled chicken skewers), and taiyaki "
            "(fish-shaped pastries) are essential street food experiences."
        ),
        "description": "Comprehensive guide to Tokyo street food covering ramen, sushi, and snacks",
    },
    {
        "uri": "urn:semantic_test:doc:nyc_pizza_history",
        "name": "The History of New York Pizza",
        "headline": "How Pizza Became NYC's Iconic Food",
        "content": (
            "# Origins\n\n"
            "New York-style pizza traces its roots to the early 1900s when Italian "
            "immigrants brought their recipes to Manhattan. Lombardi's, opened in 1905, "
            "is considered the first pizzeria in America.\n\n"
            "## The New York Slice\n\n"
            "Characterized by its large, foldable slices with a thin crust, New York "
            "pizza uses high-gluten bread flour and is cooked in coal or gas deck ovens. "
            "The water from NYC's municipal supply is often credited for the distinctive "
            "crust texture.\n\n"
            "## Famous Pizzerias\n\n"
            "Joe's Pizza in Greenwich Village, Di Fara in Brooklyn, and Prince Street "
            "Pizza are considered among the best in the city. Each has its own unique "
            "approach to the classic New York slice."
        ),
        "description": "Historical overview of New York pizza from Italian immigration to modern day",
    },
    {
        "uri": "urn:semantic_test:doc:london_architecture",
        "name": "London's Architectural Heritage",
        "headline": "From Roman Walls to The Shard",
        "content": (
            "# Roman and Medieval London\n\n"
            "London's architectural story begins with the Romans who built the first "
            "city walls around AD 200. The Tower of London, begun by William the "
            "Conqueror in 1066, remains one of the most iconic medieval structures.\n\n"
            "## Georgian and Victorian Era\n\n"
            "The Great Fire of 1666 led to a rebuilding boom. Sir Christopher Wren "
            "designed St Paul's Cathedral. The Victorian era brought grand railway "
            "stations like St Pancras and the Houses of Parliament.\n\n"
            "## Modern Architecture\n\n"
            "The Shard (2012), the Gherkin (2003), and the Walkie-Talkie (2014) "
            "transformed London's skyline. The city balances preservation of historic "
            "buildings with bold contemporary design."
        ),
        "description": "Survey of London architecture from Roman times to modern skyscrapers",
    },
]

# ---------------------------------------------------------------------------
# Entity Registry test data
# ---------------------------------------------------------------------------
ER_ENTITY_TYPE_KEY = "semantic_test_business"
ER_AGENT_TYPE_KEY = "semantic_test_bot"
ER_AGENT_URI = "urn:vital-ai:agent:semantic-test-bot-001"

# Entity Registry test entities (slug → definition)
ER_ENTITIES = [
    {
        "slug": "er_sunrise_bakery",
        "name": "Sunrise Bakery",
        "type_key": ER_ENTITY_TYPE_KEY,
        "description": "Artisan bakery specializing in sourdough and pastries in Brooklyn",
        "country": "US",
        "locality": "New York",
        "lat": 40.6782,
        "lon": -73.9442,
        "location_name": "Sunrise Brooklyn Store",
        "address": "456 Atlantic Avenue",
    },
    {
        "slug": "er_tokyo_ramen_house",
        "name": "Tokyo Ramen House",
        "type_key": ER_ENTITY_TYPE_KEY,
        "description": "Authentic tonkotsu ramen restaurant in Shibuya",
        "country": "JP",
        "locality": "Tokyo",
        "lat": 35.6595,
        "lon": 139.7004,
        "location_name": "Shibuya Main Shop",
        "address": "2-10 Dogenzaka",
    },
    {
        "slug": "er_london_fintech",
        "name": "London FinTech Solutions",
        "type_key": ER_ENTITY_TYPE_KEY,
        "description": "Financial technology company providing payment processing in the City of London",
        "country": "GB",
        "locality": "London",
        "lat": 51.5155,
        "lon": -0.0922,
        "location_name": "City Office",
        "address": "30 Moorgate",
    },
]

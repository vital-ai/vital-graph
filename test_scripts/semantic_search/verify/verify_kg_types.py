"""KG Type, Frame, and Document search verification via SPARQL."""

from test_scripts.semantic_search.config import (
    VECTOR_INDEX_NAME, ENTITY_TYPE_ARTICLE,
    FRAME_TYPE_LOCATION, FRAME_TYPE_DESCRIPTION,
)
from test_scripts.semantic_search.verify import SearchVerifier


async def test_kg_types(v: SearchVerifier):
    """Verify KG types are searchable via SPARQL."""
    print("\n  --- KG Type Search ---")

    # Query for entity types
    query = """PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
PREFIX core: <http://vital.ai/ontology/vital-core#>
SELECT ?type ?name
WHERE {
  ?type a haley:KGEntityType .
  OPTIONAL { ?type core:hasName ?name }
}
LIMIT 20"""
    try:
        resp = await v.sparql(query)
        bindings = resp.results.get("bindings", []) if resp.results else []
        v.check("KG Entity types query returns results",
                len(bindings) >= 3, f"count={len(bindings)}")
    except Exception as e:
        v.check("KG Entity types query", False, str(e))

    # Query for frame types
    query2 = """PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
PREFIX core: <http://vital.ai/ontology/vital-core#>
SELECT ?type ?name
WHERE {
  ?type a haley:KGFrameType .
  OPTIONAL { ?type core:hasName ?name }
}
LIMIT 20"""
    try:
        resp = await v.sparql(query2)
        bindings = resp.results.get("bindings", []) if resp.results else []
        v.check("KG Frame types query returns results",
                len(bindings) >= 3, f"count={len(bindings)}")
    except Exception as e:
        v.check("KG Frame types query", False, str(e))

    # Query for slot types
    query3 = """PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
PREFIX core: <http://vital.ai/ontology/vital-core#>
SELECT ?type ?name
WHERE {
  ?type a haley:KGSlotType .
  OPTIONAL { ?type core:hasName ?name }
}
LIMIT 20"""
    try:
        resp = await v.sparql(query3)
        bindings = resp.results.get("bindings", []) if resp.results else []
        v.check("KG Slot types query returns results",
                len(bindings) >= 5, f"count={len(bindings)}")
    except Exception as e:
        v.check("KG Slot types query", False, str(e))


async def test_kg_frames_documents(v: SearchVerifier):
    """Verify KG frames and documents (articles) are queryable."""
    print("\n  --- KG Frame & Document Search ---")

    # Query frames of type LocationFrame
    query = f"""PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
SELECT ?frame ?slot_value
WHERE {{
  ?frame a haley:KGFrame .
  ?frame haley:hasKGFrameType <{FRAME_TYPE_LOCATION}> .
  OPTIONAL {{ ?frame haley:hasTextSlotValue ?slot_value }}
}}
LIMIT 20"""
    try:
        resp = await v.sparql(query)
        bindings = resp.results.get("bindings", []) if resp.results else []
        v.check("LocationFrame query returns results",
                len(bindings) > 0, f"count={len(bindings)}")
    except Exception as e:
        v.check("LocationFrame query", False, str(e))

    # Query DescriptionFrame (text descriptions)
    query2 = f"""PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
SELECT ?frame ?text
WHERE {{
  ?frame a haley:KGFrame .
  ?frame haley:hasKGFrameType <{FRAME_TYPE_DESCRIPTION}> .
  OPTIONAL {{ ?frame haley:hasTextSlotValue ?text }}
}}
LIMIT 10"""
    try:
        resp = await v.sparql(query2)
        bindings = resp.results.get("bindings", []) if resp.results else []
        v.check("DescriptionFrame query returns results",
                len(bindings) > 0, f"count={len(bindings)}")
    except Exception as e:
        v.check("DescriptionFrame query", False, str(e))

    # Vector search specifically targeting articles (documents)
    # NOTE: No ORDER BY / LIMIT — avoids vg_optimize top-K rewrite which
    # would drive from the vector index globally and miss type-filtered entities.
    query3 = f"""PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
PREFIX core: <http://vital.ai/ontology/vital-core#>
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
SELECT ?entity ?name ?score
WHERE {{
  ?entity a haley:KGEntity .
  ?entity haley:hasKGEntityType <{ENTITY_TYPE_ARTICLE}> .
  OPTIONAL {{ ?entity core:hasName ?name }}
  BIND(vg:vectorSimilarity(?entity, "food culture culinary travel", "{VECTOR_INDEX_NAME}") AS ?score)
  FILTER(BOUND(?score))
  FILTER(?score > 0.1)
}}"""
    try:
        resp = await v.sparql(query3)
        bindings = resp.results.get("bindings", []) if resp.results else []
        v.check("Vector search on ArticleEntity returns results",
                len(bindings) > 0, f"count={len(bindings)}")
    except Exception as e:
        v.check("Vector search on ArticleEntity", False, str(e))

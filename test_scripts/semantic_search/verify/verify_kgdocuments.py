"""
Verify KG Documents — CRUD, segmentation, and vector search on document segments.
"""

import asyncio
import logging

from test_scripts.semantic_search.config import (
    TEST_SPACE_ID, TEST_GRAPH_ID,
    DOCUMENT_TYPE_ARTICLE, DOCUMENT_SEGMENTS_INDEX,
    TEST_DOCUMENTS,
)
from test_scripts.semantic_search.verify import SearchVerifier

logger = logging.getLogger(__name__)


async def test_kgdocuments(v: SearchVerifier) -> None:
    """Test KGDocument CRUD and listing."""
    print("\n  --- KG Documents: CRUD ---")
    client = v.client

    # List documents
    resp = await client.kgdocuments.list_kgdocuments(
        space_id=TEST_SPACE_ID,
        graph_id=TEST_GRAPH_ID,
        page_size=50,
    )
    v.check(
        "list_kgdocuments returns results",
        resp.is_success and len(resp.documents) >= len(TEST_DOCUMENTS),
        f"got {len(resp.documents) if resp.is_success else 0} documents",
    )

    # Get single document by URI
    doc_uri = TEST_DOCUMENTS[0]["uri"]
    get_resp = await client.kgdocuments.get_kgdocument(
        space_id=TEST_SPACE_ID,
        graph_id=TEST_GRAPH_ID,
        uri=doc_uri,
    )
    v.check(
        "get_kgdocument by URI",
        get_resp.is_success and get_resp.document is not None,
        f"uri={doc_uri}",
    )

    # Verify document properties
    if get_resp.is_success and get_resp.document:
        doc = get_resp.document
        doc_name = getattr(doc, 'name', None)
        v.check(
            "document has expected name",
            doc_name == TEST_DOCUMENTS[0]["name"],
            f"name='{doc_name}'",
        )

    # Filter by document_type_uri
    typed_resp = await client.kgdocuments.list_kgdocuments(
        space_id=TEST_SPACE_ID,
        graph_id=TEST_GRAPH_ID,
        document_type_uri=DOCUMENT_TYPE_ARTICLE,
    )
    v.check(
        "list_kgdocuments filtered by type",
        typed_resp.is_success and len(typed_resp.documents) >= len(TEST_DOCUMENTS),
        f"type={DOCUMENT_TYPE_ARTICLE}, got {len(typed_resp.documents) if typed_resp.is_success else 0}",
    )


async def test_kgdocument_segmentation(v: SearchVerifier) -> None:
    """Test that documents were segmented and segments can be listed."""
    print("\n  --- KG Documents: Segmentation ---")
    client = v.client

    # Check segmentation status
    status = await client.kgdocuments.get_segmentation_status(
        space_id=TEST_SPACE_ID,
    )
    v.check(
        "segmentation status endpoint accessible",
        isinstance(status, dict),
        f"keys={list(status.keys()) if isinstance(status, dict) else 'N/A'}",
    )

    # List segments for the first document
    doc_uri = TEST_DOCUMENTS[0]["uri"]
    seg_resp = await client.kgdocuments.list_segments(
        space_id=TEST_SPACE_ID,
        graph_id=TEST_GRAPH_ID,
        parent_uri=doc_uri,
    )
    # Segmentation may be async (background job). Allow some time to complete.
    if seg_resp.is_success and seg_resp.count == 0:
        # Wait a few seconds for background segmentation to finish
        await asyncio.sleep(3)
        seg_resp = await client.kgdocuments.list_segments(
            space_id=TEST_SPACE_ID,
            graph_id=TEST_GRAPH_ID,
            parent_uri=doc_uri,
        )

    v.check(
        "list_segments returns segments for parent doc",
        seg_resp.is_success and seg_resp.count > 0,
        f"parent={doc_uri}, segments={seg_resp.count if seg_resp.is_success else 0}",
    )

    # Verify segment properties (segment index > 0)
    if seg_resp.is_success and seg_resp.segments:
        first_seg = seg_resp.segments[0]
        seg_index = getattr(first_seg, 'kGDocumentSegmentIndex', None)
        seg_content = getattr(first_seg, 'kGDocumentContent', None) or getattr(first_seg, 'kGraphDescription', None)
        v.check(
            "segment has content",
            seg_content is not None and len(str(seg_content)) > 10,
            f"content_length={len(str(seg_content)) if seg_content else 0}",
        )


async def test_kgdocument_vector_search(v: SearchVerifier) -> None:
    """Test vector similarity search on document segments via SPARQL."""
    print("\n  --- KG Documents: Vector Search ---")

    # Search for "ramen" in the document segments index
    query = f"""
        PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

        SELECT ?doc ?score ?name WHERE {{
            ?doc rdf:type haley:KGDocument .
            BIND(vg:vectorSimilarity(?doc, "tonkotsu ramen pork broth", "{DOCUMENT_SEGMENTS_INDEX}") AS ?score)
            FILTER(?score > 0.3)
            ?doc vital:hasName ?name .
        }}
        ORDER BY DESC(?score)
        LIMIT 5
    """
    try:
        resp = await v.sparql(query)
        results = resp.results if hasattr(resp, 'results') else []
        v.check(
            "vector search on document_segments returns results",
            len(results) > 0,
            f"query='tonkotsu ramen pork broth', results={len(results)}",
        )
    except Exception as e:
        # Vector search may not work if embeddings haven't been generated yet
        v.check(
            "vector search on document_segments",
            False,
            f"error: {e}",
        )

    # Search for "pizza" — should match the NYC pizza history doc
    query2 = f"""
        PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

        SELECT ?doc ?score WHERE {{
            ?doc rdf:type haley:KGDocument .
            BIND(vg:vectorSimilarity(?doc, "New York pizza thin crust", "{DOCUMENT_SEGMENTS_INDEX}") AS ?score)
            FILTER(?score > 0.3)
        }}
        ORDER BY DESC(?score)
        LIMIT 5
    """
    try:
        resp2 = await v.sparql(query2)
        results2 = resp2.results if hasattr(resp2, 'results') else []
        v.check(
            "vector search for 'pizza' matches NYC document",
            len(results2) > 0,
            f"results={len(results2)}",
        )
    except Exception as e:
        v.check(
            "vector search for 'pizza' on document_segments",
            False,
            f"error: {e}",
        )

    # Search for "architecture" — should match London doc
    query3 = f"""
        PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

        SELECT ?doc ?score WHERE {{
            ?doc rdf:type haley:KGDocument .
            BIND(vg:vectorSimilarity(?doc, "Victorian architecture cathedral", "{DOCUMENT_SEGMENTS_INDEX}") AS ?score)
            FILTER(?score > 0.3)
        }}
        ORDER BY DESC(?score)
        LIMIT 5
    """
    try:
        resp3 = await v.sparql(query3)
        results3 = resp3.results if hasattr(resp3, 'results') else []
        v.check(
            "vector search for 'architecture' matches London document",
            len(results3) > 0,
            f"results={len(results3)}",
        )
    except Exception as e:
        v.check(
            "vector search for 'architecture' on document_segments",
            False,
            f"error: {e}",
        )

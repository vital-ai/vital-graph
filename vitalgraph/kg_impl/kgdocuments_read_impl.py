"""
KGDocuments READ Implementation for VitalGraph

This module provides READ operations for KGDocuments using SPARQL queries.
Implements GET, LIST, and segment listing with proper VitalSigns integration.

Follows the same pattern as kgtypes_read_impl.py.
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional, Tuple
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from .kg_backend_utils import KGBackendInterface
from .kg_graph_retrieval_utils import GraphObjectRetriever


# Managed segment type URIs (should not be returned in default listings)
_MANAGED_SEGMENT_TYPES = frozenset([
    "urn:segtype:segmentation_parent",
    "urn:segtype:markdown_section",
    "urn:segtype:text_chunk",
])

# KGDocument type URIs (including subclasses)
_KGDOCUMENT_TYPE_URIS = [
    "http://vital.ai/ontology/haley-ai-kg#KGDocument",
]

# Segment type predicate
_HAS_SEGMENT_TYPE_URI = "http://vital.ai/ontology/haley-ai-kg#hasKGDocumentSegmentTypeURI"


class KGDocumentsReadProcessor:
    """Processor for KGDocuments READ operations."""

    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.KGDocumentsReadProcessor")
        self.retriever = None

    def _ensure_retriever(self, backend):
        """Initialize retriever if not already done."""
        if self.retriever is None:
            self.retriever = GraphObjectRetriever(backend)

    async def get_kgdocument_by_uri(
        self, backend, space_id: str, graph_id: str, document_uri: str
    ) -> Optional[GraphObject]:
        """
        Get a single KGDocument by URI.

        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            document_uri: URI of the KGDocument to retrieve

        Returns:
            Optional[GraphObject]: KGDocument GraphObject or None if not found
        """
        try:
            self.logger.debug(f"Getting KGDocument by URI: {document_uri}")
            self._ensure_retriever(backend)

            triples = await self.retriever.get_object_triples(
                space_id, graph_id, document_uri, include_materialized_edges=False
            )

            if not triples:
                self.logger.debug(f"KGDocument not found: {document_uri}")
                return None

            graph_object = await asyncio.to_thread(GraphObject.from_triples, triples)
            if graph_object:
                self.logger.debug(f"Retrieved KGDocument: {document_uri} ({len(triples)} triples)")
            return graph_object

        except Exception as e:
            self.logger.error(f"Failed to get KGDocument {document_uri}: {e}")
            raise

    async def list_kgdocuments(
        self,
        backend,
        space_id: str,
        graph_id: str,
        page_size: int = 10,
        offset: int = 0,
        search: Optional[str] = None,
        include_segments: bool = False,
        document_type_uri: Optional[str] = None,
    ) -> Tuple[List[tuple], int]:
        """
        List KGDocuments with pagination and optional filtering.

        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            page_size: Number of documents per page
            offset: Number to skip
            search: Optional search text (matches name/headline/content)
            include_segments: If False (default), exclude segment/parent objects
            document_type_uri: Optional filter by kGDocumentType

        Returns:
            Tuple[List[Tuple], int]: (RDFLib triples, total count)
        """
        try:
            self.logger.debug(
                f"Listing KGDocuments (page_size={page_size}, offset={offset}, "
                f"search={search}, include_segments={include_segments})"
            )
            self._ensure_retriever(backend)

            # Build property filters to exclude managed segments by default
            property_filters = None
            if not include_segments:
                # Use a negative filter: exclude objects that have a managed segmentTypeURI
                property_filters = {
                    "_exclude_segment_types": True,
                }

            # Optionally filter by document_type_uri
            if document_type_uri:
                if property_filters is None:
                    property_filters = {}
                property_filters["document_type_uri"] = document_type_uri

            triples, total_count = await self.retriever.list_objects(
                space_id, graph_id, _KGDOCUMENT_TYPE_URIS,
                property_filters=property_filters,
                include_materialized_edges=False,
                page_size=page_size,
                offset=offset,
                search=search,
                include_count=True,
            )

            self.logger.debug(f"Listed {len(triples)} KGDocument triples (total: {total_count})")
            return triples, total_count

        except Exception as e:
            self.logger.error(f"Failed to list KGDocuments: {e}")
            raise

    async def list_segments(
        self,
        backend,
        space_id: str,
        graph_id: str,
        parent_uri: str,
    ) -> List[GraphObject]:
        """
        List all segments for a given parent/original document URI.

        Finds segments by URI prefix pattern ({parent_uri}_seg_*) and
        returns them ordered by segment index.

        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            parent_uri: URI of the parent copy or original document

        Returns:
            List[GraphObject]: Ordered list of segment GraphObjects
        """
        try:
            self.logger.debug(f"Listing segments for parent: {parent_uri}")
            self._ensure_retriever(backend)

            # Use SPARQL edge traversal to find segments.
            # Handles two cases via UNION:
            #   1. parent_uri is the ORIGINAL doc → two-hop: original → parent_copy → segments
            #   2. parent_uri is already a PARENT COPY → one-hop: parent_copy → segments
            sparql = f"""
                PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
                PREFIX vital: <http://vital.ai/ontology/vital-core#>

                SELECT DISTINCT ?seg WHERE {{
                    GRAPH <{graph_id}> {{
                        {{
                            ?e1 vital:hasEdgeSource <{parent_uri}> .
                            ?e1 vital:hasEdgeDestination ?parent_copy .
                            ?parent_copy haley:hasKGDocumentSegmentTypeURI <urn:segtype:segmentation_parent> .
                            ?e2 vital:hasEdgeSource ?parent_copy .
                            ?e2 vital:hasEdgeDestination ?seg .
                            ?seg haley:hasKGDocumentSegmentTypeURI ?segType .
                            FILTER(?segType != <urn:segtype:segmentation_parent>)
                        }} UNION {{
                            ?e3 vital:hasEdgeSource <{parent_uri}> .
                            ?e3 vital:hasEdgeDestination ?seg .
                            ?seg haley:hasKGDocumentSegmentTypeURI ?segType .
                            FILTER(?segType != <urn:segtype:segmentation_parent>)
                        }}
                    }}
                }}
                ORDER BY ?seg
            """
            results = await backend.execute_sparql_query(space_id, sparql)
            bindings = results.get("results", {}).get("bindings", [])

            segment_uris = [b["seg"]["value"] for b in bindings if "seg" in b]

            if not segment_uris:
                self.logger.debug(f"No segments found for {parent_uri}")
                return []

            # Get full triples for each segment
            grouped_triples = await self.retriever.get_objects_by_uris(
                space_id, graph_id, segment_uris, include_materialized_edges=False
            )

            # Flatten and convert
            all_triples = []
            for uri_triples in grouped_triples.values():
                all_triples.extend(uri_triples)

            if not all_triples:
                return []

            graph_objects = await asyncio.to_thread(GraphObject.from_triples_list, all_triples)

            # Sort by segment index
            def _seg_index(obj):
                idx = getattr(obj, "kGDocumentSegmentIndex", None)
                return idx if idx is not None else 999999

            graph_objects.sort(key=_seg_index)
            self.logger.debug(f"Found {len(graph_objects)} segments for {parent_uri}")
            return graph_objects

        except Exception as e:
            self.logger.error(f"Failed to list segments for {parent_uri}: {e}")
            raise

    async def get_document_graph(
        self,
        backend,
        space_id: str,
        graph_id: str,
        document_uri: str,
    ) -> List[GraphObject]:
        """
        Get the full document graph for a KGDocument URI.

        Returns the original document, parent copy (segmentation_parent),
        all segment KGDocuments, and the connecting Edge_hasKGDocumentSegment
        edges.

        Handles both cases:
        - document_uri is the original → retrieves original + parent + segments + edges
        - document_uri is a parent copy → retrieves parent + segments + edges

        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            document_uri: URI of the original or parent document

        Returns:
            List[GraphObject]: All objects in the document tree
        """
        try:
            self.logger.debug(f"Getting document graph for: {document_uri}")
            self._ensure_retriever(backend)

            # SPARQL: find the original doc, parent copy, all segments, and all edges
            sparql = f"""
                PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
                PREFIX vital: <http://vital.ai/ontology/vital-core#>

                SELECT DISTINCT ?obj WHERE {{
                    GRAPH <{graph_id}> {{
                        {{
                            # The document itself
                            BIND(<{document_uri}> AS ?obj)
                        }} UNION {{
                            # Edges from the document
                            ?obj vital:hasEdgeSource <{document_uri}> .
                            ?obj vital:vitaltype haley:Edge_hasKGDocumentSegment .
                        }} UNION {{
                            # Direct children (parent copies or segments)
                            ?edge vital:hasEdgeSource <{document_uri}> .
                            ?edge vital:vitaltype haley:Edge_hasKGDocumentSegment .
                            ?edge vital:hasEdgeDestination ?obj .
                        }} UNION {{
                            # Two-hop: original → parent_copy → segments
                            ?e1 vital:hasEdgeSource <{document_uri}> .
                            ?e1 vital:vitaltype haley:Edge_hasKGDocumentSegment .
                            ?e1 vital:hasEdgeDestination ?parent_copy .
                            ?parent_copy haley:hasKGDocumentSegmentTypeURI <urn:segtype:segmentation_parent> .
                            ?e2 vital:hasEdgeSource ?parent_copy .
                            ?e2 vital:vitaltype haley:Edge_hasKGDocumentSegment .
                            ?e2 vital:hasEdgeDestination ?obj .
                        }} UNION {{
                            # Two-hop edges (parent_copy → segment edges)
                            ?e1 vital:hasEdgeSource <{document_uri}> .
                            ?e1 vital:vitaltype haley:Edge_hasKGDocumentSegment .
                            ?e1 vital:hasEdgeDestination ?parent_copy .
                            ?parent_copy haley:hasKGDocumentSegmentTypeURI <urn:segtype:segmentation_parent> .
                            ?obj vital:hasEdgeSource ?parent_copy .
                            ?obj vital:vitaltype haley:Edge_hasKGDocumentSegment .
                        }}
                    }}
                }}
            """
            results = await backend.execute_sparql_query(space_id, sparql)
            bindings = results.get("results", {}).get("bindings", [])

            obj_uris = [b["obj"]["value"] for b in bindings if "obj" in b]

            if not obj_uris:
                self.logger.debug(f"No document graph found for {document_uri}")
                return []

            # Remove duplicates while preserving order
            seen = set()
            unique_uris = []
            for uri in obj_uris:
                if uri not in seen:
                    seen.add(uri)
                    unique_uris.append(uri)

            # Fetch full triples for all URIs
            grouped_triples = await self.retriever.get_objects_by_uris(
                space_id, graph_id, unique_uris, include_materialized_edges=False
            )

            all_triples = []
            for uri_triples in grouped_triples.values():
                all_triples.extend(uri_triples)

            if not all_triples:
                return []

            graph_objects = await asyncio.to_thread(GraphObject.from_triples_list, all_triples)
            self.logger.debug(
                f"Document graph for {document_uri}: {len(graph_objects)} objects"
            )
            return graph_objects

        except Exception as e:
            self.logger.error(f"Failed to get document graph for {document_uri}: {e}")
            raise

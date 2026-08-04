"""
KGRelations Read Implementation

This module contains the core implementation logic for KGRelation read/list operations.
It provides backend-agnostic functions for querying and retrieving relations.
"""

import logging
from typing import List, Dict, Any, Optional, Tuple

# VitalSigns imports
from vital_ai_vitalsigns.model.GraphObject import GraphObject

# Local imports
from .kg_backend_utils import KGBackendInterface
from .kg_graph_retrieval_utils import GraphObjectRetriever


class KGRelationsReadProcessor:
    """Processor for KGRelation read operations with backend abstraction."""
    
    def __init__(self, backend: KGBackendInterface):
        """
        Initialize with backend interface.
        
        Args:
            backend: Backend interface implementation
        """
        self.backend = backend
        self.logger = logging.getLogger(f"{__name__}.KGRelationsReadProcessor")
        self.retriever = GraphObjectRetriever(backend)
    
    async def list_relations(self, space_id: str, graph_id: str,
                           entity_source_uri: Optional[str] = None,
                           entity_destination_uri: Optional[str] = None,
                           relation_type_uri: Optional[str] = None,
                           direction: str = "outgoing",
                           page_size: int = 100,
                           offset: int = 0,
                           sort_by: Optional[str] = None,
                           sort_order: str = "asc") -> Tuple[List[Tuple], int, List[str]]:
        """
        List KG Relations with filtering and pagination.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_source_uri: Optional filter by source entity
            entity_destination_uri: Optional filter by destination entity
            relation_type_uri: Optional filter by relation type
            direction: Direction filter ("outgoing", "incoming", "both")
            page_size: Number of relations per page
            offset: Number of relations to skip
            
            sort_by: Optional property URI to order by, e.g.
                vital-core#hasListIndex. Relations without the property sort
                last, in both directions.
            sort_order: 'asc' or 'desc'

        Returns:
            Tuple of (RDFLib triples, total count, ordered relation URIs).
            The URI list is empty when no sort was requested; callers use it to
            restore ordering after rebuilding objects from triples.
        """
        try:
            self.logger.info(f"Listing KG Relations (page_size: {page_size}, offset: {offset})")
            
            # Define KGRelation type URI (relations are stored as Edge_hasKGRelation)
            type_uris = ["http://vital.ai/ontology/haley-ai-kg#Edge_hasKGRelation"]
            
            # Build property filters
            property_filters = {}
            
            if relation_type_uri:
                property_filters["http://vital.ai/ontology/haley-ai-kg#hasKGRelationType"] = relation_type_uri
            
            if entity_source_uri:
                property_filters["http://vital.ai/ontology/vital-core#hasEdgeSource"] = entity_source_uri
            
            if entity_destination_uri:
                property_filters["http://vital.ai/ontology/vital-core#hasEdgeDestination"] = entity_destination_uri
            
            # Note: direction filter is not yet supported in centralized retriever
            # For now, we'll ignore it and log a warning if it's not "outgoing"
            if direction != "outgoing":
                self.logger.warning(f"Direction filter '{direction}' not yet supported in centralized retriever, using 'outgoing'")
            
            if sort_by:
                # Sorted path: page ordered subject URIs first, then fetch their
                # triples. list_objects cannot be used here — its outer query
                # re-sorts by ?s and its fast path pages by subject_uuid, either
                # of which discards the requested order.
                ordered_uris, total_count = await self.retriever.list_object_uris_sorted(
                    space_id, graph_id, type_uris,
                    sort_by=sort_by, sort_order=sort_order,
                    property_filters=property_filters if property_filters else None,
                    page_size=page_size, offset=offset,
                )
                triples = []
                if ordered_uris:
                    # get_objects_by_uris returns Dict[subject_uri, triples],
                    # not a flat list. Flatten in page order so the triples
                    # themselves already follow the requested ordering.
                    grouped = await self.retriever.get_objects_by_uris(
                        space_id, graph_id, ordered_uris,
                        include_materialized_edges=False,
                    )
                    for uri in ordered_uris:
                        triples.extend(grouped.get(uri, []))
                self.logger.info(
                    f"✅ Listed {len(ordered_uris)} sorted relations (total: {total_count})")
                return triples, total_count, ordered_uris

            # Use centralized retriever (filters OUT materialized edges by default)
            triples, total_count = await self.retriever.list_objects(
                space_id, graph_id, type_uris,
                property_filters=property_filters if property_filters else None,
                include_materialized_edges=False,
                page_size=page_size,
                offset=offset,
                include_count=True
            )
            
            self.logger.info(f"✅ Listed {len(triples)} relation RDFLib triples (total: {total_count})")
            return triples, total_count, []
            
        except Exception as e:
            self.logger.error(f"❌ Failed to list KG Relations: {e}")
            raise
    
    async def get_relation_by_uri(self, space_id: str, graph_id: str, relation_uri: str) -> List[Tuple]:
        """
        Get a specific KG Relation by URI.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            relation_uri: URI of the relation to retrieve
            
        Returns:
            List[Tuple]: List of RDFLib triples for the relation
        """
        try:
            self.logger.info(f"Getting KG Relation: {relation_uri}")
            
            # Use centralized retriever (filters OUT materialized edges by default)
            triples = await self.retriever.get_object_triples(
                space_id, graph_id, relation_uri, include_materialized_edges=False
            )
            
            if not triples:
                self.logger.info(f"Relation not found: {relation_uri}")
                return []
            
            self.logger.info(f"✅ Retrieved relation with {len(triples)} triples")
            return triples
            
        except Exception as e:
            self.logger.error(f"❌ Failed to get KG Relation: {e}")
            raise

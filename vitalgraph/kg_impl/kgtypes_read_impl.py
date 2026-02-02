"""
KGTypes READ Implementation for VitalGraph

This module provides READ operations for KGTypes using SPARQL queries.
Implements GET, LIST, and batch GET operations with proper VitalSigns integration.
"""

import logging
from typing import List, Dict, Any, Optional, Tuple
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGType import KGType
from .kg_backend_utils import FusekiPostgreSQLBackendAdapter
from .kg_graph_retrieval_utils import GraphObjectRetriever


class KGTypesReadProcessor:
    """Processor for KGTypes READ operations."""
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.KGTypesReadProcessor")
        self.retriever = None  # Will be initialized when backend is available
    
    async def get_kgtype_by_uri(self, backend, space_id: str, graph_id: str, kgtype_uri: str) -> Optional[GraphObject]:
        """
        Get a single KGType by URI.
        
        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            kgtype_uri: URI of the KGType to retrieve
            
        Returns:
            Optional[GraphObject]: KGType GraphObject or None if not found
        """
        try:
            self.logger.info(f"🔍 Getting KGType by URI: {kgtype_uri}")
            
            # Initialize retriever if not already done
            if self.retriever is None:
                self.retriever = GraphObjectRetriever(backend)
            
            # Use centralized retriever (filters OUT materialized edges by default)
            triples = await self.retriever.get_object_triples(
                space_id, graph_id, kgtype_uri, include_materialized_edges=False
            )
            
            if not triples:
                self.logger.info(f"KGType not found: {kgtype_uri}")
                return None
            
            # Convert triples to VitalSigns GraphObject
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            
            # Log triples for debugging
            self.logger.info(f"🔍 Converting {len(triples)} triples to GraphObject for {kgtype_uri}")
            for i, triple in enumerate(triples[:5]):  # Log first 5 triples
                self.logger.info(f"  Triple {i+1}: {triple}")
            
            try:
                graph_object = GraphObject.from_triples(triples)
                if graph_object:
                    self.logger.info(f"✅ Successfully created GraphObject for {kgtype_uri}")
                    self.logger.info(f"  GraphObject type: {type(graph_object).__name__}")
                    self.logger.info(f"  GraphObject URI: {getattr(graph_object, 'URI', 'No URI attribute')}")
                else:
                    self.logger.warning(f"⚠️  GraphObject.from_triples returned None for {kgtype_uri}")
                    return None
            except Exception as e:
                self.logger.error(f"❌ Failed to convert triples to GraphObject for {kgtype_uri}: {e}")
                return None
            
            self.logger.info(f"✅ Retrieved KGType: {kgtype_uri} with {len(triples)} triples")
            return graph_object
            
        except Exception as e:
            self.logger.error(f"❌ Failed to get KGType {kgtype_uri}: {e}")
            raise
    
    async def get_kgtypes_by_uris(self, backend, space_id: str, graph_id: str, kgtype_uris: List[str]) -> List[GraphObject]:
        """
        Get multiple KGTypes by URIs.
        
        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            kgtype_uris: List of KGType URIs to retrieve
            
        Returns:
            List[GraphObject]: List of KGType GraphObjects (may be subclasses of KGType or KGType instances)
        """
        try:
            self.logger.info(f"🔍 Getting {len(kgtype_uris)} KGTypes by URIs")
            
            # Initialize retriever if not already done
            if self.retriever is None:
                self.retriever = GraphObjectRetriever(backend)
            
            # Use centralized retriever (filters OUT materialized edges by default)
            grouped_triples = await self.retriever.get_objects_by_uris(
                space_id, graph_id, kgtype_uris, include_materialized_edges=False
            )
            
            # Flatten grouped triples into a single list
            triples = []
            for uri, uri_triples in grouped_triples.items():
                triples.extend(uri_triples)
            
            # Handle empty triples list
            if not triples:
                self.logger.info(f"✅ No KGTypes found for the given URIs")
                return []
            
            # Convert RDFLib triples to VitalSigns GraphObjects
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            graph_objects = GraphObject.from_triples_list(triples)
            
            self.logger.info(f"✅ Retrieved {len(graph_objects)} KGType GraphObjects from {len(triples)} triples")
            return graph_objects
            
        except Exception as e:
            self.logger.error(f"❌ Failed to get KGTypes by URIs: {e}")
            raise
    
    async def list_kgtypes(self, backend, space_id: str, graph_id: str, 
                          page_size: int = 100, offset: int = 0, 
                          search: Optional[str] = None) -> Tuple[List[tuple], int]:
        """
        List KGTypes with pagination and optional search.
        
        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            page_size: Number of types per page
            offset: Number of types to skip
            search: Optional search text to filter types
            
        Returns:
            Tuple[List[Tuple], int]: (List of RDFLib triples (subject, predicate, object), total count)
        """
        try:
            self.logger.info(f"🔍 Listing KGTypes (page_size: {page_size}, offset: {offset}, search: {search})")
            
            # Initialize retriever if not already done
            if self.retriever is None:
                self.retriever = GraphObjectRetriever(backend)
            
            # Define KGType type URIs
            kgtype_uris = [
                "http://vital.ai/ontology/haley-ai-kg#KGType",
                "http://vital.ai/ontology/haley-ai-kg#KGEntityType",
                "http://vital.ai/ontology/haley-ai-kg#KGFrameType",
                "http://vital.ai/ontology/haley-ai-kg#KGRelationType",
                "http://vital.ai/ontology/haley-ai-kg#KGSlotType"
            ]
            
            # Use centralized retriever (filters OUT materialized edges by default)
            triples, total_count = await self.retriever.list_objects(
                space_id, graph_id, kgtype_uris,
                property_filters=None,
                include_materialized_edges=False,
                page_size=page_size,
                offset=offset,
                search=search,
                include_count=True
            )
            
            self.logger.info(f"✅ Listed {len(triples)} KGType RDFLib triples (total: {total_count})")
            return triples, total_count
            
        except Exception as e:
            self.logger.error(f"❌ Failed to list KGTypes: {e}")
            raise

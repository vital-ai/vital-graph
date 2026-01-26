"""
Fuseki-PostgreSQL Database Objects Layer

This module implements the database objects layer for the Fuseki-PostgreSQL hybrid backend.
It provides object-level abstraction using the two-phase query pattern:
1. Phase 1: Find subject URIs matching criteria
2. Phase 2: Retrieve complete objects for those URIs

Used by KGTypeImpl, ObjectsImpl, and other endpoint implementations.
"""

import logging
from typing import List, Dict, Any, Optional, Tuple

from .fuseki_query_utils import FusekiQueryUtils


class FusekiPostgreSQLDbObjects:
    """Database objects layer implementing the two-phase query pattern for Fuseki-PostgreSQL backend."""
    
    def __init__(self, space_impl):
        """
        Initialize the database objects layer.
        
        Args:
            space_impl: FusekiPostgreSQLSpaceImpl instance
        """
        self.space_impl = space_impl
        self.fuseki_manager = space_impl.fuseki_manager
        self.logger = logging.getLogger(f"{__name__}.FusekiPostgreSQLDbObjects")
        
        self.logger.info("Initialized FusekiPostgreSQLDbObjects with two-phase query architecture")
    
    async def list_objects(self, space_id: str, graph_id: Optional[str] = None, 
                          page_size: int = 100, offset: int = 0, 
                          filters: Optional[Dict[str, Any]] = None) -> Tuple[List[Any], int]:
        """
        List objects using two-phase query: find URIs then get complete objects.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier (defaults to "main")
            page_size: Number of objects per page
            offset: Offset for pagination
            filters: Dict with vitaltype_filter, search_text, subject_uri, etc.
            
        Returns:
            Tuple of (graph_objects: List[GraphObject], total_count: int)
        """
        try:
            # Default to main graph if not specified
            if graph_id is None:
                graph_id = "main"
            
            self.logger.info(f"Listing objects in space {space_id}, graph {graph_id} (page_size={page_size}, offset={offset})")
            
            # Phase 1: Find subject URIs matching criteria
            subject_uris, total_count = await FusekiQueryUtils.find_subject_uris_by_criteria(
                self.fuseki_manager, space_id, graph_id, filters, page_size, offset
            )
            
            if not subject_uris:
                self.logger.info(f"No objects found matching criteria")
                return [], total_count
            
            # Phase 2: Get complete objects for found URIs (with batching)
            triples = await FusekiQueryUtils.get_objects_batch_processing(
                self.fuseki_manager, space_id, subject_uris, graph_id
            )
            
            if not triples:
                self.logger.warning(f"No triples found for {len(subject_uris)} subject URIs")
                return [], total_count
            
            # Phase 3: Convert to VitalSigns GraphObjects
            from vital_ai_vitalsigns.vitalsigns import VitalSigns
            vitalsigns = VitalSigns()
            graph_objects = vitalsigns.from_triples_list(triples)
            
            self.logger.info(f"Successfully listed {len(graph_objects)} objects (total: {total_count})")
            return graph_objects, total_count
            
        except Exception as e:
            self.logger.error(f"Error listing objects: {e}")
            return [], 0
    
    async def get_objects_by_uris(self, space_id: str, uris: List[str], 
                                graph_id: Optional[str] = None) -> List[Any]:
        """
        Get multiple objects by URI list using batch processing.
        
        Args:
            space_id: Space identifier
            uris: List of subject URIs to retrieve
            graph_id: Graph identifier (defaults to "main")
            
        Returns:
            List of VitalSigns GraphObjects
        """
        try:
            # Default to main graph if not specified
            if graph_id is None:
                graph_id = "main"
            
            self.logger.info(f"Getting {len(uris)} objects by URIs in space {space_id}, graph {graph_id}")
            
            if not uris:
                self.logger.debug("No URIs provided, returning empty list")
                return []
            
            # Use batch processing to retrieve objects
            triples = await FusekiQueryUtils.get_objects_batch_processing(
                self.fuseki_manager, space_id, uris, graph_id
            )
            
            if not triples:
                self.logger.warning(f"No triples found for {len(uris)} URIs")
                return []
            
            # Convert to VitalSigns GraphObjects
            from vital_ai_vitalsigns.vitalsigns import VitalSigns
            vitalsigns = VitalSigns()
            graph_objects = vitalsigns.from_triples_list(triples)
            
            self.logger.info(f"Successfully retrieved {len(graph_objects)} objects from {len(triples)} triples")
            return graph_objects
            
        except Exception as e:
            self.logger.error(f"Error getting objects by URIs: {e}")
            return []
    
    async def get_objects_by_uris_batch(self, space_id: str, subject_uris: List[str], 
                                      graph_id: Optional[str] = None) -> List[Tuple[str, str, str, str]]:
        """
        Get objects as raw quads (used by KGTypeImpl pattern for compatibility).
        
        Args:
            space_id: Space identifier
            subject_uris: List of subject URIs to retrieve
            graph_id: Graph identifier (defaults to "main")
            
        Returns:
            List of (subject, predicate, object, graph) quads
        """
        try:
            # Default to main graph if not specified
            if graph_id is None:
                graph_id = "main"
            
            self.logger.info(f"Getting {len(subject_uris)} objects as quads in space {space_id}, graph {graph_id}")
            
            if not subject_uris:
                self.logger.debug("No subject URIs provided, returning empty list")
                return []
            
            # Use batch processing to retrieve triples
            triples = await FusekiQueryUtils.get_objects_batch_processing(
                self.fuseki_manager, space_id, subject_uris, graph_id
            )
            
            if not triples:
                self.logger.warning(f"No triples found for {len(subject_uris)} subject URIs")
                return []
            
            # Convert to quad format expected by existing code (add graph context)
            graph_uri = FusekiQueryUtils.build_graph_uri(space_id, graph_id)
            quads = [(s, p, o, graph_uri) for s, p, o in triples]
            
            self.logger.info(f"Successfully retrieved {len(quads)} quads for {len(subject_uris)} subjects")
            return quads
            
        except Exception as e:
            self.logger.error(f"Error getting objects as quads: {e}")
            return []
    
    async def get_existing_object_uris(self, space_id: str, uris: List[str]) -> List[str]:
        """
        Check which URIs exist by querying for any triple with those subjects.
        
        Args:
            space_id: Space identifier
            uris: List of URIs to check for existence
            
        Returns:
            List of URIs that exist in the space
        """
        try:
            self.logger.info(f"Checking existence of {len(uris)} URIs in space {space_id}")
            
            if not uris:
                self.logger.debug("No URIs provided for existence check")
                return []
            
            # Use FusekiQueryUtils to check URI existence
            existing_uris = await FusekiQueryUtils.check_uris_exist(
                self.fuseki_manager, space_id, uris
            )
            
            self.logger.info(f"URI existence check complete: {len(existing_uris)}/{len(uris)} URIs exist")
            return existing_uris
            
        except Exception as e:
            self.logger.error(f"Error checking URI existence: {e}")
            return []
    
    async def get_object_by_uri(self, space_id: str, uri: str, 
                              graph_id: Optional[str] = None) -> Optional[Any]:
        """
        Get a single object by URI.
        
        Args:
            space_id: Space identifier
            uri: Subject URI to retrieve
            graph_id: Graph identifier (defaults to "main")
            
        Returns:
            VitalSigns GraphObject or None if not found
        """
        try:
            # Default to main graph if not specified
            if graph_id is None:
                graph_id = "main"
            
            self.logger.info(f"Getting single object by URI {uri} in space {space_id}, graph {graph_id}")
            
            # Use get_objects_by_uris with single URI
            objects = await self.get_objects_by_uris(space_id, [uri], graph_id)
            
            if objects:
                self.logger.info(f"Successfully retrieved object {uri}")
                return objects[0]
            else:
                self.logger.info(f"Object {uri} not found")
                return None
                
        except Exception as e:
            self.logger.error(f"Error getting object by URI {uri}: {e}")
            return None
    
    async def count_objects(self, space_id: str, graph_id: Optional[str] = None, 
                          filters: Optional[Dict[str, Any]] = None) -> int:
        """
        Count objects matching criteria without retrieving them.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier (defaults to "main")
            filters: Dict with vitaltype_filter, search_text, etc.
            
        Returns:
            Total count of matching objects
        """
        try:
            # Default to main graph if not specified
            if graph_id is None:
                graph_id = "main"
            
            self.logger.info(f"Counting objects in space {space_id}, graph {graph_id}")
            
            # Use Phase 1 query with large page size to get total count
            # We don't need the URIs, just the count
            _, total_count = await FusekiQueryUtils.find_subject_uris_by_criteria(
                self.fuseki_manager, space_id, graph_id, filters, page_size=1, offset=0
            )
            
            self.logger.info(f"Object count: {total_count}")
            return total_count
            
        except Exception as e:
            self.logger.error(f"Error counting objects: {e}")
            return 0
    
    async def search_objects(self, space_id: str, search_text: str, 
                           graph_id: Optional[str] = None, 
                           vitaltype_filter: Optional[str] = None,
                           page_size: int = 100, offset: int = 0) -> Tuple[List[Any], int]:
        """
        Search objects by text across all properties.
        
        Args:
            space_id: Space identifier
            search_text: Text to search for
            graph_id: Graph identifier (defaults to "main")
            vitaltype_filter: Optional vitaltype URI filter
            page_size: Number of objects per page
            offset: Offset for pagination
            
        Returns:
            Tuple of (graph_objects: List[GraphObject], total_count: int)
        """
        try:
            # Default to main graph if not specified
            if graph_id is None:
                graph_id = "main"
            
            self.logger.info(f"Searching objects for '{search_text}' in space {space_id}, graph {graph_id}")
            
            # Build filters for search
            filters = {'search_text': search_text}
            if vitaltype_filter:
                filters['vitaltype_filter'] = vitaltype_filter
            
            # Use list_objects with search filters
            return await self.list_objects(space_id, graph_id, page_size, offset, filters)
            
        except Exception as e:
            self.logger.error(f"Error searching objects: {e}")
            return [], 0

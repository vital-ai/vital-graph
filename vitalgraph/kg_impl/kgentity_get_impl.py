"""
KGEntity Get Implementation Module

This module provides the core implementation logic for KGEntity retrieval operations,
designed to be used by REST endpoints and direct API calls.

The module handles:
- Single entity retrieval by URI
- Entity graph retrieval with include_entity_graph option
- Backend abstraction for different storage systems
- Error handling and validation
- VitalSigns object conversion
"""

import logging
from typing import List, Optional, Dict, Any, Union
from enum import Enum

# Import VitalSigns for object handling
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGEntity import KGEntity

# Import response models
from ..model.kgentities_model import EntitiesResponse

# Import backend utilities
from .kg_backend_utils import FusekiPostgreSQLBackendAdapter, BackendOperationResult


class EntityRetrievalMode(Enum):
    """Enumeration of entity retrieval modes."""
    SINGLE = "single"
    WITH_GRAPH = "with_graph"


class KGEntityGetProcessor:
    """
    Core processor for KGEntity retrieval operations.
    
    Handles the business logic for retrieving entities from the backend,
    including single entity retrieval and complete entity graph retrieval.
    """
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        Initialize the KGEntity get processor.
        
        Args:
            logger: Optional logger instance
        """
        self.logger = logger or logging.getLogger(__name__)
    
    async def get_entity(
        self,
        space_id: str,
        graph_id: str,
        entity_uri: Optional[str] = None,
        reference_id: Optional[str] = None,
        include_entity_graph: bool = False,
        backend_adapter: Optional[FusekiPostgreSQLBackendAdapter] = None
    ) -> List[GraphObject]:
        """
        Retrieve a single entity by URI or reference ID.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier  
            entity_uri: URI of the entity to retrieve (mutually exclusive with reference_id)
            reference_id: Reference ID of the entity to retrieve (mutually exclusive with entity_uri)
            include_entity_graph: Whether to include complete entity graph
            backend_adapter: Backend adapter instance
            
        Returns:
            List[GraphObject]: List of retrieved GraphObjects
            
        Raises:
            Exception: If retrieval fails
        """
        try:
            if entity_uri:
                self.logger.info(f"Retrieving entity: {entity_uri}")
            elif reference_id:
                self.logger.info(f"Retrieving entity by reference ID: {reference_id}")
            else:
                raise ValueError("Either entity_uri or reference_id must be provided")
                
            self.logger.info(f"Include entity graph: {include_entity_graph}")
            
            if not backend_adapter:
                raise ValueError("Backend adapter is required")
            
            # Determine retrieval mode
            mode = EntityRetrievalMode.WITH_GRAPH if include_entity_graph else EntityRetrievalMode.SINGLE
            
            # Retrieve entity data from backend
            retrieval_result = await self._retrieve_entity_from_backend(
                backend_adapter=backend_adapter,
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri,
                reference_id=reference_id,
                mode=mode
            )
            
            if not retrieval_result.success:
                self.logger.warning(f"Entity not found: {entity_uri}")
                return []
            
            self.logger.info(f"Successfully retrieved entity with {len(retrieval_result.objects)} objects")
            return retrieval_result.objects
            
        except Exception as e:
            self.logger.error(f"Error retrieving entity {entity_uri}: {e}")
            raise
    
    async def _retrieve_entity_from_backend(
        self,
        backend_adapter: FusekiPostgreSQLBackendAdapter,
        space_id: str,
        graph_id: str,
        entity_uri: Optional[str] = None,
        reference_id: Optional[str] = None,
        mode: EntityRetrievalMode = EntityRetrievalMode.SINGLE
    ) -> BackendOperationResult:
        """
        Retrieve entity data from the backend by URI or reference ID.
        
        Args:
            backend_adapter: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: URI of the entity to retrieve (mutually exclusive with reference_id)
            reference_id: Reference ID of the entity to retrieve (mutually exclusive with entity_uri)
            mode: Retrieval mode (single or with graph)
            
        Returns:
            BackendOperationResult: Result containing retrieved objects
        """
        try:
            if mode == EntityRetrievalMode.WITH_GRAPH:
                # Retrieve complete entity graph
                if entity_uri:
                    self.logger.info(f"Retrieving complete entity graph for: {entity_uri}")
                    return await backend_adapter.get_entity_graph(space_id, graph_id, entity_uri)
                elif reference_id:
                    self.logger.info(f"Retrieving complete entity graph by reference ID: {reference_id}")
                    return await backend_adapter.get_entity_graph_by_reference_id(space_id, graph_id, reference_id)
            else:
                # Retrieve single entity
                if entity_uri:
                    self.logger.info(f"Retrieving single entity: {entity_uri}")
                    return await backend_adapter.get_entity(space_id, graph_id, entity_uri)
                elif reference_id:
                    self.logger.info(f"Retrieving single entity by reference ID: {reference_id}")
                    return await backend_adapter.get_entity_by_reference_id(space_id, graph_id, reference_id)
                
        except Exception as e:
            identifier = entity_uri or reference_id
            self.logger.error(f"Backend retrieval failed for {identifier}: {e}")
            return BackendOperationResult(
                success=False,
                message=f"Backend retrieval failed: {str(e)}",
                objects=[]
            )
    


# Convenience functions for direct usage
async def get_entity(
    space_id: str,
    graph_id: str,
    entity_uri: str,
    include_entity_graph: bool = False,
    backend_adapter: Optional[FusekiPostgreSQLBackendAdapter] = None,
    logger: Optional[logging.Logger] = None
) -> EntitiesResponse:
    """
    Convenience function for entity retrieval.
    
    Args:
        space_id: Space identifier
        graph_id: Graph identifier
        entity_uri: URI of the entity to retrieve
        include_entity_graph: Whether to include complete entity graph
        backend_adapter: Backend adapter instance
        logger: Optional logger instance
        
    Returns:
        EntitiesResponse: Response containing the retrieved entity data
    """
    processor = KGEntityGetProcessor(logger=logger)
    return await processor.get_entity(
        space_id=space_id,
        graph_id=graph_id,
        entity_uri=entity_uri,
        include_entity_graph=include_entity_graph,
        backend_adapter=backend_adapter
    )

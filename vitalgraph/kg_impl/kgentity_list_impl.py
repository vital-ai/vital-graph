"""
KGEntity List Implementation for VitalGraph.

This module provides the implementation for listing KG entities with filtering,
pagination, and search capabilities, working exclusively with GraphObjects.
"""

import logging
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

# VitalSigns imports for proper integration
import vital_ai_vitalsigns as vitalsigns
from vital_ai_vitalsigns.model.GraphObject import GraphObject

# KG domain model imports
from ai_haley_kg_domain.model.KGEntity import KGEntity

# Backend utilities - no direct import needed, will use backend_adapter method


@dataclass
class ListEntitiesResult:
    """Result container for list operations."""
    entities: List[GraphObject]
    total_count: int


class KGEntityListProcessor:
    """
    Processor for KGEntity list operations with backend integration.
    
    Handles entity listing with filtering, pagination, and search capabilities
    while working exclusively with GraphObjects (no JsonLD handling).
    """
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)
    
    async def list_entities(self, space_id: str, graph_id: str, 
                           backend_adapter,
                           page_size: int = 10, offset: int = 0,
                           entity_type_uri: Optional[str] = None,
                           search: Optional[str] = None,
                           include_entity_graph: bool = False) -> ListEntitiesResult:
        """
        List KGEntities with filtering and pagination.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            page_size: Number of entities per page
            offset: Starting offset for pagination
            entity_type_uri: Optional filter by entity type
            search: Optional search term for entity content
            include_entity_graph: Whether to include complete entity graphs
            backend_adapter: Backend adapter instance
            
        Returns:
            ListEntitiesResult: Contains List[GraphObject] and total count
        """
        try:
            self.logger.debug(f"Listing entities in space '{space_id}', graph '{graph_id}'")
            self.logger.debug(f"Parameters: page_size={page_size}, offset={offset}, entity_type_uri={entity_type_uri}, search={search}, include_entity_graph={include_entity_graph}")
            
            # Get total count first
            total_count = await self._get_total_count(
                space_id, graph_id, entity_type_uri, search, backend_adapter
            )
            
            if total_count == 0:
                self.logger.debug("No entities found matching criteria")
                return ListEntitiesResult(entities=[], total_count=0)
            
            # Get entities with pagination
            entities = await self._get_entities_page(
                space_id, graph_id, page_size, offset, entity_type_uri, 
                search, include_entity_graph, backend_adapter
            )
            
            self.logger.debug(f"Retrieved {len(entities)} entities (total: {total_count})")
            return ListEntitiesResult(entities=entities, total_count=total_count)
            
        except Exception as e:
            self.logger.error(f"Error listing entities: {e}")
            raise
    
    async def _get_total_count(self, space_id: str, graph_id: str, 
                              entity_type_uri: Optional[str], search: Optional[str],
                              backend_adapter) -> int:
        """Get total count of entities matching criteria."""
        try:
            # Build count query using the existing method
            count_query = self._build_count_query(graph_id, entity_type_uri, search)
            self.logger.debug(f"Count query: {count_query}")
            
            # Execute count query using execute_sparql_query
            result = await backend_adapter.execute_sparql_query(space_id, count_query)
            
            if not result:
                self.logger.warning("Count query returned no results")
                return 0
            
            # Handle different result formats
            if isinstance(result, list) and len(result) > 0:
                # Direct list format (as seen in debug output)
                binding = result[0]
                if 'count' in binding:
                    count_value = binding['count']['value']
                    count = int(count_value)
                    self.logger.debug(f"Found {count} entities matching criteria")
                    return count
            elif isinstance(result, dict):
                # Standard SPARQL JSON format
                bindings = result.get('results', {}).get('bindings', [])
                if bindings and 'count' in bindings[0]:
                    count_value = bindings[0]['count']['value']
                    count = int(count_value)
                    self.logger.debug(f"Found {count} entities matching criteria")
                    return count
            
            self.logger.warning(f"Count query returned unexpected format: {type(result)}")
            return 0
            
        except Exception as e:
            self.logger.error(f"Error getting entity count: {e}")
            return 0
    
    async def _get_entities_page(self, space_id: str, graph_id: str,
                                page_size: int, offset: int,
                                entity_type_uri: Optional[str], search: Optional[str],
                                include_entity_graph: bool, backend_adapter) -> List[GraphObject]:
        """Get a page of entities matching criteria."""
        try:
            # First, get entity URIs using SELECT query
            select_query_parts = [
                "PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>",
                "PREFIX vital-core: <http://vital.ai/ontology/vital-core#>",
                "SELECT DISTINCT ?entity WHERE {",
                f"  GRAPH <{graph_id}> {{",
                "    ?entity vital-core:vitaltype haley:KGEntity ."
            ]
            
            # Add entity type filtering if specified
            if entity_type_uri:
                select_query_parts.append(f"    ?entity haley:hasKGEntityType <{entity_type_uri}> .")
            
            # Add search filtering if specified
            if search:
                select_query_parts.extend([
                    "    ?entity <http://vital.ai/ontology/vital-core#hasName> ?name .",
                    f"    FILTER(CONTAINS(LCASE(?name), LCASE(\"{search}\")))"
                ])
            
            select_query_parts.extend([
                "  }",
                "}",
                f"LIMIT {page_size}",
                f"OFFSET {offset}"
            ])
            
            select_query = "\n".join(select_query_parts)
            self.logger.debug(f"Entity URIs query: {select_query}")
            
            # Execute SELECT query to get entity URIs
            result = await backend_adapter.execute_sparql_query(space_id, select_query)
            
            if not result:
                self.logger.debug("No entity URIs found")
                return []
            
            # Extract entity URIs from results - handle different formats
            entity_uris = []
            if isinstance(result, list):
                # Direct list format (as seen in debug output)
                for binding in result:
                    if 'entity' in binding:
                        entity_uri = binding['entity']['value']
                        entity_uris.append(entity_uri)
            elif isinstance(result, dict):
                # Standard SPARQL JSON format
                bindings = result.get('results', {}).get('bindings', [])
                for binding in bindings:
                    if 'entity' in binding:
                        entity_uri = binding['entity']['value']
                        entity_uris.append(entity_uri)
            
            if not entity_uris:
                self.logger.debug("No entity URIs extracted from query results")
                return []
            
            self.logger.debug(f"Found {len(entity_uris)} entity URIs: {entity_uris}")
            
            # Now retrieve each entity as a GraphObject
            entities = []
            for entity_uri in entity_uris:
                try:
                    if include_entity_graph:
                        # Use KGEntityGetProcessor to get complete entity graph with frames and slots
                        from .kgentity_get_impl import KGEntityGetProcessor
                        get_processor = KGEntityGetProcessor(logger=self.logger)
                        entity_objects = await get_processor.get_entity(
                            space_id=space_id,
                            graph_id=graph_id,
                            entity_uri=entity_uri,
                            include_entity_graph=True,
                            backend_adapter=backend_adapter
                        )
                        if entity_objects:
                            # Add all objects (entity + frames + slots + edges)
                            entities.extend(entity_objects)
                            self.logger.debug(f"Retrieved complete entity graph for: {entity_uri} ({len(entity_objects)} objects)")
                        else:
                            self.logger.warning(f"Failed to retrieve entity graph for: {entity_uri}")
                    else:
                        # Use the backend's get_entity method to retrieve just the basic entity
                        entity_result = await backend_adapter.get_entity(space_id, graph_id, entity_uri)
                        if entity_result and hasattr(entity_result, 'objects') and entity_result.objects:
                            # Log how many objects were retrieved
                            self.logger.debug(f"🔍 entity_result.objects contains {len(entity_result.objects)} objects for {entity_uri}")
                            if len(entity_result.objects) > 1:
                                self.logger.warning(f"⚠️ Expected 1 object but got {len(entity_result.objects)} - only using first one")
                            # Log the type of the object
                            obj = entity_result.objects[0]
                            self.logger.debug(f"🔍 Object type: {type(obj).__name__}, Object class: {obj.__class__.__name__}")
                            if hasattr(obj, 'URI'):
                                self.logger.debug(f"🔍 Object URI: {obj.URI}")
                            # Add the first object (should be the entity itself)
                            entities.append(obj)
                            self.logger.debug(f"Retrieved basic entity: {entity_uri}")
                        else:
                            self.logger.warning(f"Failed to retrieve entity data for: {entity_uri}")
                except Exception as e:
                    self.logger.warning(f"Error retrieving entity {entity_uri}: {e}")
                    continue
            
            self.logger.debug(f"Successfully retrieved {len(entities)} entities")
            return entities
            
        except Exception as e:
            self.logger.error(f"Error getting entities page: {e}")
            return []
    
    def _build_count_query(self, graph_id: str, entity_type_uri: Optional[str], 
                          search: Optional[str]) -> str:
        """Build SPARQL count query."""
        # Base count query
        query_parts = [
            "PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>",
            "PREFIX vital-core: <http://vital.ai/ontology/vital-core#>",
            "SELECT (COUNT(DISTINCT ?entity) AS ?count) WHERE {",
            f"  GRAPH <{graph_id}> {{"
        ]
        
        # Entity type constraint
        if entity_type_uri:
            query_parts.extend([
                "    ?entity vital-core:vitaltype haley:KGEntity .",
                f"    ?entity haley:hasKGEntityType <{entity_type_uri}> ."
            ])
        else:
            query_parts.append("    ?entity vital-core:vitaltype haley:KGEntity .")
        
        # Search constraint
        if search:
            query_parts.extend([
                "    ?entity ?p ?o .",
                f"    FILTER(CONTAINS(LCASE(STR(?o)), LCASE(\"{search}\")))"
            ])
        
        query_parts.extend([
            "  }",
            "}"
        ])
        
        return "\n".join(query_parts)
    
    def _build_entities_query(self, graph_id: str, page_size: int, offset: int,
                             entity_type_uri: Optional[str], search: Optional[str],
                             include_entity_graph: bool) -> str:
        """Build SPARQL entities query with pagination."""
        if include_entity_graph:
            return self._build_entity_graph_query(graph_id, page_size, offset, entity_type_uri, search)
        else:
            return self._build_simple_entities_query(graph_id, page_size, offset, entity_type_uri, search)
    
    def _build_simple_entities_query(self, graph_id: str, page_size: int, offset: int,
                                    entity_type_uri: Optional[str], search: Optional[str]) -> str:
        """Build simple entities query (entity properties only)."""
        query_parts = [
            "PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>",
            "PREFIX vital-core: <http://vital.ai/ontology/vital-core#>",
            "SELECT ?s ?p ?o WHERE {",
            f"  GRAPH <{graph_id}> {{"
        ]
        
        # Subquery to get entity URIs with pagination
        subquery_parts = [
            "    {",
            "      SELECT DISTINCT ?s WHERE {",
            f"        GRAPH <{graph_id}> {{"
        ]
        
        # Entity type constraint
        if entity_type_uri:
            subquery_parts.extend([
                "          ?s vital-core:vitaltype haley:KGEntity .",
                f"          ?s haley:hasKGEntityType <{entity_type_uri}> ."
            ])
        else:
            subquery_parts.append("          ?s vital-core:vitaltype haley:KGEntity .")
        
        # Search constraint
        if search:
            subquery_parts.extend([
                "          ?s ?sp ?so .",
                f"          FILTER(CONTAINS(LCASE(STR(?so)), LCASE(\"{search}\")))"
            ])
        
        subquery_parts.extend([
            "        }",
            "      }",
            "      ORDER BY ?s",
            f"      LIMIT {page_size}",
            f"      OFFSET {offset}",
            "    }"
        ])
        
        query_parts.extend(subquery_parts)
        query_parts.extend([
            "    ?s ?p ?o .",
            "    FILTER(?p != <http://vital.ai/vitalgraph/direct#hasEntityFrame> &&",
            "           ?p != <http://vital.ai/vitalgraph/direct#hasFrame> &&",
            "           ?p != <http://vital.ai/vitalgraph/direct#hasSlot>)",
            "  }",
            "}",
            "ORDER BY ?s ?p"
        ])
        
        return "\n".join(query_parts)
    
    def _build_entity_graph_query(self, graph_id: str, page_size: int, offset: int,
                                 entity_type_uri: Optional[str], search: Optional[str]) -> str:
        """Build entity graph query (includes related frames, slots, edges)."""
        query_parts = [
            "SELECT ?s ?p ?o WHERE {",
            f"  GRAPH <{graph_id}> {{"
        ]
        
        # Subquery to get entity URIs with pagination
        subquery_parts = [
            "    {",
            "      SELECT DISTINCT ?entity WHERE {",
            f"        GRAPH <{graph_id}> {{"
        ]
        
        # Entity type constraint
        if entity_type_uri:
            subquery_parts.extend([
                f"          ?entity a <{entity_type_uri}> .",
                "          ?entity a <http://vital.ai/ontology/haley-ai-kg#KGEntity> ."
            ])
        else:
            subquery_parts.append("          ?entity a <http://vital.ai/ontology/haley-ai-kg#KGEntity> .")
        
        # Search constraint
        if search:
            subquery_parts.extend([
                "          ?entity ?sp ?so .",
                f"          FILTER(CONTAINS(LCASE(STR(?so)), LCASE(\"{search}\")))"
            ])
        
        subquery_parts.extend([
            "        }",
            "      }",
            "      ORDER BY ?entity",
            f"      LIMIT {page_size}",
            f"      OFFSET {offset}",
            "    }"
        ])
        
        query_parts.extend(subquery_parts)
        
        # Get complete entity graph using hasKGGraphURI grouping
        query_parts.extend([
            "    {",
            "      ?s <http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI> ?entity .",
            "      ?s ?p ?o .",
            "      FILTER(?p != <http://vital.ai/vitalgraph/direct#hasEntityFrame> &&",
            "             ?p != <http://vital.ai/vitalgraph/direct#hasFrame> &&",
            "             ?p != <http://vital.ai/vitalgraph/direct#hasSlot>)",
            "    }",
            "    UNION",
            "    {",
            "      ?entity ?p ?o .",
            "      BIND(?entity AS ?s)",
            "      FILTER(?p != <http://vital.ai/vitalgraph/direct#hasEntityFrame> &&",
            "             ?p != <http://vital.ai/vitalgraph/direct#hasFrame> &&",
            "             ?p != <http://vital.ai/vitalgraph/direct#hasSlot>)",
            "    }",
            "  }",
            "}",
            "ORDER BY ?s ?p"
        ])
        
        return "\n".join(query_parts)

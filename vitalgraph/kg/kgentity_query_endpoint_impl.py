"""
KGEntity Query Operations Implementation

This module contains the implementation functions for KGEntity query operations,
extracted from MockKGEntitiesEndpoint to improve code organization and maintainability.

Enhanced with sorting support using the KGQueryCriteriaBuilder.
"""

from typing import Any
from vitalgraph.model.kgentities_model import EntityQueryRequest, EntityQueryResponse
from vitalgraph.sparql.kg_query_builder import (
    KGQueryCriteriaBuilder, 
    EntityQueryCriteria as SparqlEntityQueryCriteria,
    SortCriteria as SparqlSortCriteria,
    SlotCriteria as SparqlSlotCriteria
)


def query_entities_impl(endpoint_instance, space_id: str, graph_id: str, query_request: EntityQueryRequest) -> EntityQueryResponse:
    """
    Query KGEntities using enhanced criteria-based search with sorting support.
    
    Args:
        endpoint_instance: The MockKGEntitiesEndpoint instance (for access to methods and logger)
        space_id: Space identifier
        graph_id: Graph identifier
        query_request: EntityQueryRequest containing search criteria, sorting, and pagination
        
    Returns:
        EntityQueryResponse containing list of matching entity URIs and pagination info
    """
    endpoint_instance._log_method_call("query_entities", space_id=space_id, graph_id=graph_id, query_request=query_request)
    
    try:
        # Get space from space manager
        space = endpoint_instance.space_manager.get_space(space_id)
        if not space:
            return EntityQueryResponse(
                entity_uris=[],
                total_count=0,
                page_size=query_request.page_size,
                offset=query_request.offset
            )
        
        # Convert Pydantic models to dataclass models for SPARQL builder
        sparql_criteria = _convert_to_sparql_criteria(query_request.criteria)
        
        # Initialize enhanced query builder
        query_builder = KGQueryCriteriaBuilder()
        
        # Build SPARQL query with sorting support
        if sparql_criteria.sort_criteria:
            sparql_query = query_builder.build_entity_query_sparql_with_sorting(
                criteria=sparql_criteria,
                graph_id=graph_id,
                page_size=query_request.page_size,
                offset=query_request.offset
            )
        else:
            # Use existing method for backward compatibility
            sparql_query = query_builder.build_entity_query_sparql(
                criteria=sparql_criteria,
                graph_id=graph_id,
                page_size=query_request.page_size,
                offset=query_request.offset
            )
        
        # Debug: Log the generated SPARQL query
        endpoint_instance.logger.info(f"Generated entity SPARQL query:\n{sparql_query}")
        
        endpoint_instance.logger.debug(f"Generated SPARQL query with sorting: {sparql_query}")
        
        # Execute query using existing SPARQL execution method
        results = endpoint_instance._execute_sparql_query(space, sparql_query)
        
        # Debug: Log the SPARQL results structure
        endpoint_instance.logger.info(f"SPARQL results type: {type(results)}")
        endpoint_instance.logger.info(f"SPARQL results keys: {results.keys() if isinstance(results, dict) else 'Not a dict'}")
        if results.get("bindings"):
            endpoint_instance.logger.info(f"Number of bindings: {len(results['bindings'])}")
            if results["bindings"]:
                endpoint_instance.logger.info(f"First binding structure: {results['bindings'][0]}")
        
        # Extract entity URIs from results
        entity_uris = []
        if results.get("bindings"):
            for binding in results["bindings"]:
                endpoint_instance.logger.debug(f"Processing binding: {binding}")
                entity_uri = binding.get("entity", {}).get("value", "")
                if entity_uri and entity_uri not in entity_uris:
                    entity_uris.append(entity_uri)
                    endpoint_instance.logger.debug(f"Added entity URI: {entity_uri}")
        
        endpoint_instance.logger.info(f"Final entity URIs extracted: {entity_uris}")
        
        # For mock implementation, we'll use the actual count as total_count
        # In real implementation, this would be a separate COUNT query
        total_count = len(entity_uris)
        
        return EntityQueryResponse(
            entity_uris=entity_uris,
            total_count=total_count,
            page_size=query_request.page_size,
            offset=query_request.offset
        )
        
    except Exception as e:
        endpoint_instance.logger.error(f"Error querying entities with enhanced builder: {e}")
        return EntityQueryResponse(
            entity_uris=[],
            total_count=0,
            page_size=query_request.page_size,
            offset=query_request.offset
        )


def _convert_to_sparql_criteria(pydantic_criteria) -> SparqlEntityQueryCriteria:
    """Convert Pydantic EntityQueryCriteria to dataclass EntityQueryCriteria for SPARQL builder.
    
    Args:
        pydantic_criteria: Pydantic EntityQueryCriteria model
        
    Returns:
        Dataclass EntityQueryCriteria for SPARQL builder
    """
    # Convert slot criteria
    sparql_slot_criteria = None
    if pydantic_criteria.slot_criteria:
        sparql_slot_criteria = [
            SparqlSlotCriteria(
                slot_type=slot.slot_type,
                slot_class_uri=slot.slot_class_uri,
                value=slot.value,
                comparator=slot.comparator,
                frame_type=slot.frame_type  # Fix: Include frame_type for multi-frame queries
            )
            for slot in pydantic_criteria.slot_criteria
        ]
    
    # Convert sort criteria
    sparql_sort_criteria = None
    if pydantic_criteria.sort_criteria:
        sparql_sort_criteria = [
            SparqlSortCriteria(
                sort_type=sort.sort_type,
                slot_type=sort.slot_type,
                frame_type=sort.frame_type,
                property_uri=sort.property_uri,
                sort_order=sort.sort_order,
                priority=sort.priority
            )
            for sort in pydantic_criteria.sort_criteria
        ]
    
    return SparqlEntityQueryCriteria(
        search_string=pydantic_criteria.search_string,
        entity_type=pydantic_criteria.entity_type,
        frame_type=pydantic_criteria.frame_type,
        slot_criteria=sparql_slot_criteria,
        sort_criteria=sparql_sort_criteria
    )
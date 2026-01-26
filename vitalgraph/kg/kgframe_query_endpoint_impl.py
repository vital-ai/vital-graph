"""
KGFrame Query Operations Implementation

This module contains the implementation functions for KGFrame query operations,
extracted from MockKGFramesEndpoint to improve code organization and maintainability.

Enhanced with sorting support using the KGQueryCriteriaBuilder.
"""

from typing import Any
from vitalgraph.model.kgframes_model import FrameQueryRequest, FrameQueryResponse
from vitalgraph.sparql.kg_query_builder import (
    KGQueryCriteriaBuilder, 
    FrameQueryCriteria as SparqlFrameQueryCriteria,
    SortCriteria as SparqlSortCriteria,
    SlotCriteria as SparqlSlotCriteria
)


def query_frames_impl(endpoint_instance, space_id: str, graph_id: str, query_request: FrameQueryRequest) -> FrameQueryResponse:
    """
    Query KGFrames using enhanced criteria-based search with sorting support.
    
    Args:
        endpoint_instance: The MockKGFramesEndpoint instance (for access to methods and logger)
        space_id: Space identifier
        graph_id: Graph identifier
        query_request: FrameQueryRequest containing search criteria, sorting, and pagination
        
    Returns:
        FrameQueryResponse containing list of matching frame URIs and pagination info
    """
    endpoint_instance._log_method_call("query_frames", space_id=space_id, graph_id=graph_id, query_request=query_request)
    
    try:
        # Get space from space manager
        space = endpoint_instance.space_manager.get_space(space_id)
        if not space:
            return FrameQueryResponse(
                frame_uris=[],
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
            sparql_query = query_builder.build_frame_query_sparql_with_sorting(
                criteria=sparql_criteria,
                graph_id=graph_id,
                page_size=query_request.page_size,
                offset=query_request.offset
            )
        else:
            # Use existing method for backward compatibility
            sparql_query = query_builder.build_frame_query_sparql(
                criteria=sparql_criteria,
                graph_id=graph_id,
                page_size=query_request.page_size,
                offset=query_request.offset
            )
        
        endpoint_instance.logger.debug(f"Generated SPARQL query with sorting: {sparql_query}")
        
        # Execute query using existing SPARQL execution method
        results = endpoint_instance._execute_sparql_query(space, sparql_query)
        
        # Extract frame URIs from results
        frame_uris = []
        if results.get("bindings"):
            for binding in results["bindings"]:
                frame_uri = binding.get("frame", {}).get("value", "")
                if frame_uri and frame_uri not in frame_uris:
                    frame_uris.append(frame_uri)
        
        # For mock implementation, we'll use the actual count as total_count
        # In real implementation, this would be a separate COUNT query
        total_count = len(frame_uris)
        
        return FrameQueryResponse(
            frame_uris=frame_uris,
            total_count=total_count,
            page_size=query_request.page_size,
            offset=query_request.offset
        )
        
    except Exception as e:
        endpoint_instance.logger.error(f"Error querying frames with enhanced builder: {e}")
        return FrameQueryResponse(
            frame_uris=[],
            total_count=0,
            page_size=query_request.page_size,
            offset=query_request.offset
        )


def _convert_to_sparql_criteria(pydantic_criteria) -> SparqlFrameQueryCriteria:
    """Convert Pydantic FrameQueryCriteria to dataclass FrameQueryCriteria for SPARQL builder.
    
    Args:
        pydantic_criteria: Pydantic FrameQueryCriteria model
        
    Returns:
        Dataclass FrameQueryCriteria for SPARQL builder
    """
    # Convert slot criteria
    sparql_slot_criteria = None
    if pydantic_criteria.slot_criteria:
        sparql_slot_criteria = [
            SparqlSlotCriteria(
                slot_type=slot.slot_type,
                value=slot.value,
                comparator=slot.comparator
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
    
    return SparqlFrameQueryCriteria(
        search_string=pydantic_criteria.search_string,
        frame_type=pydantic_criteria.frame_type,
        entity_type=pydantic_criteria.entity_type,
        slot_criteria=sparql_slot_criteria,
        sort_criteria=sparql_sort_criteria
    )
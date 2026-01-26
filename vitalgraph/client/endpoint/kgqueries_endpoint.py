"""
VitalGraph Client KGQueries Endpoint

Client-side implementation for KG entity-to-entity connection query operations.
"""

import logging
from typing import Dict, Any, Optional, List

from .base_endpoint import BaseEndpoint
from ..utils.client_utils import VitalGraphClientError, validate_required_params, build_query_params
from ...model.kgqueries_model import (
    KGQueryRequest,
    KGQueryResponse,
    KGQueryCriteria
)
from ...model.kgentities_model import EntityQueryCriteria

logger = logging.getLogger(__name__)


class KGQueriesEndpoint(BaseEndpoint):
    """Client endpoint for KG entity-to-entity connection queries."""
    
    def query_connections(
        self,
        space_id: str,
        graph_id: str,
        criteria: KGQueryCriteria,
        page_size: int = 10,
        offset: int = 0
    ) -> KGQueryResponse:
        """
        Query entity-to-entity connections based on criteria.
        
        Supports two query types:
        - relation: Find entities connected via Edge_hasKGRelation
        - frame: Find entities connected via shared KGFrames
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            criteria: Query criteria specifying query type and filters
            page_size: Number of results per page (default: 10)
            offset: Offset for pagination (default: 0)
            
        Returns:
            KGQueryResponse with connections based on query_type
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, criteria=criteria)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgqueries"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id
            )
            
            # Build request body
            request_body = KGQueryRequest(
                criteria=criteria,
                page_size=page_size,
                offset=offset
            )
            
            # Log complete request for debugging
            request_dict = request_body.model_dump()
            logger.info(f"KGQuery Request URL: {url}")
            logger.info(f"KGQuery Request Params: {params}")
            logger.info(f"KGQuery Request Body: {request_dict}")
            
            # Make typed request
            response = self._make_typed_request(
                'POST',
                url,
                KGQueryResponse,
                params=params,
                json=request_dict
            )
            
            # Log response for debugging
            logger.info(f"KGQuery Response: query_type={response.query_type}, total_count={response.total_count}")
            
            return response
            
        except VitalGraphClientError as e:
            logger.error(f"Error querying connections: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error querying connections: {e}")
            raise VitalGraphClientError(f"Failed to query connections: {str(e)}")
    
    def query_frame_connections(
        self,
        space_id: str,
        graph_id: str,
        source_entity_uris: Optional[List[str]] = None,
        destination_entity_uris: Optional[List[str]] = None,
        source_entity_criteria: Optional[EntityQueryCriteria] = None,
        destination_entity_criteria: Optional[EntityQueryCriteria] = None,
        shared_frame_types: Optional[List[str]] = None,
        exclude_self_connections: bool = True,
        page_size: int = 10,
        offset: int = 0
    ) -> KGQueryResponse:
        """
        Convenience method for querying frame-based connections.
        
        Find entities connected via shared KGFrames.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            source_entity_uris: Optional list of source entity URIs
            destination_entity_uris: Optional list of destination entity URIs
            source_entity_criteria: Optional criteria for source entities
            destination_entity_criteria: Optional criteria for destination entities
            shared_frame_types: Optional list of frame types to filter by
            exclude_self_connections: Exclude connections from entity to itself (default: True)
            page_size: Number of results per page (default: 10)
            offset: Offset for pagination (default: 0)
            
        Returns:
            KGQueryResponse with frame connections
            
        Raises:
            VitalGraphClientError: If request fails
        """
        # Build frame query criteria
        criteria = KGQueryCriteria(
            query_type="frame",
            source_entity_uris=source_entity_uris,
            destination_entity_uris=destination_entity_uris,
            source_entity_criteria=source_entity_criteria,
            destination_entity_criteria=destination_entity_criteria,
            shared_frame_types=shared_frame_types,
            exclude_self_connections=exclude_self_connections
        )
        
        return self.query_connections(
            space_id=space_id,
            graph_id=graph_id,
            criteria=criteria,
            page_size=page_size,
            offset=offset
        )
    
    def query_relation_connections(
        self,
        space_id: str,
        graph_id: str,
        source_entity_uris: Optional[List[str]] = None,
        destination_entity_uris: Optional[List[str]] = None,
        source_entity_criteria: Optional[EntityQueryCriteria] = None,
        destination_entity_criteria: Optional[EntityQueryCriteria] = None,
        relation_type_uris: Optional[List[str]] = None,
        direction: str = "outgoing",
        source_frame_criteria: Optional[List] = None,
        destination_frame_criteria: Optional[List] = None,
        exclude_self_connections: bool = True,
        page_size: int = 10,
        offset: int = 0
    ) -> KGQueryResponse:
        """
        Convenience method for querying relation-based connections.
        
        Find entities connected via Edge_hasKGRelation.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            source_entity_uris: Optional list of source entity URIs
            destination_entity_uris: Optional list of destination entity URIs
            source_entity_criteria: Optional criteria for source entities
            destination_entity_criteria: Optional criteria for destination entities
            relation_type_uris: Optional list of relation type URIs to filter by
            direction: Direction of relations: "outgoing", "incoming", or "bidirectional" (default: "outgoing")
            source_frame_criteria: Optional list of FrameCriteria for filtering source entities by frames/slots
            destination_frame_criteria: Optional list of FrameCriteria for filtering destination entities by frames/slots
            exclude_self_connections: Exclude connections from entity to itself (default: True)
            page_size: Number of results per page (default: 10)
            offset: Offset for pagination (default: 0)
            
        Returns:
            KGQueryResponse with relation connections
            
        Raises:
            VitalGraphClientError: If request fails
        """
        # Build relation query criteria
        criteria = KGQueryCriteria(
            query_type="relation",
            source_entity_uris=source_entity_uris,
            destination_entity_uris=destination_entity_uris,
            source_entity_criteria=source_entity_criteria,
            destination_entity_criteria=destination_entity_criteria,
            relation_type_uris=relation_type_uris,
            direction=direction,
            source_frame_criteria=source_frame_criteria,
            destination_frame_criteria=destination_frame_criteria,
            exclude_self_connections=exclude_self_connections
        )
        
        return self.query_connections(
            space_id=space_id,
            graph_id=graph_id,
            criteria=criteria,
            page_size=page_size,
            offset=offset
        )

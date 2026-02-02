"""
VitalGraph Client Triples Endpoint

Client-side implementation for Triples operations.
"""

import httpx
from typing import Dict, Any, Optional, List

from .base_endpoint import BaseEndpoint
from ..utils.client_utils import VitalGraphClientError, validate_required_params, build_query_params
from ...model.triples_model import (
    TripleListResponse, TripleOperationResponse, TripleListRequest
)
from ...model.jsonld_model import JsonLdDocument, JsonLdObject, JsonLdRequest


class TriplesEndpoint(BaseEndpoint):
    """Client endpoint for Triples operations."""
    
    def list_triples(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, 
                    subject: Optional[str] = None, predicate: Optional[str] = None, 
                    object: Optional[str] = None, object_filter: Optional[str] = None) -> TripleListResponse:
        """
        List/Search triples with optional filtering.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            page_size: Number of triples per page
            offset: Offset for pagination
            subject: Subject URI filter (optional)
            predicate: Predicate URI filter (optional)
            object: Object value filter (optional)
            object_filter: Keyword to search within object values (optional)
            
        Returns:
            TripleListResponse containing triples data and pagination info
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id)
        
        url = f"{self._get_server_url().rstrip('/')}/api/graphs/triples"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            page_size=page_size,
            offset=offset,
            subject=subject,
            predicate=predicate,
            object=object,
            object_filter=object_filter
        )
        
        return self._make_typed_request('GET', url, TripleListResponse, params=params)
    
    def add_triples(self, space_id: str, graph_id: str, document: JsonLdRequest) -> TripleOperationResponse:
        """
        Add triples to a graph.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            document: JSON-LD request (JsonLdObject for single triple or JsonLdDocument for multiple triples)
            
        Returns:
            TripleOperationResponse containing operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, document=document)
        
        url = f"{self._get_server_url().rstrip('/')}/api/graphs/triples"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id
        )
        
        # Send the JsonLdRequest directly (server handles discriminated union)
        # The server will automatically detect JsonLdObject vs JsonLdDocument
        return self._make_typed_request('POST', url, TripleOperationResponse, params=params, json=document.model_dump(by_alias=True))
    
    def delete_triples(self, space_id: str, graph_id: str, 
                      subject: Optional[str] = None, predicate: Optional[str] = None, 
                      object: Optional[str] = None) -> TripleOperationResponse:
        """
        Delete triples from a graph by pattern.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            subject: Subject URI filter for pattern-based deletion (optional)
            predicate: Predicate URI filter for pattern-based deletion (optional)
            object: Object value filter for pattern-based deletion (optional)
            
        Returns:
            TripleOperationResponse containing operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id)
        
        # Validate that at least one pattern filter is provided
        if not any([subject, predicate, object]):
            raise VitalGraphClientError("At least one pattern filter (subject/predicate/object) must be provided for deletion")
        
        url = f"{self._get_server_url().rstrip('/')}/api/graphs/triples"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            subject=subject,
            predicate=predicate,
            object=object
        )
        
        return self._make_typed_request('DELETE', url, TripleOperationResponse, params=params)

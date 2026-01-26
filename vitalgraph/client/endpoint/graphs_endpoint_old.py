"""
VitalGraph Client Graphs Endpoint

Client-side implementation for Graph management operations.
"""

import requests
from typing import Dict, Any, Optional, List

from .base_endpoint import BaseEndpoint
from ..utils.client_utils import VitalGraphClientError, validate_required_params
from ...model.sparql_model import (
    GraphInfo, SPARQLGraphRequest, SPARQLGraphResponse
)


class GraphsEndpoint(BaseEndpoint):
    """Client endpoint for Graph management operations."""
    
    def list_graphs(self, space_id: str) -> List[GraphInfo]:
        """
        List graphs in a space.
        
        Args:
            space_id: Space identifier
            
        Returns:
            List of GraphInfo objects
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id)
        
        url = f"{self._get_server_url().rstrip('/')}/api/graphs/sparql/{space_id}/graphs"
        
        # Make request and manually parse list of GraphInfo objects
        response = self._make_authenticated_request('GET', url)
        response_data = response.json()
        
        # Parse each item in the list as a GraphInfo object
        if isinstance(response_data, list):
            return [GraphInfo.model_validate(item) for item in response_data]
        else:
            raise VitalGraphClientError(f"Expected list response, got {type(response_data)}")
    
    def get_graph_info(self, space_id: str, graph_uri: str) -> Optional[GraphInfo]:
        """
        Get information about a specific graph.
        
        Args:
            space_id: Space identifier
            graph_uri: Graph URI
            
        Returns:
            GraphInfo object or None if graph doesn't exist
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_uri=graph_uri)
        
        url = f"{self._get_server_url().rstrip('/')}/api/graphs/sparql/{space_id}/graph/{graph_uri}"
        
        try:
            response = self._make_authenticated_request('GET', url)
            response_data = response.json()
            
            # Handle case where server returns null for non-existent graphs
            if response_data is None:
                return None
            
            return GraphInfo.model_validate(response_data)
        except Exception as e:
            # If it's a 404 or similar, return None instead of raising
            if hasattr(e, 'response') and e.response.status_code == 404:
                return None
            raise VitalGraphClientError(f"Failed to get graph info: {e}")
    
    def create_graph(self, space_id: str, graph_uri: str) -> SPARQLGraphResponse:
        """
        Create a new graph.
        
        Args:
            space_id: Space identifier
            graph_uri: Graph URI to create
            
        Returns:
            SPARQLGraphResponse with creation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_uri=graph_uri)
        
        url = f"{self._get_server_url().rstrip('/')}/api/graphs/sparql/{space_id}/graph/{graph_uri}"
        
        return self._make_typed_request('PUT', url, SPARQLGraphResponse)
    
    def drop_graph(self, space_id: str, graph_uri: str, silent: bool = False) -> SPARQLGraphResponse:
        """
        Drop (delete) a graph.
        
        Args:
            space_id: Space identifier
            graph_uri: Graph URI to drop
            silent: Execute silently (optional)
            
        Returns:
            SPARQLGraphResponse with deletion result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_uri=graph_uri)
        
        url = f"{self._get_server_url().rstrip('/')}/api/graphs/sparql/{space_id}/graph/{graph_uri}"
        params = {"silent": silent} if silent else None
        
        return self._make_typed_request('DELETE', url, SPARQLGraphResponse, params=params)
    
    def clear_graph(self, space_id: str, graph_uri: str) -> SPARQLGraphResponse:
        """
        Clear a graph (remove all triples but keep the graph).
        
        Args:
            space_id: Space identifier
            graph_uri: Graph URI to clear
            
        Returns:
            SPARQLGraphResponse with clear operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_uri=graph_uri)
        
        # Use the POST endpoint for graph operations with CLEAR operation
        url = f"{self._get_server_url().rstrip('/')}/api/graphs/sparql/{space_id}/graph"
        
        request_data = SPARQLGraphRequest(
            operation="CLEAR",
            target_graph_uri=graph_uri
        )
        
        return self._make_typed_request('POST', url, SPARQLGraphResponse, json=request_data.model_dump())

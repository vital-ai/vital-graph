"""
VitalGraph Client Graphs Endpoint

Client-side implementation for Graph management operations.
"""

import httpx
from typing import Dict, Any, Optional, List

from .base_endpoint import BaseEndpoint
from ..utils.client_utils import VitalGraphClientError, validate_required_params
from ...model.sparql_model import GraphInfo, SPARQLGraphRequest, SPARQLGraphResponse
from ..response.client_response import (
    GraphResponse,
    GraphsListResponse,
    GraphCreateResponse,
    GraphDeleteResponse,
    GraphClearResponse
)


class GraphsEndpoint(BaseEndpoint):
    """Client endpoint for Graph management operations."""
    
    def list_graphs(self, space_id: str) -> GraphsListResponse:
        """
        List graphs in a space.
        
        Args:
            space_id: Space identifier
            
        Returns:
            GraphsListResponse with graphs list
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id)
        
        try:
            url = f"{self._get_server_url().rstrip('/')}/api/graphs/sparql/{space_id}/graphs"
            
            response = self._make_authenticated_request('GET', url)
            response_data = response.json()
            
            # Parse each item in the list as a GraphInfo object
            if isinstance(response_data, list):
                graphs = [GraphInfo.model_validate(item) for item in response_data]
                return GraphsListResponse(
                    graphs=graphs,
                    total=len(graphs),
                    error_code=0,
                    status_code=200,
                    message='Graphs listed successfully'
                )
            else:
                return GraphsListResponse(
                    graphs=[],
                    total=0,
                    error_code=1,
                    status_code=500,
                    error_message=f"Expected list response, got {type(response_data)}"
                )
        except Exception as e:
            return GraphsListResponse(
                graphs=[],
                total=0,
                error_code=1,
                status_code=500,
                error_message=str(e)
            )
    
    def get_graph_info(self, space_id: str, graph_uri: str) -> GraphResponse:
        """
        Get information about a specific graph.
        
        Args:
            space_id: Space identifier
            graph_uri: Graph URI
            
        Returns:
            GraphResponse with graph info
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_uri=graph_uri)
        
        try:
            url = f"{self._get_server_url().rstrip('/')}/api/graphs/sparql/{space_id}/graph/{graph_uri}"
            
            response = self._make_authenticated_request('GET', url)
            response_data = response.json()
            
            # Handle case where server returns null for non-existent graphs
            if response_data is None:
                return GraphResponse(
                    graph=None,
                    error_code=0,
                    status_code=404,
                    message='Graph not found'
                )
            
            # Handle new GraphInfoResponse structure from server
            if isinstance(response_data, dict) and 'success' in response_data:
                # New response format with success/graph_info/error structure
                if response_data.get('success'):
                    graph_info_data = response_data.get('graph_info')
                    if graph_info_data:
                        graph = GraphInfo.model_validate(graph_info_data)
                        return GraphResponse(
                            graph=graph,
                            error_code=0,
                            status_code=200,
                            message=response_data.get('message', 'Graph info retrieved successfully')
                        )
                # Error case
                return GraphResponse(
                    graph=None,
                    error_code=1,
                    status_code=404 if 'not found' in response_data.get('error', '').lower() else 500,
                    message=response_data.get('error', 'Failed to get graph info')
                )
            
            # Fallback: try to parse as direct GraphInfo (old format)
            graph = GraphInfo.model_validate(response_data)
            return GraphResponse(
                graph=graph,
                error_code=0,
                status_code=200,
                message='Graph info retrieved successfully'
            )
        except Exception as e:
            # If it's a 404 or similar, return not found response
            if hasattr(e, 'response') and hasattr(e.response, 'status_code') and e.response.status_code == 404:
                return GraphResponse(
                    graph=None,
                    error_code=0,
                    status_code=404,
                    message='Graph not found'
                )
            return GraphResponse(
                graph=None,
                error_code=1,
                status_code=500,
                error_message=str(e)
            )
    
    def create_graph(self, space_id: str, graph_uri: str) -> GraphCreateResponse:
        """
        Create a new graph.
        
        Args:
            space_id: Space identifier
            graph_uri: Graph URI to create
            
        Returns:
            GraphCreateResponse with creation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_uri=graph_uri)
        
        try:
            url = f"{self._get_server_url().rstrip('/')}/api/graphs/sparql/{space_id}/graph/{graph_uri}"
            
            response = self._make_authenticated_request('PUT', url)
            response_data = response.json()
            
            return GraphCreateResponse(
                graph_uri=graph_uri,
                created=True,
                error_code=0,
                status_code=200,
                message=response_data.get('message', 'Graph created successfully')
            )
        except Exception as e:
            return GraphCreateResponse(
                graph_uri=graph_uri,
                created=False,
                error_code=1,
                status_code=500,
                error_message=str(e)
            )
    
    def drop_graph(self, space_id: str, graph_uri: str, silent: bool = False) -> GraphDeleteResponse:
        """
        Drop (delete) a graph.
        
        Args:
            space_id: Space identifier
            graph_uri: Graph URI to drop
            silent: Execute silently (optional)
            
        Returns:
            GraphDeleteResponse with deletion result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_uri=graph_uri)
        
        try:
            url = f"{self._get_server_url().rstrip('/')}/api/graphs/sparql/{space_id}/graph/{graph_uri}"
            params = {"silent": silent} if silent else None
            
            response = self._make_authenticated_request('DELETE', url, params=params)
            response_data = response.json()
            
            return GraphDeleteResponse(
                graph_uri=graph_uri,
                deleted=True,
                error_code=0,
                status_code=200,
                message=response_data.get('message', 'Graph deleted successfully')
            )
        except Exception as e:
            return GraphDeleteResponse(
                graph_uri=graph_uri,
                deleted=False,
                error_code=1,
                status_code=500,
                error_message=str(e)
            )
    
    def clear_graph(self, space_id: str, graph_uri: str) -> GraphClearResponse:
        """
        Clear a graph (remove all triples but keep the graph).
        
        Args:
            space_id: Space identifier
            graph_uri: Graph URI to clear
            
        Returns:
            GraphClearResponse with clear operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_uri=graph_uri)
        
        try:
            # Use the POST endpoint for graph operations with CLEAR operation
            url = f"{self._get_server_url().rstrip('/')}/api/graphs/sparql/{space_id}/graph"
            
            request_data = SPARQLGraphRequest(
                operation="CLEAR",
                target_graph_uri=graph_uri
            )
            
            response = self._make_authenticated_request('POST', url, json=request_data.model_dump())
            response_data = response.json()
            
            return GraphClearResponse(
                graph_uri=graph_uri,
                cleared=True,
                triples_removed=response_data.get('triples_removed', 0),
                error_code=0,
                status_code=200,
                message=response_data.get('message', 'Graph cleared successfully')
            )
        except Exception as e:
            return GraphClearResponse(
                graph_uri=graph_uri,
                cleared=False,
                triples_removed=0,
                error_code=1,
                status_code=500,
                error_message=str(e)
            )

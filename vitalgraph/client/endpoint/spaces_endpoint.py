"""
VitalGraph Client Spaces Endpoint

Client-side implementation for Spaces operations.
"""

import requests
from typing import Dict, Any, Optional

from .base_endpoint import BaseEndpoint
from ..utils.client_utils import VitalGraphClientError, validate_required_params, build_query_params
from ...model.spaces_model import Space
from ..response.client_response import (
    SpaceResponse,
    SpaceInfoResponse,
    SpacesListResponse,
    SpaceCreateResponse,
    SpaceUpdateResponse,
    SpaceDeleteResponse
)
from typing import List


class SpacesEndpoint(BaseEndpoint):
    """Client endpoint for Spaces operations."""
    
    def list_spaces(self, tenant: Optional[str] = None) -> SpacesListResponse:
        """
        List all spaces.
        
        Args:
            tenant: Optional tenant filter
            
        Returns:
            SpacesListResponse with spaces list
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        
        try:
            url = f"{self._get_server_url().rstrip('/')}/api/spaces"
            params = build_query_params(tenant=tenant)
            
            response = self._make_authenticated_request('GET', url, params=params)
            response_data = response.json()
            
            # Extract spaces from server response
            spaces_data = response_data.get('spaces', [])
            spaces = [Space(**space_data) for space_data in spaces_data]
            
            return SpacesListResponse(
                spaces=spaces,
                total=response_data.get('total_count', len(spaces)),
                error_code=0,
                status_code=200,
                message=response_data.get('message', 'Spaces listed successfully')
            )
        except Exception as e:
            return SpacesListResponse(
                spaces=[],
                total=0,
                error_code=1,
                status_code=500,
                error_message=str(e)
            )
    
    def create_space(self, space: Space) -> SpaceCreateResponse:
        """
        Create a new space.
        
        Args:
            space: Space object with space data
            
        Returns:
            SpaceCreateResponse with created space
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space=space)
        
        try:
            url = f"{self._get_server_url().rstrip('/')}/api/spaces"
            
            response = self._make_authenticated_request('POST', url, json=space.model_dump())
            response_data = response.json()
            
            # Extract created space from server response
            created_space = None
            if 'space' in response_data and response_data['space']:
                created_space = Space(**response_data['space'])
            
            return SpaceCreateResponse(
                space=created_space,
                created_count=response_data.get('created_count', 1),
                created_uris=response_data.get('created_uris', []),
                error_code=0,
                status_code=201,
                message=response_data.get('message', 'Space created successfully')
            )
        except Exception as e:
            return SpaceCreateResponse(
                space=None,
                created_count=0,
                created_uris=[],
                error_code=1,
                status_code=500,
                error_message=str(e)
            )
    
    def add_space(self, space: Space) -> SpaceCreateResponse:
        """
        Add a new space (deprecated - use create_space instead).
        
        Args:
            space: Space object with space data
            
        Returns:
            SpaceCreateResponse with created space
            
        Raises:
            VitalGraphClientError: If request fails
        """
        return self.create_space(space)
    
    def get_space(self, space_id: str) -> SpaceResponse:
        """
        Get a space by ID.
        
        Args:
            space_id: Space ID
            
        Returns:
            SpaceResponse with space data
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id)
        
        try:
            url = f"{self._get_server_url().rstrip('/')}/api/spaces/{space_id}"
            
            response = self._make_authenticated_request('GET', url)
            response_data = response.json()
            
            # Server now returns SpaceResponse structure
            space = None
            if response_data.get('space'):
                space = Space(**response_data['space'])
            
            success = response_data.get('success', True)
            message = response_data.get('message', 'Space retrieved successfully')
            
            return SpaceResponse(
                space=space,
                error_code=0 if success else 1,
                status_code=200,
                message=message
            )
        except Exception as e:
            return SpaceResponse(
                space=None,
                error_code=1,
                status_code=500,
                error_message=str(e)
            )
    
    def get_space_info(self, space_id: str) -> SpaceInfoResponse:
        """
        Get detailed space information including statistics.
        
        Args:
            space_id: Space ID
            
        Returns:
            SpaceInfoResponse with space info and statistics
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id)
        
        try:
            url = f"{self._get_server_url().rstrip('/')}/api/spaces/{space_id}/info"
            
            response = self._make_authenticated_request('GET', url)
            response_data = response.json()
            
            # Server now returns SpaceInfoResponse structure
            space = None
            if response_data.get('space'):
                space = Space(**response_data['space'])
            
            success = response_data.get('success', True)
            message = response_data.get('message', 'Space info retrieved successfully')
            
            return SpaceInfoResponse(
                space=space,
                statistics=response_data.get('statistics'),
                quad_dump=response_data.get('quad_dump'),
                error_code=0 if success else 1,
                status_code=200,
                message=message
            )
        except Exception as e:
            return SpaceInfoResponse(
                space=None,
                statistics=None,
                quad_dump=None,
                error_code=1,
                status_code=500,
                error_message=str(e)
            )
    
    def update_space(self, space_id: str, space: Space) -> SpaceUpdateResponse:
        """
        Update a space.
        
        Args:
            space_id: Space ID
            space: Updated space object
            
        Returns:
            SpaceUpdateResponse with update result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, space=space)
        
        try:
            url = f"{self._get_server_url().rstrip('/')}/api/spaces/{space_id}"
            
            response = self._make_authenticated_request('PUT', url, json=space.model_dump())
            response_data = response.json()
            
            # Extract updated space from server response
            updated_space = None
            if 'space' in response_data:
                updated_space = Space(**response_data['space'])
            
            return SpaceUpdateResponse(
                space=updated_space,
                updated_count=response_data.get('updated_count', 1),
                error_code=0,
                status_code=200,
                message=response_data.get('message', 'Space updated successfully')
            )
        except Exception as e:
            return SpaceUpdateResponse(
                space=None,
                updated_count=0,
                error_code=1,
                status_code=500,
                error_message=str(e)
            )
    
    def delete_space(self, space_id: str) -> SpaceDeleteResponse:
        """
        Delete a space.
        
        Args:
            space_id: Space ID
            
        Returns:
            SpaceDeleteResponse with deletion result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id)
        
        try:
            url = f"{self._get_server_url().rstrip('/')}/api/spaces/{space_id}"
            
            response = self._make_authenticated_request('DELETE', url)
            response_data = response.json()
            
            return SpaceDeleteResponse(
                deleted_count=response_data.get('deleted_count', 1),
                space_id=space_id,
                error_code=0,
                status_code=200,
                message=response_data.get('message', 'Space deleted successfully')
            )
        except Exception as e:
            return SpaceDeleteResponse(
                deleted_count=0,
                space_id=space_id,
                error_code=1,
                status_code=500,
                error_message=str(e)
            )
    
    def filter_spaces(self, name_filter: str, tenant: Optional[str] = None) -> SpacesListResponse:
        """
        Filter spaces by name.
        
        Args:
            name_filter: Name filter string
            tenant: Optional tenant filter
            
        Returns:
            SpacesListResponse with filtered spaces
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(name_filter=name_filter)
        
        try:
            url = f"{self._get_server_url().rstrip('/')}/api/spaces/filter/{name_filter}"
            params = build_query_params(tenant=tenant)
            
            response = self._make_authenticated_request('GET', url, params=params)
            response_data = response.json()
            
            # Extract spaces from server response
            spaces_data = response_data.get('spaces', [])
            spaces = [Space(**space_data) for space_data in spaces_data]
            
            return SpacesListResponse(
                spaces=spaces,
                total=response_data.get('total_count', len(spaces)),
                error_code=0,
                status_code=200,
                message=response_data.get('message', 'Spaces filtered successfully')
            )
        except Exception as e:
            return SpacesListResponse(
                spaces=[],
                total=0,
                error_code=1,
                status_code=500,
                error_message=str(e)
            )

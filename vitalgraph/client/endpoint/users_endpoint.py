"""
VitalGraph Client Users Endpoint

Client-side implementation for Users operations.
"""

import httpx
from typing import Dict, Any, Optional, List

from .base_endpoint import BaseEndpoint
from ..utils.client_utils import VitalGraphClientError, validate_required_params, build_query_params
from ...model.users_model import (
    User, UserCreate, UsersListResponse, UserCreateResponse, UserUpdateResponse, UserDeleteResponse,
    PasswordChangeRequest, PasswordChangeResponse,
)


class UsersEndpoint(BaseEndpoint):
    """Client endpoint for Users operations."""
    
    async def list_users(self, tenant: Optional[str] = None) -> UsersListResponse:
        """
        List all users.
        
        Args:
            tenant: Optional tenant filter
            
        Returns:
            UsersListResponse containing users data
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        
        url = f"{self._get_server_url().rstrip('/')}/api/users"
        params = build_query_params(tenant=tenant)
        
        return await self._make_typed_request('GET', url, UsersListResponse, params=params)
    
    async def add_user(self, user: UserCreate) -> UserCreateResponse:
        """
        Add a new user.
        
        Args:
            user: UserCreate object with username, password, and profile data
            
        Returns:
            UserCreateResponse containing creation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(user=user)
        
        url = f"{self._get_server_url().rstrip('/')}/api/users"
        
        return await self._make_typed_request('POST', url, UserCreateResponse, json=user.model_dump())
    
    async def get_user(self, user_id: str) -> User:
        """
        Get a user by ID.
        
        Args:
            user_id: User ID
            
        Returns:
            User object (password excluded)
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(user_id=user_id)
        
        url = f"{self._get_server_url().rstrip('/')}/api/users/user"
        params = build_query_params(user_id=user_id)
        
        return await self._make_typed_request('GET', url, User, params=params)
    
    async def update_user(self, user_id: str, user: User) -> UserUpdateResponse:
        """
        Update a user.
        
        Args:
            user_id: User ID
            user: Updated user object
            
        Returns:
            UserUpdateResponse containing update result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(user_id=user_id, user=user)
        
        url = f"{self._get_server_url().rstrip('/')}/api/users"
        params = build_query_params(user_id=user_id)
        
        return await self._make_typed_request('PUT', url, UserUpdateResponse, params=params, json=user.model_dump())
    
    async def delete_user(self, user_id: str) -> UserDeleteResponse:
        """
        Delete a user.
        
        Args:
            user_id: User ID
            
        Returns:
            UserDeleteResponse containing deletion result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(user_id=user_id)
        
        url = f"{self._get_server_url().rstrip('/')}/api/users"
        params = build_query_params(user_id=user_id)
        
        return await self._make_typed_request('DELETE', url, UserDeleteResponse, params=params)
    
    async def filter_users(self, name_filter: str, tenant: Optional[str] = None) -> UsersListResponse:
        """
        Filter users by name.
        
        Args:
            name_filter: Case-insensitive substring filter on username or full_name
            tenant: Optional tenant filter
            
        Returns:
            UsersListResponse containing filtered users
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(name_filter=name_filter)
        
        url = f"{self._get_server_url().rstrip('/')}/api/users"
        params = build_query_params(name_filter=name_filter, tenant=tenant)
        
        return await self._make_typed_request('GET', url, UsersListResponse, params=params)

    async def get_user_spaces(self, user_id: str) -> Dict[str, Any]:
        """Get space access map for a user (admin only).

        Args:
            user_id: Username to query

        Returns:
            Dict with 'username' and 'spaces' keys
        """
        self._check_connection()
        validate_required_params(user_id=user_id)

        url = f"{self._get_server_url().rstrip('/')}/api/users/spaces"
        params = build_query_params(user_id=user_id)
        response = await self._make_authenticated_request('GET', url, params=params)
        return response.json()

    async def grant_space_access(self, user_id: str, space_id: str, access_level: str = "rw") -> Dict[str, Any]:
        """Grant or update space access for a user (admin only).

        Args:
            user_id: Username to grant access to
            space_id: Space ID to grant access for
            access_level: 'r' (read) or 'rw' (read-write)

        Returns:
            Dict with confirmation message
        """
        self._check_connection()
        validate_required_params(user_id=user_id, space_id=space_id)

        url = f"{self._get_server_url().rstrip('/')}/api/users/spaces"
        params = build_query_params(user_id=user_id, space_id=space_id)
        body = {"access_level": access_level}
        response = await self._make_authenticated_request('PUT', url, params=params, json=body)
        return response.json()

    async def revoke_space_access(self, user_id: str, space_id: str) -> Dict[str, Any]:
        """Revoke a user's access to a specific space (admin only).

        Args:
            user_id: Username to revoke access from
            space_id: Space ID to revoke access for

        Returns:
            Dict with confirmation message
        """
        self._check_connection()
        validate_required_params(user_id=user_id, space_id=space_id)

        url = f"{self._get_server_url().rstrip('/')}/api/users/spaces"
        params = build_query_params(user_id=user_id, space_id=space_id)
        response = await self._make_authenticated_request('DELETE', url, params=params)
        return response.json()

    async def change_password(self, current_password: str, new_password: str) -> PasswordChangeResponse:
        """Change the authenticated user's own password.

        Args:
            current_password: Current password (must match stored hash)
            new_password: New password (minimum 8 characters)

        Returns:
            PasswordChangeResponse confirming the change
        """
        self._check_connection()
        validate_required_params(current_password=current_password, new_password=new_password)

        url = f"{self._get_server_url().rstrip('/')}/api/me/password"
        request = PasswordChangeRequest(
            current_password=current_password, new_password=new_password
        )
        return await self._make_typed_request(
            'POST', url, PasswordChangeResponse, json=request.model_dump(),
        )

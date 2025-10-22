"""Users Endpoint for VitalGraph

Implements REST API endpoints for user management operations.
"""

from typing import Dict, List, Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import JSONResponse
import logging

from ..model.users_model import (
    User, UsersListResponse, UserCreateResponse, UserUpdateResponse, UserDeleteResponse
)


class UsersEndpoint:
    """Users endpoint handler."""
    
    def __init__(self, api, auth_dependency):
        self.api = api
        self.auth_dependency = auth_dependency
        self.logger = logging.getLogger(f"{__name__}.UsersEndpoint")
        self.router = APIRouter()
        self._setup_routes()
    
    def _setup_routes(self):
        """Setup user management routes."""
        
        @self.router.get(
            "/users",
            response_model=UsersListResponse,
            tags=["Users"],
            summary="List Users",
            description="Get a list of all accessible user accounts for the authenticated user"
        )
        async def list_users(current_user: Dict = Depends(self.auth_dependency)):
            users = await self.api.list_users(current_user)
            return UsersListResponse(
                users=users,
                total_count=len(users),
                page_size=len(users),  # No pagination implemented yet
                offset=0
            )
        
        @self.router.post(
            "/users",
            response_model=UserCreateResponse,
            tags=["Users"],
            summary="Create User",
            description="Create a new user account with specified permissions and access rights"
        )
        async def add_user(user: User, current_user: Dict = Depends(self.auth_dependency)):
            created_user = await self.api.add_user(user.dict(), current_user)
            return UserCreateResponse(
                message="User created successfully",
                created_count=1,
                created_uris=[str(created_user.get('id', ''))]
            )
        
        @self.router.get(
            "/users/{user_id}",
            response_model=User,
            tags=["Users"],
            summary="Get User",
            description="Retrieve detailed information about a specific user account by ID"
        )
        async def get_user(user_id: str, current_user: Dict = Depends(self.auth_dependency)):
            return await self.api.get_user_by_id(user_id, current_user)
        
        @self.router.put(
            "/users/{user_id}",
            response_model=UserUpdateResponse,
            tags=["Users"],
            summary="Update User",
            description="Update an existing user account (requires complete user object)"
        )
        async def update_user(user_id: str, user: User, current_user: Dict = Depends(self.auth_dependency)):
            updated_user = await self.api.update_user(user_id, user.dict(), current_user)
            return UserUpdateResponse(
                message="User updated successfully",
                updated_uri=str(updated_user.get('id', user_id))
            )
        
        @self.router.delete(
            "/users/{user_id}",
            response_model=UserDeleteResponse,
            tags=["Users"],
            summary="Delete User",
            description="Permanently delete a user account and revoke all associated access"
        )
        async def delete_user(user_id: str, current_user: Dict = Depends(self.auth_dependency)):
            return await self.api.delete_user(user_id, current_user)


def create_users_router(api, auth_dependency) -> APIRouter:
    """Create and return the users router."""
    endpoint = UsersEndpoint(api, auth_dependency)
    return endpoint.router
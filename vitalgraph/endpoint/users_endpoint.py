"""Users Endpoint for VitalGraph

Implements REST API endpoints for user management operations.
Admin-only endpoints are enforced via role checks.
"""

from typing import Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
import logging

from ..auth.audit import emit_audit_event
from ..auth.role_dependencies import require_admin
from ..auth.password import verify_password, hash_password
from ..model.users_model import (
    User, UserCreate, UsersListResponse, UserCreateResponse, UserUpdateResponse, UserDeleteResponse,
    PasswordChangeRequest, PasswordChangeResponse
)


class UsersEndpoint:
    """Users endpoint handler with role enforcement."""
    
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
            description="Get a list of all accessible user accounts (admin only)"
        )
        async def list_users(
            name_filter: Optional[str] = Query(None, description="Case-insensitive substring filter on username or full_name"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            require_admin(current_user)
            users = await self.api.list_users(current_user, name_filter=name_filter)
            return UsersListResponse(
                users=users,
                total_count=len(users),
                page_size=len(users),
                offset=0
            )
        
        @self.router.post(
            "/users",
            response_model=UserCreateResponse,
            tags=["Users"],
            summary="Create User",
            description="Create a new user account (admin only)"
        )
        async def add_user(user: UserCreate, current_user: Dict = Depends(self.auth_dependency)):
            require_admin(current_user)
            created_user = await self.api.add_user(user.model_dump(), current_user)
            return UserCreateResponse(
                message="User created successfully",
                created_count=1,
                created_uris=[str(created_user.get('id', ''))]
            )
        
        @self.router.get(
            "/users/user",
            response_model=User,
            tags=["Users"],
            summary="Get User",
            description="Retrieve detailed information about a specific user account (admin only)"
        )
        async def get_user(
            user_id: str = Query(..., description="User ID"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            require_admin(current_user)
            return await self.api.get_user_by_id(user_id, current_user)
        
        @self.router.put(
            "/users",
            response_model=UserUpdateResponse,
            tags=["Users"],
            summary="Update User",
            description="Update an existing user account (admin only)"
        )
        async def update_user(
            user: User,
            user_id: str = Query(..., description="User ID"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            require_admin(current_user)
            await self.api.update_user(user_id, user.model_dump(), current_user)
            return UserUpdateResponse(
                message="User updated successfully",
                updated_uri=user_id
            )
        
        @self.router.delete(
            "/users",
            response_model=UserDeleteResponse,
            tags=["Users"],
            summary="Delete User",
            description="Permanently delete a user account (admin only)"
        )
        async def delete_user(
            user_id: str = Query(..., description="User ID"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            require_admin(current_user)
            await self.api.delete_user(user_id, current_user)
            return UserDeleteResponse(
                message="User deleted successfully",
                deleted_count=1,
                deleted_uris=[user_id]
            )

        @self.router.get(
            "/users/spaces",
            tags=["Users"],
            summary="Get User Space Access",
            description="Get space access map for a user (admin only)"
        )
        async def get_user_spaces(
            user_id: str = Query(..., description="User ID"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            require_admin(current_user)
            user = await self.api.db.get_user_by_username(user_id)
            if not user:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
            spaces = await self.api.db.get_user_spaces(user["user_id"])
            return {"username": user_id, "spaces": spaces}

        @self.router.put(
            "/users/spaces",
            tags=["Users"],
            summary="Grant Space Access",
            description="Grant or update space access for a user (admin only)"
        )
        async def grant_space_access(
            body: dict,
            user_id: str = Query(..., description="User ID"),
            space_id: str = Query(..., description="Space ID"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            require_admin(current_user)
            user = await self.api.db.get_user_by_username(user_id)
            if not user:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
            access_level = body.get("access_level", "r")
            if access_level not in ("rw", "r"):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="access_level must be 'rw' or 'r'")
            try:
                await self.api.db.set_user_space_access(
                    user["user_id"], space_id, access_level,
                    granted_by=current_user.get("username")
                )
            except ValueError as e:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
            emit_audit_event("auth.space_access.granted", current_user.get("username", "system"),
                             target=user_id, space_id=space_id, level=access_level)
            return {"message": f"Access '{access_level}' granted to '{user_id}' for space '{space_id}'"}

        @self.router.delete(
            "/users/spaces",
            tags=["Users"],
            summary="Revoke Space Access",
            description="Revoke a user's access to a specific space (admin only)"
        )
        async def revoke_space_access(
            user_id: str = Query(..., description="User ID"),
            space_id: str = Query(..., description="Space ID"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            require_admin(current_user)
            user = await self.api.db.get_user_by_username(user_id)
            if not user:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
            await self.api.db.revoke_user_space_access(user["user_id"], space_id)
            emit_audit_event("auth.space_access.revoked", current_user.get("username", "system"),
                             target=user_id, space_id=space_id)
            return {"message": f"Access revoked for '{user_id}' on space '{space_id}'"}

        @self.router.post(
            "/me/password",
            response_model=PasswordChangeResponse,
            tags=["Users"],
            summary="Change Own Password",
            description="Change the authenticated user's password (requires current password)"
        )
        async def change_own_password(
            body: PasswordChangeRequest,
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """Self-service password change for authenticated users."""
            username = current_user["username"]

            # Fetch user from DB to get stored hash
            if self.api.db is None:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Database not available"
                )

            user = await self.api.db.get_user_by_username(username)
            if not user or not user.get("is_active", True):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User not found or inactive"
                )

            # Verify current password
            stored_hash = user.get("password_hash")
            if not stored_hash or not verify_password(body.current_password, stored_hash):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Current password is incorrect"
                )

            # Ensure new password differs from current
            if body.current_password == body.new_password:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="New password must differ from current password"
                )

            # Hash and store new password (also bumps token_version)
            new_hash = hash_password(body.new_password)
            await self.api.db.update_user_password_hash(username, new_hash)

            # Invalidate token version cache so revocation propagates immediately
            if hasattr(self.api, 'auth') and self.api.auth:
                self.api.auth.invalidate_token_cache(username)

            # Notify all instances via PostgreSQL LISTEN/NOTIFY
            if self.api.signal_manager:
                try:
                    await self.api.signal_manager.notify_token_version_changed(
                        username, signal_type="password_changed"
                    )
                except Exception as e:
                    self.logger.warning(f"Token version NOTIFY failed for '{username}': {e}")

            emit_audit_event("auth.password.changed", username,
                             target=username, changed_by="self")
            self.logger.info(f"Password changed for user '{username}' (self-service)")
            return PasswordChangeResponse()


def create_users_router(api, auth_dependency) -> APIRouter:
    """Create and return the users router."""
    endpoint = UsersEndpoint(api, auth_dependency)
    return endpoint.router
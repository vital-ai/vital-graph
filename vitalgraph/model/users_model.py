"""Users Model Classes

Pydantic models for user management operations.
"""

from typing import Optional, List
from pydantic import BaseModel, Field

from .api_model import BasePaginatedResponse, BaseCreateResponse, BaseUpdateResponse, BaseDeleteResponse, BaseOperationResponse


class User(BaseModel):
    """User model for VitalGraph database.
    
    Represents a user account with authentication credentials and profile information.
    Users can access and manage spaces within their authorized tenant scope.
    """
    id: Optional[str] = Field(
        None, 
        description="Unique user identifier (username)",
        example="admin"
    )
    username: str = Field(
        ..., 
        description="Unique username for authentication (required)",
        example="admin"
    )
    full_name: Optional[str] = Field(
        "", 
        description="Full display name of the user",
        example="Admin User"
    )
    email: Optional[str] = Field(
        "", 
        description="User email address for notifications and recovery",
        example="admin@example.com"
    )
    profile_image: Optional[str] = Field(
        None, 
        description="URL or path to user's profile image",
        example="/images/users/bonnie-green.png"
    )
    role: str = Field(
        ..., 
        description="User role/permission level",
        example="Administrator"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "admin",
                "username": "admin",
                "full_name": "Admin User",
                "email": "admin@example.com",
                "profile_image": "/images/users/bonnie-green.png",
                "role": "Administrator"
            }
        }


class UserCreate(BaseModel):
    """Request model for creating a new user account.

    Includes a write-only ``password`` field that is never returned in
    responses.  The ``User`` model is used for all read operations.
    """
    username: str = Field(
        ...,
        description="Unique username for authentication (required)",
        example="newuser"
    )
    password: str = Field(
        ...,
        min_length=8,
        description="Initial password (write-only, minimum 8 characters)"
    )
    full_name: Optional[str] = Field(
        "",
        description="Full display name of the user",
        example="New User"
    )
    email: Optional[str] = Field(
        "",
        description="User email address",
        example="newuser@example.com"
    )
    role: str = Field(
        "user",
        description="User role: admin, user, or reader",
        example="user"
    )


class UsersListResponse(BasePaginatedResponse):
    """Response model for users listing operations."""
    users: List[User] = Field(..., description="List of users")


class UserCreateResponse(BaseCreateResponse):
    """Response model for user creation operations."""
    pass


class UserUpdateResponse(BaseUpdateResponse):
    """Response model for user update operations."""
    pass


class UserDeleteResponse(BaseDeleteResponse):
    """Response model for user deletion operations."""
    pass


class UserOperationResponse(BaseOperationResponse):
    """Response model for general user operations."""
    pass


class PasswordChangeRequest(BaseModel):
    """Request model for self-service password change."""
    current_password: str = Field(..., description="Current password (must match stored hash)")
    new_password: str = Field(..., min_length=8, description="New password (minimum 8 characters)")


class PasswordChangeResponse(BaseModel):
    """Response model for self-service password change."""
    message: str = "Password changed successfully"
    tokens_invalidated: bool = True
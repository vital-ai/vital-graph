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
    full_name: str = Field(
        ..., 
        description="Full display name of the user",
        example="Admin User"
    )
    email: str = Field(
        ..., 
        description="User email address for notifications and recovery (required)",
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
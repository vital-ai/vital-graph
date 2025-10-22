"""Mock User

Mock implementation of a VitalGraph user for testing.
"""

from typing import Dict, Any, Optional
from datetime import datetime


class MockUser:
    """
    Mock implementation of a VitalGraph user.
    
    Represents a user in the mock VitalGraph system with
    basic user properties and metadata.
    """
    
    def __init__(self, user_id: int, username: str, email: str, 
                 tenant: Optional[str] = None, **kwargs):
        """
        Initialize a mock user.
        
        Args:
            user_id: Unique user identifier
            username: Username
            email: User email address
            tenant: Optional tenant identifier
            **kwargs: Additional user properties
        """
        self.user_id = user_id
        self.username = username
        self.email = email
        self.tenant = tenant
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        self.is_active = True
        self.properties = kwargs
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert user to dictionary representation.
        
        Returns:
            Dictionary containing user data
        """
        return {
            "user_id": self.user_id,
            "username": self.username,
            "email": self.email,
            "tenant": self.tenant,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "is_active": self.is_active,
            **self.properties
        }
    
    def update(self, **kwargs) -> None:
        """
        Update user properties.
        
        Args:
            **kwargs: Properties to update
        """
        for key, value in kwargs.items():
            if key in ["username", "email", "tenant", "is_active"]:
                setattr(self, key, value)
            else:
                self.properties[key] = value
        
        self.updated_at = datetime.now()
    
    def __str__(self) -> str:
        """String representation of the user."""
        return f"MockUser(id={self.user_id}, username='{self.username}', email='{self.email}')"
    
    def __repr__(self) -> str:
        """Detailed string representation of the user."""
        return self.__str__()
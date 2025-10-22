"""Mock Space Manager

Mock implementation of a VitalGraph space manager for testing.
Manages collections of spaces and users.
"""

from typing import Dict, Any, Optional, List
import logging

from .mock_space import MockSpace
from .mock_user import MockUser

logger = logging.getLogger(__name__)


class MockSpaceManager:
    """
    Mock implementation of a VitalGraph space manager.
    
    Manages a collection of mock spaces and users for testing.
    Each space contains its own pyoxigraph store for data storage.
    """
    
    def __init__(self):
        """Initialize the mock space manager."""
        self.spaces: Dict[int, MockSpace] = {}
        self.users: List[MockUser] = []
        self._next_space_id = 1
        self._next_user_id = 1
        
        logger.info("Initialized MockSpaceManager")
    
    # Space Management
    
    def create_space(self, name: str, tenant: Optional[str] = None, **kwargs) -> MockSpace:
        """
        Create a new mock space.
        
        Args:
            name: Space name
            tenant: Optional tenant identifier
            **kwargs: Additional space properties
            
        Returns:
            Created MockSpace instance
        """
        space_id = self._next_space_id
        self._next_space_id += 1
        
        space = MockSpace(
            space_id=space_id,
            name=name,
            tenant=tenant,
            **kwargs
        )
        
        self.spaces[space_id] = space
        logger.info(f"Created space {space_id}: '{name}'")
        return space
    
    def get_space(self, space_id) -> Optional[MockSpace]:
        """
        Get a space by ID or name.
        
        Args:
            space_id: Space identifier (int) or space name (str)
            
        Returns:
            MockSpace instance or None if not found
        """
        # If it's an integer, look up by ID
        if isinstance(space_id, int):
            return self.spaces.get(space_id)
        
        # If it's a string, look up by name
        if isinstance(space_id, str):
            for space in self.spaces.values():
                if space.name == space_id:
                    return space
        
        return None
    
    def list_spaces(self, tenant: Optional[str] = None) -> List[MockSpace]:
        """
        List all spaces, optionally filtered by tenant.
        
        Args:
            tenant: Optional tenant filter
            
        Returns:
            List of MockSpace instances
        """
        spaces = list(self.spaces.values())
        
        if tenant:
            spaces = [space for space in spaces if space.tenant == tenant]
        
        return spaces
    
    def update_space(self, space_id: int, **kwargs) -> bool:
        """
        Update a space's properties.
        
        Args:
            space_id: Space identifier
            **kwargs: Properties to update
            
        Returns:
            True if space was updated, False if not found
        """
        space = self.get_space(space_id)
        if space:
            space.update(**kwargs)
            logger.info(f"Updated space {space_id}")
            return True
        return False
    
    def delete_space(self, space_id: int) -> bool:
        """
        Delete a space.
        
        Args:
            space_id: Space identifier
            
        Returns:
            True if space was deleted, False if not found
        """
        if space_id in self.spaces:
            space = self.spaces[space_id]
            del self.spaces[space_id]
            logger.info(f"Deleted space {space_id}: '{space.name}'")
            return True
        return False
    
    def filter_spaces(self, name_filter: str, tenant: Optional[str] = None) -> List[MockSpace]:
        """
        Filter spaces by name pattern.
        
        Args:
            name_filter: Name filter pattern
            tenant: Optional tenant filter
            
        Returns:
            List of matching MockSpace instances
        """
        spaces = self.list_spaces(tenant)
        filtered = []
        
        for space in spaces:
            if name_filter.lower() in space.name.lower():
                filtered.append(space)
        
        return filtered
    
    # User Management
    
    def create_user(self, username: str, email: str, tenant: Optional[str] = None, **kwargs) -> MockUser:
        """
        Create a new mock user.
        
        Args:
            username: Username
            email: User email
            tenant: Optional tenant identifier
            **kwargs: Additional user properties
            
        Returns:
            Created MockUser instance
        """
        user_id = self._next_user_id
        self._next_user_id += 1
        
        user = MockUser(
            user_id=user_id,
            username=username,
            email=email,
            tenant=tenant,
            **kwargs
        )
        
        self.users.append(user)
        logger.info(f"Created user {user_id}: '{username}'")
        return user
    
    def get_user(self, user_id: int) -> Optional[MockUser]:
        """
        Get a user by ID.
        
        Args:
            user_id: User identifier
            
        Returns:
            MockUser instance or None if not found
        """
        for user in self.users:
            if user.user_id == user_id:
                return user
        return None
    
    def get_user_by_username(self, username: str) -> Optional[MockUser]:
        """
        Get a user by username.
        
        Args:
            username: Username
            
        Returns:
            MockUser instance or None if not found
        """
        for user in self.users:
            if user.username == username:
                return user
        return None
    
    def list_users(self, tenant: Optional[str] = None) -> List[MockUser]:
        """
        List all users, optionally filtered by tenant.
        
        Args:
            tenant: Optional tenant filter
            
        Returns:
            List of MockUser instances
        """
        users = self.users.copy()
        
        if tenant:
            users = [user for user in users if user.tenant == tenant]
        
        return users
    
    def update_user(self, user_id: int, **kwargs) -> bool:
        """
        Update a user's properties.
        
        Args:
            user_id: User identifier
            **kwargs: Properties to update
            
        Returns:
            True if user was updated, False if not found
        """
        user = self.get_user(user_id)
        if user:
            user.update(**kwargs)
            logger.info(f"Updated user {user_id}")
            return True
        return False
    
    def delete_user(self, user_id: int) -> bool:
        """
        Delete a user.
        
        Args:
            user_id: User identifier
            
        Returns:
            True if user was deleted, False if not found
        """
        user = self.get_user(user_id)
        if user:
            self.users.remove(user)
            logger.info(f"Deleted user {user_id}: '{user.username}'")
            return True
        return False
    
    def filter_users(self, name_filter: str, tenant: Optional[str] = None) -> List[MockUser]:
        """
        Filter users by name pattern.
        
        Args:
            name_filter: Name filter pattern
            tenant: Optional tenant filter
            
        Returns:
            List of matching MockUser instances
        """
        users = self.list_users(tenant)
        filtered = []
        
        for user in users:
            if (name_filter.lower() in user.username.lower() or 
                name_filter.lower() in user.email.lower()):
                filtered.append(user)
        
        return filtered
    
    # Statistics and Info
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get manager statistics.
        
        Returns:
            Dictionary containing statistics
        """
        total_graphs = sum(len(space.graphs) for space in self.spaces.values())
        total_triples = sum(space.get_total_triple_count() for space in self.spaces.values())
        
        return {
            "total_spaces": len(self.spaces),
            "total_users": len(self.users),
            "total_graphs": total_graphs,
            "total_triples": total_triples,
            "active_spaces": len([s for s in self.spaces.values() if s.is_active]),
            "active_users": len([u for u in self.users if u.is_active])
        }
    
    def __str__(self) -> str:
        """String representation of the manager."""
        return f"MockSpaceManager(spaces={len(self.spaces)}, users={len(self.users)})"
    
    def __repr__(self) -> str:
        """Detailed string representation of the manager."""
        return self.__str__()
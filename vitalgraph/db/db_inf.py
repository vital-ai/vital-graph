# interface for db

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List


class DbImplInterface(ABC):
    """
    Common interface for database implementation components.
    Both PostgreSQL and FUSEKI_POSTGRESQL backends will implement this interface.
    """
    
    @abstractmethod
    async def connect(self) -> bool:
        """Establish database connection."""
        pass
    
    @abstractmethod
    async def disconnect(self) -> bool:
        """Close database connection."""
        pass
    
    @abstractmethod
    async def is_connected(self) -> bool:
        """Check if database connection is active."""
        pass
    
    @abstractmethod
    async def execute_query(self, query: str, params: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """Execute a database query and return results."""
        pass
    
    @abstractmethod
    async def execute_update(self, query: str, params: Optional[Dict] = None) -> bool:
        """Execute a database update/insert/delete operation."""
        pass
    
    @abstractmethod
    async def begin_transaction(self) -> Any:
        """Begin a database transaction."""
        pass
    
    @abstractmethod
    async def commit_transaction(self, transaction: Any) -> bool:
        """Commit a database transaction."""
        pass
    
    @abstractmethod
    async def rollback_transaction(self, transaction: Any) -> bool:
        """Rollback a database transaction."""
        pass
    
    @abstractmethod
    def get_connection_info(self) -> Dict[str, Any]:
        """Get database connection information."""
        pass

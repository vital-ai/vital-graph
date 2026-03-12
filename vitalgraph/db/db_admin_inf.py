"""
Common admin interface for VitalGraph database backends.

Each backend implementation (sparql_sql, fuseki_postgresql) provides
its own admin module that implements this interface.  The admin CLI
delegates to the backend-specific admin module instead of containing
inline DDL and queries.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List

from .common.models import GraphData, SpaceData, UserData


class DbAdminInterface(ABC):
    """Abstract base class for backend-specific admin operations."""

    @abstractmethod
    async def check_admin_tables(self, db_impl) -> Dict[str, Any]:
        """Check which admin tables exist.

        Returns:
            Dict with at least:
              - 'expected': int  (total expected tables)
              - 'found': int    (tables that exist)
              - 'tables': List[str]  (names of existing tables)
        """

    @abstractmethod
    async def init_tables(self, db_impl) -> bool:
        """Create admin tables, indexes, and seed data.

        Should be idempotent (uses IF NOT EXISTS).

        Returns:
            True on success.
        """

    @abstractmethod
    async def purge_tables(self, db_impl) -> bool:
        """Delete all data from admin and per-space tables, keeping structure.

        Returns:
            True on success.
        """

    @abstractmethod
    async def delete_tables(self, db_impl) -> bool:
        """Drop all admin and per-space tables.

        Returns:
            True on success.
        """

    @abstractmethod
    async def get_info(self, db_impl, config=None) -> Dict[str, Any]:
        """Return installation info suitable for display.

        Returns:
            Dict with backend-specific status information.
        """

    @abstractmethod
    async def list_spaces(self, db_impl) -> List[SpaceData]:
        """List all configured spaces.

        Returns:
            List of SpaceData records.
        """

    @abstractmethod
    async def list_graphs(self, db_impl, space_id: str = None) -> List[GraphData]:
        """List graphs, optionally filtered by space.

        Args:
            space_id: If provided, only return graphs for this space.

        Returns:
            List of GraphData records.
        """

    @abstractmethod
    async def list_users(self, db_impl) -> List[UserData]:
        """List all configured users.

        Returns:
            List of UserData records.
        """

"""
VitalGraph Client - Admin Endpoint

Client-side endpoint for Admin REST API operations (resync, etc.).
"""

import logging
from typing import Optional

from .base_endpoint import BaseEndpoint
from ..utils.client_utils import build_query_params
from ...model.admin_model import ResyncResponse, AuditLogResponse


logger = logging.getLogger(__name__)


class AdminClientEndpoint(BaseEndpoint):
    """Client endpoint for Admin operations."""

    def __init__(self, client):
        super().__init__(client)
        self._base_path = "/api/admin"

    def _url(self, path: str = "") -> str:
        return f"{self._get_server_url()}{self._base_path}{path}"

    async def resync(self, space_id: str) -> ResyncResponse:
        """Resync all auxiliary tables (edge, frame_entity, stats) for a space.

        Rebuilds maintained tables from rdf_quad, runs ANALYZE, and
        invalidates the in-memory stats cache.

        Args:
            space_id: Space ID to resync

        Returns:
            ResyncResponse with row counts and elapsed time
        """
        self._check_connection()
        return await self._make_typed_request(
            "POST",
            self._url("/resync"),
            ResyncResponse,
            params={"space_id": space_id},
        )

    async def audit_log(
        self,
        event: Optional[str] = None,
        actor: Optional[str] = None,
        level: Optional[str] = None,
        last: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> AuditLogResponse:
        """Query the audit log with filters and pagination (admin only).

        Args:
            event: Filter by event name (prefix match)
            actor: Filter by actor username
            level: Filter by level (INFO, WARN, ERROR)
            last: Duration filter, e.g. '24h', '7d'
            limit: Max entries to return (1-500, default 50)
            offset: Offset for pagination

        Returns:
            AuditLogResponse with entries and total count
        """
        self._check_connection()
        params = build_query_params(
            event=event, actor=actor, level=level,
            last=last, limit=limit, offset=offset,
        )
        return await self._make_typed_request(
            "GET",
            self._url("/audit"),
            AuditLogResponse,
            params=params,
        )

"""
VitalGraph Client - Admin Endpoint

Client-side endpoint for Admin REST API operations (resync, etc.).
"""

import logging
from typing import Optional

from .base_endpoint import BaseEndpoint
from ...endpoint.admin_endpoint import ResyncResponse


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

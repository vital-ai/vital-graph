"""
VitalGraph Client - Geo Config Endpoint

Client-side endpoint for Geo Configuration REST API operations.
"""

import logging
from typing import Dict, List, Optional

from .base_endpoint import BaseEndpoint
from ..utils.client_utils import VitalGraphClientError, validate_required_params
from ...model.geo_model import GeoConfigOut, UpdateGeoConfigRequest

logger = logging.getLogger(__name__)


class GeoConfigClientEndpoint(BaseEndpoint):
    """Client endpoint for Geo Config management operations."""

    def __init__(self, client):
        super().__init__(client)

    def _url(self, space_id: str) -> str:
        return f"{self._get_server_url()}/api/spaces/{space_id}/geo-config"

    async def get_config(self, space_id: str) -> GeoConfigOut:
        """Get current geo configuration for a space (creates defaults if absent).

        Args:
            space_id: Space ID

        Returns:
            GeoConfigOut with current config
        """
        self._check_connection()
        validate_required_params(space_id=space_id)
        return await self._make_typed_request(
            "GET", self._url(space_id), GeoConfigOut,
        )

    async def update_config(
        self,
        space_id: str,
        enabled: Optional[bool] = None,
        auto_sync: Optional[bool] = None,
        lat_predicates: Optional[List[str]] = None,
        lon_predicates: Optional[List[str]] = None,
    ) -> GeoConfigOut:
        """Update geo configuration for a space.

        Args:
            space_id: Space ID
            enabled: Enable/disable geo extraction
            auto_sync: Enable/disable auto-sync on data changes
            lat_predicates: List of latitude predicate URIs
            lon_predicates: List of longitude predicate URIs

        Returns:
            GeoConfigOut with updated config
        """
        self._check_connection()
        validate_required_params(space_id=space_id)
        request = UpdateGeoConfigRequest(
            enabled=enabled, auto_sync=auto_sync,
            lat_predicates=lat_predicates, lon_predicates=lon_predicates,
        )
        return await self._make_typed_request(
            "PUT", self._url(space_id), GeoConfigOut,
            json=request.model_dump(exclude_none=True),
        )

    async def delete_config(self, space_id: str) -> Dict:
        """Reset geo configuration to unconfigured state.

        Args:
            space_id: Space ID

        Returns:
            Dict with confirmation message
        """
        self._check_connection()
        validate_required_params(space_id=space_id)
        response = await self._make_authenticated_request(
            "DELETE", self._url(space_id),
        )
        return response.json()

"""
VitalGraph Client - Geo Points Endpoint

Client-side endpoint for Geo Points REST API operations.
"""

import logging
from typing import Optional

from .base_endpoint import BaseEndpoint
from ..utils.client_utils import VitalGraphClientError, validate_required_params, build_query_params
from ...model.geo_model import GeoPointsResponse

logger = logging.getLogger(__name__)


class GeoPointsClientEndpoint(BaseEndpoint):
    """Client endpoint for listing/querying geo points."""

    def __init__(self, client):
        super().__init__(client)

    def _url(self, space_id: str) -> str:
        return f"{self._get_server_url()}/api/spaces/{space_id}/geo"

    async def list_points(
        self,
        space_id: str,
        near_lat: Optional[float] = None,
        near_lon: Optional[float] = None,
        radius_km: Optional[float] = None,
        graph_uri: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> GeoPointsResponse:
        """List geo-populated entities in a space.

        Optionally filter by spatial radius and/or graph URI.
        Spatial query requires all three: near_lat, near_lon, radius_km.

        Args:
            space_id: Space ID
            near_lat: Latitude of center point
            near_lon: Longitude of center point
            radius_km: Radius in km (0.001–40075)
            graph_uri: Filter to a specific graph URI
            limit: Max results (1-1000, default 100)
            offset: Pagination offset

        Returns:
            GeoPointsResponse with points, total count, limit, offset
        """
        self._check_connection()
        validate_required_params(space_id=space_id)
        params = build_query_params(
            near_lat=near_lat, near_lon=near_lon, radius_km=radius_km,
            graph_uri=graph_uri, limit=limit, offset=offset,
        )
        return await self._make_typed_request(
            "GET", self._url(space_id), GeoPointsResponse, params=params,
        )

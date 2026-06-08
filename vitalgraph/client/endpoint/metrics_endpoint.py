"""
VitalGraph Client - Metrics Endpoint

Client-side endpoint for Query Metrics REST API operations.
"""

import logging
from typing import Any, Dict

from .base_endpoint import BaseEndpoint
from ..utils.client_utils import VitalGraphClientError, validate_required_params, build_query_params
from ...model.metrics_model import MetricsResponse, SlowQueriesResponse

logger = logging.getLogger(__name__)


class MetricsClientEndpoint(BaseEndpoint):
    """Client endpoint for query metrics operations."""

    def __init__(self, client):
        super().__init__(client)

    def _url(self, space_id: str, path: str = "") -> str:
        return f"{self._get_server_url()}/api/spaces/{space_id}/metrics{path}"

    async def get_metrics(
        self, space_id: str, range: str = "realtime",
    ) -> Dict[str, Any]:
        """Get time-series query metrics for a space.

        Args:
            space_id: Space ID
            range: Time range — realtime, 24h, 7d, 30d

        Returns:
            Dict with success, space_id, range, granularity, timestamps, series, totals
        """
        self._check_connection()
        validate_required_params(space_id=space_id)
        params = build_query_params(range=range)
        response = await self._make_authenticated_request(
            "GET", self._url(space_id), params=params,
        )
        return response.json()

    async def get_slow_queries(
        self, space_id: str, limit: int = 50,
    ) -> Dict[str, Any]:
        """Get recent slow queries for a space.

        Args:
            space_id: Space ID
            limit: Max entries (1-100, default 50)

        Returns:
            Dict with success, space_id, slow_queries list
        """
        self._check_connection()
        validate_required_params(space_id=space_id)
        params = build_query_params(limit=limit)
        response = await self._make_authenticated_request(
            "GET", self._url(space_id, "/slow"), params=params,
        )
        return response.json()

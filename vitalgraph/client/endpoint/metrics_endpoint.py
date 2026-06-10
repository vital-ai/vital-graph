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

    _METRICS_URL = "/api/metrics"
    _SLOW_URL = "/api/metrics/slow"

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
        url = f"{self._get_server_url()}{self._METRICS_URL}"
        params = build_query_params(space_id=space_id, range=range)
        response = await self._make_authenticated_request(
            "GET", url, params=params,
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
        url = f"{self._get_server_url()}{self._SLOW_URL}"
        params = build_query_params(space_id=space_id, limit=limit)
        response = await self._make_authenticated_request(
            "GET", url, params=params,
        )
        return response.json()

"""
VitalGraph Client - Process Tracking Endpoint

Client-side endpoint for Process Tracking REST API operations.
"""

import logging
from typing import Any, Dict, List, Optional

from .base_endpoint import BaseEndpoint
from ...endpoint.process_endpoint import (
    ProcessListResponse,
    ProcessResponse,
    SchedulerStatusResponse,
    TriggerRequest,
    TriggerResponse,
)


logger = logging.getLogger(__name__)


class ProcessClientEndpoint(BaseEndpoint):
    """Client endpoint for Process Tracking operations."""

    def __init__(self, client):
        super().__init__(client)
        self._base_path = "/api/processes"

    def _url(self, path: str = "") -> str:
        return f"{self._get_server_url()}{self._base_path}{path}"

    # ------------------------------------------------------------------
    # List / Get
    # ------------------------------------------------------------------

    async def list_processes(
        self,
        process_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ProcessListResponse:
        """List process records with optional filters."""
        self._check_connection()
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if process_type:
            params["process_type"] = process_type
        if status:
            params["status"] = status
        return await self._make_typed_request(
            "GET", self._url(), ProcessListResponse, params=params,
        )

    async def get_process(self, process_id: str) -> ProcessResponse:
        """Get a single process record by ID."""
        self._check_connection()
        return await self._make_typed_request(
            "GET", self._url("/detail"), ProcessResponse,
            params={"process_id": process_id},
        )

    # ------------------------------------------------------------------
    # Scheduler status
    # ------------------------------------------------------------------

    async def get_scheduler_status(self) -> SchedulerStatusResponse:
        """Get the current scheduler status."""
        self._check_connection()
        return await self._make_typed_request(
            "GET", self._url("/scheduler"), SchedulerStatusResponse,
        )

    # ------------------------------------------------------------------
    # Trigger
    # ------------------------------------------------------------------

    async def trigger(
        self,
        process_type: str,
        space_id: Optional[str] = None,
    ) -> TriggerResponse:
        """Manually trigger a maintenance operation."""
        self._check_connection()
        body = TriggerRequest(process_type=process_type, space_id=space_id)
        return await self._make_typed_request(
            "POST", self._url("/trigger"), TriggerResponse,
            json=body.model_dump(exclude_none=True),
        )

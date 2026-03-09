"""
VitalGraph Client - Agent Registry Endpoint

Client-side endpoint for Agent Registry REST API operations.
"""

import logging
from typing import Any, Dict, List, Optional

from .base_endpoint import BaseEndpoint
from ...agent_registry.agent_models import (
    AgentCreate,
    AgentEndpointCreate,
    AgentEndpointResponse,
    AgentEndpointUpdate,
    AgentListResponse,
    AgentResponse,
    AgentStatusChange,
    AgentTypeCreate,
    AgentTypeResponse,
    AgentUpdate,
)


logger = logging.getLogger(__name__)


class AgentRegistryClientEndpoint(BaseEndpoint):
    """Client endpoint for Agent Registry operations."""

    def __init__(self, client):
        super().__init__(client)
        self._base_path = "/api/agents"

    def _url(self, path: str) -> str:
        return f"{self._get_server_url()}{self._base_path}{path}"

    # ------------------------------------------------------------------
    # Agent Types
    # ------------------------------------------------------------------

    async def list_agent_types(self) -> List[AgentTypeResponse]:
        """List all agent types."""
        self._check_connection()
        response = await self._make_authenticated_request(
            "GET", self._url("/agent/types"),
        )
        data = response.json()
        return [AgentTypeResponse.model_validate(t) for t in data]

    async def create_agent_type(self, request: AgentTypeCreate) -> AgentTypeResponse:
        """Create a new agent type."""
        self._check_connection()
        return await self._make_typed_request(
            "POST", self._url("/agent/types"), AgentTypeResponse,
            json=request.model_dump(exclude_none=True),
        )

    # ------------------------------------------------------------------
    # Agent CRUD
    # ------------------------------------------------------------------

    async def create_agent(self, request: AgentCreate) -> AgentResponse:
        """Create a new agent."""
        self._check_connection()
        return await self._make_typed_request(
            "POST", self._url("/agent"), AgentResponse,
            json=request.model_dump(exclude_none=True),
        )

    async def get_agent(self, agent_id: str) -> AgentListResponse:
        """Get agent by ID."""
        self._check_connection()
        return await self._make_typed_request(
            "GET", self._url("/agent"), AgentListResponse,
            params={"agent_id": agent_id},
        )

    async def get_agent_by_uri(self, agent_uri: str) -> AgentListResponse:
        """Get agent by URI."""
        self._check_connection()
        return await self._make_typed_request(
            "GET", self._url("/agent"), AgentListResponse,
            params={"agent_uri": agent_uri},
        )

    async def search_agents(
        self,
        query: Optional[str] = None,
        type_key: Optional[str] = None,
        entity_id: Optional[str] = None,
        capability: Optional[str] = None,
        protocol_format_uri: Optional[str] = None,
        status: Optional[str] = 'active',
        page: int = 1,
        page_size: int = 20,
    ) -> AgentListResponse:
        """Search/list agents with filters."""
        self._check_connection()
        params: Dict[str, Any] = {"page": page, "page_size": page_size}
        if query:
            params["query"] = query
        if type_key:
            params["type_key"] = type_key
        if entity_id:
            params["entity_id"] = entity_id
        if capability:
            params["capability"] = capability
        if protocol_format_uri:
            params["protocol_format_uri"] = protocol_format_uri
        if status:
            params["status"] = status
        return await self._make_typed_request(
            "GET", self._url("/agent"), AgentListResponse, params=params,
        )

    async def update_agent(self, agent_id: str, request: AgentUpdate) -> AgentResponse:
        """Update an agent."""
        self._check_connection()
        return await self._make_typed_request(
            "PUT", self._url("/agent"), AgentResponse,
            params={"agent_id": agent_id},
            json=request.model_dump(exclude_none=True),
        )

    async def delete_agent(self, agent_id: str) -> Dict[str, Any]:
        """Soft-delete an agent."""
        self._check_connection()
        response = await self._make_authenticated_request(
            "DELETE", self._url("/agent"),
            params={"agent_id": agent_id},
        )
        return response.json()

    async def change_agent_status(self, agent_id: str, request: AgentStatusChange) -> Dict[str, Any]:
        """Change agent status."""
        self._check_connection()
        response = await self._make_authenticated_request(
            "PUT", self._url("/agent/status"),
            params={"agent_id": agent_id},
            json=request.model_dump(exclude_none=True),
        )
        return response.json()

    # ------------------------------------------------------------------
    # Agent Endpoints
    # ------------------------------------------------------------------

    async def list_endpoints(self, agent_id: str) -> List[AgentEndpointResponse]:
        """List all endpoints for an agent."""
        self._check_connection()
        response = await self._make_authenticated_request(
            "GET", self._url("/agent/endpoints"),
            params={"agent_id": agent_id},
        )
        data = response.json()
        return [AgentEndpointResponse.model_validate(ep) for ep in data]

    async def create_endpoint(self, agent_id: str, request: AgentEndpointCreate) -> AgentEndpointResponse:
        """Create an endpoint for an agent."""
        self._check_connection()
        return await self._make_typed_request(
            "POST", self._url("/agent/endpoints"), AgentEndpointResponse,
            params={"agent_id": agent_id},
            json=request.model_dump(exclude_none=True),
        )

    async def update_endpoint(self, endpoint_id: int, request: AgentEndpointUpdate) -> AgentEndpointResponse:
        """Update an endpoint."""
        self._check_connection()
        return await self._make_typed_request(
            "PUT", self._url("/agent/endpoints"), AgentEndpointResponse,
            params={"endpoint_id": endpoint_id},
            json=request.model_dump(exclude_none=True),
        )

    async def delete_endpoint(self, endpoint_id: int) -> Dict[str, Any]:
        """Delete an endpoint."""
        self._check_connection()
        response = await self._make_authenticated_request(
            "DELETE", self._url("/agent/endpoints"),
            params={"endpoint_id": endpoint_id},
        )
        return response.json()

    # ------------------------------------------------------------------
    # Change Log
    # ------------------------------------------------------------------

    async def get_change_log(self, agent_id: str, limit: int = 50) -> Dict[str, Any]:
        """Get agent change log."""
        self._check_connection()
        response = await self._make_authenticated_request(
            "GET", self._url("/agent/changelog"),
            params={"agent_id": agent_id, "limit": limit},
        )
        return response.json()

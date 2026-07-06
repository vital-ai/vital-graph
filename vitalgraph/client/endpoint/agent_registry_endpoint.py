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
    AgentFunctionCreate,
    AgentFunctionResponse,
    AgentFunctionUpdate,
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
    # Agent Functions
    # ------------------------------------------------------------------

    async def list_functions(self, agent_id: str) -> List[AgentFunctionResponse]:
        """List all functions for an agent."""
        self._check_connection()
        response = await self._make_authenticated_request(
            "GET", self._url("/agent/functions"),
            params={"agent_id": agent_id},
        )
        data = response.json()
        return [AgentFunctionResponse.model_validate(fn) for fn in data]

    async def create_function(self, agent_id: str, request: AgentFunctionCreate) -> AgentFunctionResponse:
        """Create a function for an agent."""
        self._check_connection()
        return await self._make_typed_request(
            "POST", self._url("/agent/functions"), AgentFunctionResponse,
            params={"agent_id": agent_id},
            json=request.model_dump(exclude_none=True),
        )

    async def get_function(self, function_id: int) -> AgentFunctionResponse:
        """Get a function by ID."""
        self._check_connection()
        return await self._make_typed_request(
            "GET", self._url("/agent/function"), AgentFunctionResponse,
            params={"function_id": function_id},
        )

    async def update_function(self, function_id: int, request: AgentFunctionUpdate) -> AgentFunctionResponse:
        """Update a function."""
        self._check_connection()
        return await self._make_typed_request(
            "PUT", self._url("/agent/functions"), AgentFunctionResponse,
            params={"function_id": function_id},
            json=request.model_dump(exclude_none=True),
        )

    async def delete_function(self, function_id: int) -> Dict[str, Any]:
        """Soft-delete a function."""
        self._check_connection()
        response = await self._make_authenticated_request(
            "DELETE", self._url("/agent/functions"),
            params={"function_id": function_id},
        )
        return response.json()

    async def discover_by_function(self, function_uri: str, agent_status: str = 'active') -> Dict[str, Any]:
        """Find agents that provide a specific function URI."""
        self._check_connection()
        response = await self._make_authenticated_request(
            "GET", self._url("/agent/function/discover"),
            params={"function_uri": function_uri, "agent_status": agent_status},
        )
        return response.json()

    async def discover_agents(
        self,
        capability: Optional[str] = None,
        type_key: Optional[str] = None,
        protocol_format_uri: Optional[str] = None,
        protocol_config_key: Optional[str] = None,
        protocol_config_contains: Optional[Dict[str, Any]] = None,
        agent_status: str = 'active',
    ) -> Dict[str, Any]:
        """Discover agents by capability, type, protocol, protocol_config, and status.

        Args:
            protocol_config_key: Check that protocol_config has this top-level key.
            protocol_config_contains: JSONB containment filter — pass a dict fragment
                that the agent's protocol_config must contain (uses @> operator).
                Example: {"mcp": {"capabilities": ["tools"]}}
        """
        self._check_connection()
        import json
        params: Dict[str, Any] = {"agent_status": agent_status}
        if capability is not None:
            params["capability"] = capability
        if type_key is not None:
            params["type_key"] = type_key
        if protocol_format_uri is not None:
            params["protocol_format_uri"] = protocol_format_uri
        if protocol_config_key is not None:
            params["protocol_config_key"] = protocol_config_key
        if protocol_config_contains is not None:
            params["protocol_config_contains"] = json.dumps(protocol_config_contains)
        response = await self._make_authenticated_request(
            "GET", self._url("/agent/discover"), params=params,
        )
        return response.json()

    # ------------------------------------------------------------------
    # Rollback
    # ------------------------------------------------------------------

    async def rollback_agent(self, agent_id: str, log_id: int) -> AgentResponse:
        """Rollback an agent to a previous changelog state."""
        self._check_connection()
        return await self._make_typed_request(
            "PUT", self._url("/agent/rollback"), AgentResponse,
            params={"agent_id": agent_id, "log_id": log_id},
        )

    # ------------------------------------------------------------------
    # Semantic / FTS Search
    # ------------------------------------------------------------------

    async def vector_search(self, query: str, limit: int = 10) -> Dict[str, Any]:
        """Semantic agent search using vector embeddings."""
        self._check_connection()
        response = await self._make_authenticated_request(
            "GET", self._url("/agent/search/vector"),
            params={"query": query, "limit": limit},
        )
        return response.json()

    async def fts_search(self, query: str, limit: int = 20) -> Dict[str, Any]:
        """Full-text agent search."""
        self._check_connection()
        response = await self._make_authenticated_request(
            "GET", self._url("/agent/search/fts"),
            params={"query": query, "limit": limit},
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

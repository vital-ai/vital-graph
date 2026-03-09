"""
Agent Registry REST API Endpoint.

Provides CRUD operations for agents, agent types, endpoints, and change logs.
All resource identification uses query parameters (not path parameters).
"""

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from .agent_models import (
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


def _agent_to_response(agent: dict) -> AgentResponse:
    """Convert an agent dict from the impl layer to an AgentResponse."""
    endpoints = []
    if agent.get('endpoints'):
        endpoints = [AgentEndpointResponse(**ep) for ep in agent['endpoints']]

    return AgentResponse(
        agent_id=agent['agent_id'],
        agent_type_key=agent.get('agent_type_key', ''),
        agent_type_label=agent.get('agent_type_label', ''),
        entity_id=agent.get('entity_id'),
        agent_name=agent['agent_name'],
        agent_uri=agent['agent_uri'],
        description=agent.get('description'),
        version=agent.get('version'),
        status=agent['status'],
        protocol_format_uri=agent.get('protocol_format_uri'),
        auth_service_uri=agent.get('auth_service_uri'),
        auth_service_config=agent.get('auth_service_config') or {},
        capabilities=agent.get('capabilities') or [],
        metadata=agent.get('metadata') or {},
        endpoints=endpoints,
        created_time=agent.get('created_time'),
        updated_time=agent.get('updated_time'),
        created_by=agent.get('created_by'),
        notes=agent.get('notes'),
    )


class AgentRegistryEndpoint:
    """FastAPI endpoint handler for the Agent Registry."""

    def __init__(self, app_impl, auth_dependency):
        """
        Args:
            app_impl: VitalGraphAppImpl instance (provides self.agent_registry at runtime).
            auth_dependency: FastAPI dependency for JWT auth.
        """
        self.app_impl = app_impl
        self.auth_dependency = auth_dependency
        self.logger = logging.getLogger(f"{__name__}.AgentRegistryEndpoint")
        self.router = APIRouter()
        self._setup_routes()

    @property
    def registry(self):
        """Get the AgentRegistryImpl from app_impl (set during startup)."""
        reg = getattr(self.app_impl, 'agent_registry', None)
        if reg is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Agent Registry not initialized",
            )
        return reg

    # ------------------------------------------------------------------
    # Route setup
    # ------------------------------------------------------------------

    def _setup_routes(self):
        auth = self.auth_dependency

        # ============================================================
        # Agent Types
        # ============================================================

        @self.router.get("/agent/types", response_model=List[AgentTypeResponse],
                         tags=["Agent Registry"])
        async def list_agent_types_route(current_user: Dict = Depends(auth)):
            types = await self.registry.list_agent_types()
            return [AgentTypeResponse(**t) for t in types]

        @self.router.post("/agent/types", response_model=AgentTypeResponse,
                          tags=["Agent Registry"])
        async def create_agent_type_route(
            request: AgentTypeCreate, current_user: Dict = Depends(auth),
        ):
            try:
                at = await self.registry.create_agent_type(
                    type_key=request.type_key,
                    type_label=request.type_label,
                    type_description=request.type_description,
                )
                return AgentTypeResponse(**at)
            except Exception as e:
                if 'duplicate key' in str(e).lower() or 'unique' in str(e).lower():
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"Agent type already exists: {request.type_key}",
                    )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e),
                )

        # ============================================================
        # Agent CRUD
        # ============================================================

        @self.router.get("/agent", response_model=AgentListResponse,
                         tags=["Agent Registry"])
        async def list_agents_route(
            agent_id: Optional[str] = Query(None, description="Get agent by ID"),
            agent_uri: Optional[str] = Query(None, description="Get agent by URI"),
            query: Optional[str] = Query(None, description="Search text (ILIKE on name, uri, description)"),
            type_key: Optional[str] = Query(None, description="Filter by agent type URI"),
            entity_id: Optional[str] = Query(None, description="Filter by entity ID"),
            capability: Optional[str] = Query(None, description="Filter by capability tag"),
            protocol_format_uri: Optional[str] = Query(None, description="Filter by protocol format URI"),
            agent_status: Optional[str] = Query('active', alias="status", description="Filter by status"),
            page: int = Query(1, ge=1),
            page_size: int = Query(20, ge=1, le=100),
            current_user: Dict = Depends(auth),
        ):
            # Single agent by ID
            if agent_id:
                agent = await self.registry.get_agent(agent_id)
                if agent is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Agent not found: {agent_id}",
                    )
                return AgentListResponse(
                    agents=[_agent_to_response(agent)],
                    total_count=1, page_size=1, offset=0,
                )

            # Single agent by URI
            if agent_uri:
                agent = await self.registry.get_agent_by_uri(agent_uri)
                if agent is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Agent not found: {agent_uri}",
                    )
                return AgentListResponse(
                    agents=[_agent_to_response(agent)],
                    total_count=1, page_size=1, offset=0,
                )

            # List/search
            agents, total = await self.registry.search_agents(
                query=query, type_key=type_key, status=agent_status,
                entity_id=entity_id, capability=capability,
                protocol_format_uri=protocol_format_uri,
                page=page, page_size=page_size,
            )
            return AgentListResponse(
                agents=[_agent_to_response(a) for a in agents],
                total_count=total,
                page_size=page_size,
                offset=(page - 1) * page_size,
            )

        @self.router.post("/agent", response_model=AgentResponse,
                          tags=["Agent Registry"])
        async def create_agent_route(
            request: AgentCreate, current_user: Dict = Depends(auth),
        ):
            try:
                endpoints = None
                agent = await self.registry.create_agent(
                    agent_type_key=request.agent_type_key,
                    agent_name=request.agent_name,
                    agent_uri=request.agent_uri,
                    entity_id=request.entity_id,
                    description=request.description,
                    version=request.version,
                    protocol_format_uri=request.protocol_format_uri,
                    auth_service_uri=request.auth_service_uri,
                    auth_service_config=request.auth_service_config,
                    capabilities=request.capabilities,
                    metadata=request.metadata,
                    notes=request.notes,
                    created_by=current_user.get('username'),
                    endpoints=endpoints,
                )
                full = await self.registry.get_agent(agent['agent_id'])
                return _agent_to_response(full)
            except ValueError as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=str(e),
                )
            except Exception as e:
                if 'duplicate key' in str(e).lower() or 'unique' in str(e).lower():
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"Agent URI already exists: {request.agent_uri}",
                    )
                self.logger.error("Error creating agent: %s", e)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e),
                )

        @self.router.put("/agent", response_model=AgentResponse,
                         tags=["Agent Registry"])
        async def update_agent_route(
            request: AgentUpdate,
            agent_id: str = Query(..., description="Agent ID"),
            current_user: Dict = Depends(auth),
        ):
            try:
                agent = await self.registry.update_agent(
                    agent_id=agent_id,
                    agent_type_key=request.agent_type_key,
                    entity_id=request.entity_id,
                    agent_name=request.agent_name,
                    description=request.description,
                    version=request.version,
                    status=request.status,
                    protocol_format_uri=request.protocol_format_uri,
                    auth_service_uri=request.auth_service_uri,
                    auth_service_config=request.auth_service_config,
                    capabilities=request.capabilities,
                    metadata=request.metadata,
                    notes=request.notes,
                    updated_by=current_user.get('username'),
                )
                if agent is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Agent not found: {agent_id}",
                    )
                return _agent_to_response(agent)
            except ValueError as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=str(e),
                )

        @self.router.delete("/agent", tags=["Agent Registry"])
        async def delete_agent_route(
            agent_id: str = Query(..., description="Agent ID"),
            current_user: Dict = Depends(auth),
        ):
            deleted = await self.registry.delete_agent(
                agent_id, deleted_by=current_user.get('username'),
            )
            if not deleted:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Agent not found: {agent_id}",
                )
            return {"success": True, "agent_id": agent_id}

        # ============================================================
        # Agent Status
        # ============================================================

        @self.router.put("/agent/status", tags=["Agent Registry"])
        async def change_agent_status_route(
            request: AgentStatusChange,
            agent_id: str = Query(..., description="Agent ID"),
            current_user: Dict = Depends(auth),
        ):
            try:
                agent = await self.registry.update_agent(
                    agent_id=agent_id, status=request.status,
                    updated_by=current_user.get('username'),
                )
                if agent is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Agent not found: {agent_id}",
                    )
                return {"success": True, "agent_id": agent_id, "status": request.status}
            except ValueError as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=str(e),
                )

        # ============================================================
        # Agent Endpoints
        # ============================================================

        @self.router.get("/agent/endpoints", response_model=List[AgentEndpointResponse],
                         tags=["Agent Registry"])
        async def list_endpoints_route(
            agent_id: str = Query(..., description="Agent ID"),
            current_user: Dict = Depends(auth),
        ):
            eps = await self.registry.list_endpoints(agent_id)
            return [AgentEndpointResponse(**ep) for ep in eps]

        @self.router.post("/agent/endpoints", response_model=AgentEndpointResponse,
                          tags=["Agent Registry"])
        async def create_endpoint_route(
            request: AgentEndpointCreate,
            agent_id: str = Query(..., description="Agent ID"),
            current_user: Dict = Depends(auth),
        ):
            try:
                ep = await self.registry.create_endpoint(
                    agent_id=agent_id,
                    endpoint_uri=request.endpoint_uri,
                    endpoint_url=request.endpoint_url,
                    protocol=request.protocol,
                    notes=request.notes,
                    created_by=current_user.get('username'),
                )
                return AgentEndpointResponse(**ep)
            except Exception as e:
                if 'duplicate key' in str(e).lower() or 'unique' in str(e).lower():
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"Endpoint URI already exists for this agent: {request.endpoint_uri}",
                    )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e),
                )

        @self.router.put("/agent/endpoints", response_model=AgentEndpointResponse,
                         tags=["Agent Registry"])
        async def update_endpoint_route(
            request: AgentEndpointUpdate,
            endpoint_id: int = Query(..., description="Endpoint ID"),
            current_user: Dict = Depends(auth),
        ):
            ep = await self.registry.update_endpoint(
                endpoint_id=endpoint_id,
                endpoint_url=request.endpoint_url,
                protocol=request.protocol,
                status=request.status,
                notes=request.notes,
                updated_by=current_user.get('username'),
            )
            if ep is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Endpoint not found: {endpoint_id}",
                )
            return AgentEndpointResponse(**ep)

        @self.router.delete("/agent/endpoints", tags=["Agent Registry"])
        async def delete_endpoint_route(
            endpoint_id: int = Query(..., description="Endpoint ID"),
            current_user: Dict = Depends(auth),
        ):
            deleted = await self.registry.delete_endpoint(
                endpoint_id, deleted_by=current_user.get('username'),
            )
            if not deleted:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Endpoint not found: {endpoint_id}",
                )
            return {"success": True, "endpoint_id": endpoint_id}

        # ============================================================
        # Change Log
        # ============================================================

        @self.router.get("/agent/changelog", tags=["Agent Registry"])
        async def get_agent_changelog_route(
            agent_id: str = Query(..., description="Agent ID"),
            limit: int = Query(50, ge=1, le=500),
            current_user: Dict = Depends(auth),
        ):
            entries = await self.registry.get_change_log(agent_id, limit=limit)
            return {"agent_id": agent_id, "entries": entries}


def create_agent_registry_router(app_impl, auth_dependency) -> APIRouter:
    """Factory function to create the agent registry router."""
    endpoint = AgentRegistryEndpoint(app_impl, auth_dependency)
    return endpoint.router

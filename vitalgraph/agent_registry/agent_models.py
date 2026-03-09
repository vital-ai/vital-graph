"""
Pydantic models and constants for the AI Agent Registry.

Defines:
- Protocol format URI constants (AgentProtocol)
- Auth service URI constants (AgentAuthService)
- Request/response models for agent CRUD operations
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Protocol Format Constants
# ---------------------------------------------------------------------------

class AgentProtocol:
    """Well-known protocol format URIs."""
    AIMP = "urn:vital-ai:protocol:aimp:1.0"
    OPENAI_CHAT = "urn:vital-ai:protocol:openai-chat:1.0"
    A2A = "urn:vital-ai:protocol:a2a:1.0"
    MCP = "urn:vital-ai:protocol:mcp:1.0"

    ALL = [AIMP, OPENAI_CHAT, A2A, MCP]


# ---------------------------------------------------------------------------
# Auth Service Constants
# ---------------------------------------------------------------------------

class AgentAuthService:
    """Well-known auth service URIs."""
    KEYCLOAK = "urn:vital-ai:auth:keycloak"
    COGNITO = "urn:vital-ai:auth:cognito"
    AUTH0 = "urn:vital-ai:auth:auth0"
    OKTA = "urn:vital-ai:auth:okta"
    AZURE_AD = "urn:vital-ai:auth:azure-ad"

    ALL = [KEYCLOAK, COGNITO, AUTH0, OKTA, AZURE_AD]


# ---------------------------------------------------------------------------
# Agent Type models
# ---------------------------------------------------------------------------

class AgentTypeCreate(BaseModel):
    type_key: str
    type_label: str
    type_description: Optional[str] = None


class AgentTypeResponse(BaseModel):
    type_id: int
    type_key: str
    type_label: str
    type_description: Optional[str] = None
    created_time: Optional[datetime] = None
    updated_time: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Agent models
# ---------------------------------------------------------------------------

class AgentCreate(BaseModel):
    agent_type_key: str
    entity_id: Optional[str] = None
    agent_name: str
    agent_uri: str
    description: Optional[str] = None
    version: Optional[str] = None
    protocol_format_uri: Optional[str] = None
    auth_service_uri: Optional[str] = None
    auth_service_config: Dict[str, Any] = Field(default_factory=dict)
    capabilities: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    notes: Optional[str] = None


class AgentUpdate(BaseModel):
    """All fields optional — only provided fields are updated."""
    agent_type_key: Optional[str] = None
    entity_id: Optional[str] = None
    agent_name: Optional[str] = None
    description: Optional[str] = None
    version: Optional[str] = None
    status: Optional[str] = None
    protocol_format_uri: Optional[str] = None
    auth_service_uri: Optional[str] = None
    auth_service_config: Optional[Dict[str, Any]] = None
    capabilities: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None


class AgentResponse(BaseModel):
    agent_id: str
    agent_type_key: str
    agent_type_label: str
    entity_id: Optional[str] = None
    agent_name: str
    agent_uri: str
    description: Optional[str] = None
    version: Optional[str] = None
    status: str
    protocol_format_uri: Optional[str] = None
    auth_service_uri: Optional[str] = None
    auth_service_config: Dict[str, Any] = Field(default_factory=dict)
    capabilities: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    endpoints: List["AgentEndpointResponse"] = Field(default_factory=list)
    created_time: Optional[datetime] = None
    updated_time: Optional[datetime] = None
    created_by: Optional[str] = None
    notes: Optional[str] = None


class AgentListResponse(BaseModel):
    agents: List[AgentResponse]
    total_count: int
    page_size: int
    offset: int


# ---------------------------------------------------------------------------
# Agent Endpoint models
# ---------------------------------------------------------------------------

class AgentEndpointCreate(BaseModel):
    endpoint_uri: str
    endpoint_url: str
    protocol: str = "websocket"
    notes: Optional[str] = None


class AgentEndpointUpdate(BaseModel):
    endpoint_url: Optional[str] = None
    protocol: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class AgentEndpointResponse(BaseModel):
    endpoint_id: int
    agent_id: str
    endpoint_uri: str
    endpoint_url: str
    protocol: str
    status: str
    created_time: Optional[datetime] = None
    updated_time: Optional[datetime] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Status change model
# ---------------------------------------------------------------------------

class AgentStatusChange(BaseModel):
    status: str
    comment: Optional[str] = None


# Resolve forward references
AgentResponse.model_rebuild()

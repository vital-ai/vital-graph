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

from ..model.result_status import OperationStatus, ResultStatus


# ---------------------------------------------------------------------------
# Protocol Format Constants
# ---------------------------------------------------------------------------

class AgentProtocol:
    """Well-known protocol format URIs."""
    AIMP = "urn:vital-ai:protocol:aimp:1.0"
    OPENAI_CHAT = "urn:vital-ai:protocol:openai-chat:1.0"
    OPENAI_RESPONSES = "urn:vital-ai:protocol:openai-responses:1.0"
    A2A = "urn:vital-ai:protocol:a2a:1.0"
    MCP = "urn:vital-ai:protocol:mcp:1.0"
    REST = "urn:vital-ai:protocol:rest:1.0"

    ALL = [AIMP, OPENAI_CHAT, OPENAI_RESPONSES, A2A, MCP, REST]


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
    protocol_config: Dict[str, Any] = Field(default_factory=dict)
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
    protocol_config: Optional[Dict[str, Any]] = None
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
    protocol_config: Dict[str, Any] = Field(default_factory=dict)
    endpoints: List["AgentEndpointResponse"] = Field(default_factory=list)
    created_time: Optional[datetime] = None
    updated_time: Optional[datetime] = None
    created_by: Optional[str] = None
    notes: Optional[str] = None


class AgentListResponse(ResultStatus):
    status: OperationStatus = OperationStatus.FOUND
    agents: List[AgentResponse] = Field(default_factory=list)
    total_count: int = 0
    page_size: int = 0
    offset: int = 0


# ---------------------------------------------------------------------------
# Agent Endpoint models
# ---------------------------------------------------------------------------

class AgentEndpointCreate(BaseModel):
    endpoint_uri: str
    endpoint_url: str
    protocol: str = "websocket"
    transport_config: Dict[str, Any] = Field(default_factory=dict)
    notes: Optional[str] = None


class AgentEndpointUpdate(BaseModel):
    endpoint_url: Optional[str] = None
    protocol: Optional[str] = None
    transport_config: Optional[Dict[str, Any]] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class AgentEndpointResponse(BaseModel):
    endpoint_id: int
    agent_id: str
    endpoint_uri: str
    endpoint_url: str
    protocol: str
    status: str
    transport_config: Dict[str, Any] = Field(default_factory=dict)
    created_time: Optional[datetime] = None
    updated_time: Optional[datetime] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Agent Function models
# ---------------------------------------------------------------------------

class AgentFunctionCreate(BaseModel):
    function_uri: str
    function_name: str
    description: Optional[str] = None
    parameters: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Dict[str, Any] = Field(default_factory=dict)
    notes: Optional[str] = None


class AgentFunctionUpdate(BaseModel):
    """All fields optional — only provided fields are updated."""
    function_name: Optional[str] = None
    description: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None
    output_schema: Optional[Dict[str, Any]] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class AgentFunctionResponse(BaseModel):
    function_id: int
    agent_id: str
    function_uri: str
    function_name: str
    description: Optional[str] = None
    parameters: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Dict[str, Any] = Field(default_factory=dict)
    status: str = "active"
    created_time: Optional[datetime] = None
    updated_time: Optional[datetime] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Status change model
# ---------------------------------------------------------------------------

class AgentStatusChange(BaseModel):
    status: str
    comment: Optional[str] = None


# ---------------------------------------------------------------------------
# Response-status contract envelopes
# ---------------------------------------------------------------------------
# AgentResponse / AgentEndpointResponse / AgentFunctionResponse each carry their
# own domain `status` field (the agent/endpoint/function lifecycle state:
# active, deleted, …). That collides with the contract's `status`
# (OperationStatus), so these models CANNOT inherit ResultStatus directly.
#
# Same resolution as the entity registry: a NESTED ENVELOPE. The contract lives
# on the envelope; the data record is nested in a named Optional field, None on
# not-found / invalid-request. HTTP stays 200 for every domain outcome.

class AgentEnvelope(ResultStatus):
    status: OperationStatus = OperationStatus.FOUND
    agent: Optional[AgentResponse] = None


class AgentTypeEnvelope(ResultStatus):
    status: OperationStatus = OperationStatus.FOUND
    agent_type: Optional[AgentTypeResponse] = None


class AgentEndpointEnvelope(ResultStatus):
    status: OperationStatus = OperationStatus.FOUND
    endpoint: Optional[AgentEndpointResponse] = None


class AgentFunctionEnvelope(ResultStatus):
    status: OperationStatus = OperationStatus.FOUND
    function: Optional[AgentFunctionResponse] = None


# -- list envelopes (were bare JSON arrays) --

class AgentTypeListResponse(ResultStatus):
    status: OperationStatus = OperationStatus.FOUND
    agent_types: List[AgentTypeResponse] = Field(default_factory=list)
    total_count: int = 0


class AgentEndpointListResponse(ResultStatus):
    status: OperationStatus = OperationStatus.FOUND
    endpoints: List[AgentEndpointResponse] = Field(default_factory=list)
    total_count: int = 0


class AgentFunctionListResponse(ResultStatus):
    status: OperationStatus = OperationStatus.FOUND
    functions: List[AgentFunctionResponse] = Field(default_factory=list)
    total_count: int = 0


# -- write / delete outcomes (were {"success": true, ...} literals) --

class AgentDeleteResponse(ResultStatus):
    status: OperationStatus = OperationStatus.DELETED
    agent_id: Optional[str] = None


class AgentEndpointDeleteResponse(ResultStatus):
    status: OperationStatus = OperationStatus.DELETED
    endpoint_id: Optional[int] = None


class AgentFunctionDeleteResponse(ResultStatus):
    status: OperationStatus = OperationStatus.DELETED
    function_id: Optional[int] = None


class AgentStatusChangeResponse(ResultStatus):
    """Result of PUT /agent/status. ``agent_status`` is the agent's new
    lifecycle state, named apart from the contract's ``status``."""
    status: OperationStatus = OperationStatus.UPDATED
    agent_id: Optional[str] = None
    agent_status: Optional[str] = None


# -- discovery / search --

class AgentDiscoverResponse(ResultStatus):
    status: OperationStatus = OperationStatus.FOUND
    agents: List[AgentResponse] = Field(default_factory=list)
    total_count: int = 0


class AgentFunctionDiscoverResponse(ResultStatus):
    status: OperationStatus = OperationStatus.FOUND
    function_uri: str = ""
    agents: List[Dict[str, Any]] = Field(default_factory=list)
    total_count: int = 0


class AgentSearchResult(BaseModel):
    """An agent plus its per-search-mode score."""
    agent: AgentResponse
    similarity: Optional[float] = None
    fts_rank: Optional[float] = None


class AgentSearchResponse(ResultStatus):
    status: OperationStatus = OperationStatus.FOUND
    query: str = ""
    results: List[AgentSearchResult] = Field(default_factory=list)
    total_count: int = 0


# -- change log --

class AgentChangeLogEntry(BaseModel):
    log_id: Optional[int] = None
    agent_id: Optional[str] = None
    change_type: Optional[str] = None
    change_detail: Dict[str, Any] = Field(default_factory=dict)
    changed_by: Optional[str] = None
    changed_time: Optional[datetime] = None

    class Config:
        extra = "allow"


class AgentChangeLogResponse(ResultStatus):
    status: OperationStatus = OperationStatus.FOUND
    agent_id: str = ""
    entries: List[AgentChangeLogEntry] = Field(default_factory=list)
    total_count: int = 0


# Resolve forward references
AgentResponse.model_rebuild()

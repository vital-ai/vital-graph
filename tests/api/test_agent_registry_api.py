"""API tests: Agent Registry CRUD via VitalGraphClient.

Tests agent type, agent, endpoint, and function lifecycle.
Based on test_scripts/vitalgraph_client_test/sparql_sql/case_agent_registry_crud.py
"""

from __future__ import annotations

import uuid

import pytest

from vitalgraph.agent_registry.agent_models import (
    AgentCreate,
    AgentEndpointCreate,
    AgentEndpointUpdate,
    AgentFunctionCreate,
    AgentFunctionUpdate,
    AgentProtocol,
    AgentStatusChange,
    AgentTypeCreate,
    AgentUpdate,
)

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]


class TestAgentRegistryCrud:
    """Agent registry lifecycle: types → agents → endpoints → functions → cleanup."""

    async def test_list_agent_types(self, vg_client):
        """List agent types — seed chat type should exist."""
        ar = vg_client.agent_registry
        types = await ar.list_agent_types()
        keys = [t.type_key for t in types]
        assert "urn:vital-ai:agent-type:chat" in keys

    async def test_create_agent_type(self, vg_client):
        """Create an agent type (idempotent — 409 is acceptable)."""
        ar = vg_client.agent_registry
        type_key = f"urn:vital-ai:agent-type:test-{uuid.uuid4().hex[:6]}"
        try:
            at = await ar.create_agent_type(AgentTypeCreate(
                type_key=type_key,
                type_label="Test Bot",
                type_description="Agent type created by API tests",
            ))
            assert at.type_key == type_key
        except Exception as e:
            # 409 / duplicate is OK
            assert "409" in str(e) or "already exists" in str(e).lower()

    async def test_agent_lifecycle(self, vg_client):
        """Create → get → update → status change → delete agent."""
        ar = vg_client.agent_registry
        agent_uri = f"urn:vital-ai:agent:test-{uuid.uuid4().hex[:8]}"

        # Create
        agent = await ar.create_agent(AgentCreate(
            agent_type_key="urn:vital-ai:agent-type:chat",
            agent_name="API Test Agent",
            agent_uri=agent_uri,
            description="Agent created by API test suite",
            version="1.0.0",
            protocol_format_uri=AgentProtocol.AIMP,
            capabilities=["chat", "search"],
            metadata={"test": True},
        ))
        agent_id = agent.agent_id
        assert agent_id and agent_id.startswith("agt_")

        # Get by ID
        resp = await ar.get_agent(agent_id)
        assert resp.agents and resp.agents[0].agent_id == agent_id

        # Get by URI
        resp = await ar.get_agent_by_uri(agent_uri)
        assert resp.agents and resp.agents[0].agent_uri == agent_uri

        # Search
        resp = await ar.search_agents(query="API Test Agent", status="active")
        assert resp.total_count >= 1

        # Update
        updated = await ar.update_agent(agent_id, AgentUpdate(
            description="Updated by API tests",
            version="1.1.0",
            capabilities=["chat", "search", "summarize"],
        ))
        assert updated.version == "1.1.0"
        assert "summarize" in updated.capabilities

        # Status change
        resp = await ar.change_agent_status(agent_id, AgentStatusChange(status="inactive"))
        assert resp.get("success")
        assert resp.get("status") == "inactive"

        # Delete (soft)
        resp = await ar.delete_agent(agent_id)
        assert resp.get("success")

        # Verify hidden from active search
        resp = await ar.search_agents(query="API Test Agent", status="active")
        found_ids = [a.agent_id for a in resp.agents]
        assert agent_id not in found_ids

    async def test_endpoint_lifecycle(self, vg_client):
        """Create agent → create/update/delete endpoint."""
        ar = vg_client.agent_registry
        agent_uri = f"urn:vital-ai:agent:ep-test-{uuid.uuid4().hex[:8]}"

        agent = await ar.create_agent(AgentCreate(
            agent_type_key="urn:vital-ai:agent-type:chat",
            agent_name="Endpoint Test Agent",
            agent_uri=agent_uri,
            description="For endpoint lifecycle test",
            version="1.0.0",
            protocol_format_uri=AgentProtocol.AIMP,
        ))
        agent_id = agent.agent_id

        # Create endpoint
        ep_uri = f"urn:vital-ai:endpoint:test-{uuid.uuid4().hex[:6]}"
        ep = await ar.create_endpoint(agent_id, AgentEndpointCreate(
            endpoint_uri=ep_uri,
            endpoint_url="wss://test.example.com/ws",
            protocol="websocket",
            notes="Test endpoint",
        ))
        endpoint_id = ep.endpoint_id
        assert ep.endpoint_uri == ep_uri

        # List endpoints
        eps = await ar.list_endpoints(agent_id)
        assert any(e.endpoint_id == endpoint_id for e in eps)

        # Update endpoint
        updated_ep = await ar.update_endpoint(endpoint_id, AgentEndpointUpdate(
            endpoint_url="wss://test.example.com/ws/v2",
            notes="Updated test endpoint",
        ))
        assert updated_ep.endpoint_url == "wss://test.example.com/ws/v2"

        # Delete endpoint
        resp = await ar.delete_endpoint(endpoint_id)
        assert resp.get("success")

        # Verify gone
        eps_after = await ar.list_endpoints(agent_id)
        active_ids = [e.endpoint_id for e in eps_after]
        assert endpoint_id not in active_ids

        # Cleanup agent
        await ar.delete_agent(agent_id)

    async def test_function_lifecycle(self, vg_client):
        """Create agent → create/update/delete function."""
        ar = vg_client.agent_registry
        agent_uri = f"urn:vital-ai:agent:fn-test-{uuid.uuid4().hex[:8]}"

        agent = await ar.create_agent(AgentCreate(
            agent_type_key="urn:vital-ai:agent-type:chat",
            agent_name="Function Test Agent",
            agent_uri=agent_uri,
            description="For function lifecycle test",
            version="1.0.0",
            protocol_format_uri=AgentProtocol.AIMP,
        ))
        agent_id = agent.agent_id

        # Create function
        fn_uri = f"urn:generate_test_{uuid.uuid4().hex[:6]}"
        fn = await ar.create_function(agent_id, AgentFunctionCreate(
            function_uri=fn_uri,
            function_name="Generate Test Report",
            description="Generates a test report",
            parameters={
                "business_name": {"description": "Name", "type": "string", "required": True},
            },
            notes="Test function",
        ))
        function_id = fn.function_id
        assert fn.function_uri == fn_uri

        # List functions
        fns = await ar.list_functions(agent_id)
        assert any(f.function_id == function_id for f in fns)

        # Get function
        got_fn = await ar.get_function(function_id)
        assert got_fn.function_uri == fn_uri

        # Update function
        updated_fn = await ar.update_function(function_id, AgentFunctionUpdate(
            description="Updated description",
            parameters={
                "business_name": {"description": "Name", "type": "string", "required": True},
                "format": {"description": "Output format", "type": "string", "required": False},
            },
        ))
        assert updated_fn.parameters.get("format") is not None

        # Delete function
        resp = await ar.delete_function(function_id)
        assert resp.get("success")

        # Verify gone
        fns_after = await ar.list_functions(agent_id)
        active_ids = [f.function_id for f in fns_after]
        assert function_id not in active_ids

        # Cleanup agent
        await ar.delete_agent(agent_id)

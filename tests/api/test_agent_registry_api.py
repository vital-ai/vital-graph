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
    AgentListResponse,
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


class TestAgentRegistryNewFields:
    """Tests for protocol_config, transport_config, output_schema fields."""

    async def test_protocol_config_roundtrip(self, vg_client):
        """Create agent with protocol_config and verify it round-trips."""
        ar = vg_client.agent_registry
        agent_uri = f"urn:vital-ai:agent:pc-test-{uuid.uuid4().hex[:8]}"
        pc = {"version": "1.0", "supported_methods": ["tools/list", "tools/call"]}

        agent = await ar.create_agent(AgentCreate(
            agent_type_key="urn:vital-ai:agent-type:chat",
            agent_name="Protocol Config Test",
            agent_uri=agent_uri,
            protocol_format_uri=AgentProtocol.MCP,
            protocol_config=pc,
        ))
        agent_id = agent.agent_id
        assert agent.protocol_config == pc

        # Verify via get
        resp = await ar.get_agent(agent_id)
        assert resp.agents[0].protocol_config == pc

        # Update protocol_config
        new_pc = {"version": "2.0", "supported_methods": ["tools/list"]}
        updated = await ar.update_agent(agent_id, AgentUpdate(protocol_config=new_pc))
        assert updated.protocol_config == new_pc

        await ar.delete_agent(agent_id)

    async def test_transport_config_roundtrip(self, vg_client):
        """Create endpoint with transport_config and verify it round-trips."""
        ar = vg_client.agent_registry
        agent_uri = f"urn:vital-ai:agent:tc-test-{uuid.uuid4().hex[:8]}"

        agent = await ar.create_agent(AgentCreate(
            agent_type_key="urn:vital-ai:agent-type:chat",
            agent_name="Transport Config Test",
            agent_uri=agent_uri,
        ))
        agent_id = agent.agent_id

        tc = {"tls": True, "timeout_ms": 30000, "headers": {"X-Custom": "test"}}
        ep = await ar.create_endpoint(agent_id, AgentEndpointCreate(
            endpoint_uri=f"urn:ep:{uuid.uuid4().hex[:6]}",
            endpoint_url="https://example.com/api",
            protocol="https",
            transport_config=tc,
        ))
        assert ep.transport_config == tc

        # Update transport_config
        new_tc = {"tls": True, "timeout_ms": 60000}
        updated_ep = await ar.update_endpoint(ep.endpoint_id, AgentEndpointUpdate(
            transport_config=new_tc,
        ))
        assert updated_ep.transport_config == new_tc

        await ar.delete_agent(agent_id)

    async def test_output_schema_roundtrip(self, vg_client):
        """Create function with output_schema and verify it round-trips."""
        ar = vg_client.agent_registry
        agent_uri = f"urn:vital-ai:agent:os-test-{uuid.uuid4().hex[:8]}"

        agent = await ar.create_agent(AgentCreate(
            agent_type_key="urn:vital-ai:agent-type:chat",
            agent_name="Output Schema Test",
            agent_uri=agent_uri,
        ))
        agent_id = agent.agent_id

        out_schema = {"type": "object", "properties": {"result": {"type": "string"}}}
        fn = await ar.create_function(agent_id, AgentFunctionCreate(
            function_uri=f"urn:fn:{uuid.uuid4().hex[:6]}",
            function_name="Test Func",
            parameters={"input": {"type": "string"}},
            output_schema=out_schema,
        ))
        assert fn.output_schema == out_schema

        # Update output_schema
        new_os = {"type": "object", "properties": {"result": {"type": "integer"}}}
        updated_fn = await ar.update_function(fn.function_id, AgentFunctionUpdate(
            output_schema=new_os,
        ))
        assert updated_fn.output_schema == new_os

        await ar.delete_agent(agent_id)

    async def test_new_protocol_constants(self, vg_client):
        """Verify new protocol constants exist."""
        assert AgentProtocol.OPENAI_RESPONSES == "urn:vital-ai:protocol:openai-responses:1.0"
        assert AgentProtocol.REST == "urn:vital-ai:protocol:rest:1.0"
        assert "urn:vital-ai:protocol:openai-responses:1.0" in AgentProtocol.ALL
        assert "urn:vital-ai:protocol:rest:1.0" in AgentProtocol.ALL


class TestAgentRegistryRollback:
    """Tests for changelog snapshots and agent rollback."""

    async def test_update_captures_snapshot(self, vg_client):
        """Update agent and verify changelog has before/after snapshot."""
        ar = vg_client.agent_registry
        agent_uri = f"urn:vital-ai:agent:snap-test-{uuid.uuid4().hex[:8]}"

        agent = await ar.create_agent(AgentCreate(
            agent_type_key="urn:vital-ai:agent-type:chat",
            agent_name="Snapshot Test Original",
            agent_uri=agent_uri,
            version="1.0.0",
            capabilities=["chat"],
        ))
        agent_id = agent.agent_id

        # Update
        await ar.update_agent(agent_id, AgentUpdate(
            agent_name="Snapshot Test Updated",
            version="2.0.0",
            capabilities=["chat", "search"],
        ))

        # Check changelog
        log = await ar.get_change_log(agent_id)
        entries = log.get("entries", [])
        update_entries = [e for e in entries if e["change_type"] == "agent_updated"]
        assert len(update_entries) >= 1

        detail = update_entries[0].get("change_detail", {})
        assert "before" in detail
        assert "after" in detail
        assert detail["before"]["agent_name"] == "Snapshot Test Original"
        assert detail["after"]["agent_name"] == "Snapshot Test Updated"
        assert detail["before"]["version"] == "1.0.0"
        assert detail["after"]["version"] == "2.0.0"

        await ar.delete_agent(agent_id)

    async def test_rollback_agent(self, vg_client):
        """Create -> update -> rollback -> verify original state restored."""
        ar = vg_client.agent_registry
        agent_uri = f"urn:vital-ai:agent:rb-test-{uuid.uuid4().hex[:8]}"

        # Create with initial state
        agent = await ar.create_agent(AgentCreate(
            agent_type_key="urn:vital-ai:agent-type:chat",
            agent_name="Rollback Test Original",
            agent_uri=agent_uri,
            version="1.0.0",
            description="Original description",
        ))
        agent_id = agent.agent_id

        # Update to new state
        await ar.update_agent(agent_id, AgentUpdate(
            agent_name="Rollback Test Changed",
            version="2.0.0",
            description="Changed description",
        ))

        # Verify updated
        resp = await ar.get_agent(agent_id)
        assert resp.agents[0].agent_name == "Rollback Test Changed"
        assert resp.agents[0].version == "2.0.0"

        # Get the update log entry
        log = await ar.get_change_log(agent_id)
        entries = log.get("entries", [])
        update_entry = next(
            (e for e in entries if e["change_type"] == "agent_updated"), None
        )
        assert update_entry is not None
        log_id = update_entry["log_id"]

        # Rollback
        rolled_back = await ar.rollback_agent(agent_id, log_id)
        assert rolled_back.agent_name == "Rollback Test Original"
        assert rolled_back.version == "1.0.0"
        assert rolled_back.description == "Original description"

        # Verify rollback logged
        log_after = await ar.get_change_log(agent_id)
        entries_after = log_after.get("entries", [])
        rollback_entries = [e for e in entries_after if e["change_type"] == "agent_rollback"]
        assert len(rollback_entries) >= 1
        rb_detail = rollback_entries[0].get("change_detail", {})
        assert rb_detail.get("rollback_from_log_id") == log_id

        await ar.delete_agent(agent_id)

    async def test_rollback_invalid_log_id(self, vg_client):
        """Rollback with invalid log_id should fail."""
        ar = vg_client.agent_registry
        agent_uri = f"urn:vital-ai:agent:rbi-test-{uuid.uuid4().hex[:8]}"

        agent = await ar.create_agent(AgentCreate(
            agent_type_key="urn:vital-ai:agent-type:chat",
            agent_name="Rollback Invalid Test",
            agent_uri=agent_uri,
        ))
        agent_id = agent.agent_id

        # Try rollback with bogus log_id — should get 400
        with pytest.raises(Exception) as exc_info:
            await ar.rollback_agent(agent_id, 999999999)
        assert "400" in str(exc_info.value) or "not found" in str(exc_info.value).lower()

        await ar.delete_agent(agent_id)

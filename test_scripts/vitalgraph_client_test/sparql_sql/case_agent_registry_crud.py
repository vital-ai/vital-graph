"""
Agent Registry CRUD Test Case — SPARQL-SQL Backend

Tests the full agent registry lifecycle via the VitalGraph client:
  1. List agent types (seed data)
  2. Create agent type
  3. Create agent
  4. Get agent by ID
  5. Get agent by URI
  6. Search agents (text, type filter)
  7. Update agent
  8. Create endpoint
  9. List endpoints
  10. Update endpoint
  11. Delete endpoint
  12. Change agent status
  13. Get change log
  14. Delete agent (soft)
  15. Verify soft-deleted agent hidden from search
"""

import logging
from typing import Dict, Any

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

logger = logging.getLogger(__name__)

AGENT_TYPE_KEY = "urn:vital-ai:agent-type:test-bot"
AGENT_URI = "urn:vital-ai:agent:test-crud-bot-001"
ENDPOINT_URI = "urn:vital-ai:endpoint:test-crud-ws"
FUNCTION_URI = "urn:generate_test_report"


class AgentRegistryCrudTester:
    """Client-based test for Agent Registry CRUD against sparql_sql backend."""

    def __init__(self, client):
        self.client = client

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _pass(self, results, label):
        logger.info(f"✅ PASS: {label}")
        results["tests_passed"] += 1

    def _fail(self, results, label, err):
        logger.error(f"❌ FAIL: {label} — {err}")
        results["errors"].append(f"{label}: {err}")
        results["tests_failed"] += 1

    # ------------------------------------------------------------------
    # main entry point
    # ------------------------------------------------------------------
    async def run_tests(self) -> Dict[str, Any]:
        results = {
            "test_name": "Agent Registry CRUD",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": [],
        }

        logger.info(f"\n{'=' * 80}")
        logger.info(f"  Agent Registry CRUD")
        logger.info(f"{'=' * 80}")

        ar = self.client.agent_registry
        agent_id = None
        endpoint_id = None

        # --- 1. List agent types (should include seed chat type) ---
        results["tests_run"] += 1
        try:
            types = await ar.list_agent_types()
            seed_keys = [t.type_key for t in types]
            if "urn:vital-ai:agent-type:chat" in seed_keys:
                self._pass(results, f"List agent types — found {len(types)} type(s), seed chat type present")
            else:
                raise Exception(f"Seed chat type not found. Got keys: {seed_keys}")
        except Exception as e:
            self._fail(results, "List agent types", e)

        # --- 2. Create agent type ---
        results["tests_run"] += 1
        try:
            at = await ar.create_agent_type(AgentTypeCreate(
                type_key=AGENT_TYPE_KEY,
                type_label="Test Bot",
                type_description="Agent type created by automated tests",
            ))
            if at.type_key == AGENT_TYPE_KEY:
                self._pass(results, f"Create agent type — type_id={at.type_id}")
            else:
                raise Exception(f"Unexpected type_key: {at.type_key}")
        except Exception as e:
            err_str = str(e)
            if '409' in err_str or 'duplicate' in err_str.lower() or 'already exists' in err_str.lower():
                self._pass(results, "Create agent type — already exists (OK)")
            else:
                self._fail(results, "Create agent type", e)

        # --- 3. Create agent ---
        results["tests_run"] += 1
        try:
            agent = await ar.create_agent(AgentCreate(
                agent_type_key=AGENT_TYPE_KEY,
                agent_name="Test CRUD Bot",
                agent_uri=AGENT_URI,
                description="Agent created by automated CRUD tests",
                version="1.0.0",
                protocol_format_uri=AgentProtocol.AIMP,
                capabilities=["chat", "search"],
                metadata={"test": True, "suite": "crud"},
            ))
            agent_id = agent.agent_id
            if agent_id and agent_id.startswith("agt_"):
                self._pass(results, f"Create agent — agent_id={agent_id}")
            else:
                raise Exception(f"Unexpected agent_id: {agent_id}")
        except Exception as e:
            self._fail(results, "Create agent", e)
            return results  # can't continue without agent_id

        # --- 4. Get agent by ID ---
        results["tests_run"] += 1
        try:
            resp = await ar.get_agent(agent_id)
            if resp.agents and resp.agents[0].agent_id == agent_id:
                got = resp.agents[0]
                self._pass(results, f"Get agent by ID — name={got.agent_name}")
            else:
                raise Exception(f"Agent not found or ID mismatch")
        except Exception as e:
            self._fail(results, "Get agent by ID", e)

        # --- 5. Get agent by URI ---
        results["tests_run"] += 1
        try:
            resp = await ar.get_agent_by_uri(AGENT_URI)
            if resp.agents and resp.agents[0].agent_uri == AGENT_URI:
                self._pass(results, f"Get agent by URI — agent_id={resp.agents[0].agent_id}")
            else:
                raise Exception(f"Agent not found by URI")
        except Exception as e:
            self._fail(results, "Get agent by URI", e)

        # --- 6. Search agents ---
        results["tests_run"] += 1
        try:
            resp = await ar.search_agents(query="CRUD Bot", status="active")
            if resp.total_count >= 1:
                self._pass(results, f"Search agents — total_count={resp.total_count}")
            else:
                raise Exception(f"Search returned 0 results")
        except Exception as e:
            self._fail(results, "Search agents", e)

        # --- 7. Update agent ---
        results["tests_run"] += 1
        try:
            updated = await ar.update_agent(agent_id, AgentUpdate(
                description="Updated description from CRUD test",
                version="1.1.0",
                capabilities=["chat", "search", "summarize"],
            ))
            if updated.version == "1.1.0" and "summarize" in updated.capabilities:
                self._pass(results, f"Update agent — version={updated.version}, caps={updated.capabilities}")
            else:
                raise Exception(f"Update did not apply: version={updated.version}")
        except Exception as e:
            self._fail(results, "Update agent", e)

        # --- 8. Create endpoint ---
        results["tests_run"] += 1
        try:
            ep = await ar.create_endpoint(agent_id, AgentEndpointCreate(
                endpoint_uri=ENDPOINT_URI,
                endpoint_url="wss://test.example.com/ws",
                protocol="websocket",
                notes="Test endpoint",
            ))
            endpoint_id = ep.endpoint_id
            if ep.endpoint_uri == ENDPOINT_URI:
                self._pass(results, f"Create endpoint — endpoint_id={endpoint_id}")
            else:
                raise Exception(f"Unexpected endpoint_uri: {ep.endpoint_uri}")
        except Exception as e:
            self._fail(results, "Create endpoint", e)

        # --- 9. List endpoints ---
        results["tests_run"] += 1
        try:
            eps = await ar.list_endpoints(agent_id)
            if len(eps) >= 1 and any(e.endpoint_id == endpoint_id for e in eps):
                self._pass(results, f"List endpoints — count={len(eps)}")
            else:
                raise Exception(f"Endpoint not found in list, count={len(eps)}")
        except Exception as e:
            self._fail(results, "List endpoints", e)

        # --- 10. Update endpoint ---
        results["tests_run"] += 1
        try:
            if endpoint_id:
                updated_ep = await ar.update_endpoint(endpoint_id, AgentEndpointUpdate(
                    endpoint_url="wss://test.example.com/ws/v2",
                    notes="Updated test endpoint",
                ))
                if updated_ep.endpoint_url == "wss://test.example.com/ws/v2":
                    self._pass(results, f"Update endpoint — url={updated_ep.endpoint_url}")
                else:
                    raise Exception(f"Update did not apply: url={updated_ep.endpoint_url}")
            else:
                raise Exception("No endpoint_id to update")
        except Exception as e:
            self._fail(results, "Update endpoint", e)

        # --- 11. Delete endpoint ---
        results["tests_run"] += 1
        try:
            if endpoint_id:
                resp = await ar.delete_endpoint(endpoint_id)
                if resp.get("success"):
                    self._pass(results, f"Delete endpoint — endpoint_id={endpoint_id}")
                else:
                    raise Exception(f"Delete did not succeed: {resp}")
            else:
                raise Exception("No endpoint_id to delete")
        except Exception as e:
            self._fail(results, "Delete endpoint", e)

        # --- 12. Verify endpoint soft-deleted ---
        results["tests_run"] += 1
        try:
            eps_after = await ar.list_endpoints(agent_id)
            active_ids = [e.endpoint_id for e in eps_after]
            if endpoint_id not in active_ids:
                self._pass(results, "Verify endpoint soft-deleted (not in active list)")
            else:
                raise Exception(f"Endpoint {endpoint_id} still in active list")
        except Exception as e:
            self._fail(results, "Verify endpoint soft-deleted", e)

        # --- 13. Create function ---
        function_id = None
        results["tests_run"] += 1
        try:
            fn = await ar.create_function(agent_id, AgentFunctionCreate(
                function_uri=FUNCTION_URI,
                function_name="Generate Test Report",
                description="Generates a test report for automated testing",
                parameters={
                    "business_name": {
                        "description": "Name of the business",
                        "type": "string",
                        "required": True,
                    },
                    "report_focus": {
                        "description": "Focus area of the report",
                        "type": "string",
                        "required": False,
                    },
                },
                notes="Test function",
            ))
            function_id = fn.function_id
            if fn.function_uri == FUNCTION_URI and fn.parameters.get("business_name"):
                self._pass(results, f"Create function — function_id={function_id}")
            else:
                raise Exception(f"Unexpected function: uri={fn.function_uri}")
        except Exception as e:
            self._fail(results, "Create function", e)

        # --- 14. List functions ---
        results["tests_run"] += 1
        try:
            fns = await ar.list_functions(agent_id)
            if len(fns) >= 1 and any(f.function_id == function_id for f in fns):
                self._pass(results, f"List functions — count={len(fns)}")
            else:
                raise Exception(f"Function not found in list, count={len(fns)}")
        except Exception as e:
            self._fail(results, "List functions", e)

        # --- 15. Get function by ID ---
        results["tests_run"] += 1
        try:
            if function_id:
                fn = await ar.get_function(function_id)
                if fn.function_uri == FUNCTION_URI:
                    self._pass(results, f"Get function — name={fn.function_name}")
                else:
                    raise Exception(f"Function URI mismatch: {fn.function_uri}")
            else:
                raise Exception("No function_id to get")
        except Exception as e:
            self._fail(results, "Get function by ID", e)

        # --- 16. Update function ---
        results["tests_run"] += 1
        try:
            if function_id:
                updated_fn = await ar.update_function(function_id, AgentFunctionUpdate(
                    description="Updated description from CRUD test",
                    parameters={
                        "business_name": {
                            "description": "Name of the business",
                            "type": "string",
                            "required": True,
                        },
                        "report_focus": {
                            "description": "Focus area of the report",
                            "type": "string",
                            "required": False,
                        },
                        "market_segments": {
                            "description": "Market segments to analyze",
                            "type": "array",
                            "required": False,
                        },
                    },
                ))
                if updated_fn.parameters.get("market_segments"):
                    self._pass(results, f"Update function — added market_segments param")
                else:
                    raise Exception(f"Update did not apply")
            else:
                raise Exception("No function_id to update")
        except Exception as e:
            self._fail(results, "Update function", e)

        # --- 17. Discover agents by function URI ---
        results["tests_run"] += 1
        try:
            disc = await ar.discover_by_function(FUNCTION_URI)
            agents_found = disc.get("agents", [])
            if len(agents_found) >= 1:
                self._pass(results, f"Discover by function — {len(agents_found)} agent(s) found")
            else:
                raise Exception(f"No agents found for function {FUNCTION_URI}")
        except Exception as e:
            self._fail(results, "Discover by function URI", e)

        # --- 18. Delete function (soft) ---
        results["tests_run"] += 1
        try:
            if function_id:
                resp = await ar.delete_function(function_id)
                if resp.get("success"):
                    self._pass(results, f"Delete function — function_id={function_id}")
                else:
                    raise Exception(f"Delete did not succeed: {resp}")
            else:
                raise Exception("No function_id to delete")
        except Exception as e:
            self._fail(results, "Delete function", e)

        # --- 19. Verify function soft-deleted ---
        results["tests_run"] += 1
        try:
            fns_after = await ar.list_functions(agent_id)
            active_ids = [f.function_id for f in fns_after]
            if function_id not in active_ids:
                self._pass(results, "Verify function soft-deleted (not in active list)")
            else:
                raise Exception(f"Function {function_id} still in active list")
        except Exception as e:
            self._fail(results, "Verify function soft-deleted", e)

        # --- 20. Change agent status ---
        results["tests_run"] += 1
        try:
            resp = await ar.change_agent_status(agent_id, AgentStatusChange(status="inactive"))
            if resp.get("success") and resp.get("status") == "inactive":
                self._pass(results, "Change agent status to inactive")
            else:
                raise Exception(f"Status change failed: {resp}")
        except Exception as e:
            self._fail(results, "Change agent status", e)

        # --- 14. Get change log ---
        results["tests_run"] += 1
        try:
            log = await ar.get_change_log(agent_id)
            entries = log.get("entries", [])
            if len(entries) >= 3:
                change_types = [e.get("change_type") for e in entries]
                self._pass(results, f"Get change log — {len(entries)} entries, types={change_types[:5]}")
            else:
                raise Exception(f"Expected >=3 log entries, got {len(entries)}")
        except Exception as e:
            self._fail(results, "Get change log", e)

        # --- 15. Delete agent (soft) ---
        results["tests_run"] += 1
        try:
            resp = await ar.delete_agent(agent_id)
            if resp.get("success"):
                self._pass(results, f"Delete agent — agent_id={agent_id}")
            else:
                raise Exception(f"Delete failed: {resp}")
        except Exception as e:
            self._fail(results, "Delete agent", e)

        # --- 16. Verify soft-deleted agent hidden from search ---
        results["tests_run"] += 1
        try:
            resp = await ar.search_agents(query="CRUD Bot", status="active")
            found_ids = [a.agent_id for a in resp.agents]
            if agent_id not in found_ids:
                self._pass(results, "Verify soft-deleted agent hidden from active search")
            else:
                raise Exception(f"Deleted agent {agent_id} still in active search results")
        except Exception as e:
            self._fail(results, "Verify soft-deleted agent hidden", e)

        results["tests_failed"] = results["tests_run"] - results["tests_passed"]
        return results

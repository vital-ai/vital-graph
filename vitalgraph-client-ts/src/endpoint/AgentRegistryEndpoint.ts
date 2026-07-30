import { BaseEndpoint } from './BaseEndpoint.js';
import { validateRequired } from '../utils/params.js';
import type { VitalGraphResponse } from '../response/types.js';

/** An agent registry record (agent, endpoint, function, type). */
export type AgentRecord = Record<string, unknown>;

/**
 * Server envelope for agent registry LIST routes. These previously returned a
 * bare JSON array; they now return `{ success, status, message, <field>: [...],
 * total_count }` so an empty read is distinguishable from a failure.
 *
 * The list methods below return this envelope RATHER than unwrapping it, so
 * callers can read `status`/`success`/`message` alongside the rows.
 */
export type AgentListEnvelope<K extends string> = VitalGraphResponse &
  Partial<Record<K, AgentRecord[] | null>> & { total_count?: number };

export interface SearchAgentsOptions {
  query?: string;
  typeKey?: string;
  entityId?: string;
  capability?: string;
  protocolFormatUri?: string;
  status?: string;
  page?: number;
  pageSize?: number;
}

export class AgentRegistryEndpoint extends BaseEndpoint {
  // ------------------------------------------------------------------
  // Agent Types
  // ------------------------------------------------------------------

  async listAgentTypes(): Promise<AgentListEnvelope<'agent_types'>> {
    return this.request('GET', '/api/agents/agent/types');
  }

  async createAgentType(data: Record<string, unknown>): Promise<VitalGraphResponse> {
    return this.request('POST', '/api/agents/agent/types', { json: data });
  }

  // ------------------------------------------------------------------
  // Agent CRUD
  // ------------------------------------------------------------------

  async createAgent(data: Record<string, unknown>): Promise<VitalGraphResponse> {
    return this.request('POST', '/api/agents/agent', { json: data });
  }

  async getAgent(agentId: string): Promise<VitalGraphResponse> {
    validateRequired({ agent_id: agentId });
    return this.request('GET', '/api/agents/agent', {
      params: { agent_id: agentId },
    });
  }

  async getAgentByUri(agentUri: string): Promise<VitalGraphResponse> {
    validateRequired({ agent_uri: agentUri });
    return this.request('GET', '/api/agents/agent', {
      params: { agent_uri: agentUri },
    });
  }

  async searchAgents(options: SearchAgentsOptions = {}): Promise<VitalGraphResponse> {
    return this.request('GET', '/api/agents/agent', {
      params: {
        query: options.query,
        type_key: options.typeKey,
        entity_id: options.entityId,
        capability: options.capability,
        protocol_format_uri: options.protocolFormatUri,
        status: options.status ?? 'active',
        page: options.page ?? 1,
        page_size: options.pageSize ?? 20,
      },
    });
  }

  async updateAgent(agentId: string, data: Record<string, unknown>): Promise<VitalGraphResponse> {
    validateRequired({ agent_id: agentId });
    return this.request('PUT', '/api/agents/agent', {
      params: { agent_id: agentId },
      json: data,
    });
  }

  async deleteAgent(agentId: string): Promise<VitalGraphResponse> {
    validateRequired({ agent_id: agentId });
    return this.request('DELETE', '/api/agents/agent', {
      params: { agent_id: agentId },
    });
  }

  /**
   * Change an agent's lifecycle status.
   *
   * NOTE: the response's `status` field is the CONTRACT status
   * (`updated` / `not_found` / `invalid_request`). The agent's new lifecycle
   * state is returned as `agent_status` — it previously came back as `status`.
   */
  async changeAgentStatus(agentId: string, data: Record<string, unknown>): Promise<VitalGraphResponse> {
    validateRequired({ agent_id: agentId });
    return this.request('PUT', '/api/agents/agent/status', {
      params: { agent_id: agentId },
      json: data,
    });
  }

  // ------------------------------------------------------------------
  // Agent Endpoints
  // ------------------------------------------------------------------

  async listEndpoints(agentId: string): Promise<AgentListEnvelope<'endpoints'>> {
    validateRequired({ agent_id: agentId });
    return this.request('GET', '/api/agents/agent/endpoints', {
      params: { agent_id: agentId },
    });
  }

  async createEndpoint(agentId: string, data: Record<string, unknown>): Promise<VitalGraphResponse> {
    validateRequired({ agent_id: agentId });
    return this.request('POST', '/api/agents/agent/endpoints', {
      params: { agent_id: agentId },
      json: data,
    });
  }

  async updateEndpoint(endpointId: number, data: Record<string, unknown>): Promise<VitalGraphResponse> {
    return this.request('PUT', '/api/agents/agent/endpoints', {
      params: { endpoint_id: endpointId },
      json: data,
    });
  }

  async deleteEndpoint(endpointId: number): Promise<VitalGraphResponse> {
    return this.request('DELETE', '/api/agents/agent/endpoints', {
      params: { endpoint_id: endpointId },
    });
  }

  // ------------------------------------------------------------------
  // Agent Functions
  // ------------------------------------------------------------------

  async listFunctions(agentId: string): Promise<AgentListEnvelope<'functions'>> {
    validateRequired({ agent_id: agentId });
    return this.request('GET', '/api/agents/agent/functions', {
      params: { agent_id: agentId },
    });
  }

  async createFunction(agentId: string, data: Record<string, unknown>): Promise<VitalGraphResponse> {
    validateRequired({ agent_id: agentId });
    return this.request('POST', '/api/agents/agent/functions', {
      params: { agent_id: agentId },
      json: data,
    });
  }

  async getFunction(functionId: number): Promise<VitalGraphResponse> {
    return this.request('GET', '/api/agents/agent/function', {
      params: { function_id: functionId },
    });
  }

  async updateFunction(functionId: number, data: Record<string, unknown>): Promise<VitalGraphResponse> {
    return this.request('PUT', '/api/agents/agent/functions', {
      params: { function_id: functionId },
      json: data,
    });
  }

  async deleteFunction(functionId: number): Promise<VitalGraphResponse> {
    return this.request('DELETE', '/api/agents/agent/functions', {
      params: { function_id: functionId },
    });
  }

  async discoverByFunction(functionUri: string, agentStatus = 'active'): Promise<VitalGraphResponse> {
    validateRequired({ function_uri: functionUri });
    return this.request('GET', '/api/agents/agent/function/discover', {
      params: { function_uri: functionUri, agent_status: agentStatus },
    });
  }

  // ------------------------------------------------------------------
  // Change Log
  // ------------------------------------------------------------------

  async getChangeLog(agentId: string, limit = 50): Promise<VitalGraphResponse> {
    validateRequired({ agent_id: agentId });
    return this.request('GET', '/api/agents/agent/changelog', {
      params: { agent_id: agentId, limit },
    });
  }
}

import { BaseEndpoint } from './BaseEndpoint.js';
import { validateRequired } from '../utils/params.js';
import type { VitalGraphResponse } from '../response/types.js';

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

  async listAgentTypes(): Promise<VitalGraphResponse> {
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

  async listEndpoints(agentId: string): Promise<VitalGraphResponse> {
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

  async listFunctions(agentId: string): Promise<VitalGraphResponse> {
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

import { BaseEndpoint } from './BaseEndpoint.js';
import { validateRequired } from '../utils/params.js';
import type {
  GraphResponse,
  GraphsListResponse,
  GraphCreateResponse,
  GraphDeleteResponse,
  GraphClearResponse,
  GraphCountsResponse,
} from '../response/types.js';

export class GraphsEndpoint extends BaseEndpoint {
  async list(spaceId: string): Promise<GraphsListResponse> {
    validateRequired({ space_id: spaceId });
    return this.request('GET', '/api/graphs/graphs', {
      params: { space_id: spaceId },
    });
  }

  async getInfo(spaceId: string, graphUri: string): Promise<GraphResponse> {
    validateRequired({ space_id: spaceId, graph_uri: graphUri });
    return this.request('GET', '/api/graphs/graph', {
      params: { space_id: spaceId, graph_uri: graphUri },
    });
  }

  async create(spaceId: string, graphUri: string): Promise<GraphCreateResponse> {
    validateRequired({ space_id: spaceId, graph_uri: graphUri });
    return this.request('PUT', '/api/graphs/graph', {
      params: { space_id: spaceId, graph_uri: graphUri },
    });
  }

  async executeOperation(spaceId: string, data: Record<string, unknown>): Promise<GraphCreateResponse> {
    validateRequired({ space_id: spaceId });
    return this.request('POST', '/api/graphs/graph', {
      params: { space_id: spaceId },
      json: data,
    });
  }

  async delete(spaceId: string, graphUri: string): Promise<GraphDeleteResponse> {
    validateRequired({ space_id: spaceId, graph_uri: graphUri });
    return this.request('DELETE', '/api/graphs/graph', {
      params: { space_id: spaceId, graph_uri: graphUri },
    });
  }

  async clear(spaceId: string, graphUri: string): Promise<GraphClearResponse> {
    validateRequired({ space_id: spaceId, graph_uri: graphUri });
    return this.request('POST', '/api/graphs/graph', {
      params: { space_id: spaceId },
      json: { operation: 'CLEAR', target_graph_uri: graphUri },
    });
  }

  async getCounts(spaceId: string, graphId: string): Promise<GraphCountsResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId });
    return this.request('GET', '/api/graphs/graph_counts', {
      params: { space_id: spaceId, graph_id: graphId },
    });
  }
}

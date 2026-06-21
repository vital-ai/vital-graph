import { BaseEndpoint } from './BaseEndpoint.js';
import { validateRequired } from '../utils/params.js';
import type {
  ObjectResponse,
  ObjectsListResponse,
  ObjectCreateResponse,
  ObjectUpdateResponse,
  ObjectDeleteResponse,
} from '../response/types.js';

export class ObjectsEndpoint extends BaseEndpoint {
  async list(
    spaceId: string,
    graphId: string,
    pageSize = 10,
    offset = 0,
    search?: string,
  ): Promise<ObjectsListResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId });
    return this.request('GET', '/api/graphs/objects', {
      params: { space_id: spaceId, graph_id: graphId, page_size: pageSize, offset, search },
    });
  }

  async get(spaceId: string, graphId: string, uri: string): Promise<ObjectResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId, uri });
    return this.request('GET', '/api/graphs/objects', {
      params: { space_id: spaceId, graph_id: graphId, uri },
    });
  }

  async create(spaceId: string, graphId: string, data: unknown): Promise<ObjectCreateResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId });
    return this.request('POST', '/api/graphs/objects', {
      params: { space_id: spaceId, graph_id: graphId },
      json: data,
    });
  }

  async update(spaceId: string, graphId: string, uri: string, data: unknown): Promise<ObjectUpdateResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId, uri });
    return this.request('PUT', '/api/graphs/objects', {
      params: { space_id: spaceId, graph_id: graphId, uri },
      json: data,
    });
  }

  async delete(spaceId: string, graphId: string, uri: string): Promise<ObjectDeleteResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId, uri });
    return this.request('DELETE', '/api/graphs/objects', {
      params: { space_id: spaceId, graph_id: graphId, uri },
    });
  }

  async batchDelete(spaceId: string, graphId: string, uris: string[]): Promise<ObjectDeleteResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId });
    return this.request('DELETE', '/api/graphs/objects', {
      params: { space_id: spaceId, graph_id: graphId },
      json: { uris },
    });
  }
}

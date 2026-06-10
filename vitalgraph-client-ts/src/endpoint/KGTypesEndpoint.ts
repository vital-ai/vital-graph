import { BaseEndpoint } from './BaseEndpoint.js';
import { validateRequired } from '../utils/params.js';
import type {
  KGTypeResponse,
  KGTypesListResponse,
  KGTypeCreateResponse,
  KGTypeUpdateResponse,
  KGTypeDeleteResponse,
} from '../response/types.js';

export class KGTypesEndpoint extends BaseEndpoint {
  async list(
    spaceId: string,
    graphId: string,
    pageSize = 10,
    offset = 0,
    search?: string,
  ): Promise<KGTypesListResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId });
    return this.request('GET', '/api/graphs/kgtypes', {
      params: { space_id: spaceId, graph_id: graphId, page_size: pageSize, offset, search },
    });
  }

  async get(spaceId: string, graphId: string, uri: string): Promise<KGTypeResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId, uri });
    return this.request('GET', '/api/graphs/kgtypes/kgtype', {
      params: { space_id: spaceId, graph_id: graphId, uri },
    });
  }

  async create(spaceId: string, graphId: string, data: unknown): Promise<KGTypeCreateResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId });
    return this.request('POST', '/api/graphs/kgtypes', {
      params: { space_id: spaceId, graph_id: graphId },
      json: data,
    });
  }

  async update(spaceId: string, graphId: string, uri: string, data: unknown): Promise<KGTypeUpdateResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId, uri });
    return this.request('PUT', '/api/graphs/kgtypes', {
      params: { space_id: spaceId, graph_id: graphId, uri },
      json: data,
    });
  }

  async delete(spaceId: string, graphId: string, uri: string): Promise<KGTypeDeleteResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId, uri });
    return this.request('DELETE', '/api/graphs/kgtypes', {
      params: { space_id: spaceId, graph_id: graphId, uri },
    });
  }

  async getByUris(spaceId: string, graphId: string, uris: string[]): Promise<KGTypesListResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId });
    return this.request('GET', '/api/graphs/kgtypes', {
      params: { space_id: spaceId, graph_id: graphId, uris: uris.join(',') },
    });
  }

  async batchDelete(spaceId: string, graphId: string, uris: string[]): Promise<KGTypeDeleteResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId });
    return this.request('DELETE', '/api/graphs/kgtypes', {
      params: { space_id: spaceId, graph_id: graphId },
      json: { uris },
    });
  }
}

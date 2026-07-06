import { BaseEndpoint } from './BaseEndpoint.js';
import { validateRequired } from '../utils/params.js';
import type { PaginatedGraphObjectResponse, DeleteResponse, VitalGraphResponse } from '../response/types.js';

export class KGRelationsEndpoint extends BaseEndpoint {
  async list(
    spaceId: string,
    graphId: string,
    pageSize = 10,
    offset = 0,
    search?: string,
  ): Promise<PaginatedGraphObjectResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId });
    return this.request('GET', '/api/graphs/kgrelations', {
      params: { space_id: spaceId, graph_id: graphId, page_size: pageSize, offset, search },
    });
  }

  async create(
    spaceId: string,
    graphId: string,
    data: unknown,
  ): Promise<VitalGraphResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId });
    return this.request('POST', '/api/graphs/kgrelations', {
      params: { space_id: spaceId, graph_id: graphId },
      json: data,
    });
  }

  async delete(
    spaceId: string,
    graphId: string,
    uri: string,
  ): Promise<DeleteResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId, uri });
    return this.request('DELETE', '/api/graphs/kgrelations', {
      params: { space_id: spaceId, graph_id: graphId },
      json: { relation_uris: [uri] },
    });
  }

  async get(
    spaceId: string,
    graphId: string,
    uri: string,
  ): Promise<VitalGraphResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId, uri });
    return this.request('GET', '/api/graphs/kgrelations', {
      params: { space_id: spaceId, graph_id: graphId, uri },
    });
  }

  async update(
    spaceId: string,
    graphId: string,
    uri: string,
    data: unknown,
  ): Promise<VitalGraphResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId, uri });
    return this.request('POST', '/api/graphs/kgrelations', {
      params: { space_id: spaceId, graph_id: graphId, operation_mode: 'update' },
      json: data,
    });
  }

  async upsert(
    spaceId: string,
    graphId: string,
    data: unknown,
  ): Promise<VitalGraphResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId });
    return this.request('POST', '/api/graphs/kgrelations', {
      params: { space_id: spaceId, graph_id: graphId, upsert: true },
      json: data,
    });
  }

  async query(
    spaceId: string,
    graphId: string,
    queryCriteria: unknown,
  ): Promise<PaginatedGraphObjectResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId });
    return this.request('POST', '/api/graphs/kgrelations/query', {
      params: { space_id: spaceId, graph_id: graphId },
      json: queryCriteria,
    });
  }
}

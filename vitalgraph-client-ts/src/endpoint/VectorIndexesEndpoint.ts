import { BaseEndpoint } from './BaseEndpoint.js';
import { validateRequired } from '../utils/params.js';
import type { VectorIndexResponse, VectorIndexesListResponse, VitalGraphResponse } from '../response/types.js';

export class VectorIndexesEndpoint extends BaseEndpoint {
  async list(spaceId: string): Promise<VectorIndexesListResponse> {
    validateRequired({ space_id: spaceId });
    return this.request('GET', '/api/vector-indexes', { params: { space_id: spaceId } });
  }

  async get(spaceId: string, indexName: string): Promise<VectorIndexResponse> {
    validateRequired({ space_id: spaceId, index_name: indexName });
    return this.request('GET', '/api/vector-indexes', {
      params: { space_id: spaceId, index_name: indexName },
    });
  }

  async create(spaceId: string, data: unknown): Promise<VitalGraphResponse> {
    validateRequired({ space_id: spaceId });
    return this.request('POST', '/api/vector-indexes', {
      params: { space_id: spaceId },
      json: data,
    });
  }

  async delete(spaceId: string, indexId: string): Promise<VitalGraphResponse> {
    validateRequired({ space_id: spaceId, index_name: indexId });
    return this.request('DELETE', '/api/vector-indexes', {
      params: { space_id: spaceId, index_name: indexId },
    });
  }

  async reindex(spaceId: string, indexId: string): Promise<VitalGraphResponse> {
    validateRequired({ space_id: spaceId, index_name: indexId });
    return this.request('POST', '/api/vector-indexes/reindex', {
      params: { space_id: spaceId, index_name: indexId },
    });
  }

  async upsertVectors(spaceId: string, indexId: string, vectors: unknown[]): Promise<VitalGraphResponse> {
    validateRequired({ space_id: spaceId, index_name: indexId });
    return this.request('POST', '/api/vector-indexes/vectors', {
      params: { space_id: spaceId, index_name: indexId },
      json: { vectors },
    });
  }

  async getVectors(spaceId: string, indexId: string, uris: string[]): Promise<VitalGraphResponse> {
    validateRequired({ space_id: spaceId, index_name: indexId });
    return this.request('GET', '/api/vector-indexes/vectors', {
      params: { space_id: spaceId, index_name: indexId, uris: uris.join(',') },
    });
  }
}

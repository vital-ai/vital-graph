import { BaseEndpoint } from './BaseEndpoint.js';
import { validateRequired } from '../utils/params.js';
import type { VectorMappingResponse, VectorMappingsListResponse, VitalGraphResponse } from '../response/types.js';

export class VectorMappingsEndpoint extends BaseEndpoint {
  async list(spaceId: string, filters?: { index_name?: string; mapping_type?: string; enabled?: boolean }): Promise<VectorMappingsListResponse> {
    validateRequired({ space_id: spaceId });
    return this.request('GET', '/api/vector-mappings', {
      params: { space_id: spaceId, ...filters },
    });
  }

  async get(spaceId: string, mappingId: number | string): Promise<VectorMappingResponse> {
    validateRequired({ space_id: spaceId, mapping_id: mappingId });
    return this.request('GET', '/api/vector-mappings', {
      params: { space_id: spaceId, mapping_id: mappingId },
    });
  }

  async create(spaceId: string, data: unknown): Promise<VitalGraphResponse> {
    validateRequired({ space_id: spaceId });
    return this.request('POST', '/api/vector-mappings', {
      params: { space_id: spaceId },
      json: data,
    });
  }

  async update(spaceId: string, mappingId: number | string, data: unknown): Promise<VitalGraphResponse> {
    validateRequired({ space_id: spaceId, mapping_id: mappingId });
    return this.request('PUT', '/api/vector-mappings', {
      params: { space_id: spaceId, mapping_id: mappingId },
      json: data,
    });
  }

  async delete(spaceId: string, mappingId: number | string): Promise<VitalGraphResponse> {
    validateRequired({ space_id: spaceId, mapping_id: mappingId });
    return this.request('DELETE', '/api/vector-mappings', {
      params: { space_id: spaceId, mapping_id: mappingId },
    });
  }

  async getProperties(spaceId: string, mappingId: number | string): Promise<VitalGraphResponse> {
    validateRequired({ space_id: spaceId, mapping_id: mappingId });
    return this.request('GET', '/api/vector-mappings/properties', {
      params: { space_id: spaceId, mapping_id: mappingId },
    });
  }

  async addProperty(spaceId: string, mappingId: number | string, data: unknown): Promise<VitalGraphResponse> {
    validateRequired({ space_id: spaceId, mapping_id: mappingId });
    return this.request('POST', '/api/vector-mappings/properties', {
      params: { space_id: spaceId, mapping_id: mappingId },
      json: data,
    });
  }

  async removeProperty(spaceId: string, mappingId: number | string, propertyId: number | string): Promise<VitalGraphResponse> {
    validateRequired({ space_id: spaceId, mapping_id: mappingId, property_id: propertyId });
    return this.request('DELETE', '/api/vector-mappings/properties', {
      params: { space_id: spaceId, mapping_id: mappingId, property_id: propertyId },
    });
  }
}

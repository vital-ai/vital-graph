import { BaseEndpoint } from './BaseEndpoint.js';
import { validateRequired } from '../utils/params.js';
import type { VitalGraphResponse } from '../response/types.js';

export interface FuzzyMappingProperty {
  property_id: number;
  mapping_id: number;
  property_uri: string;
  property_role: string;
  ordinal: number;
}

export interface FuzzyMapping {
  mapping_id: number;
  mapping_type: string;
  type_uri: string | null;
  index_name: string;
  enabled: boolean;
  shingle_k: number;
  num_perm: number;
  lsh_threshold: number;
  phonetic_bonus: number;
  created_time: string | null;
  properties: FuzzyMappingProperty[];
}

export interface FuzzyMappingResponse extends VitalGraphResponse {
  mapping_id: number;
  mapping_type: string;
  type_uri: string | null;
  index_name: string;
  enabled: boolean;
  shingle_k: number;
  num_perm: number;
  lsh_threshold: number;
  phonetic_bonus: number;
  properties: FuzzyMappingProperty[];
}

export interface FuzzyMappingsListResponse extends VitalGraphResponse {
  mappings: FuzzyMapping[];
  total_count: number;
}

export interface FuzzyMappingStatsResponse extends VitalGraphResponse {
  mapping_id: number;
  band_count: number;
  entity_count: number;
  phonetic_band_count: number;
}

export class FuzzyMappingsEndpoint extends BaseEndpoint {
  async list(spaceId: string, filters?: { index_name?: string; mapping_type?: string; enabled?: boolean }): Promise<FuzzyMappingsListResponse> {
    validateRequired({ space_id: spaceId });
    return this.request('GET', '/api/fuzzy-mappings', {
      params: { space_id: spaceId, ...filters },
    });
  }

  async get(spaceId: string, mappingId: number | string): Promise<FuzzyMappingResponse> {
    validateRequired({ space_id: spaceId, mapping_id: mappingId });
    return this.request('GET', '/api/fuzzy-mappings', {
      params: { space_id: spaceId, mapping_id: mappingId },
    });
  }

  async create(spaceId: string, data: unknown): Promise<FuzzyMappingResponse> {
    validateRequired({ space_id: spaceId });
    return this.request('POST', '/api/fuzzy-mappings', {
      params: { space_id: spaceId },
      json: data,
    });
  }

  async update(spaceId: string, mappingId: number | string, data: unknown): Promise<FuzzyMappingResponse> {
    validateRequired({ space_id: spaceId, mapping_id: mappingId });
    return this.request('PUT', '/api/fuzzy-mappings', {
      params: { space_id: spaceId, mapping_id: mappingId },
      json: data,
    });
  }

  async delete(spaceId: string, mappingId: number | string): Promise<VitalGraphResponse> {
    validateRequired({ space_id: spaceId, mapping_id: mappingId });
    return this.request('DELETE', '/api/fuzzy-mappings', {
      params: { space_id: spaceId, mapping_id: mappingId },
    });
  }

  async addProperty(spaceId: string, mappingId: number | string, data: unknown): Promise<VitalGraphResponse> {
    validateRequired({ space_id: spaceId, mapping_id: mappingId });
    return this.request('POST', '/api/fuzzy-mappings/properties', {
      params: { space_id: spaceId, mapping_id: mappingId },
      json: data,
    });
  }

  async removeProperty(spaceId: string, mappingId: number | string, propertyId: number | string): Promise<VitalGraphResponse> {
    validateRequired({ space_id: spaceId, mapping_id: mappingId, property_id: propertyId });
    return this.request('DELETE', '/api/fuzzy-mappings/properties', {
      params: { space_id: spaceId, mapping_id: mappingId, property_id: propertyId },
    });
  }

  async getStats(spaceId: string, mappingId: number | string): Promise<FuzzyMappingStatsResponse> {
    validateRequired({ space_id: spaceId, mapping_id: mappingId });
    return this.request('GET', '/api/fuzzy-mappings/stats', {
      params: { space_id: spaceId, mapping_id: mappingId },
    });
  }

  async populate(spaceId: string, mappingId: number | string): Promise<VitalGraphResponse> {
    validateRequired({ space_id: spaceId, mapping_id: mappingId });
    return this.request('POST', '/api/fuzzy-mappings/populate', {
      params: { space_id: spaceId, mapping_id: mappingId },
    });
  }
}

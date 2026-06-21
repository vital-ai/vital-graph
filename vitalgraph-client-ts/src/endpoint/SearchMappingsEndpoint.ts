import { BaseEndpoint } from './BaseEndpoint.js';
import { validateRequired } from '../utils/params.js';
import type { VitalGraphResponse } from '../response/types.js';

export interface SearchMappingProperty {
  property_id: number;
  mapping_id: number;
  property_uri: string;
  property_role: string;
  ordinal: number;
}

export interface SearchMapping {
  mapping_id: number;
  mapping_type: string;
  type_uri: string | null;
  index_name: string;
  enabled: boolean;
  source_type: string;
  separator: string;
  include_pred_name: boolean;
  include_type_desc: boolean;
  created_time: string | null;
  properties: SearchMappingProperty[];
}

export interface SearchMappingResponse extends VitalGraphResponse, SearchMapping {}

export interface SearchMappingsListResponse extends VitalGraphResponse {
  mappings: SearchMapping[];
  total_count: number;
}

export interface SearchMappingPropertyResponse extends VitalGraphResponse, SearchMappingProperty {}

export class SearchMappingsEndpoint extends BaseEndpoint {
  async list(
    spaceId: string,
    options?: { indexName?: string; mappingType?: string; enabled?: boolean },
  ): Promise<SearchMappingsListResponse> {
    validateRequired({ space_id: spaceId });
    const params: Record<string, string> = { space_id: spaceId };
    if (options?.indexName) params.index_name = options.indexName;
    if (options?.mappingType) params.mapping_type = options.mappingType;
    if (options?.enabled !== undefined) params.enabled = String(options.enabled);
    return this.request('GET', '/api/search-mappings', { params });
  }

  async get(spaceId: string, mappingId: number): Promise<SearchMappingResponse> {
    validateRequired({ space_id: spaceId });
    return this.request('GET', `/api/search-mappings/${mappingId}`, {
      params: { space_id: spaceId },
    });
  }

  async create(spaceId: string, data: {
    index_name: string;
    mapping_type: string;
    type_uri?: string;
    enabled?: boolean;
    source_type?: string;
    separator?: string;
    include_pred_name?: boolean;
    include_type_desc?: boolean;
  }): Promise<SearchMappingResponse> {
    validateRequired({ space_id: spaceId, index_name: data.index_name });
    return this.request('POST', '/api/search-mappings', {
      params: { space_id: spaceId },
      json: data,
    });
  }

  async update(spaceId: string, mappingId: number, data: {
    enabled?: boolean;
    source_type?: string;
    separator?: string;
    include_pred_name?: boolean;
    include_type_desc?: boolean;
  }): Promise<SearchMappingResponse> {
    validateRequired({ space_id: spaceId });
    return this.request('PUT', `/api/search-mappings/${mappingId}`, {
      params: { space_id: spaceId },
      json: data,
    });
  }

  async delete(spaceId: string, mappingId: number): Promise<VitalGraphResponse> {
    validateRequired({ space_id: spaceId });
    return this.request('DELETE', `/api/search-mappings/${mappingId}`, {
      params: { space_id: spaceId },
    });
  }

  async addProperty(spaceId: string, mappingId: number, data: {
    property_uri: string;
    property_role?: string;
    ordinal?: number;
  }): Promise<SearchMappingPropertyResponse> {
    validateRequired({ space_id: spaceId, property_uri: data.property_uri });
    return this.request('POST', `/api/search-mappings/${mappingId}/properties`, {
      params: { space_id: spaceId },
      json: data,
    });
  }

  async removeProperty(
    spaceId: string, mappingId: number, propertyId: number,
  ): Promise<VitalGraphResponse> {
    validateRequired({ space_id: spaceId });
    return this.request(
      'DELETE',
      `/api/search-mappings/${mappingId}/properties/${propertyId}`,
      { params: { space_id: spaceId } },
    );
  }
}

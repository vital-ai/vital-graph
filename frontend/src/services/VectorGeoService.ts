/**
 * Vector & Geo API Service
 *
 * Provides methods for vector index, vector mapping, geo config,
 * and geo points API endpoints.
 */

import { apiService } from './ApiService';
import type {
  VectorIndex,
  VectorIndexListResponse,
  CreateVectorIndexRequest,
  ReindexRequest,
  ReindexResponse,
  VectorMapping,
  MappingListResponse,
  CreateVectorMappingRequest,
  UpdateVectorMappingRequest,
  MappingProperty,
  GeoConfig,
  GeoPointsResponse,
  GeoPointsQuery,
} from '../types/vectorGeo';

class VectorGeoService {
  // ---------------------------------------------------------------------------
  // Vector Indexes
  // ---------------------------------------------------------------------------

  async getVectorIndexes(spaceId: string): Promise<VectorIndex[]> {
    const response = await apiService.get(`/api/spaces/${spaceId}/vector-indexes`);
    if (response.ok) {
      const data: VectorIndexListResponse = await response.json();
      return data.indexes || [];
    }
    throw new Error(`Failed to get vector indexes: ${response.status}`);
  }

  async getVectorIndex(spaceId: string, indexName: string): Promise<VectorIndex> {
    const response = await apiService.get(`/api/spaces/${spaceId}/vector-indexes/${indexName}`);
    if (response.ok) {
      return response.json();
    }
    throw new Error(`Failed to get vector index: ${response.status}`);
  }

  async createVectorIndex(spaceId: string, data: CreateVectorIndexRequest): Promise<VectorIndex> {
    const response = await apiService.post(`/api/spaces/${spaceId}/vector-indexes`, data);
    if (response.ok) {
      return response.json();
    }
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to create vector index: ${response.status}`);
  }

  async deleteVectorIndex(spaceId: string, indexName: string): Promise<void> {
    const response = await apiService.delete(`/api/spaces/${spaceId}/vector-indexes/${indexName}`);
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.detail || `Failed to delete vector index: ${response.status}`);
    }
  }

  async reindex(spaceId: string, indexName: string, data?: ReindexRequest): Promise<ReindexResponse> {
    const response = await apiService.post(
      `/api/spaces/${spaceId}/vector-indexes/${indexName}/reindex`,
      data || {}
    );
    if (response.ok) {
      return response.json();
    }
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to trigger reindex: ${response.status}`);
  }

  // ---------------------------------------------------------------------------
  // Vector Mappings
  // ---------------------------------------------------------------------------

  async getVectorMappings(
    spaceId: string,
    filters?: { index_name?: string; mapping_type?: string; enabled?: boolean }
  ): Promise<VectorMapping[]> {
    const params = new URLSearchParams();
    if (filters?.index_name) params.set('index_name', filters.index_name);
    if (filters?.mapping_type) params.set('mapping_type', filters.mapping_type);
    if (filters?.enabled !== undefined) params.set('enabled', String(filters.enabled));
    const qs = params.toString();
    const url = `/api/spaces/${spaceId}/vector-mappings${qs ? `?${qs}` : ''}`;
    const response = await apiService.get(url);
    if (response.ok) {
      const data: MappingListResponse = await response.json();
      return data.mappings || [];
    }
    throw new Error(`Failed to get vector mappings: ${response.status}`);
  }

  async getVectorMapping(spaceId: string, mappingId: number): Promise<VectorMapping> {
    const response = await apiService.get(`/api/spaces/${spaceId}/vector-mappings/${mappingId}`);
    if (response.ok) {
      return response.json();
    }
    throw new Error(`Failed to get vector mapping: ${response.status}`);
  }

  async createVectorMapping(spaceId: string, data: CreateVectorMappingRequest): Promise<VectorMapping> {
    const response = await apiService.post(`/api/spaces/${spaceId}/vector-mappings`, data);
    if (response.ok) {
      return response.json();
    }
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to create vector mapping: ${response.status}`);
  }

  async updateVectorMapping(
    spaceId: string,
    mappingId: number,
    data: UpdateVectorMappingRequest
  ): Promise<VectorMapping> {
    const response = await apiService.put(`/api/spaces/${spaceId}/vector-mappings/${mappingId}`, data);
    if (response.ok) {
      return response.json();
    }
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to update vector mapping: ${response.status}`);
  }

  async deleteVectorMapping(spaceId: string, mappingId: number): Promise<void> {
    const response = await apiService.delete(`/api/spaces/${spaceId}/vector-mappings/${mappingId}`);
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.detail || `Failed to delete vector mapping: ${response.status}`);
    }
  }

  async addMappingProperty(
    spaceId: string,
    mappingId: number,
    data: { property_uri: string; property_role: string; ordinal?: number }
  ): Promise<MappingProperty> {
    const response = await apiService.post(
      `/api/spaces/${spaceId}/vector-mappings/${mappingId}/properties`,
      data
    );
    if (response.ok) {
      return response.json();
    }
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to add mapping property: ${response.status}`);
  }

  async removeMappingProperty(spaceId: string, mappingId: number, propertyId: number): Promise<void> {
    const response = await apiService.delete(
      `/api/spaces/${spaceId}/vector-mappings/${mappingId}/properties/${propertyId}`
    );
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.detail || `Failed to remove mapping property: ${response.status}`);
    }
  }

  // ---------------------------------------------------------------------------
  // Geo Config
  // ---------------------------------------------------------------------------

  async getGeoConfig(spaceId: string): Promise<GeoConfig> {
    const response = await apiService.get(`/api/spaces/${spaceId}/geo-config`);
    if (response.ok) {
      return response.json();
    }
    throw new Error(`Failed to get geo config: ${response.status}`);
  }

  // ---------------------------------------------------------------------------
  // Geo Points
  // ---------------------------------------------------------------------------

  async getGeoPoints(spaceId: string, query?: GeoPointsQuery): Promise<GeoPointsResponse> {
    const params = new URLSearchParams();
    if (query?.near_lat !== undefined) params.set('near_lat', String(query.near_lat));
    if (query?.near_lon !== undefined) params.set('near_lon', String(query.near_lon));
    if (query?.radius_km !== undefined) params.set('radius_km', String(query.radius_km));
    if (query?.graph_uri) params.set('graph_uri', query.graph_uri);
    if (query?.limit !== undefined) params.set('limit', String(query.limit));
    if (query?.offset !== undefined) params.set('offset', String(query.offset));
    const qs = params.toString();
    const url = `/api/spaces/${spaceId}/geo${qs ? `?${qs}` : ''}`;
    const response = await apiService.get(url);
    if (response.ok) {
      return response.json();
    }
    throw new Error(`Failed to get geo points: ${response.status}`);
  }
}

export const vectorGeoService = new VectorGeoService();

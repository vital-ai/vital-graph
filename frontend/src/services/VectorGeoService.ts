/**
 * Vector & Geo API Service
 *
 * Provides methods for vector index, vector mapping, geo config,
 * and geo points API endpoints.
 * Delegates to the @vital-ai/vitalgraph-client via vgClient.
 */

import { vgClient } from './FrontendVitalGraphClient';
import type {
  VectorIndex,
  CreateVectorIndexRequest,
  ReindexRequest,
  ReindexResponse,
  VectorMapping,
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
    const data = await vgClient.vectorIndexes.list(spaceId);
    return (data as any).indexes || [];
  }

  async getVectorIndex(spaceId: string, indexName: string): Promise<VectorIndex> {
    const data = await vgClient.vectorIndexes.get(spaceId, indexName);
    return (data as any).indexes?.[0] ?? data;
  }

  async createVectorIndex(spaceId: string, data: CreateVectorIndexRequest): Promise<VectorIndex> {
    return vgClient.vectorIndexes.create(spaceId, data) as any;
  }

  async deleteVectorIndex(spaceId: string, indexName: string): Promise<void> {
    await vgClient.vectorIndexes.delete(spaceId, indexName);
  }

  async reindex(spaceId: string, indexName: string, _data?: ReindexRequest): Promise<ReindexResponse> {
    return vgClient.vectorIndexes.reindex(spaceId, indexName) as any;
  }

  // ---------------------------------------------------------------------------
  // Vector Mappings
  // ---------------------------------------------------------------------------

  async getVectorMappings(
    spaceId: string,
    filters?: { index_name?: string; mapping_type?: string; enabled?: boolean }
  ): Promise<VectorMapping[]> {
    const data = await vgClient.vectorMappings.list(spaceId, filters);
    return (data as any).mappings || [];
  }

  async getVectorMapping(spaceId: string, mappingId: number): Promise<VectorMapping> {
    return vgClient.vectorMappings.get(spaceId, mappingId) as any;
  }

  async createVectorMapping(spaceId: string, data: CreateVectorMappingRequest): Promise<VectorMapping> {
    return vgClient.vectorMappings.create(spaceId, data) as any;
  }

  async updateVectorMapping(
    spaceId: string,
    mappingId: number,
    data: UpdateVectorMappingRequest
  ): Promise<VectorMapping> {
    return vgClient.vectorMappings.update(spaceId, mappingId, data) as any;
  }

  async deleteVectorMapping(spaceId: string, mappingId: number): Promise<void> {
    await vgClient.vectorMappings.delete(spaceId, mappingId);
  }

  async addMappingProperty(
    spaceId: string,
    mappingId: number,
    data: { property_uri: string; property_role: string; ordinal?: number }
  ): Promise<MappingProperty> {
    return vgClient.vectorMappings.addProperty(spaceId, mappingId, data) as any;
  }

  async removeMappingProperty(spaceId: string, mappingId: number, propertyId: number): Promise<void> {
    await vgClient.vectorMappings.removeProperty(spaceId, mappingId, propertyId);
  }

  // ---------------------------------------------------------------------------
  // Geo Config
  // ---------------------------------------------------------------------------

  async getGeoConfig(spaceId: string): Promise<GeoConfig> {
    return vgClient.geoConfig.get(spaceId) as any;
  }

  // ---------------------------------------------------------------------------
  // Geo Points
  // ---------------------------------------------------------------------------

  async getGeoPoints(spaceId: string, query?: GeoPointsQuery): Promise<GeoPointsResponse> {
    const params: Record<string, unknown> = {};
    if (query?.near_lat !== undefined) params.near_lat = query.near_lat;
    if (query?.near_lon !== undefined) params.near_lon = query.near_lon;
    if (query?.radius_km !== undefined) params.radius_km = query.radius_km;
    if (query?.graph_uri) params.graph_uri = query.graph_uri;
    if (query?.limit !== undefined) params.limit = query.limit;
    if (query?.offset !== undefined) params.offset = query.offset;
    return vgClient.geoPoints.list(spaceId, params) as any;
  }
}

export const vectorGeoService = new VectorGeoService();

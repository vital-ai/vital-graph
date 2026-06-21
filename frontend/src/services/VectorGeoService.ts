/* eslint-disable @typescript-eslint/no-explicit-any */
/**
 * Vector & Geo API Service
 *
 * Provides methods for vector index, geo config,
 * and geo points API endpoints.
 * All calls go through apiService.client (the typed VitalGraph client).
 */

import { apiService } from './ApiService';
import type {
  VectorIndex,
  CreateVectorIndexRequest,
  ReindexRequest,
  ReindexResponse,
  GeoConfig,
  GeoPointsResponse,
  GeoPointsQuery,
} from '../types/vectorGeo';

class VectorGeoService {
  private get client() { return apiService.client; }

  // ---------------------------------------------------------------------------
  // Vector Indexes
  // ---------------------------------------------------------------------------

  async getVectorIndexes(spaceId: string): Promise<VectorIndex[]> {
    const data = await this.client.vectorIndexes.list(spaceId);
    return (data as any).indexes || [];
  }

  async getVectorIndex(spaceId: string, indexName: string): Promise<VectorIndex> {
    const data = await this.client.vectorIndexes.get(spaceId, indexName);
    return (data as any).indexes?.[0] ?? data;
  }

  async createVectorIndex(spaceId: string, data: CreateVectorIndexRequest): Promise<VectorIndex> {
    return this.client.vectorIndexes.create(spaceId, data) as any;
  }

  async deleteVectorIndex(spaceId: string, indexName: string): Promise<void> {
    await this.client.vectorIndexes.delete(spaceId, indexName);
  }

  async reindex(spaceId: string, indexName: string, _data?: ReindexRequest): Promise<ReindexResponse> {
    return this.client.vectorIndexes.reindex(spaceId, indexName) as any;
  }

  // ---------------------------------------------------------------------------
  // Geo Config
  // ---------------------------------------------------------------------------

  async getGeoConfig(spaceId: string): Promise<GeoConfig> {
    return this.client.geoConfig.get(spaceId) as any;
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
    return this.client.geoPoints.list(spaceId, params) as any;
  }
}

export const vectorGeoService = new VectorGeoService();

import { BaseEndpoint } from './BaseEndpoint.js';
import { validateRequired } from '../utils/params.js';
import type { GeoPointsListResponse } from '../response/types.js';

export interface SearchNearbyOptions {
  spaceId: string;
  lat: number;
  lon: number;
  radiusKm: number;
  graphUri?: string;
  limit?: number;
  offset?: number;
}

export class GeoPointsEndpoint extends BaseEndpoint {
  async list(spaceId: string, params?: Record<string, unknown>): Promise<GeoPointsListResponse> {
    validateRequired({ space_id: spaceId });
    return this.request('GET', '/api/geo', {
      params: { space_id: spaceId, ...params },
    });
  }

  async searchNearby(options: SearchNearbyOptions): Promise<GeoPointsListResponse> {
    validateRequired({ space_id: options.spaceId });
    return this.request('GET', '/api/geo', {
      params: {
        space_id: options.spaceId,
        near_lat: options.lat,
        near_lon: options.lon,
        radius_km: options.radiusKm,
        graph_uri: options.graphUri,
        limit: options.limit,
        offset: options.offset,
      },
    });
  }
}

import { BaseEndpoint } from './BaseEndpoint.js';
import { validateRequired } from '../utils/params.js';
import type { GeoPointsListResponse } from '../response/types.js';

export class GeoPointsEndpoint extends BaseEndpoint {
  async list(spaceId: string, params?: Record<string, unknown>): Promise<GeoPointsListResponse> {
    validateRequired({ space_id: spaceId });
    return this.request('GET', '/api/geo', {
      params: { space_id: spaceId, ...params },
    });
  }
}

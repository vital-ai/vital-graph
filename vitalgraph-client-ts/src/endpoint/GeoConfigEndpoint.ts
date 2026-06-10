import { BaseEndpoint } from './BaseEndpoint.js';
import { validateRequired } from '../utils/params.js';
import type { GeoConfigResponse, VitalGraphResponse } from '../response/types.js';

export class GeoConfigEndpoint extends BaseEndpoint {
  async get(spaceId: string): Promise<GeoConfigResponse> {
    validateRequired({ space_id: spaceId });
    return this.request('GET', '/api/geo-config', { params: { space_id: spaceId } });
  }

  async update(spaceId: string, data: unknown): Promise<VitalGraphResponse> {
    validateRequired({ space_id: spaceId });
    return this.request('PUT', '/api/geo-config', {
      params: { space_id: spaceId },
      json: data,
    });
  }

  async delete(spaceId: string): Promise<VitalGraphResponse> {
    validateRequired({ space_id: spaceId });
    return this.request('DELETE', '/api/geo-config', { params: { space_id: spaceId } });
  }
}

import { BaseEndpoint } from './BaseEndpoint.js';
import { validateRequired } from '../utils/params.js';
import type {
  SpaceResponse,
  SpaceInfoResponse,
  SpacesListResponse,
  SpaceCreateResponse,
  SpaceUpdateResponse,
  SpaceDeleteResponse,
  SpaceAnalyticsResponse,
} from '../response/types.js';

export class SpacesEndpoint extends BaseEndpoint {
  async list(tenant?: string): Promise<SpacesListResponse> {
    return this.request('GET', '/api/spaces', { params: { tenant } });
  }

  async get(spaceId: string): Promise<SpaceResponse> {
    validateRequired({ space_id: spaceId });
    return this.request('GET', '/api/spaces/space', { params: { space_id: spaceId } });
  }

  async create(space: Record<string, unknown>): Promise<SpaceCreateResponse> {
    return this.request('POST', '/api/spaces', { json: space });
  }

  async update(spaceId: string, data: Record<string, unknown>): Promise<SpaceUpdateResponse> {
    validateRequired({ space_id: spaceId });
    return this.request('PUT', '/api/spaces', { params: { space_id: spaceId }, json: data });
  }

  async delete(spaceId: string): Promise<SpaceDeleteResponse> {
    validateRequired({ space_id: spaceId });
    return this.request('DELETE', '/api/spaces', { params: { space_id: spaceId } });
  }

  async getInfo(spaceId: string): Promise<SpaceInfoResponse> {
    validateRequired({ space_id: spaceId });
    return this.request('GET', '/api/spaces/info', { params: { space_id: spaceId } });
  }

  async getAnalytics(spaceId: string, options?: { refresh?: boolean; graph_uri?: string }): Promise<SpaceAnalyticsResponse> {
    validateRequired({ space_id: spaceId });
    return this.request('GET', '/api/spaces/analytics', {
      params: { space_id: spaceId, refresh: options?.refresh, graph_uri: options?.graph_uri },
    });
  }

  async filter(params: Record<string, unknown>): Promise<SpacesListResponse> {
    return this.request('GET', '/api/spaces/filter', { params });
  }
}

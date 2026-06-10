import { BaseEndpoint } from './BaseEndpoint.js';
import { validateRequired } from '../utils/params.js';
import type { MetricsResponse, SlowQueriesResponse } from '../response/types.js';

export class MetricsEndpoint extends BaseEndpoint {
  async getMetrics(spaceId: string, range?: string): Promise<MetricsResponse> {
    validateRequired({ space_id: spaceId });
    return this.request('GET', '/api/metrics', { params: { space_id: spaceId, range } });
  }

  async getSlowQueries(spaceId: string, limit = 20): Promise<SlowQueriesResponse> {
    validateRequired({ space_id: spaceId });
    return this.request('GET', '/api/metrics/slow', { params: { space_id: spaceId, limit } });
  }
}

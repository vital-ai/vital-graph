import { BaseEndpoint } from './BaseEndpoint.js';
import type { VitalGraphResponse } from '../response/types.js';

export class AdminEndpoint extends BaseEndpoint {
  async resync(spaceId?: string): Promise<VitalGraphResponse> {
    return this.request('POST', '/api/admin/resync', { params: { space_id: spaceId } });
  }

  async getAuditLog(params?: Record<string, unknown>): Promise<VitalGraphResponse> {
    return this.request('GET', '/api/admin/audit', { params });
  }

  async rebuild(spaceId?: string): Promise<VitalGraphResponse> {
    return this.request('POST', '/api/admin/rebuild', { params: { space_id: spaceId } });
  }

  async health(): Promise<VitalGraphResponse> {
    return this.request('GET', '/health');
  }

  async cacheStats(): Promise<VitalGraphResponse> {
    return this.request('GET', '/health/cache');
  }
}

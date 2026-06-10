import { BaseEndpoint } from './BaseEndpoint.js';
import type { VitalGraphResponse } from '../response/types.js';

export class ProcessEndpoint extends BaseEndpoint {
  async list(): Promise<VitalGraphResponse> {
    return this.request('GET', '/api/processes');
  }

  async get(processId: string): Promise<VitalGraphResponse> {
    return this.request('GET', '/api/processes/detail', {
      params: { process_id: processId },
    });
  }

  async getScheduler(): Promise<VitalGraphResponse> {
    return this.request('GET', '/api/processes/scheduler');
  }

  async trigger(processName: string, params?: Record<string, unknown>): Promise<VitalGraphResponse> {
    return this.request('POST', '/api/processes/trigger', {
      json: { process_name: processName, ...params },
    });
  }
}

import { BaseEndpoint } from './BaseEndpoint.js';
import { validateRequired } from '../utils/params.js';
import type {
  ExportJobResponse,
  ExportJobsResponse,
  ExportCreateResponse,
  ExportDeleteResponse,
  ExportExecuteResponse,
  ExportStatusResponse,
} from '../response/types.js';

export class ExportEndpoint extends BaseEndpoint {
  async list(spaceId: string): Promise<ExportJobsResponse> {
    validateRequired({ space_id: spaceId });
    return this.request('GET', '/api/data/export', { params: { space_id: spaceId } });
  }

  async get(jobId: string): Promise<ExportJobResponse> {
    validateRequired({ job_id: jobId });
    return this.request('GET', '/api/data/export/job', { params: { job_id: jobId } });
  }

  async create(spaceId: string, config: unknown): Promise<ExportCreateResponse> {
    validateRequired({ space_id: spaceId });
    return this.request('POST', '/api/data/export', {
      params: { space_id: spaceId },
      json: config,
    });
  }

  async delete(jobId: string): Promise<ExportDeleteResponse> {
    validateRequired({ job_id: jobId });
    return this.request('DELETE', '/api/data/export', { params: { job_id: jobId } });
  }

  async execute(jobId: string): Promise<ExportExecuteResponse> {
    validateRequired({ job_id: jobId });
    return this.request('POST', '/api/data/export/execute', { params: { job_id: jobId } });
  }

  async status(jobId: string): Promise<ExportStatusResponse> {
    validateRequired({ job_id: jobId });
    return this.request('GET', '/api/data/export/status', { params: { job_id: jobId } });
  }

  async download(jobId: string): Promise<ArrayBuffer> {
    validateRequired({ job_id: jobId });
    const response = await this.requestRaw('GET', '/api/data/export/download', {
      params: { job_id: jobId },
    });
    return response.arrayBuffer();
  }
}

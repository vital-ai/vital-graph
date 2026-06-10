import { BaseEndpoint } from './BaseEndpoint.js';
import { validateRequired } from '../utils/params.js';
import type {
  ImportJobResponse,
  ImportJobsResponse,
  ImportCreateResponse,
  ImportDeleteResponse,
  ImportExecuteResponse,
  ImportStatusResponse,
  ImportLogResponse,
  ImportUploadResponse,
} from '../response/types.js';

export class ImportEndpoint extends BaseEndpoint {
  async list(spaceId: string): Promise<ImportJobsResponse> {
    validateRequired({ space_id: spaceId });
    return this.request('GET', '/api/data/import', { params: { space_id: spaceId } });
  }

  async get(jobId: string): Promise<ImportJobResponse> {
    validateRequired({ job_id: jobId });
    return this.request('GET', '/api/data/import/job', { params: { job_id: jobId } });
  }

  async create(spaceId: string, config: unknown): Promise<ImportCreateResponse> {
    validateRequired({ space_id: spaceId });
    return this.request('POST', '/api/data/import', {
      params: { space_id: spaceId },
      json: config,
    });
  }

  async delete(jobId: string): Promise<ImportDeleteResponse> {
    validateRequired({ job_id: jobId });
    return this.request('DELETE', '/api/data/import', { params: { job_id: jobId } });
  }

  async execute(jobId: string): Promise<ImportExecuteResponse> {
    validateRequired({ job_id: jobId });
    return this.request('POST', '/api/data/import/execute', { params: { job_id: jobId } });
  }

  async status(jobId: string): Promise<ImportStatusResponse> {
    validateRequired({ job_id: jobId });
    return this.request('GET', '/api/data/import/status', { params: { job_id: jobId } });
  }

  async log(jobId: string): Promise<ImportLogResponse> {
    validateRequired({ job_id: jobId });
    return this.request('GET', '/api/data/import/log', { params: { job_id: jobId } });
  }

  async upload(jobId: string, file: Blob | ArrayBuffer, filename: string): Promise<ImportUploadResponse> {
    validateRequired({ job_id: jobId });
    const formData = new FormData();
    const blob = file instanceof Blob ? file : new Blob([file]);
    formData.append('file', blob, filename);
    return this.request('POST', '/api/data/import/upload', {
      params: { job_id: jobId },
      body: formData,
    });
  }
}

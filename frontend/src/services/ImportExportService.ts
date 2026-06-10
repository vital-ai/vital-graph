/**
 * Import/Export API Service for VitalGraph frontend.
 *
 * Delegates to @vital-ai/vitalgraph-client via vgClient.
 */

import { vgClient } from './FrontendVitalGraphClient';

// ---------------------------------------------------------------------------
// Types (aligned with backend Pydantic models)
// ---------------------------------------------------------------------------

export interface LogEntry {
  timestamp?: string;
  level?: string;
  message: string;
  [key: string]: unknown;
}

export interface ImportExportJob {
  job_id: string;
  job_type: 'import' | 'export';
  space_id: string;
  graph_uri?: string | null;
  status: string;
  mode?: string;
  progress_pct: number;
  records_done: number;
  records_total?: number | null;
  file_s3_key?: string | null;
  file_name?: string | null;
  file_size?: number | null;
  file_format?: string | null;
  config?: Record<string, unknown> | null;
  checkpoint_offset?: number;
  checkpoint_batch?: number;
  error_message?: string | null;
  log_entries?: (string | LogEntry)[];
  created_by?: string | null;
  created_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  updated_at?: string | null;
}

export interface JobStatusResponse {
  job_id: string;
  status: string;
  progress_pct: number;
  records_done: number;
  records_total?: number | null;
  file_s3_key?: string | null;
  file_name?: string | null;
  file_size?: number | null;
  started_at?: string | null;
  completed_at?: string | null;
  error_message?: string | null;
}

export interface ImportLogResponse {
  job_id: string;
  log_entries: LogEntry[];
  total_entries: number;
}

export interface CreateImportRequest {
  space_id: string;
  graph_uri?: string;
  mode?: 'append' | 'replace';
  file_format?: string;
  config?: Record<string, unknown>;
}

export interface CreateExportRequest {
  space_id: string;
  graph_uri?: string;
  file_format?: string;
  config?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Service
// ---------------------------------------------------------------------------

class ImportExportService {
  // -------------------------------------------------------------------------
  // Import jobs
  // -------------------------------------------------------------------------

  async listImportJobs(spaceId?: string, _status?: string): Promise<ImportExportJob[]> {
    if (!spaceId) throw new Error('space_id is required');
    const data = await vgClient.imports.list(spaceId);
    return (data as any).jobs || [];
  }

  async getImportJob(jobId: string): Promise<ImportExportJob> {
    const data = await vgClient.imports.get(jobId);
    return (data as any).job ?? data;
  }

  async createImportJob(req: CreateImportRequest): Promise<ImportExportJob> {
    const data = await vgClient.imports.create(req.space_id, req);
    return (data as any).job ?? data;
  }

  async uploadImportFile(jobId: string, file: File): Promise<{ filename: string; file_size: number }> {
    return vgClient.imports.upload(jobId, file, file.name) as any;
  }

  async executeImportJob(jobId: string): Promise<void> {
    await vgClient.imports.execute(jobId);
  }

  async getImportStatus(jobId: string): Promise<JobStatusResponse> {
    return vgClient.imports.status(jobId) as any;
  }

  async deleteImportJob(jobId: string): Promise<void> {
    await vgClient.imports.delete(jobId);
  }

  async getImportLog(jobId: string): Promise<ImportLogResponse> {
    return vgClient.imports.log(jobId) as any;
  }

  // -------------------------------------------------------------------------
  // Export jobs
  // -------------------------------------------------------------------------

  async listExportJobs(spaceId?: string, _status?: string): Promise<ImportExportJob[]> {
    if (!spaceId) throw new Error('space_id is required');
    const data = await vgClient.exports.list(spaceId);
    return (data as any).jobs || [];
  }

  async getExportJob(jobId: string): Promise<ImportExportJob> {
    const data = await vgClient.exports.get(jobId);
    return (data as any).job ?? data;
  }

  async createExportJob(req: CreateExportRequest): Promise<ImportExportJob> {
    const data = await vgClient.exports.create(req.space_id, req);
    return (data as any).job ?? data;
  }

  async executeExportJob(jobId: string): Promise<void> {
    await vgClient.exports.execute(jobId);
  }

  async getExportStatus(jobId: string): Promise<JobStatusResponse> {
    return vgClient.exports.status(jobId) as any;
  }

  async deleteExportJob(jobId: string): Promise<void> {
    await vgClient.exports.delete(jobId);
  }

  getExportDownloadUrl(jobId: string): string {
    return `${window.location.origin}/api/data/export/${jobId}/download`;
  }
}

export const importExportService = new ImportExportService();
export default importExportService;

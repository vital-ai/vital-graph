/**
 * Import/Export API Service for VitalGraph frontend.
 *
 * Wraps the REST endpoints at /api/data/import and /api/data/export.
 */

import { apiService } from './ApiService';

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

  async listImportJobs(spaceId?: string, status?: string): Promise<ImportExportJob[]> {
    const params = new URLSearchParams();
    if (spaceId) params.set('space_id', spaceId);
    if (status) params.set('status', status);
    const qs = params.toString();
    const url = `/api/data/import${qs ? '?' + qs : ''}`;
    const response = await apiService.get(url);
    if (!response.ok) throw new Error(`Failed to list import jobs: ${response.status}`);
    const data = await response.json();
    return data.jobs || [];
  }

  async getImportJob(jobId: string): Promise<ImportExportJob> {
    const response = await apiService.get(`/api/data/import/${jobId}`);
    if (!response.ok) throw new Error(`Failed to get import job: ${response.status}`);
    const data = await response.json();
    return data.job;
  }

  async createImportJob(req: CreateImportRequest): Promise<ImportExportJob> {
    const response = await apiService.post('/api/data/import', req);
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to create import job: ${response.status}`);
    }
    const data = await response.json();
    return data.job;
  }

  async uploadImportFile(jobId: string, file: File): Promise<{ filename: string; file_size: number }> {
    const formData = new FormData();
    formData.append('file', file);

    // Use raw fetch for multipart — ApiService sets Content-Type to JSON
    const authHeader = (await import('./AuthService')).authService.getAuthHeader();
    const response = await fetch(`${window.location.origin}/api/data/import/${jobId}/upload`, {
      method: 'POST',
      headers: { ...authHeader },
      body: formData,
    });
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || `Upload failed: ${response.status}`);
    }
    return response.json();
  }

  async executeImportJob(jobId: string): Promise<void> {
    const response = await apiService.post(`/api/data/import/${jobId}/execute`);
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || `Execute failed: ${response.status}`);
    }
  }

  async getImportStatus(jobId: string): Promise<JobStatusResponse> {
    const response = await apiService.get(`/api/data/import/${jobId}/status`);
    if (!response.ok) throw new Error(`Failed to get status: ${response.status}`);
    return response.json();
  }

  async deleteImportJob(jobId: string): Promise<void> {
    const response = await apiService.delete(`/api/data/import/${jobId}`);
    if (!response.ok) throw new Error(`Failed to delete: ${response.status}`);
  }

  async getImportLog(jobId: string): Promise<ImportLogResponse> {
    const response = await apiService.get(`/api/data/import/${jobId}/log`);
    if (!response.ok) throw new Error(`Failed to get log: ${response.status}`);
    return response.json();
  }

  // -------------------------------------------------------------------------
  // Export jobs
  // -------------------------------------------------------------------------

  async listExportJobs(spaceId?: string, status?: string): Promise<ImportExportJob[]> {
    const params = new URLSearchParams();
    if (spaceId) params.set('space_id', spaceId);
    if (status) params.set('status', status);
    const qs = params.toString();
    const url = `/api/data/export${qs ? '?' + qs : ''}`;
    const response = await apiService.get(url);
    if (!response.ok) throw new Error(`Failed to list export jobs: ${response.status}`);
    const data = await response.json();
    return data.jobs || [];
  }

  async getExportJob(jobId: string): Promise<ImportExportJob> {
    const response = await apiService.get(`/api/data/export/${jobId}`);
    if (!response.ok) throw new Error(`Failed to get export job: ${response.status}`);
    const data = await response.json();
    return data.job;
  }

  async createExportJob(req: CreateExportRequest): Promise<ImportExportJob> {
    const response = await apiService.post('/api/data/export', req);
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to create export job: ${response.status}`);
    }
    const data = await response.json();
    return data.job;
  }

  async executeExportJob(jobId: string): Promise<void> {
    const response = await apiService.post(`/api/data/export/${jobId}/execute`);
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || `Execute failed: ${response.status}`);
    }
  }

  async getExportStatus(jobId: string): Promise<JobStatusResponse> {
    const response = await apiService.get(`/api/data/export/${jobId}/status`);
    if (!response.ok) throw new Error(`Failed to get status: ${response.status}`);
    return response.json();
  }

  async deleteExportJob(jobId: string): Promise<void> {
    const response = await apiService.delete(`/api/data/export/${jobId}`);
    if (!response.ok) throw new Error(`Failed to delete: ${response.status}`);
  }

  getExportDownloadUrl(jobId: string): string {
    return `${window.location.origin}/api/data/export/${jobId}/download`;
  }
}

export const importExportService = new ImportExportService();
export default importExportService;

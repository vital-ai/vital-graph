/**
 * File types for VitalGraph frontend
 */

export interface FileEntry {
  uri: string;
  rdf_type: string;
  filename: string;
  file_type: string;
  file_size: number;
  properties_count: number;
}

export interface FileListResponse {
  files: FileEntry[];
  total_count: number;
  offset: number;
  page_size: number;
}

export interface FileUploadResponse {
  success: boolean;
  uri?: string;
  filename?: string;
  message?: string;
  error?: string;
}

import { BaseEndpoint } from './BaseEndpoint.js';
import { validateRequired } from '../utils/params.js';
import type {
  FileResponse,
  FilesListResponse,
  FileCreateResponse,
  FileUpdateResponse,
  FileDeleteResponse,
  FileUploadResponse,
} from '../response/types.js';

export class FilesEndpoint extends BaseEndpoint {
  async list(
    spaceId: string,
    graphId?: string,
    pageSize = 100,
    offset = 0,
    fileFilter?: string,
  ): Promise<FilesListResponse> {
    validateRequired({ space_id: spaceId });
    return this.request('GET', '/api/files', {
      params: { space_id: spaceId, graph_id: graphId, page_size: pageSize, offset, file_filter: fileFilter },
    });
  }

  async get(spaceId: string, fileUri: string): Promise<FileResponse> {
    validateRequired({ space_id: spaceId, file_uri: fileUri });
    return this.request('GET', '/api/files/file', {
      params: { space_id: spaceId, file_uri: fileUri },
    });
  }

  async create(spaceId: string, graphId: string, data: unknown): Promise<FileCreateResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId });
    return this.request('POST', '/api/files', {
      params: { space_id: spaceId, graph_id: graphId },
      json: data,
    });
  }

  async update(spaceId: string, fileUri: string, data: unknown): Promise<FileUpdateResponse> {
    validateRequired({ space_id: spaceId, file_uri: fileUri });
    return this.request('PUT', '/api/files', {
      params: { space_id: spaceId, file_uri: fileUri },
      json: data,
    });
  }

  async delete(spaceId: string, fileUri: string): Promise<FileDeleteResponse> {
    validateRequired({ space_id: spaceId, file_uri: fileUri });
    return this.request('DELETE', '/api/files', {
      params: { space_id: spaceId, file_uri: fileUri },
    });
  }

  async upload(
    spaceId: string,
    graphId: string,
    fileUri: string,
    file: Blob | ArrayBuffer,
    filename: string,
    options?: {
      contentType?: string;
      metadata?: Record<string, string>;
    },
  ): Promise<FileUploadResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId, uri: fileUri });
    const formData = new FormData();
    const blob = file instanceof Blob ? file : new Blob([file]);
    formData.append('file', blob, filename);
    if (options?.metadata) {
      for (const [key, value] of Object.entries(options.metadata)) {
        formData.append(key, value);
      }
    }
    return this.request('POST', '/api/files/upload', {
      params: { space_id: spaceId, graph_id: graphId, uri: fileUri, content_type: options?.contentType },
      body: formData,
    });
  }

  async download(spaceId: string, fileUri: string, graphId?: string): Promise<ArrayBuffer> {
    validateRequired({ space_id: spaceId, file_uri: fileUri });
    const response = await this.requestRaw('GET', '/api/files/download', {
      params: { space_id: spaceId, graph_id: graphId, uri: fileUri },
    });
    return response.arrayBuffer();
  }

  async batchDelete(spaceId: string, fileUris: string[]): Promise<FileDeleteResponse> {
    validateRequired({ space_id: spaceId });
    return this.request('DELETE', '/api/files', {
      params: { space_id: spaceId },
      json: { file_uris: fileUris },
    });
  }

  async getByUris(spaceId: string, fileUris: string[]): Promise<FilesListResponse> {
    validateRequired({ space_id: spaceId });
    return this.request('GET', '/api/files', {
      params: { space_id: spaceId, file_uris: fileUris.join(',') },
    });
  }
}

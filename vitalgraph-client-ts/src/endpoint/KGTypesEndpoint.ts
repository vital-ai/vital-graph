import { BaseEndpoint } from './BaseEndpoint.js';
import { validateRequired } from '../utils/params.js';
import type {
  KGTypeResponse,
  KGTypesListResponse,
  KGTypeCreateResponse,
  KGTypeUpdateResponse,
  KGTypeDeleteResponse,
  KGTypeRelationshipsResponse,
  KGTypeRelationshipCreateResponse,
  KGTypeRelationshipDeleteResponse,
  KGTypeDocumentationResponse,
  KGTypeDocumentationUpdateResponse,
  KGTypeDocumentationDeleteResponse,
  KGTypeSearchResponse,
} from '../response/types.js';

export class KGTypesEndpoint extends BaseEndpoint {
  async list(
    spaceId: string,
    pageSize = 10,
    offset = 0,
    search?: string,
    typeUri?: string,
  ): Promise<KGTypesListResponse> {
    validateRequired({ space_id: spaceId });
    return this.request('GET', '/api/graphs/kgtypes', {
      params: { space_id: spaceId, page_size: pageSize, offset, search, type_uri: typeUri },
    });
  }

  async get(spaceId: string, uri: string): Promise<KGTypeResponse> {
    validateRequired({ space_id: spaceId, uri });
    return this.request('GET', '/api/graphs/kgtypes', {
      params: { space_id: spaceId, uri },
    });
  }

  async create(spaceId: string, data: unknown): Promise<KGTypeCreateResponse> {
    validateRequired({ space_id: spaceId });
    return this.request('POST', '/api/graphs/kgtypes', {
      params: { space_id: spaceId },
      json: data,
    });
  }

  async update(spaceId: string, uri: string, data: unknown): Promise<KGTypeUpdateResponse> {
    validateRequired({ space_id: spaceId, uri });
    return this.request('PUT', '/api/graphs/kgtypes', {
      params: { space_id: spaceId, uri },
      json: data,
    });
  }

  async delete(spaceId: string, uri: string): Promise<KGTypeDeleteResponse> {
    validateRequired({ space_id: spaceId, uri });
    return this.request('DELETE', '/api/graphs/kgtypes', {
      params: { space_id: spaceId, uri },
    });
  }

  async getByUris(spaceId: string, uris: string[]): Promise<KGTypesListResponse> {
    validateRequired({ space_id: spaceId });
    return this.request('GET', '/api/graphs/kgtypes', {
      params: { space_id: spaceId, uris: uris.join(',') },
    });
  }

  async batchDelete(spaceId: string, uris: string[]): Promise<KGTypeDeleteResponse> {
    validateRequired({ space_id: spaceId });
    return this.request('DELETE', '/api/graphs/kgtypes', {
      params: { space_id: spaceId },
      json: { uris },
    });
  }

  async getRelationships(spaceId: string, typeUri: string): Promise<KGTypeRelationshipsResponse> {
    validateRequired({ space_id: spaceId, id: typeUri });
    return this.request('GET', '/api/graphs/kgtypes/relationships', {
      params: { space_id: spaceId, id: typeUri },
    });
  }

  async createRelationship(
    spaceId: string, typeUri: string,
    edgeType: string, targetUri: string,
  ): Promise<KGTypeRelationshipCreateResponse> {
    validateRequired({ space_id: spaceId, id: typeUri });
    return this.request('POST', '/api/graphs/kgtypes/relationships', {
      params: { space_id: spaceId, id: typeUri },
      json: { edge_type: edgeType, target_uri: targetUri },
    });
  }

  async deleteRelationship(
    spaceId: string, typeUri: string, edgeUri: string,
  ): Promise<KGTypeRelationshipDeleteResponse> {
    validateRequired({ space_id: spaceId, id: typeUri, edge_uri: edgeUri });
    return this.request('DELETE', '/api/graphs/kgtypes/relationships', {
      params: { space_id: spaceId, id: typeUri, edge_uri: edgeUri },
    });
  }

  // ── Documentation ──────────────────────────────────────────────────

  async getDocumentation(spaceId: string, typeUri: string): Promise<KGTypeDocumentationResponse> {
    validateRequired({ space_id: spaceId, id: typeUri });
    return this.request('GET', '/api/graphs/kgtypes/documentation', {
      params: { space_id: spaceId, id: typeUri },
    });
  }

  async updateDocumentation(
    spaceId: string, typeUri: string, content: string,
  ): Promise<KGTypeDocumentationUpdateResponse> {
    validateRequired({ space_id: spaceId, id: typeUri });
    return this.request('PUT', '/api/graphs/kgtypes/documentation', {
      params: { space_id: spaceId, id: typeUri },
      json: { content },
    });
  }

  async deleteDocumentation(spaceId: string, typeUri: string): Promise<KGTypeDocumentationDeleteResponse> {
    validateRequired({ space_id: spaceId, id: typeUri });
    return this.request('DELETE', '/api/graphs/kgtypes/documentation', {
      params: { space_id: spaceId, id: typeUri },
    });
  }

  // ── Search ─────────────────────────────────────────────────────────

  async search(
    spaceId: string, query: string,
    options?: { type?: string; search_mode?: 'keyword' | 'fts' | 'vector' | 'hybrid'; alpha?: number; page_size?: number; offset?: number },
  ): Promise<KGTypeSearchResponse> {
    validateRequired({ space_id: spaceId, q: query });
    return this.request('GET', '/api/graphs/kgtypes/search', {
      params: {
        space_id: spaceId, q: query,
        type: options?.type, search_mode: options?.search_mode, alpha: options?.alpha,
        page_size: options?.page_size, offset: options?.offset,
      },
    });
  }
}

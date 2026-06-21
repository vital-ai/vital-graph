import { BaseEndpoint } from './BaseEndpoint.js';
import { validateRequired } from '../utils/params.js';
import type {
  VitalGraphResponse,
  PaginatedGraphObjectResponse,
  FrameGraphResponse,
  MultiFrameGraphResponse,
  DeleteResponse,
  QueryResponse,
} from '../response/types.js';

export class KGFramesEndpoint extends BaseEndpoint {
  async list(
    spaceId: string,
    graphId: string,
    pageSize = 10,
    offset = 0,
    search?: string,
    options?: {
      sort_by?: string;
      sort_order?: 'asc' | 'desc';
      form_type?: string;
      frame_type_uri?: string;
      status?: string;
      exclude_status?: string;
      created_after?: string;
      created_before?: string;
      modified_after?: string;
      modified_before?: string;
    },
  ): Promise<PaginatedGraphObjectResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId });
    return this.request('GET', '/api/graphs/kgframes', {
      params: { space_id: spaceId, graph_id: graphId, page_size: pageSize, offset, search, ...options },
    });
  }

  async get(
    spaceId: string,
    graphId: string,
    uri: string,
  ): Promise<FrameGraphResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId, uri });
    return this.request('GET', '/api/graphs/kgframes', {
      params: { space_id: spaceId, graph_id: graphId, uri },
    });
  }

  async create(
    spaceId: string,
    graphId: string,
    data: unknown,
  ): Promise<FrameGraphResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId });
    return this.request('POST', '/api/graphs/kgframes', {
      params: { space_id: spaceId, graph_id: graphId },
      json: data,
    });
  }

  async update(
    spaceId: string,
    graphId: string,
    uri: string,
    data: unknown,
  ): Promise<FrameGraphResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId, uri });
    return this.request('POST', '/api/graphs/kgframes', {
      params: { space_id: spaceId, graph_id: graphId, operation_mode: 'update' },
      json: data,
    });
  }

  async delete(
    spaceId: string,
    graphId: string,
    uri: string,
  ): Promise<DeleteResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId, uri });
    return this.request('DELETE', '/api/graphs/kgframes', {
      params: { space_id: spaceId, graph_id: graphId, uri },
    });
  }

  async getSlots(
    spaceId: string,
    graphId: string,
    frameUri: string,
  ): Promise<PaginatedGraphObjectResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId, frame_uri: frameUri });
    return this.request('GET', '/api/graphs/kgframes/kgslots', {
      params: { space_id: spaceId, graph_id: graphId, frame_uri: frameUri },
    });
  }

  async getByUris(
    spaceId: string,
    graphId: string,
    uris: string[],
  ): Promise<MultiFrameGraphResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId });
    return this.request('GET', '/api/graphs/kgframes', {
      params: { space_id: spaceId, graph_id: graphId, uris: uris.join(',') },
    });
  }

  async batchDelete(
    spaceId: string,
    graphId: string,
    uris: string[],
  ): Promise<DeleteResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId });
    return this.request('DELETE', '/api/graphs/kgframes', {
      params: { space_id: spaceId, graph_id: graphId },
      json: { uris },
    });
  }

  async createSlots(
    spaceId: string,
    graphId: string,
    frameUri: string,
    data: unknown,
  ): Promise<VitalGraphResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId, frame_uri: frameUri });
    return this.request('POST', '/api/graphs/kgframes/kgslots', {
      params: { space_id: spaceId, graph_id: graphId, frame_uri: frameUri },
      json: data,
    });
  }

  async updateSlots(
    spaceId: string,
    graphId: string,
    frameUri: string,
    data: unknown,
  ): Promise<VitalGraphResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId, frame_uri: frameUri });
    return this.request('POST', '/api/graphs/kgframes/kgslots', {
      params: { space_id: spaceId, graph_id: graphId, frame_uri: frameUri },
      json: data,
    });
  }

  async deleteSlots(
    spaceId: string,
    graphId: string,
    frameUri: string,
    slotUris?: string[],
  ): Promise<DeleteResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId, frame_uri: frameUri });
    return this.request('DELETE', '/api/graphs/kgframes/kgslots', {
      params: { space_id: spaceId, graph_id: graphId, frame_uri: frameUri },
      json: slotUris ? { slot_uris: slotUris } : undefined,
    });
  }

  async getChildFrames(
    spaceId: string,
    graphId: string,
    parentFrameUri: string,
  ): Promise<PaginatedGraphObjectResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId, parent_frame_uri: parentFrameUri });
    return this.request('GET', '/api/graphs/kgframes/kgframes', {
      params: { space_id: spaceId, graph_id: graphId, parent_frame_uri: parentFrameUri },
    });
  }

  async createChildFrames(
    spaceId: string,
    graphId: string,
    parentFrameUri: string,
    data: unknown,
  ): Promise<VitalGraphResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId, parent_frame_uri: parentFrameUri });
    return this.request('POST', '/api/graphs/kgframes/kgframes', {
      params: { space_id: spaceId, graph_id: graphId, parent_frame_uri: parentFrameUri },
      json: data,
    });
  }

  async updateChildFrames(
    spaceId: string,
    graphId: string,
    parentFrameUri: string,
    data: unknown,
  ): Promise<VitalGraphResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId, parent_frame_uri: parentFrameUri });
    return this.request('POST', '/api/graphs/kgframes/kgframes', {
      params: { space_id: spaceId, graph_id: graphId, parent_frame_uri: parentFrameUri },
      json: data,
    });
  }

  async deleteChildFrames(
    spaceId: string,
    graphId: string,
    parentFrameUri: string,
    frameUris?: string[],
  ): Promise<DeleteResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId, parent_frame_uri: parentFrameUri });
    return this.request('DELETE', '/api/graphs/kgframes/kgframes', {
      params: { space_id: spaceId, graph_id: graphId, parent_frame_uri: parentFrameUri },
      json: frameUris ? { frame_uris: frameUris } : undefined,
    });
  }

  async queryFrames(
    spaceId: string,
    graphId: string,
    queryCriteria: Record<string, unknown>,
  ): Promise<QueryResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId });
    return this.request('POST', '/api/graphs/kgframes/query', {
      params: { space_id: spaceId, graph_id: graphId },
      json: queryCriteria,
    });
  }
}

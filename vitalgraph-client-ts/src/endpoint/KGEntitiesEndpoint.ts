import { BaseEndpoint } from './BaseEndpoint.js';
import { validateRequired } from '../utils/params.js';
import type {
  VitalGraphResponse,
  PaginatedGraphObjectResponse,
  MultiEntityGraphResponse,
  EntityGraphResponse,
  EntityResponse,
  CreateEntityResponse,
  UpdateEntityResponse,
  DeleteResponse,
  QueryResponse,
} from '../response/types.js';

export interface ListKGEntitiesOptions {
  pageSize?: number;
  offset?: number;
  entityTypeUri?: string;
  search?: string;
  includeEntityGraph?: boolean;
  sortBy?: string;
  sortOrder?: 'asc' | 'desc';
  status?: string;
  excludeStatus?: string;
  createdAfter?: string;
  createdBefore?: string;
  modifiedAfter?: string;
  modifiedBefore?: string;
  actionType?: string;
  provenanceType?: string;
}

export class KGEntitiesEndpoint extends BaseEndpoint {
  async list(
    spaceId: string,
    graphId: string,
    options: ListKGEntitiesOptions = {},
  ): Promise<PaginatedGraphObjectResponse | MultiEntityGraphResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId });
    return this.request('GET', '/api/graphs/kgentities', {
      params: {
        space_id: spaceId,
        graph_id: graphId,
        page_size: options.pageSize ?? 10,
        offset: options.offset ?? 0,
        entity_type_uri: options.entityTypeUri,
        search: options.search,
        include_entity_graph: options.includeEntityGraph,
        sort_by: options.sortBy,
        sort_order: options.sortBy ? (options.sortOrder ?? 'asc') : undefined,
        status: options.status,
        exclude_status: options.excludeStatus,
        created_after: options.createdAfter,
        created_before: options.createdBefore,
        modified_after: options.modifiedAfter,
        modified_before: options.modifiedBefore,
        action_type: options.actionType,
        provenance_type: options.provenanceType,
      },
    });
  }

  async get(
    spaceId: string,
    graphId: string,
    uri: string,
    includeEntityGraph = false,
  ): Promise<EntityResponse | EntityGraphResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId, uri });
    return this.request('GET', '/api/graphs/kgentities', {
      params: {
        space_id: spaceId,
        graph_id: graphId,
        uri,
        include_entity_graph: includeEntityGraph || undefined,
      },
    });
  }

  async create(
    spaceId: string,
    graphId: string,
    data: unknown,
  ): Promise<CreateEntityResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId });
    return this.request('POST', '/api/graphs/kgentities', {
      params: { space_id: spaceId, graph_id: graphId },
      json: data,
    });
  }

  async update(
    spaceId: string,
    graphId: string,
    uri: string,
    data: unknown,
  ): Promise<UpdateEntityResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId, uri });
    return this.request('POST', '/api/graphs/kgentities', {
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
    return this.request('DELETE', '/api/graphs/kgentities', {
      params: { space_id: spaceId, graph_id: graphId, uri },
    });
  }

  async batchDelete(
    spaceId: string,
    graphId: string,
    uris: string[],
  ): Promise<DeleteResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId });
    return this.request('DELETE', '/api/graphs/kgentities', {
      params: { space_id: spaceId, graph_id: graphId, uri_list: uris.join(',') },
    });
  }

  async getByUris(
    spaceId: string,
    graphId: string,
    uris: string[],
    includeEntityGraph = false,
  ): Promise<MultiEntityGraphResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId });
    return this.request('GET', '/api/graphs/kgentities', {
      params: {
        space_id: spaceId,
        graph_id: graphId,
        uris: uris.join(','),
        include_entity_graph: includeEntityGraph || undefined,
      },
    });
  }

  async getByReferenceIds(
    spaceId: string,
    graphId: string,
    referenceIds: string[],
    includeEntityGraph = false,
  ): Promise<MultiEntityGraphResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId });
    return this.request('GET', '/api/graphs/kgentities', {
      params: {
        space_id: spaceId,
        graph_id: graphId,
        reference_ids: referenceIds.join(','),
        include_entity_graph: includeEntityGraph || undefined,
      },
    });
  }

  async updateEntityOnly(
    spaceId: string,
    graphId: string,
    uri: string,
    data: unknown,
  ): Promise<UpdateEntityResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId, uri });
    return this.request('POST', '/api/graphs/kgentities', {
      params: { space_id: spaceId, graph_id: graphId, operation_mode: 'update', entity_only: true },
      json: data,
    });
  }

  async getFrames(
    spaceId: string,
    graphId: string,
    entityUri: string,
  ): Promise<PaginatedGraphObjectResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId, entity_uri: entityUri });
    return this.request('GET', '/api/graphs/kgentities/kgframes', {
      params: { space_id: spaceId, graph_id: graphId, entity_uri: entityUri },
    });
  }

  async createFrames(
    spaceId: string,
    graphId: string,
    entityUri: string,
    data: unknown,
  ): Promise<CreateEntityResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId, entity_uri: entityUri });
    return this.request('POST', '/api/graphs/kgentities/kgframes', {
      params: { space_id: spaceId, graph_id: graphId, entity_uri: entityUri },
      json: data,
    });
  }

  async updateFrames(
    spaceId: string,
    graphId: string,
    entityUri: string,
    data: unknown,
  ): Promise<UpdateEntityResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId, entity_uri: entityUri });
    return this.request('POST', '/api/graphs/kgentities/kgframes', {
      params: { space_id: spaceId, graph_id: graphId, entity_uri: entityUri },
      json: data,
    });
  }

  async deleteFrames(
    spaceId: string,
    graphId: string,
    entityUri: string,
    frameUris?: string[],
  ): Promise<DeleteResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId, entity_uri: entityUri });
    return this.request('DELETE', '/api/graphs/kgentities/kgframes', {
      params: { space_id: spaceId, graph_id: graphId, entity_uri: entityUri },
      json: frameUris ? { frame_uris: frameUris } : undefined,
    });
  }

  async queryEntities(
    spaceId: string,
    graphId: string,
    queryCriteria: Record<string, unknown>,
  ): Promise<QueryResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId });
    return this.request('POST', '/api/graphs/kgentities/query', {
      params: { space_id: spaceId, graph_id: graphId },
      json: queryCriteria,
    });
  }

  async count(
    spaceId: string,
    graphId: string,
    entityTypeUri?: string,
  ): Promise<VitalGraphResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId });
    return this.request('GET', '/api/graphs/kgentities/count', {
      params: {
        space_id: spaceId,
        graph_id: graphId,
        entity_type_uri: entityTypeUri,
      },
    });
  }

  async batchCount(
    spaceId: string,
    graphId: string,
    entityTypeUris: string[],
  ): Promise<VitalGraphResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId });
    return this.request('POST', '/api/graphs/kgentities/counts', {
      params: { space_id: spaceId, graph_id: graphId },
      json: { entity_type_uris: entityTypeUris },
    });
  }
}

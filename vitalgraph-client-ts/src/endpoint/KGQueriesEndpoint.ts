import { BaseEndpoint } from './BaseEndpoint.js';
import { validateRequired } from '../utils/params.js';
import type { QueryResponse } from '../response/types.js';

export class KGQueriesEndpoint extends BaseEndpoint {
  async query(
    spaceId: string,
    graphId: string,
    queryCriteria: unknown,
    pageSize = 10,
    offset = 0,
  ): Promise<QueryResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId });
    return this.request('POST', '/api/graphs/kgqueries', {
      params: { space_id: spaceId, graph_id: graphId, page_size: pageSize, offset },
      json: queryCriteria,
    });
  }

  async queryConnections(
    spaceId: string,
    graphId: string,
    entityUri: string,
    queryCriteria?: Record<string, unknown>,
  ): Promise<QueryResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId, entity_uri: entityUri });
    return this.request('POST', '/api/graphs/kgqueries', {
      params: { space_id: spaceId, graph_id: graphId, entity_uri: entityUri, query_type: 'connections' },
      json: queryCriteria ?? {},
    });
  }

  async queryFrameConnections(
    spaceId: string,
    graphId: string,
    entityUri: string,
    queryCriteria?: Record<string, unknown>,
  ): Promise<QueryResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId, entity_uri: entityUri });
    return this.request('POST', '/api/graphs/kgqueries', {
      params: { space_id: spaceId, graph_id: graphId, entity_uri: entityUri, query_type: 'frame_connections' },
      json: queryCriteria ?? {},
    });
  }

  async queryRelationConnections(
    spaceId: string,
    graphId: string,
    entityUri: string,
    queryCriteria?: Record<string, unknown>,
  ): Promise<QueryResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId, entity_uri: entityUri });
    return this.request('POST', '/api/graphs/kgqueries', {
      params: { space_id: spaceId, graph_id: graphId, entity_uri: entityUri, query_type: 'relation_connections' },
      json: queryCriteria ?? {},
    });
  }

  async queryFrames(
    spaceId: string,
    graphId: string,
    queryCriteria: Record<string, unknown>,
    pageSize = 10,
    offset = 0,
  ): Promise<QueryResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId });
    return this.request('POST', '/api/graphs/kgqueries', {
      params: { space_id: spaceId, graph_id: graphId, query_type: 'frames', page_size: pageSize, offset },
      json: queryCriteria,
    });
  }

  async queryEntities(
    spaceId: string,
    graphId: string,
    queryCriteria: Record<string, unknown>,
    pageSize = 10,
    offset = 0,
  ): Promise<QueryResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId });
    return this.request('POST', '/api/graphs/kgqueries', {
      params: { space_id: spaceId, graph_id: graphId, query_type: 'entities', page_size: pageSize, offset },
      json: queryCriteria,
    });
  }

  /**
   * Vector similarity search via the kgqueries endpoint.
   * Wraps queryEntities with vector_criteria for convenience.
   */
  async vectorSearch(
    spaceId: string,
    graphId: string,
    options: {
      searchText: string;
      indexName?: string;
      topK?: number;
      minScore?: number;
    },
  ): Promise<QueryResponse> {
    return this.queryEntities(spaceId, graphId, {
      criteria: {
        query_type: 'entity',
        vector_criteria: {
          search_text: options.searchText,
          index_name: options.indexName,
          top_k: options.topK ?? 10,
          min_score: options.minScore,
        },
      },
    }, options.topK ?? 10);
  }
}

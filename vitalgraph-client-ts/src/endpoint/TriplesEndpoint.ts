import { BaseEndpoint } from './BaseEndpoint.js';
import { validateRequired } from '../utils/params.js';
import type { TripleListResponse, TripleOperationResponse } from '../response/types.js';

export class TriplesEndpoint extends BaseEndpoint {
  async list(spaceId: string, graphId: string, subjectUri?: string, pageSize = 100, offset = 0, objectFilter?: string): Promise<TripleListResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId });
    return this.request('GET', '/api/graphs/triples', {
      params: { space_id: spaceId, graph_id: graphId, subject: subjectUri, page_size: pageSize, offset, object_filter: objectFilter },
    });
  }

  async add(spaceId: string, graphId: string, triples: unknown): Promise<TripleOperationResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId });
    return this.request('POST', '/api/graphs/triples', {
      params: { space_id: spaceId, graph_id: graphId },
      json: triples,
    });
  }

  async delete(spaceId: string, graphId: string, triples: unknown): Promise<TripleOperationResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId });
    return this.request('DELETE', '/api/graphs/triples', {
      params: { space_id: spaceId, graph_id: graphId },
      json: triples,
    });
  }
}

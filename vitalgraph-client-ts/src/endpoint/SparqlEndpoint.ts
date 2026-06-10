import { BaseEndpoint } from './BaseEndpoint.js';
import { validateRequired } from '../utils/params.js';
import type {
  SPARQLQueryResponse,
  SPARQLUpdateResponse,
  SPARQLInsertResponse,
  SPARQLDeleteResponse,
} from '../response/types.js';

export class SparqlEndpoint extends BaseEndpoint {
  async query(spaceId: string, sparql: string, graphId?: string): Promise<SPARQLQueryResponse> {
    validateRequired({ space_id: spaceId, sparql });
    const json: Record<string, unknown> = { query: sparql };
    if (graphId) json.graph_id = graphId;
    return this.request('POST', '/api/graphs/sparql/query', {
      params: { space_id: spaceId },
      json,
    });
  }

  async update(spaceId: string, sparql: string, graphId?: string): Promise<SPARQLUpdateResponse> {
    validateRequired({ space_id: spaceId, sparql });
    const json: Record<string, unknown> = { update: sparql };
    if (graphId) json.graph_id = graphId;
    return this.request('POST', '/api/graphs/sparql/update', {
      params: { space_id: spaceId },
      json,
    });
  }

  async insert(spaceId: string, sparql: string, graphId?: string): Promise<SPARQLInsertResponse> {
    validateRequired({ space_id: spaceId, sparql });
    const json: Record<string, unknown> = { update: sparql };
    if (graphId) json.graph_id = graphId;
    return this.request('POST', '/api/graphs/sparql/insert', {
      params: { space_id: spaceId },
      json,
    });
  }

  async delete(spaceId: string, sparql: string, graphId?: string): Promise<SPARQLDeleteResponse> {
    validateRequired({ space_id: spaceId, sparql });
    const json: Record<string, unknown> = { update: sparql };
    if (graphId) json.graph_id = graphId;
    return this.request('POST', '/api/graphs/sparql/delete', {
      params: { space_id: spaceId },
      json,
    });
  }
}

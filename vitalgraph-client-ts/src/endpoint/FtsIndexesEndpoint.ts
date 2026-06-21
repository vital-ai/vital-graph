import { BaseEndpoint } from './BaseEndpoint.js';
import { validateRequired } from '../utils/params.js';
import type { VitalGraphResponse } from '../response/types.js';

export interface FtsIndex {
  index_id: number;
  index_name: string;
  languages: string[];
  created_time: string | null;
  row_count?: number;
}

export interface FtsIndexResponse extends VitalGraphResponse, FtsIndex {}

export interface FtsIndexesListResponse extends VitalGraphResponse {
  indexes: FtsIndex[];
  total_count: number;
}

export interface FtsIndexStatsResponse extends VitalGraphResponse {
  index_name: string;
  row_count: number;
  distinct_entity_count: number;
  has_tsv_count: number;
}

export interface PopulateFtsResponse extends VitalGraphResponse {
  message: string;
  index_name: string;
  rows_populated: number;
  elapsed_seconds: number;
  errors: string[];
}

export class FtsIndexesEndpoint extends BaseEndpoint {
  async list(spaceId: string): Promise<FtsIndexesListResponse> {
    validateRequired({ space_id: spaceId });
    return this.request('GET', '/api/fts-indexes', {
      params: { space_id: spaceId },
    });
  }

  async create(spaceId: string, data: {
    index_name: string;
    languages?: string[];
  }): Promise<FtsIndexResponse> {
    validateRequired({ space_id: spaceId, index_name: data.index_name });
    return this.request('POST', '/api/fts-indexes', {
      params: { space_id: spaceId },
      json: data,
    });
  }

  async delete(spaceId: string, indexName: string): Promise<VitalGraphResponse> {
    validateRequired({ space_id: spaceId, index_name: indexName });
    return this.request('DELETE', '/api/fts-indexes', {
      params: { space_id: spaceId, index_name: indexName },
    });
  }

  async stats(spaceId: string, indexName: string): Promise<FtsIndexStatsResponse> {
    validateRequired({ space_id: spaceId, index_name: indexName });
    return this.request('GET', '/api/fts-indexes/stats', {
      params: { space_id: spaceId, index_name: indexName },
    });
  }

  async updateLanguages(spaceId: string, indexName: string, data: {
    languages: string[];
    refresh_tsv?: boolean;
  }): Promise<FtsIndexResponse> {
    validateRequired({ space_id: spaceId, index_name: indexName });
    return this.request('PUT', '/api/fts-indexes/languages', {
      params: { space_id: spaceId, index_name: indexName },
      json: data,
    });
  }

  async populate(spaceId: string, indexName: string, data: {
    graph_uri: string;
    mapping_type?: string;
    type_uri?: string;
    batch_size?: number;
  }): Promise<PopulateFtsResponse> {
    validateRequired({ space_id: spaceId, index_name: indexName });
    return this.request('POST', '/api/fts-indexes/populate', {
      params: { space_id: spaceId, index_name: indexName },
      json: data,
    });
  }
}

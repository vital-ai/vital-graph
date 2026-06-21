/* eslint-disable @typescript-eslint/no-explicit-any */
/**
 * Search Mappings & FTS Indexes API Service
 *
 * Provides methods for search mapping CRUD, property management,
 * and FTS index lifecycle (create, delete, stats, populate, languages).
 * All calls go through apiService.client (the typed VitalGraph client).
 */

import { apiService } from './ApiService';
import type {
  SearchMapping,
  SearchMappingProperty,
  SearchMappingIndex,
  IndexType,
  CreateSearchMappingRequest,
  UpdateSearchMappingRequest,
  FtsIndex,
  FtsIndexStats,
  CreateFtsIndexRequest,
  PopulateFtsResponse,
} from '../types/searchFts';

class SearchFtsService {
  private get client() { return apiService.client; }

  // ---------------------------------------------------------------------------
  // Search Mappings
  // ---------------------------------------------------------------------------

  async getSearchMappings(
    spaceId: string,
    filters?: { index_name?: string; mapping_type?: string; enabled?: boolean },
  ): Promise<SearchMapping[]> {
    const options: { indexName?: string; mappingType?: string; enabled?: boolean } = {};
    if (filters?.index_name) options.indexName = filters.index_name;
    if (filters?.mapping_type) options.mappingType = filters.mapping_type;
    if (filters?.enabled !== undefined) options.enabled = filters.enabled;
    const data = await this.client.searchMappings.list(spaceId, options);
    return (data as any).mappings || [];
  }

  async getSearchMapping(spaceId: string, mappingId: number): Promise<SearchMapping> {
    return this.client.searchMappings.get(spaceId, mappingId) as any;
  }

  async createSearchMapping(spaceId: string, data: CreateSearchMappingRequest): Promise<SearchMapping> {
    return this.client.searchMappings.create(spaceId, data) as any;
  }

  async updateSearchMapping(
    spaceId: string,
    mappingId: number,
    data: UpdateSearchMappingRequest,
  ): Promise<SearchMapping> {
    return this.client.searchMappings.update(spaceId, mappingId, data) as any;
  }

  async deleteSearchMapping(spaceId: string, mappingId: number): Promise<void> {
    await this.client.searchMappings.delete(spaceId, mappingId);
  }

  async addMappingProperty(
    spaceId: string,
    mappingId: number,
    data: { property_uri: string; property_role?: string; ordinal?: number },
  ): Promise<SearchMappingProperty> {
    return this.client.searchMappings.addProperty(spaceId, mappingId, data) as any;
  }

  async removeMappingProperty(spaceId: string, mappingId: number, propertyId: number): Promise<void> {
    await this.client.searchMappings.removeProperty(spaceId, mappingId, propertyId);
  }

  // ---------------------------------------------------------------------------
  // Search Mapping Index Associations (junction table)
  // ---------------------------------------------------------------------------

  async listMappingIndexes(spaceId: string, mappingId: number): Promise<SearchMappingIndex[]> {
    const url = `/api/search-mappings/${mappingId}/indexes?space_id=${encodeURIComponent(spaceId)}`;
    const resp = await this.client.makeAuthenticatedRequest(url, { method: 'GET' });
    return await resp.json() as SearchMappingIndex[];
  }

  async addMappingIndex(
    spaceId: string,
    mappingId: number,
    data: { index_type: IndexType; index_name: string },
  ): Promise<SearchMappingIndex> {
    const url = `/api/search-mappings/${mappingId}/indexes?space_id=${encodeURIComponent(spaceId)}`;
    const resp = await this.client.makeAuthenticatedRequest(url, {
      method: 'POST',
      body: JSON.stringify(data),
      headers: { 'Content-Type': 'application/json' },
    });
    return await resp.json() as SearchMappingIndex;
  }

  async removeMappingIndex(spaceId: string, mappingId: number, junctionId: number): Promise<void> {
    const url = `/api/search-mappings/${mappingId}/indexes/${junctionId}?space_id=${encodeURIComponent(spaceId)}`;
    await this.client.makeAuthenticatedRequest(url, { method: 'DELETE' });
  }

  // ---------------------------------------------------------------------------
  // FTS Indexes
  // ---------------------------------------------------------------------------

  async getFtsIndexes(spaceId: string): Promise<FtsIndex[]> {
    const data = await this.client.ftsIndexes.list(spaceId);
    return (data as any).indexes || [];
  }

  async createFtsIndex(spaceId: string, data: CreateFtsIndexRequest): Promise<FtsIndex> {
    return this.client.ftsIndexes.create(spaceId, data) as any;
  }

  async deleteFtsIndex(spaceId: string, indexName: string): Promise<void> {
    await this.client.ftsIndexes.delete(spaceId, indexName);
  }

  async getFtsStats(spaceId: string, indexName: string): Promise<FtsIndexStats> {
    return this.client.ftsIndexes.stats(spaceId, indexName) as any;
  }

  async updateFtsLanguages(
    spaceId: string,
    indexName: string,
    data: { languages: string[]; refresh_tsv?: boolean },
  ): Promise<FtsIndex> {
    return this.client.ftsIndexes.updateLanguages(spaceId, indexName, data) as any;
  }

  async populateFts(
    spaceId: string,
    indexName: string,
    data: { graph_uri: string; mapping_type?: string; type_uri?: string; batch_size?: number },
  ): Promise<PopulateFtsResponse> {
    return this.client.ftsIndexes.populate(spaceId, indexName, data) as any;
  }
}

export const searchFtsService = new SearchFtsService();

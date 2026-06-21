/**
 * Fuzzy Mapping API Service
 *
 * Provides methods for fuzzy mapping CRUD, property management,
 * and index population. Delegates to @vital-ai/vitalgraph-client.
 */

import { vgClient } from './FrontendVitalGraphClient';
import type {
  FuzzyMapping,
  FuzzyMappingProperty,
  FuzzyMappingStats,
  CreateFuzzyMappingRequest,
  UpdateFuzzyMappingRequest,
  PopulateResponse,
} from '../types/fuzzyMappings';

class FuzzyMappingService {
  // ---------------------------------------------------------------------------
  // Fuzzy Mappings
  // ---------------------------------------------------------------------------

  async getFuzzyMappings(
    spaceId: string,
    filters?: { index_name?: string; mapping_type?: string; enabled?: boolean }
  ): Promise<FuzzyMapping[]> {
    const data = await vgClient.fuzzyMappings.list(spaceId, filters);
    return (data as any).mappings || [];
  }

  async getFuzzyMapping(spaceId: string, mappingId: number): Promise<FuzzyMapping> {
    const data = await vgClient.fuzzyMappings.get(spaceId, mappingId);
    return data as any;
  }

  async createFuzzyMapping(spaceId: string, data: CreateFuzzyMappingRequest): Promise<FuzzyMapping> {
    return vgClient.fuzzyMappings.create(spaceId, data) as any;
  }

  async updateFuzzyMapping(
    spaceId: string,
    mappingId: number,
    data: UpdateFuzzyMappingRequest
  ): Promise<FuzzyMapping> {
    return vgClient.fuzzyMappings.update(spaceId, mappingId, data) as any;
  }

  async deleteFuzzyMapping(spaceId: string, mappingId: number): Promise<void> {
    await vgClient.fuzzyMappings.delete(spaceId, mappingId);
  }

  // ---------------------------------------------------------------------------
  // Properties
  // ---------------------------------------------------------------------------

  async addMappingProperty(
    spaceId: string,
    mappingId: number,
    data: { property_uri: string; property_role: string; ordinal?: number }
  ): Promise<FuzzyMappingProperty> {
    return vgClient.fuzzyMappings.addProperty(spaceId, mappingId, data) as any;
  }

  async removeMappingProperty(spaceId: string, mappingId: number, propertyId: number): Promise<void> {
    await vgClient.fuzzyMappings.removeProperty(spaceId, mappingId, propertyId);
  }

  // ---------------------------------------------------------------------------
  // Stats
  // ---------------------------------------------------------------------------

  async getStats(spaceId: string, mappingId: number): Promise<FuzzyMappingStats> {
    return vgClient.fuzzyMappings.getStats(spaceId, mappingId) as any;
  }

  // ---------------------------------------------------------------------------
  // Populate
  // ---------------------------------------------------------------------------

  async populate(spaceId: string, mappingId: number): Promise<PopulateResponse> {
    return vgClient.fuzzyMappings.populate(spaceId, mappingId) as any;
  }
}

export const fuzzyMappingService = new FuzzyMappingService();

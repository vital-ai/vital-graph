import { BaseEndpoint } from './BaseEndpoint.js';
import { validateRequired } from '../utils/params.js';
import type { VitalGraphResponse } from '../response/types.js';

export interface SearchEntitiesOptions {
  query?: string;
  typeKey?: string;
  country?: string;
  region?: string;
  status?: string;
  page?: number;
  pageSize?: number;
}

export interface SearchEntityOptions {
  q?: string;
  identifierValue?: string;
  identifierNamespace?: string;
  typeKey?: string;
  categoryKey?: string;
  country?: string;
  region?: string;
  locality?: string;
  latitude?: number;
  longitude?: number;
  radiusKm?: number;
  limit?: number;
  minCertainty?: number;
}

export interface SearchLocationOptions {
  externalLocationId?: string;
  latitude?: number;
  longitude?: number;
  radiusKm?: number;
  q?: string;
  address?: string;
  locationTypeKey?: string;
  countryCode?: string;
  locality?: string;
  adminArea1?: string;
  postalCode?: string;
  locationName?: string;
  entityId?: string;
  isPrimary?: boolean;
  includeExpired?: boolean;
  minCertainty?: number;
  limit?: number;
}

export interface FindSimilarOptions {
  name: string;
  typeKey?: string;
  country?: string;
  region?: string;
  locality?: string;
  limit?: number;
  minScore?: number;
}

export class EntityRegistryEndpoint extends BaseEndpoint {
  // ------------------------------------------------------------------
  // Entity CRUD
  // ------------------------------------------------------------------

  async createEntity(data: Record<string, unknown>): Promise<VitalGraphResponse> {
    return this.request('POST', '/api/registry/entities', { json: data });
  }

  async getEntity(entityId: string): Promise<VitalGraphResponse> {
    validateRequired({ entity_id: entityId });
    return this.request('GET', '/api/registry/entities/get', {
      params: { entity_id: entityId },
    });
  }

  async searchEntities(options: SearchEntitiesOptions = {}): Promise<VitalGraphResponse> {
    return this.request('GET', '/api/registry/entities', {
      params: {
        query: options.query,
        type_key: options.typeKey,
        country: options.country,
        region: options.region,
        status: options.status ?? 'active',
        page: options.page ?? 1,
        page_size: options.pageSize ?? 20,
      },
    });
  }

  async updateEntity(entityId: string, data: Record<string, unknown>): Promise<VitalGraphResponse> {
    validateRequired({ entity_id: entityId });
    return this.request('PUT', '/api/registry/entities/update', {
      params: { entity_id: entityId },
      json: data,
    });
  }

  async deleteEntity(entityId: string): Promise<VitalGraphResponse> {
    validateRequired({ entity_id: entityId });
    return this.request('DELETE', '/api/registry/entities/delete', {
      params: { entity_id: entityId },
    });
  }

  // ------------------------------------------------------------------
  // Identifiers
  // ------------------------------------------------------------------

  async addIdentifier(entityId: string, data: Record<string, unknown>): Promise<VitalGraphResponse> {
    validateRequired({ entity_id: entityId });
    return this.request('POST', '/api/registry/identifiers/add', {
      params: { entity_id: entityId },
      json: data,
    });
  }

  async listIdentifiers(entityId: string): Promise<VitalGraphResponse> {
    validateRequired({ entity_id: entityId });
    return this.request('GET', '/api/registry/identifiers/list', {
      params: { entity_id: entityId },
    });
  }

  async removeIdentifier(identifierId: number): Promise<VitalGraphResponse> {
    return this.request('DELETE', '/api/registry/identifiers/remove', {
      params: { identifier_id: identifierId },
    });
  }

  async lookupByIdentifier(namespace: string, value: string): Promise<VitalGraphResponse> {
    validateRequired({ namespace, value });
    return this.request('GET', '/api/registry/identifiers/lookup', {
      params: { namespace, value },
    });
  }

  // ------------------------------------------------------------------
  // Aliases
  // ------------------------------------------------------------------

  async addAlias(entityId: string, data: Record<string, unknown>): Promise<VitalGraphResponse> {
    validateRequired({ entity_id: entityId });
    return this.request('POST', '/api/registry/aliases/add', {
      params: { entity_id: entityId },
      json: data,
    });
  }

  async listAliases(entityId: string): Promise<VitalGraphResponse> {
    validateRequired({ entity_id: entityId });
    return this.request('GET', '/api/registry/aliases/list', {
      params: { entity_id: entityId },
    });
  }

  async removeAlias(aliasId: number): Promise<VitalGraphResponse> {
    return this.request('DELETE', '/api/registry/aliases/remove', {
      params: { alias_id: aliasId },
    });
  }

  // ------------------------------------------------------------------
  // Categories
  // ------------------------------------------------------------------

  async listCategories(): Promise<VitalGraphResponse> {
    return this.request('GET', '/api/registry/categories');
  }

  async createCategory(data: Record<string, unknown>): Promise<VitalGraphResponse> {
    return this.request('POST', '/api/registry/categories', { json: data });
  }

  async listEntityCategories(entityId: string): Promise<VitalGraphResponse> {
    validateRequired({ entity_id: entityId });
    return this.request('GET', '/api/registry/categories/entity', {
      params: { entity_id: entityId },
    });
  }

  async addEntityCategory(entityId: string, data: Record<string, unknown>): Promise<VitalGraphResponse> {
    validateRequired({ entity_id: entityId });
    return this.request('POST', '/api/registry/categories/assign', {
      params: { entity_id: entityId },
      json: data,
    });
  }

  async removeEntityCategory(entityId: string, categoryKey: string): Promise<VitalGraphResponse> {
    validateRequired({ entity_id: entityId, category_key: categoryKey });
    return this.request('DELETE', '/api/registry/categories/remove', {
      params: { entity_id: entityId, category_key: categoryKey },
    });
  }

  async listEntitiesByCategory(categoryKey: string): Promise<VitalGraphResponse> {
    validateRequired({ category_key: categoryKey });
    return this.request('GET', '/api/registry/categories/entities', {
      params: { category_key: categoryKey },
    });
  }

  // ------------------------------------------------------------------
  // Location Types
  // ------------------------------------------------------------------

  async listLocationTypes(): Promise<VitalGraphResponse> {
    return this.request('GET', '/api/registry/location/types');
  }

  async createLocationType(data: Record<string, unknown>): Promise<VitalGraphResponse> {
    return this.request('POST', '/api/registry/location/types', { json: data });
  }

  // ------------------------------------------------------------------
  // Locations
  // ------------------------------------------------------------------

  async createLocation(entityId: string, data: Record<string, unknown>): Promise<VitalGraphResponse> {
    validateRequired({ entity_id: entityId });
    return this.request('POST', '/api/registry/locations/add', {
      params: { entity_id: entityId },
      json: data,
    });
  }

  async getLocation(locationId: number): Promise<VitalGraphResponse> {
    return this.request('GET', '/api/registry/locations/get', {
      params: { location_id: locationId },
    });
  }

  async listLocations(entityId: string, includeExpired = false): Promise<VitalGraphResponse> {
    validateRequired({ entity_id: entityId });
    return this.request('GET', '/api/registry/locations/list', {
      params: { entity_id: entityId, include_expired: includeExpired || undefined },
    });
  }

  async updateLocation(locationId: number, data: Record<string, unknown>): Promise<VitalGraphResponse> {
    return this.request('PUT', '/api/registry/locations/update', {
      params: { location_id: locationId },
      json: data,
    });
  }

  async removeLocation(locationId: number): Promise<VitalGraphResponse> {
    return this.request('DELETE', '/api/registry/locations/remove', {
      params: { location_id: locationId },
    });
  }

  // ------------------------------------------------------------------
  // Location Categories
  // ------------------------------------------------------------------

  async addLocationCategory(locationId: number, data: Record<string, unknown>): Promise<VitalGraphResponse> {
    return this.request('POST', '/api/registry/locations/categories/assign', {
      params: { location_id: locationId },
      json: data,
    });
  }

  async removeLocationCategory(locationId: number, categoryKey: string): Promise<VitalGraphResponse> {
    return this.request('DELETE', '/api/registry/locations/categories/remove', {
      params: { location_id: locationId, category_key: categoryKey },
    });
  }

  async listLocationCategories(locationId: number): Promise<VitalGraphResponse> {
    return this.request('GET', '/api/registry/locations/categories/list', {
      params: { location_id: locationId },
    });
  }

  // ------------------------------------------------------------------
  // Relationship Types
  // ------------------------------------------------------------------

  async listRelationshipTypes(): Promise<VitalGraphResponse> {
    return this.request('GET', '/api/registry/relationship/types');
  }

  async createRelationshipType(data: Record<string, unknown>): Promise<VitalGraphResponse> {
    return this.request('POST', '/api/registry/relationship/types', { json: data });
  }

  // ------------------------------------------------------------------
  // Relationships
  // ------------------------------------------------------------------

  async createRelationship(data: Record<string, unknown>): Promise<VitalGraphResponse> {
    return this.request('POST', '/api/registry/relationships', { json: data });
  }

  async getRelationship(relationshipId: number): Promise<VitalGraphResponse> {
    return this.request('GET', '/api/registry/relationships/get', {
      params: { relationship_id: relationshipId },
    });
  }

  async listRelationships(entityId: string, direction = 'both', includeExpired = false): Promise<VitalGraphResponse> {
    validateRequired({ entity_id: entityId });
    return this.request('GET', '/api/registry/relationships/list', {
      params: { entity_id: entityId, direction, include_expired: includeExpired || undefined },
    });
  }

  async updateRelationship(relationshipId: number, data: Record<string, unknown>): Promise<VitalGraphResponse> {
    return this.request('PUT', '/api/registry/relationships/update', {
      params: { relationship_id: relationshipId },
      json: data,
    });
  }

  async removeRelationship(relationshipId: number): Promise<VitalGraphResponse> {
    return this.request('DELETE', '/api/registry/relationships/remove', {
      params: { relationship_id: relationshipId },
    });
  }

  // ------------------------------------------------------------------
  // Same-As
  // ------------------------------------------------------------------

  async createSameAs(data: Record<string, unknown>): Promise<VitalGraphResponse> {
    return this.request('POST', '/api/registry/sameas', { json: data });
  }

  async getSameAs(entityId: string): Promise<VitalGraphResponse> {
    validateRequired({ entity_id: entityId });
    return this.request('GET', '/api/registry/sameas/list', {
      params: { entity_id: entityId },
    });
  }

  async retractSameAs(sameAsId: number, data: Record<string, unknown>): Promise<VitalGraphResponse> {
    return this.request('PUT', '/api/registry/sameas/retract', {
      params: { same_as_id: sameAsId },
      json: data,
    });
  }

  async resolveEntity(entityId: string): Promise<VitalGraphResponse> {
    validateRequired({ entity_id: entityId });
    return this.request('GET', '/api/registry/sameas/resolve', {
      params: { entity_id: entityId },
    });
  }

  // ------------------------------------------------------------------
  // Entity Types
  // ------------------------------------------------------------------

  async listEntityTypes(): Promise<VitalGraphResponse> {
    return this.request('GET', '/api/registry/entity/types');
  }

  async createEntityType(data: Record<string, unknown>): Promise<VitalGraphResponse> {
    return this.request('POST', '/api/registry/entity/types', { json: data });
  }

  // ------------------------------------------------------------------
  // Change Log
  // ------------------------------------------------------------------

  async getEntityChangelog(
    entityId: string,
    changeType?: string,
    limit = 50,
    offset = 0,
  ): Promise<VitalGraphResponse> {
    validateRequired({ entity_id: entityId });
    return this.request('GET', '/api/registry/changelog/entity', {
      params: { entity_id: entityId, change_type: changeType, limit, offset },
    });
  }

  async getRecentChangelog(limit = 50, changeType?: string): Promise<VitalGraphResponse> {
    return this.request('GET', '/api/registry/changelog', {
      params: { limit, change_type: changeType },
    });
  }

  // ------------------------------------------------------------------
  // Similar / Search
  // ------------------------------------------------------------------

  async findSimilar(options: FindSimilarOptions): Promise<VitalGraphResponse> {
    validateRequired({ name: options.name });
    return this.request('GET', '/api/registry/search/similar', {
      params: {
        name: options.name,
        type_key: options.typeKey,
        country: options.country,
        region: options.region,
        locality: options.locality,
        limit: options.limit ?? 10,
        min_score: options.minScore ?? 50.0,
      },
    });
  }

  async searchEntity(options: SearchEntityOptions = {}): Promise<VitalGraphResponse> {
    return this.request('GET', '/api/registry/search/entity', {
      params: {
        q: options.q,
        identifier_value: options.identifierValue,
        identifier_namespace: options.identifierNamespace,
        type_key: options.typeKey,
        category_key: options.categoryKey,
        country: options.country,
        region: options.region,
        locality: options.locality,
        latitude: options.latitude,
        longitude: options.longitude,
        radius_km: options.radiusKm,
        limit: options.limit ?? 20,
        min_certainty: options.minCertainty ?? 0.7,
      },
    });
  }

  async searchLocation(options: SearchLocationOptions = {}): Promise<VitalGraphResponse> {
    return this.request('GET', '/api/registry/search/location', {
      params: {
        external_location_id: options.externalLocationId,
        latitude: options.latitude,
        longitude: options.longitude,
        radius_km: options.radiusKm,
        q: options.q,
        address: options.address,
        location_type_key: options.locationTypeKey,
        country_code: options.countryCode,
        locality: options.locality,
        admin_area_1: options.adminArea1,
        postal_code: options.postalCode,
        location_name: options.locationName,
        entity_id: options.entityId,
        is_primary: options.isPrimary,
        include_expired: options.includeExpired || undefined,
        min_certainty: options.minCertainty ?? 0.5,
        limit: options.limit ?? 20,
      },
    });
  }
}

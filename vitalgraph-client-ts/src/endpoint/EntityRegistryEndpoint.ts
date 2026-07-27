import { BaseEndpoint } from './BaseEndpoint.js';
import { validateRequired } from '../utils/params.js';
import type { VitalGraphResponse } from '../response/types.js';

/** A registry data record (entity, location, relationship, …). Shape is
 *  domain-specific and validated server-side, so it is left open here. */
export type RegistryRecord = Record<string, unknown>;

/**
 * Server envelope for registry routes that wrap their payload in a named data
 * field. HTTP is always 200; success/failure is read from `status`/`success`
 * and the data field is null on failure.
 */
type RegistryEnvelope<K extends string> = VitalGraphResponse &
  Partial<Record<K, RegistryRecord | null>>;

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

  async getEntity(entityId: string): Promise<RegistryRecord | null> {
    validateRequired({ entity_id: entityId });
    const body = await this.request<RegistryEnvelope<'entity'>>('GET', '/api/registry/entities/get', {
      params: { entity_id: entityId },
    });
    return body.entity ?? null;
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

  async updateEntity(entityId: string, data: Record<string, unknown>): Promise<RegistryRecord | null> {
    validateRequired({ entity_id: entityId });
    const body = await this.request<RegistryEnvelope<'entity'>>('PUT', '/api/registry/entities/update', {
      params: { entity_id: entityId },
      json: data,
    });
    return body.entity ?? null;
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

  async addIdentifier(entityId: string, data: Record<string, unknown>): Promise<RegistryRecord | null> {
    validateRequired({ entity_id: entityId });
    const body = await this.request<RegistryEnvelope<'identifier'>>('POST', '/api/registry/identifiers/add', {
      params: { entity_id: entityId },
      json: data,
    });
    return body.identifier ?? null;
  }

  async listIdentifiers(entityId: string): Promise<VitalGraphResponse> {
    validateRequired({ entity_id: entityId });
    return this.request('GET', '/api/registry/identifiers/list', {
      params: { entity_id: entityId },
    });
  }

  async removeIdentifier(identifierId: number): Promise<VitalGraphResponse> {
    return this.request('DELETE', '/api/registry/identifiers/retract', {
      params: { identifier_id: identifierId },
    });
  }

  async lookupByIdentifier(namespace: string, value: string): Promise<RegistryRecord[]> {
    validateRequired({ namespace, value });
    const body = await this.request<VitalGraphResponse & { entities?: RegistryRecord[] }>(
      'GET', '/api/registry/identifiers/lookup', {
        params: { namespace, value },
      });
    return body.entities ?? [];
  }

  // ------------------------------------------------------------------
  // Aliases
  // ------------------------------------------------------------------

  async addAlias(entityId: string, data: Record<string, unknown>): Promise<RegistryRecord | null> {
    validateRequired({ entity_id: entityId });
    const body = await this.request<RegistryEnvelope<'alias'>>('POST', '/api/registry/aliases/add', {
      params: { entity_id: entityId },
      json: data,
    });
    return body.alias ?? null;
  }

  async listAliases(entityId: string): Promise<VitalGraphResponse> {
    validateRequired({ entity_id: entityId });
    return this.request('GET', '/api/registry/aliases/list', {
      params: { entity_id: entityId },
    });
  }

  async removeAlias(aliasId: number): Promise<VitalGraphResponse> {
    return this.request('DELETE', '/api/registry/aliases/retract', {
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

  async addEntityCategory(entityId: string, data: Record<string, unknown>): Promise<RegistryRecord | null> {
    validateRequired({ entity_id: entityId });
    const body = await this.request<RegistryEnvelope<'entity_category'>>('POST', '/api/registry/categories/assign', {
      params: { entity_id: entityId },
      json: data,
    });
    return body.entity_category ?? null;
  }

  async removeEntityCategory(entityId: string, categoryKey: string): Promise<VitalGraphResponse> {
    validateRequired({ entity_id: entityId, category_key: categoryKey });
    return this.request('DELETE', '/api/registry/categories/retract', {
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

  async createLocation(entityId: string, data: Record<string, unknown>): Promise<RegistryRecord | null> {
    validateRequired({ entity_id: entityId });
    const body = await this.request<RegistryEnvelope<'location'>>('POST', '/api/registry/locations/add', {
      params: { entity_id: entityId },
      json: data,
    });
    return body.location ?? null;
  }

  async getLocation(locationId: number): Promise<RegistryRecord | null> {
    const body = await this.request<RegistryEnvelope<'location'>>('GET', '/api/registry/locations/get', {
      params: { location_id: locationId },
    });
    return body.location ?? null;
  }

  async listLocations(entityId: string, includeExpired = false): Promise<VitalGraphResponse> {
    validateRequired({ entity_id: entityId });
    return this.request('GET', '/api/registry/locations/list', {
      params: { entity_id: entityId, include_expired: includeExpired || undefined },
    });
  }

  async updateLocation(locationId: number, data: Record<string, unknown>): Promise<RegistryRecord | null> {
    const body = await this.request<RegistryEnvelope<'location'>>('PUT', '/api/registry/locations/update', {
      params: { location_id: locationId },
      json: data,
    });
    return body.location ?? null;
  }

  async removeLocation(locationId: number): Promise<VitalGraphResponse> {
    return this.request('DELETE', '/api/registry/locations/retract', {
      params: { location_id: locationId },
    });
  }

  // ------------------------------------------------------------------
  // Location Categories
  // ------------------------------------------------------------------

  async addLocationCategory(locationId: number, data: Record<string, unknown>): Promise<RegistryRecord | null> {
    const body = await this.request<RegistryEnvelope<'location_category'>>('POST', '/api/registry/locations/categories/assign', {
      params: { location_id: locationId },
      json: data,
    });
    return body.location_category ?? null;
  }

  async removeLocationCategory(locationId: number, categoryKey: string): Promise<VitalGraphResponse> {
    return this.request('DELETE', '/api/registry/locations/categories/retract', {
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

  async createRelationship(data: Record<string, unknown>): Promise<RegistryRecord | null> {
    const body = await this.request<RegistryEnvelope<'relationship'>>('POST', '/api/registry/relationships', { json: data });
    return body.relationship ?? null;
  }

  async getRelationship(relationshipId: number): Promise<RegistryRecord | null> {
    const body = await this.request<RegistryEnvelope<'relationship'>>('GET', '/api/registry/relationships/get', {
      params: { relationship_id: relationshipId },
    });
    return body.relationship ?? null;
  }

  async listRelationships(entityId: string, direction = 'both', includeExpired = false): Promise<VitalGraphResponse> {
    validateRequired({ entity_id: entityId });
    return this.request('GET', '/api/registry/relationships/list', {
      params: { entity_id: entityId, direction, include_expired: includeExpired || undefined },
    });
  }

  async updateRelationship(relationshipId: number, data: Record<string, unknown>): Promise<RegistryRecord | null> {
    const body = await this.request<RegistryEnvelope<'relationship'>>('PUT', '/api/registry/relationships/update', {
      params: { relationship_id: relationshipId },
      json: data,
    });
    return body.relationship ?? null;
  }

  async removeRelationship(relationshipId: number): Promise<VitalGraphResponse> {
    return this.request('DELETE', '/api/registry/relationships/retract', {
      params: { relationship_id: relationshipId },
    });
  }

  // ------------------------------------------------------------------
  // Same-As
  // ------------------------------------------------------------------

  async createSameAs(data: Record<string, unknown>): Promise<RegistryRecord | null> {
    const body = await this.request<RegistryEnvelope<'same_as'>>('POST', '/api/registry/sameas', { json: data });
    return body.same_as ?? null;
  }

  async getSameAs(entityId: string): Promise<VitalGraphResponse> {
    validateRequired({ entity_id: entityId });
    return this.request('GET', '/api/registry/sameas/list', {
      params: { entity_id: entityId },
    });
  }

  async retractSameAs(sameAsId: number, data: Record<string, unknown>): Promise<RegistryRecord | null> {
    const body = await this.request<RegistryEnvelope<'same_as'>>('PUT', '/api/registry/sameas/retract', {
      params: { same_as_id: sameAsId },
      json: data,
    });
    return body.same_as ?? null;
  }

  async resolveEntity(entityId: string): Promise<RegistryRecord | null> {
    validateRequired({ entity_id: entityId });
    const body = await this.request<RegistryEnvelope<'entity'>>('GET', '/api/registry/sameas/resolve', {
      params: { entity_id: entityId },
    });
    return body.entity ?? null;
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
  // Unified metadata management
  //   kind ∈ entity-types | categories | relationship-types | location-types
  //          | identifier-types | alias-types
  // ------------------------------------------------------------------

  /** List a metadata vocabulary. Active-only and count-free by default (dropdowns). */
  async listMetadata(
    kind: string,
    opts: { includeInactive?: boolean; includeUsage?: boolean; q?: string } = {},
  ): Promise<RegistryRecord[]> {
    const body = await this.request<VitalGraphResponse & { items?: RegistryRecord[] }>(
      'GET', `/api/registry/metadata/${kind}`, {
        params: {
          include_inactive: opts.includeInactive || undefined,
          include_usage: opts.includeUsage || undefined,
          q: opts.q,
        },
      });
    return body.items ?? [];
  }

  async getMetadata(kind: string, key: string): Promise<VitalGraphResponse> {
    validateRequired({ key });
    return this.request('GET', `/api/registry/metadata/${kind}/get`, { params: { key } });
  }

  async createMetadata(kind: string, data: Record<string, unknown>): Promise<VitalGraphResponse> {
    return this.request('POST', `/api/registry/metadata/${kind}`, { json: data });
  }

  async updateMetadata(kind: string, key: string, data: Record<string, unknown>): Promise<VitalGraphResponse> {
    validateRequired({ key });
    return this.request('PUT', `/api/registry/metadata/${kind}/update`, {
      params: { key }, json: data,
    });
  }

  async deleteMetadata(kind: string, key: string): Promise<VitalGraphResponse> {
    validateRequired({ key });
    return this.request('DELETE', `/api/registry/metadata/${kind}/delete`, { params: { key } });
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

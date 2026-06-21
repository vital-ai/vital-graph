// Core client
export { VitalGraphClient } from './VitalGraphClient.js';
export { ClientConfig, type VitalGraphClientOptions } from './config/ClientConfig.js';

// Factory
export { createClient } from './createClient.js';

// Errors
export { VitalGraphClientError } from './utils/errors.js';

// Utilities
export { validateRequired, buildQueryParams } from './utils/params.js';
export { deserializeGraphObjects, extractPagination, isJsonQuadsResponse } from './utils/vitalsigns.js';

// Response types
export type * from './response/types.js';
export { buildSuccessResponse, buildErrorResponse } from './response/types.js';

// Endpoint classes (for advanced usage / type narrowing)
export { BaseEndpoint } from './endpoint/BaseEndpoint.js';
export { SpacesEndpoint } from './endpoint/SpacesEndpoint.js';
export { GraphsEndpoint } from './endpoint/GraphsEndpoint.js';
export { ObjectsEndpoint } from './endpoint/ObjectsEndpoint.js';
export { KGTypesEndpoint } from './endpoint/KGTypesEndpoint.js';
export { KGEntitiesEndpoint, type ListKGEntitiesOptions } from './endpoint/KGEntitiesEndpoint.js';
export { KGFramesEndpoint } from './endpoint/KGFramesEndpoint.js';
export { KGRelationsEndpoint } from './endpoint/KGRelationsEndpoint.js';
export { KGQueriesEndpoint } from './endpoint/KGQueriesEndpoint.js';
export { KGDocumentsEndpoint } from './endpoint/KGDocumentsEndpoint.js';
export { UsersEndpoint } from './endpoint/UsersEndpoint.js';
export { ApiKeysEndpoint } from './endpoint/ApiKeysEndpoint.js';
export { FilesEndpoint } from './endpoint/FilesEndpoint.js';
export { SparqlEndpoint } from './endpoint/SparqlEndpoint.js';
export { TriplesEndpoint } from './endpoint/TriplesEndpoint.js';
export { ImportEndpoint } from './endpoint/ImportEndpoint.js';
export { ExportEndpoint } from './endpoint/ExportEndpoint.js';
export { MetricsEndpoint } from './endpoint/MetricsEndpoint.js';
export { AdminEndpoint } from './endpoint/AdminEndpoint.js';
export { ProcessEndpoint } from './endpoint/ProcessEndpoint.js';
export { VectorMappingsEndpoint } from './endpoint/VectorMappingsEndpoint.js';
export { FuzzyMappingsEndpoint } from './endpoint/FuzzyMappingsEndpoint.js';
export type { FuzzyMapping, FuzzyMappingProperty, FuzzyMappingResponse, FuzzyMappingsListResponse } from './endpoint/FuzzyMappingsEndpoint.js';
export { VectorIndexesEndpoint } from './endpoint/VectorIndexesEndpoint.js';
export { SearchMappingsEndpoint } from './endpoint/SearchMappingsEndpoint.js';
export type {
  SearchMapping, SearchMappingProperty,
  SearchMappingResponse, SearchMappingsListResponse,
} from './endpoint/SearchMappingsEndpoint.js';
export { FtsIndexesEndpoint } from './endpoint/FtsIndexesEndpoint.js';
export type {
  FtsIndex, FtsIndexResponse, FtsIndexesListResponse,
  FtsIndexStatsResponse, PopulateFtsResponse,
} from './endpoint/FtsIndexesEndpoint.js';
export { GeoConfigEndpoint } from './endpoint/GeoConfigEndpoint.js';
export { GeoPointsEndpoint, type SearchNearbyOptions } from './endpoint/GeoPointsEndpoint.js';
export { AgentRegistryEndpoint, type SearchAgentsOptions } from './endpoint/AgentRegistryEndpoint.js';
export {
  EntityRegistryEndpoint,
  type SearchEntitiesOptions,
  type SearchEntityOptions,
  type SearchLocationOptions,
  type FindSimilarOptions,
} from './endpoint/EntityRegistryEndpoint.js';
export { OntologyEndpoint, type OntologyProperty, type OntologyPropertiesResponse, type OntologyClassesResponse } from './endpoint/OntologyEndpoint.js';

import type { VitalSignsObject } from '@vital-ai/vital-model-utils';

// ============================================================================
// Base Response
// ============================================================================

export interface VitalGraphResponse {
  error_code: number;
  error_message?: string;
  status_code: number;
  message?: string;
  metadata: Record<string, unknown>;
}

// ============================================================================
// GraphObject Responses
// ============================================================================

export interface GraphObjectResponse extends VitalGraphResponse {
  objects?: VitalSignsObject[];
}

export interface PaginatedGraphObjectResponse extends GraphObjectResponse {
  total_count: number;
  page_size: number;
  offset: number;
  has_more: boolean;
  entity_type_uri?: string;
  search?: string;
}

// ============================================================================
// Entity / Frame Graph Containers
// ============================================================================

export interface EntityGraph {
  entity_uri: string;
  objects: VitalSignsObject[];
}

export interface FrameGraph {
  frame_uri: string;
  objects: VitalSignsObject[];
}

// ============================================================================
// Entity Responses
// ============================================================================

export interface EntityResponse extends GraphObjectResponse {}

export interface EntityGraphResponse extends VitalGraphResponse {
  objects?: EntityGraph;
  space_id?: string;
  graph_id?: string;
  requested_uri?: string;
  requested_reference_id?: string;
}

export interface MultiEntityGraphResponse extends VitalGraphResponse {
  graph_list?: EntityGraph[];
  space_id?: string;
  graph_id?: string;
  requested_uris?: string[];
  requested_reference_ids?: string[];
}

export interface CreateEntityResponse extends VitalGraphResponse {
  created_count: number;
  created_uris: string[];
}

export interface UpdateEntityResponse extends VitalGraphResponse {
  updated_uri?: string;
}

// ============================================================================
// Frame Responses
// ============================================================================

export interface FrameResponse extends GraphObjectResponse {}

export interface FrameGraphResponse extends VitalGraphResponse {
  frame_graph?: FrameGraph;
  space_id?: string;
  graph_id?: string;
  entity_uri?: string;
  parent_frame_uri?: string;
  requested_frame_uri?: string;
}

export interface MultiFrameGraphResponse extends VitalGraphResponse {
  frame_graph_list?: FrameGraph[];
  space_id?: string;
  graph_id?: string;
  entity_uri?: string;
  requested_frame_uris?: string[];
}

// ============================================================================
// Generic CRUD Responses
// ============================================================================

export interface DeleteResponse extends VitalGraphResponse {
  deleted_count: number;
  deleted_uris: string[];
  space_id?: string;
  graph_id?: string;
  requested_uris?: string[];
}

export interface QueryResponse extends VitalGraphResponse {
  objects?: VitalSignsObject[];
  query_info: Record<string, unknown>;
  space_id?: string;
  graph_id?: string;
  query_criteria?: Record<string, unknown>;
}

// ============================================================================
// Spaces Responses
// ============================================================================

export interface SpaceResponse extends VitalGraphResponse {
  space?: Record<string, unknown>;
}

export interface SpaceInfoResponse extends VitalGraphResponse {
  space?: Record<string, unknown>;
  statistics?: Record<string, unknown>;
  quad_dump?: string[];
}

export interface SpacesListResponse extends VitalGraphResponse {
  spaces: Record<string, unknown>[];
  total: number;
}

export interface SpaceCreateResponse extends VitalGraphResponse {
  space?: Record<string, unknown>;
  created_count: number;
}

export interface SpaceUpdateResponse extends VitalGraphResponse {
  space?: Record<string, unknown>;
  updated_count: number;
}

export interface SpaceDeleteResponse extends VitalGraphResponse {
  deleted_count: number;
  space_id?: string;
}

export interface SpaceAnalyticsResponse extends VitalGraphResponse {
  space?: Record<string, unknown>;
  analytics?: Record<string, unknown>;
}

// ============================================================================
// Graphs Responses
// ============================================================================

export interface GraphResponse extends VitalGraphResponse {
  graph?: Record<string, unknown>;
}

export interface GraphsListResponse extends VitalGraphResponse {
  graphs: Record<string, unknown>[];
  total: number;
}

export interface GraphCreateResponse extends VitalGraphResponse {
  graph_uri?: string;
  created: boolean;
}

export interface GraphDeleteResponse extends VitalGraphResponse {
  graph_uri?: string;
  deleted: boolean;
}

export interface GraphClearResponse extends VitalGraphResponse {
  graph_uri?: string;
  cleared: boolean;
  triples_removed: number;
}

export interface GraphCountsResponse extends VitalGraphResponse {
  entity_count: number;
  frame_count: number;
  relation_count: number;
}

// ============================================================================
// KGTypes Responses
// ============================================================================

export interface KGTypeResponse extends VitalGraphResponse {
  type?: Record<string, unknown>;
}

export interface KGTypesListResponse extends VitalGraphResponse {
  types: Record<string, unknown>[];
  count: number;
  page_size?: number;
  offset?: number;
}

export interface KGTypeCreateResponse extends VitalGraphResponse {
  created: boolean;
  created_count: number;
  created_uris: string[];
}

export interface KGTypeUpdateResponse extends VitalGraphResponse {
  updated: boolean;
  updated_count: number;
  updated_uris: string[];
}

export interface KGTypeDeleteResponse extends VitalGraphResponse {
  deleted: boolean;
  deleted_count: number;
  deleted_uris: string[];
}

// ============================================================================
// Objects Responses
// ============================================================================

export interface ObjectResponse extends VitalGraphResponse {
  object?: Record<string, unknown>;
}

export interface ObjectsListResponse extends VitalGraphResponse {
  objects: Record<string, unknown>[];
  count: number;
  page_size?: number;
  offset?: number;
}

export interface ObjectCreateResponse extends VitalGraphResponse {
  created: boolean;
  created_count: number;
  created_uris: string[];
}

export interface ObjectUpdateResponse extends VitalGraphResponse {
  updated: boolean;
  updated_count: number;
  updated_uris: string[];
}

export interface ObjectDeleteResponse extends VitalGraphResponse {
  deleted: boolean;
  deleted_count: number;
  deleted_uris: string[];
}

// ============================================================================
// Files Responses
// ============================================================================

export interface FileResponse extends GraphObjectResponse {
  file_uri?: string;
  file_node?: VitalSignsObject;
  space_id?: string;
  graph_id?: string;
  requested_uri?: string;
}

export interface FilesListResponse extends PaginatedGraphObjectResponse {
  space_id?: string;
  graph_id?: string;
  file_filter?: string;
}

export interface FileCreateResponse extends VitalGraphResponse {
  created_uris: string[];
  created_count: number;
  objects?: VitalSignsObject[];
  space_id?: string;
  graph_id?: string;
}

export interface FileUpdateResponse extends VitalGraphResponse {
  updated_uris: string[];
  updated_count: number;
  objects?: VitalSignsObject[];
  space_id?: string;
  graph_id?: string;
}

export interface FileDeleteResponse extends VitalGraphResponse {
  deleted_uris: string[];
  deleted_count: number;
  space_id?: string;
  graph_id?: string;
  requested_uris?: string[];
}

export interface FileUploadResponse extends VitalGraphResponse {
  file_uri: string;
  size: number;
  content_type?: string;
  filename?: string;
  space_id?: string;
  graph_id?: string;
}

export interface FileDownloadResponse extends VitalGraphResponse {
  file_uri: string;
  size: number;
  content_type?: string;
  destination: string;
  space_id?: string;
  graph_id?: string;
}

// ============================================================================
// KGDocuments Responses
// ============================================================================

export interface KGDocumentResponse extends VitalGraphResponse {
  document?: Record<string, unknown>;
}

export interface KGDocumentsListResponse extends VitalGraphResponse {
  documents: Record<string, unknown>[];
  count: number;
  page_size?: number;
  offset?: number;
}

export interface KGDocumentCreateResponse extends VitalGraphResponse {
  created: boolean;
  created_count: number;
  created_uris: string[];
}

export interface KGDocumentUpdateResponse extends VitalGraphResponse {
  updated: boolean;
  updated_count: number;
  updated_uris: string[];
}

export interface KGDocumentDeleteResponse extends VitalGraphResponse {
  deleted: boolean;
  deleted_count: number;
  deleted_uris: string[];
}

export interface KGDocumentSegmentsResponse extends VitalGraphResponse {
  segments: Record<string, unknown>[];
  count: number;
  parent_uri?: string;
}

// ============================================================================
// Users Responses
// ============================================================================

export interface UserResponse extends VitalGraphResponse {
  user?: Record<string, unknown>;
}

export interface UsersListResponse extends VitalGraphResponse {
  users: Record<string, unknown>[];
  total: number;
}

export interface UserCreateResponse extends VitalGraphResponse {
  user?: Record<string, unknown>;
  created_count: number;
}

export interface UserUpdateResponse extends VitalGraphResponse {
  user?: Record<string, unknown>;
  updated_count: number;
}

export interface UserDeleteResponse extends VitalGraphResponse {
  deleted_count: number;
  user_id?: string;
}

export interface PasswordChangeResponse extends VitalGraphResponse {
  changed: boolean;
}

// ============================================================================
// API Keys Responses
// ============================================================================

export interface ApiKeyInfo extends VitalGraphResponse {
  key_id?: string;
  name?: string;
  prefix?: string;
  created_at?: string;
  last_used_at?: string;
}

export interface ApiKeyListResponse extends VitalGraphResponse {
  keys: ApiKeyInfo[];
  total: number;
}

export interface ApiKeyCreateResponse extends VitalGraphResponse {
  key_id: string;
  api_key: string;
  name?: string;
  prefix: string;
}

export interface ApiKeyDeleteResponse extends VitalGraphResponse {
  deleted: boolean;
  key_id?: string;
}

// ============================================================================
// SPARQL Responses
// ============================================================================

export interface SPARQLQueryResponse extends VitalGraphResponse {
  results?: Record<string, unknown>;
  bindings?: Record<string, unknown>[];
}

export interface SPARQLUpdateResponse extends VitalGraphResponse {
  affected_count?: number;
}

export interface SPARQLInsertResponse extends VitalGraphResponse {
  inserted_count?: number;
}

export interface SPARQLDeleteResponse extends VitalGraphResponse {
  deleted_count?: number;
}

// ============================================================================
// Triples Responses
// ============================================================================

export interface TripleListResponse extends VitalGraphResponse {
  triples: Record<string, unknown>[];
  total: number;
}

export interface TripleOperationResponse extends VitalGraphResponse {
  affected_count: number;
}

// ============================================================================
// Import/Export Responses
// ============================================================================

export interface ImportJobResponse extends VitalGraphResponse {
  job?: Record<string, unknown>;
}

export interface ImportJobsResponse extends VitalGraphResponse {
  jobs: Record<string, unknown>[];
  total: number;
}

export interface ImportCreateResponse extends VitalGraphResponse {
  job_id: string;
}

export interface ImportDeleteResponse extends VitalGraphResponse {
  deleted: boolean;
}

export interface ImportExecuteResponse extends VitalGraphResponse {
  job_id: string;
  status: string;
}

export interface ImportStatusResponse extends VitalGraphResponse {
  job_id: string;
  status: string;
  progress?: number;
}

export interface ImportLogResponse extends VitalGraphResponse {
  job_id: string;
  log_entries: string[];
}

export interface ImportUploadResponse extends VitalGraphResponse {
  job_id: string;
  file_name: string;
  size: number;
}

export interface ExportJobResponse extends VitalGraphResponse {
  job?: Record<string, unknown>;
}

export interface ExportJobsResponse extends VitalGraphResponse {
  jobs: Record<string, unknown>[];
  total: number;
}

export interface ExportCreateResponse extends VitalGraphResponse {
  job_id: string;
}

export interface ExportDeleteResponse extends VitalGraphResponse {
  deleted: boolean;
}

export interface ExportExecuteResponse extends VitalGraphResponse {
  job_id: string;
  status: string;
}

export interface ExportStatusResponse extends VitalGraphResponse {
  job_id: string;
  status: string;
  progress?: number;
}

// ============================================================================
// Metrics Responses
// ============================================================================

export interface MetricsResponse extends VitalGraphResponse {
  metrics: Record<string, unknown>;
}

export interface SlowQueriesResponse extends VitalGraphResponse {
  queries: Record<string, unknown>[];
}

// ============================================================================
// Vector / Geo Responses
// ============================================================================

export interface VectorMappingResponse extends VitalGraphResponse {
  mapping?: Record<string, unknown>;
}

export interface VectorMappingsListResponse extends VitalGraphResponse {
  mappings: Record<string, unknown>[];
  total: number;
}

export interface VectorIndexResponse extends VitalGraphResponse {
  index?: Record<string, unknown>;
}

export interface VectorIndexesListResponse extends VitalGraphResponse {
  indexes: Record<string, unknown>[];
  total: number;
}

export interface GeoConfigResponse extends VitalGraphResponse {
  config?: Record<string, unknown>;
}

export interface GeoPointsListResponse extends VitalGraphResponse {
  points: Record<string, unknown>[];
  total: number;
}

// ============================================================================
// Generic success/error builders
// ============================================================================

export function buildSuccessResponse<T extends VitalGraphResponse>(
  partial: Omit<T, 'error_code' | 'status_code' | 'metadata'> & Partial<Pick<T, 'metadata'>>,
): T {
  return {
    error_code: 0,
    status_code: 200,
    metadata: {},
    ...partial,
  } as T;
}

export function buildErrorResponse<T extends VitalGraphResponse>(
  errorMessage: string,
  statusCode = 500,
): T {
  return {
    error_code: 1,
    error_message: errorMessage,
    status_code: statusCode,
    metadata: {},
  } as T;
}

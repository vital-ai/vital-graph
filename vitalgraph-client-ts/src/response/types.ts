import type { VitalSignsObject } from '@vital-ai/vital-model-utils';
import { VitalGraphClientError } from '../utils/errors.js';

// ============================================================================
// Result-status contract
// ============================================================================

/**
 * Machine-readable domain outcome discriminator returned by the server (mirror of
 * the server-side OperationStatus enum). HTTP is 200 for every domain outcome, so
 * success/failure is read from `status` (or `success`) in the body — never the HTTP
 * status code. A non-200 means a server-level internal error.
 */
export enum OperationStatus {
  OK = 'ok',
  CREATED = 'created',
  UPDATED = 'updated',
  UPSERTED = 'upserted',
  DELETED = 'deleted',
  FOUND = 'found',
  EMPTY = 'empty',
  NO_OP = 'no_op',
  ALREADY_EXISTS = 'already_exists',
  NOT_FOUND = 'not_found',
  PARTIAL = 'partial',
  INVALID_REQUEST = 'invalid_request',
  STORE_FAILED = 'store_failed',
  ERROR = 'error',
}

/** OperationStatus values that mean "the expected thing happened". */
export const SUCCESS_STATUSES: ReadonlySet<string> = new Set<string>([
  OperationStatus.OK,
  OperationStatus.CREATED,
  OperationStatus.UPDATED,
  OperationStatus.UPSERTED,
  OperationStatus.DELETED,
  OperationStatus.FOUND,
  OperationStatus.EMPTY,
  OperationStatus.NO_OP,
]);

// ============================================================================
// Base Response
// ============================================================================

export interface VitalGraphResponse {
  error_code: number;
  error_message?: string;
  status_code: number;
  message?: string;
  /** Server domain outcome (OperationStatus value); authoritative for success. */
  status?: string;
  /** Raw server success flag (derived from status server-side), when present. */
  success?: boolean;
  metadata: Record<string, unknown>;
}

/**
 * Whether the expected operation happened. Reads the domain `status` when present
 * (an HTTP 200 with status=already_exists is NOT a success); otherwise falls back
 * to `success`, then the legacy `error_code`.
 */
export function isSuccess(resp: VitalGraphResponse): boolean {
  if (resp.status != null) return SUCCESS_STATUSES.has(resp.status);
  if (resp.success != null) return resp.success;
  return resp.error_code === 0;
}

/** Inverse of isSuccess. */
export function isError(resp: VitalGraphResponse): boolean {
  return !isSuccess(resp);
}

/** Throw VitalGraphClientError if the response is a non-success domain outcome. */
export function assertSuccess(resp: VitalGraphResponse): void {
  if (isError(resp)) {
    const detail = resp.error_message ?? resp.message ?? resp.status ?? 'unknown error';
    const code = resp.status ?? resp.error_code;
    throw new VitalGraphClientError(`Error ${code}: ${detail}`, resp.status_code);
  }
}

// ============================================================================
// GraphObject Responses
// ============================================================================

export interface GraphObjectResponse extends VitalGraphResponse {
  objects?: VitalSignsObject[];
}

/**
 * Pagination as the server actually sends it.
 *
 * `has_more` is THREE-STATE, and the type says so:
 *
 *   true       there is another page
 *   false      this is the last page
 *   null/absent the route has not been taught to answer — NOT "no"
 *
 * It was declared `has_more: boolean` here, which was wrong in both directions.
 * Most routes omit the key entirely, so a caller under `strictNullChecks` was
 * told a value was always present when it usually was not; and the ones that do
 * send it may send `null`. Reading a missing value as `false` is the defect
 * fixed across the Python client on 2026-08-16 — the field was always present,
 * always False, and never computed, so "is there a next page?" got a confident
 * No on every list call.
 *
 * DO NOT DERIVE IT from `(offset + page_size) < total_count`. `page_size` does
 * not mean the same thing on every route: get-by-URI routes set it to the
 * number of identifiers requested and `total_count` to the number of objects
 * across them, so the formula reports a next page for a route that has none.
 * The server is the only party that knows.
 */
export interface PaginationFields {
  total_count: number;
  page_size: number;
  offset: number;
  has_more?: boolean | null;
}

export interface PaginatedGraphObjectResponse extends GraphObjectResponse, PaginationFields {
  entity_type_uri?: string;
  search?: string;
  /**
   * Frame URI → slot count, present only when requested via
   * `includeSlotCounts` on KGEntitiesEndpoint.getFrames.
   *
   * A frame with zero slots is OMITTED — read a missing key as 0, not as
   * unknown. Lets a caller decide whether a frame needs slot pagination
   * without fetching its slots.
   */
  slot_counts?: Record<string, number>;
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

/**
 * Paged on `list`, unpaged on the get-by-URI helpers.
 *
 * The pagination fields were absent here until 2026-08-16 even though the
 * server sent them, so a typed caller of `KGEntitiesEndpoint.list` with
 * `includeEntityGraph: true` could not see the total without casting — the
 * Python client had the same gap and silently dropped the value instead.
 *
 * They are optional because the get-by-URI methods share this type and have
 * nothing to page: absent means "not a paged call", not "zero".
 */
export interface MultiEntityGraphResponse extends VitalGraphResponse, Partial<PaginationFields> {
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

/** Paged on `listWithGraphs`, unpaged on the get-by-URI helpers. See above. */
export interface MultiFrameGraphResponse extends VitalGraphResponse, Partial<PaginationFields> {
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
  /** Server field name. `total` retained for backward compatibility. */
  total_count?: number;
  total?: number;
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

export interface SpaceSummary {
  space: string;
  space_name?: string | null;
  graph_count: number;
  triple_count: number;
  /**
   * True when `triple_count` is a catalog ESTIMATE rather than an exact count.
   * Accurate to well under 1% and vastly cheaper — do not compare it for
   * equality.
   */
  estimated: boolean;
}

/**
 * Every space's totals in ONE request.
 *
 * Replaces a per-space fan-out: the dashboard called `list_graphs` once per
 * space, which on 67 spaces was ~20 s of concurrent multi-second counts to
 * render four numbers.
 */
export interface SpacesSummaryResponse extends VitalGraphResponse {
  spaces: SpaceSummary[];
  total_spaces: number;
  total_graphs: number;
  total_triples: number;
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
  /**
   * Items on THIS page. `total_count` is the size of the whole result set.
   *
   * These three interfaces declared only `count` and the Python client fed it
   * the server's TOTAL, so `count` reported the whole corpus for a 25-row page.
   * KGTypeSearchResponse already documented both correctly and is the shape the
   * others are aligned to (2026-08-16).
   */
  count: number;
  total_count?: number;
  page_size?: number;
  offset?: number;
  has_more?: boolean | null;
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

export interface KGTypeRelationshipEdge {
  uri: string;
  edgeType: string;
  sourceURI: string;
  destinationURI: string;
  direction: 'outgoing' | 'incoming';
}

export interface KGTypeRelationshipType {
  uri: string;
  name: string;
  vitaltype: string;
}

export interface KGTypeRelationshipsResponse extends VitalGraphResponse {
  source_type: KGTypeRelationshipType;
  edges: KGTypeRelationshipEdge[];
  connected_types: KGTypeRelationshipType[];
}

export interface KGTypeRelationshipCreateResponse extends VitalGraphResponse {
  edge_uri: string;
  edge_type: string;
  source_uri: string;
  destination_uri: string;
}

export interface KGTypeRelationshipDeleteResponse extends VitalGraphResponse {
  deleted: boolean;
  edge_uri: string;
}

export interface KGTypeDocumentationResponse extends VitalGraphResponse {
  type_uri: string;
  content?: string;
  document_uri?: string;
  has_documentation: boolean;
}

export interface KGTypeDocumentationUpdateResponse extends VitalGraphResponse {
  type_uri: string;
  document_uri: string;
  created: boolean;
}

export interface KGTypeDocumentationDeleteResponse extends VitalGraphResponse {
  type_uri: string;
  deleted: boolean;
}

export interface KGTypeSearchResponse extends VitalGraphResponse {
  types: Record<string, unknown>[];
  count: number;
  total_count: number;
  page_size: number;
  offset: number;
  search_mode: 'keyword' | 'fts' | 'vector' | 'hybrid';
  query: string;
}

// ============================================================================
// Objects Responses
// ============================================================================

export interface ObjectResponse extends VitalGraphResponse {
  object?: Record<string, unknown>;
}

export interface ObjectsListResponse extends VitalGraphResponse {
  objects: Record<string, unknown>[];
  /**
   * Items on THIS page. `total_count` is the size of the whole result set.
   *
   * These three interfaces declared only `count` and the Python client fed it
   * the server's TOTAL, so `count` reported the whole corpus for a 25-row page.
   * KGTypeSearchResponse already documented both correctly and is the shape the
   * others are aligned to (2026-08-16).
   */
  count: number;
  total_count?: number;
  page_size?: number;
  offset?: number;
  has_more?: boolean | null;
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
  /**
   * Items on THIS page. `total_count` is the size of the whole result set.
   *
   * These three interfaces declared only `count` and the Python client fed it
   * the server's TOTAL, so `count` reported the whole corpus for a 25-row page.
   * KGTypeSearchResponse already documented both correctly and is the shape the
   * others are aligned to (2026-08-16).
   */
  count: number;
  total_count?: number;
  page_size?: number;
  offset?: number;
  has_more?: boolean | null;
}

export interface KGDocumentCreateResponse extends VitalGraphResponse {
  created: boolean;
  created_count: number;
  created_uris: string[];
}

export interface KGDocumentUploadResponse extends VitalGraphResponse {
  /** URI of the created KGDocument. */
  document_uri: string | null;
  /** URI of the FileNode holding the original bytes, null when not retained. */
  file_node_uri: string | null;
  /** Detected source extension, e.g. '.pdf'. */
  source_format: string | null;
  /** True when the content was converted to Markdown rather than passed through. */
  converted: boolean;
  /** Markdown headings in the stored content; >=2 selects the heading-based split. */
  heading_count: number;
  /** Characters of Markdown stored. */
  content_length: number;
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
  /** Unpaged: every segment is returned, so this is both the page and the total. */
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

/**
 * Server-side stage breakdown for one SPARQL query, in milliseconds.
 *
 * Mirrors `SPARQLQueryTiming` in vitalgraph/model/sparql_model.py. Always
 * populated by the sparql_sql backend; absent for backends that do not report
 * stages. Compare `total_ms` against your own wall-clock to separate server
 * cost from transport and deserialization.
 */
export interface SPARQLQueryTiming {
  /** Waiting for a connection from the pool. */
  acquire_ms?: number;
  /** SPARQL→AST compilation by the Jena sidecar. */
  sidecar_ms?: number;
  /** SQL generation from the AST. */
  gen_ms?: number;
  /** SQL execution in PostgreSQL. */
  exec_ms?: number;
  /** Converting result rows to dicts. */
  rows_to_dict_ms?: number;
  /** Building SPARQL JSON bindings from rows. */
  bindings_ms?: number;
  /** Server-side total across the stages above. */
  total_ms?: number;
  rows?: number;
  /** JOIN count in the generated SQL (complexity hint). */
  joins?: number;
  sql_chars?: number;
}

export interface SPARQLQueryResponse extends VitalGraphResponse {
  /** Query result metadata (variables, links) for SELECT queries. */
  head?: Record<string, unknown>;
  /** SELECT results; bindings live at `results.bindings`, not top level. */
  results?: Record<string, unknown>;
  /** Boolean result for ASK queries. */
  boolean?: boolean;
  /** RDF triples for CONSTRUCT/DESCRIBE queries. */
  triples?: Record<string, unknown>[];
  /** Endpoint-measured query time in seconds. */
  query_time?: number;
  /** Server-side stage breakdown; see SPARQLQueryTiming. */
  timing?: SPARQLQueryTiming;
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

/**
 * Build a client response from a server body that follows the result-status
 * contract (success / status / message in the body). Derives `error_code` from the
 * domain outcome so isSuccess/assertSuccess reflect the DOMAIN result, not the HTTP
 * code (which is 200 for every domain outcome).
 */
export function buildResponseFromServer<T extends VitalGraphResponse>(
  body: Record<string, unknown>,
  statusCode = 200,
  extra: Partial<T> = {},
): T {
  const status = body['status'] as string | undefined;
  const success = body['success'] as boolean | undefined;
  const message = body['message'] as string | undefined;

  let succeeded: boolean;
  if (status != null) succeeded = SUCCESS_STATUSES.has(status);
  else if (success != null) succeeded = success;
  else succeeded = true;

  return {
    error_code: succeeded ? 0 : 1,
    error_message: succeeded ? undefined : message,
    status_code: statusCode,
    message,
    status,
    success,
    metadata: {},
    ...extra,
  } as T;
}

/**
 * TypeScript types for Vector & Geo API endpoints
 */

// ---------------------------------------------------------------------------
// Vectorization providers
// ---------------------------------------------------------------------------

/**
 * The providers the server will accept when creating a vector index.
 *
 * These must match PROVIDER_REGISTRY in
 * vitalgraph/vectorization/registry.py. The server validates `provider` on
 * create and rejects anything else with INVALID_REQUEST, so a stale entry here
 * surfaces as a failed create.
 *
 * `dimensions` is the model's native output width and is not negotiable — the
 * index must be created at that width or search returns nothing useful.
 */
export interface VectorProviderOption {
  value: string;
  label: string;
  /** Compact form for table cells and badges — the raw values run to 37 chars. */
  short: string;
  dimensions: number;
  note: string;
}

export const VECTOR_PROVIDERS: VectorProviderOption[] = [
  {
    value: 'vitalsigns_onnx',
    label: 'VitalSigns ONNX — paraphrase-MiniLM-L3-v2',
    short: 'VitalSigns ONNX',
    dimensions: 384,
    note: 'Local, bundled, English. No API key or network needed.',
  },
  {
    value: 'paraphrase_multilingual_minilm_l12_v2',
    label: 'Multilingual — paraphrase-multilingual-MiniLM-L12-v2',
    short: 'Multilingual MiniLM',
    dimensions: 384,
    note: 'Local, baked into the server image. Multilingual; matches Weaviate.',
  },
  {
    value: 'openai',
    label: 'OpenAI — text-embedding-3-small',
    short: 'OpenAI',
    dimensions: 1536,
    note: 'Remote API. Requires a server-side key; billed per vectorization.',
  },
];

export const DEFAULT_VECTOR_PROVIDER = 'vitalsigns_onnx';

/** Native width for a provider, falling back to the 384 default. */
export function providerDimensions(provider: string): number {
  return (
    VECTOR_PROVIDERS.find((p) => p.value === provider)?.dimensions ?? 384
  );
}

/**
 * Compact display name for a provider.
 *
 * Falls back to the raw value so indexes created with a legacy or unknown
 * provider still render truthfully rather than showing a blank badge.
 */
export function providerShortLabel(provider: string): string {
  return (
    VECTOR_PROVIDERS.find((p) => p.value === provider)?.short ?? provider
  );
}

// ---------------------------------------------------------------------------
// Vector Indexes
// ---------------------------------------------------------------------------

export interface VectorIndex {
  index_name: string;
  provider: string;
  dimensions: number;
  model_name: string | null;
  distance_metric: string;
  description: string | null;
  provider_config: Record<string, unknown>;
  created_time: string;
  row_count?: number;
}

export interface VectorIndexListResponse {
  indexes: VectorIndex[];
}

export interface CreateVectorIndexRequest {
  index_name: string;
  provider: string;
  dimensions: number;
  model_name?: string;
  distance_metric?: string;
  description?: string;
  provider_config?: Record<string, unknown>;
}

export interface ReindexRequest {
  graph_uri?: string;
  mapping_type?: string;
  type_uri?: string;
  batch_size?: number;
}

export interface ReindexResponse {
  message: string;
  index_name: string;
}

// ---------------------------------------------------------------------------
// Geo Config
// ---------------------------------------------------------------------------

export interface GeoConfig {
  config_id: number;
  enabled: boolean;
  auto_sync: boolean;
  lat_predicates: string[];
  lon_predicates: string[];
  updated_time: string | null;
}

// ---------------------------------------------------------------------------
// Geo Points
// ---------------------------------------------------------------------------

export interface GeoPoint {
  subject_uri: string;
  subject_uuid: string;
  latitude: number;
  longitude: number;
  context_uuid: string;
  distance_m: number | null;
  updated_time: string | null;
}

export interface GeoPointsResponse {
  success: boolean;
  status: string;
  message: string;
  points: GeoPoint[];
  total_count: number;
  page_size: number;
  offset: number;
}

export interface GeoPointsQuery {
  near_lat?: number;
  near_lon?: number;
  radius_km?: number;
  graph_uri?: string;
  limit?: number;
  offset?: number;
}

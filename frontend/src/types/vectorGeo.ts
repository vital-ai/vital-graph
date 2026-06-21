/**
 * TypeScript types for Vector & Geo API endpoints
 */

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
  points: GeoPoint[];
  total_count: number;
  limit: number;
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

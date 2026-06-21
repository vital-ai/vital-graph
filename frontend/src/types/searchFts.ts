/**
 * TypeScript types for Search Mappings & FTS Indexes API endpoints
 */

// ---------------------------------------------------------------------------
// Search Mappings
// ---------------------------------------------------------------------------

export type SearchMappingType = 'kgentity' | 'kgdocument' | 'kgframe' | 'kgslot';
export type SearchSourceType = 'type_description' | 'properties' | 'properties_type' | 'default' | 'slots';
export type SearchPropertyRole = 'include' | 'exclude';

export interface SearchMappingProperty {
  property_id: number;
  mapping_id: number;
  property_uri: string;
  property_role: SearchPropertyRole;
  ordinal: number;
}

export type IndexType = 'vector' | 'fts';

export interface SearchMappingIndex {
  id: number;
  mapping_id: number;
  index_type: IndexType;
  index_name: string;
  created_time?: string | null;
}

export interface SearchMapping {
  mapping_id: number;
  mapping_type: SearchMappingType;
  type_uri: string | null;
  index_name: string;
  enabled: boolean;
  source_type: SearchSourceType;
  separator: string;
  include_pred_name: boolean;
  created_time: string | null;
  properties: SearchMappingProperty[];
  indexes: SearchMappingIndex[];
}

export interface SearchMappingsListResponse {
  mappings: SearchMapping[];
  total_count: number;
}

export interface CreateSearchMappingRequest {
  index_name: string;
  mapping_type: SearchMappingType;
  type_uri?: string;
  enabled?: boolean;
  source_type?: SearchSourceType;
  separator?: string;
  include_pred_name?: boolean;
}

export interface UpdateSearchMappingRequest {
  enabled?: boolean;
  source_type?: SearchSourceType;
  separator?: string;
  include_pred_name?: boolean;
}

// ---------------------------------------------------------------------------
// FTS Indexes
// ---------------------------------------------------------------------------

export interface FtsIndex {
  index_id: number;
  index_name: string;
  languages: string[];
  created_time: string | null;
  row_count?: number;
}

export interface FtsIndexesListResponse {
  indexes: FtsIndex[];
  total_count: number;
}

export interface FtsIndexStats {
  index_name: string;
  row_count: number;
  distinct_entity_count: number;
  has_tsv_count: number;
}

export interface CreateFtsIndexRequest {
  index_name: string;
  languages?: string[];
}

export interface PopulateFtsRequest {
  graph_uri: string;
  mapping_type?: string;
  type_uri?: string;
  batch_size?: number;
}

export interface PopulateFtsResponse {
  message: string;
  index_name: string;
  rows_populated: number;
  elapsed_seconds: number;
  errors: string[];
}

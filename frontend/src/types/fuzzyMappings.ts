/**
 * TypeScript types for Fuzzy Mapping API endpoints
 */

// ---------------------------------------------------------------------------
// Fuzzy Mappings
// ---------------------------------------------------------------------------

export type FuzzyMappingType = 'kgentity' | 'kgdocument' | 'kgframe' | 'kgslot';
export type FuzzyPropertyRole = 'primary' | 'alias' | 'include';

export interface FuzzyMappingProperty {
  property_id: number;
  mapping_id: number;
  property_uri: string;
  property_role: FuzzyPropertyRole;
  ordinal: number;
}

export interface FuzzyMapping {
  mapping_id: number;
  mapping_type: FuzzyMappingType;
  type_uri: string | null;
  index_name: string;
  enabled: boolean;
  shingle_k: number;
  num_perm: number;
  lsh_threshold: number;
  phonetic_bonus: number;
  created_time: string | null;
  properties: FuzzyMappingProperty[];
}

export interface FuzzyMappingListResponse {
  mappings: FuzzyMapping[];
  total_count: number;
}

export interface CreateFuzzyMappingRequest {
  mapping_type: FuzzyMappingType;
  type_uri?: string;
  index_name: string;
  enabled?: boolean;
  shingle_k?: number;
  num_perm?: number;
  lsh_threshold?: number;
  phonetic_bonus?: number;
}

export interface UpdateFuzzyMappingRequest {
  enabled?: boolean;
  shingle_k?: number;
  num_perm?: number;
  lsh_threshold?: number;
  phonetic_bonus?: number;
}

export interface FuzzyMappingStats {
  mapping_id: number;
  band_count: number;
  entity_count: number;
  phonetic_band_count: number;
}

export interface PopulateResponse {
  success: boolean;
  subjects_processed: number;
  bands_stored: number;
  elapsed_seconds: number;
}

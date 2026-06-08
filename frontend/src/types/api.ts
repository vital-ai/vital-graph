/**
 * API response types for VitalGraph backend
 * 
 * Note: Graph, Space, User, Object, File, Triple types are in their own files.
 * This file contains types that don't fit neatly into a single domain.
 */

// Space API types (extended info from /api/spaces/{id}/info)
export interface SpaceInfo {
  id?: number;
  tenant?: string;
  space: string;
  space_name: string;
  space_description?: string;
  created_time: string;
  updated_time: string;
}

// SPARQL API types
export interface SparqlQueryResponse {
  head?: {
    vars: string[];
  };
  results?: {
    bindings: Record<string, unknown>[];
  };
  boolean?: boolean;
  triples?: Record<string, unknown>[];
  query_time?: number;
  error?: string;
}

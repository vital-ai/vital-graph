/**
 * API response types for VitalGraph backend
 */

// Graph API types
export interface GraphInfo {
  graph_uri: string;
  triple_count: number;
  created_time: string | null;
  updated_time: string | null;
}

export interface GraphOperationResponse {
  success: boolean;
  operation: string;
  graph_uri?: string;
  message?: string;
  operation_time?: number;
  error?: string;
}

// Space API types  
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
    bindings: any[];
  };
  boolean?: boolean;
  triples?: any[];
  query_time?: number;
  error?: string;
}

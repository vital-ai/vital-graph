/**
 * Graph types for VitalGraph frontend
 */

export interface Graph {
  graph_uri: string;
  graph_name?: string;
  triple_count: number;
  created_time?: string | null;
  updated_time?: string | null;
}

/**
 * GraphInfo matches the raw API response shape from /api/graphs/sparql/{spaceId}/graphs
 */
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

/**
 * Triple types for VitalGraph frontend
 */

export interface Triple {
  subject: string;
  predicate: string;
  object: string;
  graph?: string;
  datatype?: string;
  language?: string;
}

export interface TripleListResponse {
  triples: Triple[];
  total_count: number;
  offset: number;
  page_size: number;
}

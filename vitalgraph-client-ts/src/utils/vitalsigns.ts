import type { VitalSignsObject } from '@vital-ai/vital-model-utils';
import { convertGraphObjects } from '@vital-ai/vital-kg-model-ts';

/**
 * Deserialize an array of raw JSON graph objects from the server into typed
 * VitalSignsObject instances using the kgClassRegistry.
 */
export function deserializeGraphObjects(
  rawJsonArray: Record<string, unknown>[],
): VitalSignsObject[] {
  if (!rawJsonArray || rawJsonArray.length === 0) return [];
  return convertGraphObjects(rawJsonArray) as VitalSignsObject[];
}

/**
 * Extract pagination metadata from a JSON Quads response envelope.
 */
export function extractPagination(responseData: Record<string, unknown>): {
  total_count: number;
  page_size: number;
  offset: number;
} {
  return {
    total_count: (responseData.total_count as number) ?? 0,
    page_size: (responseData.page_size as number) ?? 0,
    offset: (responseData.offset as number) ?? 0,
  };
}

/**
 * Check if a parsed JSON response is a JSON Quads envelope (has `results` array
 * of quad objects with s/p/o/g keys).
 */
export function isJsonQuadsResponse(responseData: unknown): boolean {
  if (typeof responseData !== 'object' || responseData === null) return false;
  const data = responseData as Record<string, unknown>;
  if (!('results' in data)) return false;
  const results = data.results;
  if (!Array.isArray(results)) return false;
  if (results.length === 0) return true;
  const first = results[0] as Record<string, unknown>;
  return typeof first === 'object' && first !== null && 's' in first;
}

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
 *
 * Mirrors `extract_pagination_from_json_quads` in the Python client, including
 * the part that is easy to get wrong.
 *
 * `has_more` is passed through and NEVER DERIVED. It has three states:
 *
 *   true         another page exists
 *   false        this is the last page
 *   undefined    the route has not been taught to answer — not "no"
 *
 * Deriving it as `(offset + page_size) < total_count` looks obvious and is
 * wrong: `page_size` does not mean the same thing on every route. Get-by-URI
 * routes set it to the number of identifiers requested and `total_count` to the
 * number of objects across them, so one identifier owning five objects yields
 * `1 < 5` → "there is another page" for a route that has none.
 *
 * Returning `false` for an absent value is the same defect one step earlier: it
 * writes down "no" when the honest answer is "nobody said". That was live in
 * the Python client on every list call until 2026-08-16.
 */
export function extractPagination(responseData: Record<string, unknown>): {
  total_count: number;
  page_size: number;
  offset: number;
  has_more?: boolean | null;
} {
  return {
    total_count: (responseData.total_count as number) ?? 0,
    page_size: (responseData.page_size as number) ?? 0,
    offset: (responseData.offset as number) ?? 0,
    has_more: responseData.has_more as boolean | null | undefined,
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

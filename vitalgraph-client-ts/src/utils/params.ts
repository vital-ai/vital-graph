import { VitalGraphClientError } from './errors.js';

/**
 * Validate that required parameters are provided.
 * Throws VitalGraphClientError if any value is null, undefined, or empty string.
 */
export function validateRequired(params: Record<string, unknown>): void {
  for (const [name, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === '') {
      throw new VitalGraphClientError(`Required parameter '${name}' is missing or empty`);
    }
  }
}

/**
 * Build a query parameters string from key-value pairs, filtering out
 * null/undefined values. Booleans and numbers are converted to strings.
 */
export function buildQueryParams(params: Record<string, unknown>): URLSearchParams {
  const searchParams = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined) {
      searchParams.set(key, String(value));
    }
  }
  return searchParams;
}

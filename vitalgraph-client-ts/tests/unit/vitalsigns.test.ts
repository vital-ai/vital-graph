import { describe, it, expect } from 'vitest';
import { extractPagination, isJsonQuadsResponse } from '../../src/utils/vitalsigns.js';

describe('extractPagination', () => {
  it('should extract all pagination fields', () => {
    const result = extractPagination({ total_count: 100, page_size: 10, offset: 20 });
    expect(result).toEqual({ total_count: 100, page_size: 10, offset: 20 });
  });

  it('should default missing fields to 0', () => {
    const result = extractPagination({});
    expect(result).toEqual({ total_count: 0, page_size: 0, offset: 0 });
  });

  it('should handle partial fields', () => {
    const result = extractPagination({ total_count: 50 });
    expect(result).toEqual({ total_count: 50, page_size: 0, offset: 0 });
  });

  // has_more is three-state and the distinction is the point: `false` means
  // "last page", `undefined` means "the route did not answer". Collapsing the
  // second into the first is the defect that made every list call report no
  // next page. See planning_client/pagination_contract_plan.md.
  it('passes has_more through when the server sends it', () => {
    expect(extractPagination({ total_count: 100, page_size: 25, offset: 0, has_more: true }).has_more)
      .toBe(true);
    expect(extractPagination({ total_count: 100, page_size: 75, offset: 50, has_more: false }).has_more)
      .toBe(false);
  });

  it('returns undefined — not false — when the server is silent', () => {
    expect(extractPagination({ total_count: 100, page_size: 25, offset: 0 }).has_more)
      .toBeUndefined();
  });

  it('never derives has_more from page_size and total_count', () => {
    // The shape of a get-by-URI response: page_size is the number of
    // identifiers asked for and total_count the objects across them, so
    // `(offset + page_size) < total_count` would claim a next page for a route
    // that has none. page_size does not mean the same thing on every route.
    expect(extractPagination({ total_count: 5, page_size: 1, offset: 0 }).has_more)
      .toBeUndefined();
  });
});

describe('isJsonQuadsResponse', () => {
  it('should return true for valid quad response with results', () => {
    const data = {
      results: [
        { s: 'urn:entity:1', p: 'rdf:type', o: 'kg:KGEntity', g: 'urn:graph:1' },
      ],
      total_count: 1,
    };
    expect(isJsonQuadsResponse(data)).toBe(true);
  });

  it('should return true for empty results array', () => {
    const data = { results: [], total_count: 0 };
    expect(isJsonQuadsResponse(data)).toBe(true);
  });

  it('should return false if results is missing', () => {
    expect(isJsonQuadsResponse({ spaces: [] })).toBe(false);
  });

  it('should return false if results is not an array', () => {
    expect(isJsonQuadsResponse({ results: 'not-array' })).toBe(false);
  });

  it('should return false if first result has no "s" key', () => {
    expect(isJsonQuadsResponse({ results: [{ name: 'foo' }] })).toBe(false);
  });

  it('should return false for null', () => {
    expect(isJsonQuadsResponse(null)).toBe(false);
  });

  it('should return false for non-objects', () => {
    expect(isJsonQuadsResponse('string')).toBe(false);
    expect(isJsonQuadsResponse(42)).toBe(false);
    expect(isJsonQuadsResponse(undefined)).toBe(false);
  });
});

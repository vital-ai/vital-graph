import { describe, it, expect } from 'vitest';
import { validateRequired, buildQueryParams } from '../../src/utils/params.js';
import { VitalGraphClientError } from '../../src/utils/errors.js';

describe('validateRequired', () => {
  it('should not throw for valid params', () => {
    expect(() => validateRequired({ space_id: 'abc', graph_id: 'xyz' })).not.toThrow();
  });

  it('should throw for null value', () => {
    expect(() => validateRequired({ space_id: null })).toThrow(VitalGraphClientError);
    expect(() => validateRequired({ space_id: null })).toThrow("'space_id'");
  });

  it('should throw for undefined value', () => {
    expect(() => validateRequired({ graph_id: undefined })).toThrow(VitalGraphClientError);
  });

  it('should throw for empty string', () => {
    expect(() => validateRequired({ uri: '' })).toThrow(VitalGraphClientError);
    expect(() => validateRequired({ uri: '' })).toThrow("'uri'");
  });

  it('should allow 0 and false as valid values', () => {
    expect(() => validateRequired({ offset: 0, active: false })).not.toThrow();
  });
});

describe('buildQueryParams', () => {
  it('should build params from non-null values', () => {
    const params = buildQueryParams({ space_id: 'abc', page_size: 10 });
    expect(params.get('space_id')).toBe('abc');
    expect(params.get('page_size')).toBe('10');
  });

  it('should filter out null values', () => {
    const params = buildQueryParams({ space_id: 'abc', search: null });
    expect(params.get('space_id')).toBe('abc');
    expect(params.has('search')).toBe(false);
  });

  it('should filter out undefined values', () => {
    const params = buildQueryParams({ space_id: 'abc', search: undefined });
    expect(params.has('search')).toBe(false);
  });

  it('should convert booleans to strings', () => {
    const params = buildQueryParams({ include_graph: true, active: false });
    expect(params.get('include_graph')).toBe('true');
    expect(params.get('active')).toBe('false');
  });

  it('should convert numbers to strings', () => {
    const params = buildQueryParams({ offset: 0, page_size: 50 });
    expect(params.get('offset')).toBe('0');
    expect(params.get('page_size')).toBe('50');
  });

  it('should return empty URLSearchParams for all-null input', () => {
    const params = buildQueryParams({ a: null, b: undefined });
    expect(params.toString()).toBe('');
  });
});

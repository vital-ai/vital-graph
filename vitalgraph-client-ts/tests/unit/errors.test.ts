import { describe, it, expect } from 'vitest';
import { VitalGraphClientError } from '../../src/utils/errors.js';

describe('VitalGraphClientError', () => {
  it('should be an instance of Error', () => {
    const err = new VitalGraphClientError('test');
    expect(err).toBeInstanceOf(Error);
    expect(err).toBeInstanceOf(VitalGraphClientError);
  });

  it('should set name to VitalGraphClientError', () => {
    const err = new VitalGraphClientError('oops');
    expect(err.name).toBe('VitalGraphClientError');
  });

  it('should store the message', () => {
    const err = new VitalGraphClientError('something broke');
    expect(err.message).toBe('something broke');
  });

  it('should store statusCode when provided', () => {
    const err = new VitalGraphClientError('not found', 404);
    expect(err.statusCode).toBe(404);
  });

  it('should leave statusCode undefined when not provided', () => {
    const err = new VitalGraphClientError('generic');
    expect(err.statusCode).toBeUndefined();
  });
});

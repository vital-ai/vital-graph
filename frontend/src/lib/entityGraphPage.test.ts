import { describe, it, expect } from 'vitest';
import {
  pageCount,
  needsPaging,
  clampOffset,
  pageNumber,
  rangeLabel,
  slotCountFor,
} from './entityGraphPage';

/**
 * Paging arithmetic for the entity graph.
 *
 * This is exactly the logic that is tedious and slow to assert through a
 * browser — thresholds, offset clamping, and the missing-key-means-zero rule
 * for slot counts — so it is unit tested here. Rendering and interaction stay
 * in the Playwright suite.
 */

describe('needsPaging', () => {
  it('is false when the level fits exactly one page', () => {
    // Strictly greater: a level that exactly fills a page needs no controls.
    expect(needsPaging(25, 25)).toBe(false);
  });

  it('is true when the level exceeds one page', () => {
    expect(needsPaging(26, 25)).toBe(true);
  });

  it('is false for an empty level', () => {
    expect(needsPaging(0, 25)).toBe(false);
  });
});

describe('pageCount', () => {
  it('rounds up a partial final page', () => {
    expect(pageCount(14, 10)).toBe(2);
  });

  it('is 1 for an empty or single-page level', () => {
    expect(pageCount(0, 10)).toBe(1);
    expect(pageCount(10, 10)).toBe(1);
  });

  it('never divides by a zero page size', () => {
    expect(pageCount(10, 0)).toBe(1);
  });
});

describe('clampOffset', () => {
  it('leaves a valid offset alone', () => {
    expect(clampOffset(10, 30, 10)).toBe(10);
  });

  it('pulls an offset past the end back to the last page', () => {
    // Deleting the last item on the final page would otherwise leave the
    // caller requesting an offset that renders an empty page.
    expect(clampOffset(100, 14, 10)).toBe(10);
  });

  it('lands exactly on a page boundary', () => {
    expect(clampOffset(999, 25, 10)).toBe(20);
  });

  it('returns 0 for an empty level', () => {
    expect(clampOffset(50, 0, 10)).toBe(0);
  });

  it('never returns a negative offset', () => {
    expect(clampOffset(-5, 30, 10)).toBe(0);
  });
});

describe('pageNumber', () => {
  it('is 1-based', () => {
    expect(pageNumber(0, 10)).toBe(1);
    expect(pageNumber(10, 10)).toBe(2);
    expect(pageNumber(20, 10)).toBe(3);
  });
});

describe('rangeLabel', () => {
  it('describes a full page', () => {
    expect(rangeLabel(20, 20, 250)).toBe('21–40 of 250');
  });

  it('describes a partial final page', () => {
    expect(rangeLabel(10, 4, 14)).toBe('11–14 of 14');
  });

  it('describes an empty level without inventing a range', () => {
    expect(rangeLabel(0, 0, 0)).toBe('0 of 0');
  });
});

describe('slotCountFor', () => {
  it('reads a present count', () => {
    expect(slotCountFor({ 'urn:f1': 12 }, 'urn:f1')).toBe(12);
  });

  it('treats a MISSING key as 0, not unknown', () => {
    // The server's grouped COUNT produces no row for a zero-slot frame, so a
    // missing key must render as "no slots" rather than undefined.
    expect(slotCountFor({ 'urn:f1': 12 }, 'urn:f2')).toBe(0);
  });

  it('preserves an explicit zero', () => {
    expect(slotCountFor({ 'urn:f1': 0 }, 'urn:f1')).toBe(0);
  });

  it('handles an absent map or frame uri', () => {
    expect(slotCountFor(undefined, 'urn:f1')).toBe(0);
    expect(slotCountFor(null, 'urn:f1')).toBe(0);
    expect(slotCountFor({ 'urn:f1': 3 }, undefined)).toBe(0);
  });
});

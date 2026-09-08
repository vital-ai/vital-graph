import { describe, it, expect } from 'vitest';
import { buildEntityListQuery, activeFilterCount, type EntityListUiState } from './entityListQuery';

const base: EntityListUiState = {
  itemsPerPage: 25, currentPage: 1, committedSearch: '', entityTypeFilter: '',
  sortBy: '', sortOrder: 'asc', statusFilter: '', actionTypeFilter: '',
  provenanceFilter: '', createdAfter: '', createdBefore: '',
  modifiedAfter: '', modifiedBefore: '',
};
const NAME = 'http://vital.ai/ontology/vital-core#hasName';

describe('sort is no longer gated on the set being narrowed', () => {
  it('sends the sort with no search and no type filter', () => {
    const q = buildEntityListQuery({ ...base, sortBy: NAME });
    expect(q.sort_by).toBe(NAME);
    expect(q.sort_order).toBe('asc');
  });

  it('sends sort_order only alongside a sort_by', () => {
    expect(buildEntityListQuery({ ...base, sortOrder: 'desc' }).sort_order).toBeUndefined();
    expect(buildEntityListQuery({ ...base, sortBy: NAME, sortOrder: 'desc' }).sort_order).toBe('desc');
  });
});

describe('blank inputs are omitted, not sent empty', () => {
  it('omits every unset filter', () => {
    const q = buildEntityListQuery(base);
    for (const k of ['search', 'entity_type_uri', 'status', 'action_type',
      'provenance_type', 'created_after', 'created_before',
      'modified_after', 'modified_before'] as const) {
      expect(q[k], `${k} should be omitted when blank`).toBeUndefined();
    }
  });

  it('passes the filters through when set', () => {
    const q = buildEntityListQuery({
      ...base, statusFilter: 'urn:Active', actionTypeFilter: 'urn:Call',
      provenanceFilter: 'urn:Import', createdAfter: '2026-01-01',
      modifiedBefore: '2026-06-30',
    });
    expect(q.status).toBe('urn:Active');
    expect(q.action_type).toBe('urn:Call');
    expect(q.provenance_type).toBe('urn:Import');
    expect(q.created_after).toBe('2026-01-01');
    expect(q.modified_before).toBe('2026-06-30');
  });
});

describe('offset', () => {
  it('is zero-based off the 1-based page number', () => {
    expect(buildEntityListQuery({ ...base, currentPage: 1 }).offset).toBe(0);
    expect(buildEntityListQuery({ ...base, currentPage: 3, itemsPerPage: 25 }).offset).toBe(50);
  });
});

describe('activeFilterCount', () => {
  it('counts only the property filters, not search or type or sort', () => {
    expect(activeFilterCount(base)).toBe(0);
    expect(activeFilterCount({ ...base, statusFilter: 'x', createdAfter: 'y' })).toBe(2);
    // A collapsed panel hides these, so the count is the only thing that says
    // a filter is narrowing the list. Search and type have their own visible
    // inputs and must not inflate it.
    expect(activeFilterCount({ ...base, committedSearch: 's', entityTypeFilter: 't' } as EntityListUiState)).toBe(0);
  });
});

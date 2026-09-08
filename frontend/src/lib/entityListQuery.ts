/**
 * Request options for the KG entity listing, built from the page's UI state.
 *
 * Extracted from `KGEntities.tsx` so the rules are assertable without a
 * browser — the same reason `entityGraphPage.ts` exists. The rules are easy to
 * get wrong in ways rendering does not show: an empty string sent instead of
 * omitted becomes a filter matching nothing, and a sort silently dropped looks
 * like a server that ignores sorting.
 */

export interface EntityListUiState {
  itemsPerPage: number;
  currentPage: number;
  committedSearch: string;
  entityTypeFilter: string;
  sortBy: string;
  sortOrder: 'asc' | 'desc';
  statusFilter: string;
  actionTypeFilter: string;
  provenanceFilter: string;
  createdAfter: string;
  createdBefore: string;
  modifiedAfter: string;
  modifiedBefore: string;
}

export interface EntityListQuery {
  page_size: number;
  offset: number;
  search?: string;
  entity_type_uri?: string;
  sort_by?: string;
  sort_order?: 'asc' | 'desc';
  status?: string;
  action_type?: string;
  provenance_type?: string;
  created_after?: string;
  created_before?: string;
  modified_after?: string;
  modified_before?: string;
}

/** Blank means "not set", and must be OMITTED rather than sent as "". */
const opt = (v: string | undefined): string | undefined => (v ? v : undefined);

export function buildEntityListQuery(ui: EntityListUiState): EntityListQuery {
  return {
    page_size: ui.itemsPerPage,
    offset: (ui.currentPage - 1) * ui.itemsPerPage,
    search: opt(ui.committedSearch),
    entity_type_uri: opt(ui.entityTypeFilter),
    // NOT conditional on the set having been narrowed first. It used to be:
    // sorting the whole space was a full scan and sort, so the sort was
    // withheld unless a search or type filter had reduced it. Since
    // `entity_prop_sort` an unnarrowed sort is an ordered index scan, so
    // withholding it only meant the user's chosen sort was quietly ignored.
    sort_by: opt(ui.sortBy),
    sort_order: ui.sortBy ? ui.sortOrder : undefined,
    status: opt(ui.statusFilter),
    action_type: opt(ui.actionTypeFilter),
    provenance_type: opt(ui.provenanceFilter),
    created_after: opt(ui.createdAfter),
    created_before: opt(ui.createdBefore),
    modified_after: opt(ui.modifiedAfter),
    modified_before: opt(ui.modifiedBefore),
  };
}

/** How many property filters are set — drives the badge on the Filters button. */
export function activeFilterCount(ui: Pick<EntityListUiState,
  'statusFilter' | 'actionTypeFilter' | 'provenanceFilter' |
  'createdAfter' | 'createdBefore' | 'modifiedAfter' | 'modifiedBefore'>): number {
  return [ui.statusFilter, ui.actionTypeFilter, ui.provenanceFilter,
    ui.createdAfter, ui.createdBefore, ui.modifiedAfter,
    ui.modifiedBefore].filter(Boolean).length;
}

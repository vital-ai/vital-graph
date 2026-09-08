import React, { useState, useEffect, useCallback } from 'react';
import { useLatestRequest } from '../hooks/useLatestRequest';
import { useParams, useNavigate } from 'react-router-dom';
import { apiService } from '../services/ApiService';
import {
  Alert, Badge, Button, Label, Pagination, Select, Spinner, TextInput
} from 'flowbite-react';
import { type SpaceInfo } from '../types/api';
import { type GraphInfo } from '../types/graphs';
import { HiPlus, HiEye, HiTrash } from 'react-icons/hi2';
import { HiSearch, HiCube, HiCollection, HiSortAscending, HiSortDescending, HiFilter } from 'react-icons/hi';
import CopyButton from '../components/CopyButton';
import {
  parseEntitiesFromQuads,
  shortenUri,
  type Quad,
} from '../utils/QuadUtils';
import ConfirmDialog from '../components/ConfirmDialog';
import { buildEntityListQuery, activeFilterCount } from '../lib/entityListQuery';

// Every property `{space}_entity_prop_sort` indexes. Sorting by any of them is
// an ordered index scan rather than a scan-and-sort of the whole space, so the
// list is no longer limited to the three that were tolerable to sort slowly.
const SORT_OPTIONS: { label: string; value: string }[] = [
  { label: 'Name', value: 'http://vital.ai/ontology/vital-core#hasName' },
  { label: 'Modified', value: 'http://vital.ai/ontology/vital#hasObjectModificationDateTime' },
  { label: 'Created', value: 'http://vital.ai/ontology/vital-aimp#hasObjectCreationTime' },
  { label: 'Status', value: 'http://vital.ai/ontology/vital-aimp#hasObjectStatusType' },
  { label: 'Entity type', value: 'http://vital.ai/ontology/haley-ai-kg#hasKGEntityType' },
  { label: 'Provenance', value: 'http://vital.ai/ontology/haley-ai-kg#hasKGProvenanceType' },
];

interface KGEntity {
  uri: string;
  rdf_type: string;
  name: string;
  properties_count: number;
}

const KGEntities: React.FC = () => {
  const navigate = useNavigate();
  const { spaceId, graphId } = useParams<{ spaceId?: string; graphId?: string }>();

  const [spaces, setSpaces] = useState<SpaceInfo[]>([]);
  const [graphs, setGraphs] = useState<GraphInfo[]>([]);
  const [selectedSpace, setSelectedSpace] = useState(spaceId || '');
  const [selectedGraph, setSelectedGraph] = useState(graphId ? decodeURIComponent(graphId) : '');
  const [spacesLoading, setSpacesLoading] = useState(true);
  const [graphsLoading, setGraphsLoading] = useState(false);

  const [entities, setEntities] = useState<KGEntity[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [totalCount, setTotalCount] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [itemsPerPage, setItemsPerPage] = useState(25);
  const [searchTerm, setSearchTerm] = useState('');
  const [committedSearch, setCommittedSearch] = useState('');
  const [deletingEntity, setDeletingEntity] = useState<KGEntity | null>(null);
  const [sortBy, setSortBy] = useState<string>('');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('asc');
  const [entityTypeFilter, setEntityTypeFilter] = useState<string>('');
  // Server-side property filters. Each is served from the same table the sort
  // is, so a filtered page costs about what an unfiltered one does.
  const [showFilters, setShowFilters] = useState(false);
  const [statusFilter, setStatusFilter] = useState('');
  const [actionTypeFilter, setActionTypeFilter] = useState('');
  const [provenanceFilter, setProvenanceFilter] = useState('');
  const [createdAfter, setCreatedAfter] = useState('');
  const [createdBefore, setCreatedBefore] = useState('');
  const [modifiedAfter, setModifiedAfter] = useState('');
  const [modifiedBefore, setModifiedBefore] = useState('');

  // Fetch spaces
  const fetchSpaces = useCallback(async () => {
    try {
      setSpacesLoading(true);
      setSpaces(await apiService.getSpaces());
    } catch { /* ignore */ }
    finally { setSpacesLoading(false); }
  }, []);

  useEffect(() => { fetchSpaces(); }, [fetchSpaces]);

  // Fetch graphs
  const fetchGraphs = useCallback(async () => {
    if (!selectedSpace) { setGraphs([]); return; }
    try {
      setGraphsLoading(true);
      setGraphs((await apiService.getGraphs(selectedSpace)).graphs ?? []);
    } catch { setGraphs([]); }
    finally { setGraphsLoading(false); }
  }, [selectedSpace]);

  useEffect(() => { fetchGraphs(); }, [fetchGraphs]);

  // Navigate to hierarchical URL when selection changes
  useEffect(() => {
    if (selectedSpace && selectedGraph && !spaceId) {
      navigate(`/space/${selectedSpace}/graph/${encodeURIComponent(selectedGraph)}/objects/kgentities`, { replace: true });
    }
  }, [selectedSpace, selectedGraph, navigate, spaceId]);

  const handleSearch = useCallback(() => {
    setCommittedSearch(searchTerm);
    setCurrentPage(1);
  }, [searchTerm]);


  // Discard responses from superseded requests — see useLatestRequest.
  const beginRequest = useLatestRequest();

  const fetchEntities = useCallback(async () => {
    if (!selectedSpace || !selectedGraph) return;
    const isStale = beginRequest();
    try {
      setLoading(true);
      setError(null);
      const data = await apiService.getEntities(selectedSpace, selectedGraph,
        buildEntityListQuery({
          itemsPerPage, currentPage, committedSearch, entityTypeFilter,
          sortBy, sortOrder, statusFilter, actionTypeFilter, provenanceFilter,
          createdAfter, createdBefore, modifiedAfter, modifiedBefore,
        }));
      if (isStale()) return;   // a newer fetch already answered
      const quads: Quad[] = data.results || [];
      const grouped = parseEntitiesFromQuads(quads);
      const parsed: KGEntity[] = grouped.map(e => ({
        uri: e.uri,
        rdf_type: e.rdf_type,
        name: e.name,
        properties_count: e.properties_count,
      }));

      setEntities(parsed);
      setTotalCount(data.total_count ?? parsed.length);
    } catch {
      if (isStale()) return;
      setError('Failed to load KG entities.');
      setEntities([]);
    } finally {
      if (!isStale()) setLoading(false);
    }
  }, [selectedSpace, selectedGraph, itemsPerPage, currentPage, committedSearch,
      entityTypeFilter, sortBy, sortOrder, statusFilter, actionTypeFilter,
      provenanceFilter, createdAfter, createdBefore, modifiedAfter,
      modifiedBefore, beginRequest]);

  useEffect(() => { fetchEntities(); }, [fetchEntities]);

  // Sorting no longer depends on the set being narrowed first, so there is
  // nothing to reset when a search or type filter is cleared — clearing one
  // used to silently drop the user's chosen sort.
  const filterCount = activeFilterCount({
    statusFilter, actionTypeFilter, provenanceFilter,
    createdAfter, createdBefore, modifiedAfter, modifiedBefore,
  });

  const clearFilters = () => {
    setStatusFilter(''); setActionTypeFilter(''); setProvenanceFilter('');
    setCreatedAfter(''); setCreatedBefore('');
    setModifiedAfter(''); setModifiedBefore('');
    setCurrentPage(1);
  };

  const totalPages = Math.max(1, Math.ceil(totalCount / itemsPerPage));
  const hasSelection = selectedSpace && selectedGraph;

  const handleDelete = async (entity: KGEntity) => {
    try {
      await apiService.deleteEntity(selectedSpace, selectedGraph, entity.uri);
      setDeletingEntity(null);
      await fetchEntities();
    } catch {
      setError('Failed to delete entity.');
      setDeletingEntity(null);
    }
  };

  const toggleSort = (field: string) => {
    if (sortBy === field) {
      setSortOrder(prev => prev === 'asc' ? 'desc' : 'asc');
    } else {
      setSortBy(field);
      setSortOrder('asc');
    }
    setCurrentPage(1);
  };

  const SortIcon: React.FC<{ field: string }> = ({ field }) => {
    if (sortBy !== field) return <HiSortAscending className="w-3.5 h-3.5 text-gray-300" />;
    return sortOrder === 'asc'
      ? <HiSortAscending className="w-3.5 h-3.5 text-blue-500" />
      : <HiSortDescending className="w-3.5 h-3.5 text-blue-500" />;
  };

  return (
    <div className="space-y-5" data-testid="kgentities-page">
      {/* Page Title */}
      <div className="flex items-center gap-2 mb-2">
        <HiCollection className="w-6 h-6 text-blue-600" />
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white" data-testid="kgentities-title">KG Entities</h1>
      </div>

      {/* Space / Graph selectors */}
      <div className="flex flex-col sm:flex-row gap-4">
        <div className="flex-1 max-w-xs">
          <Label htmlFor="space-select" className="text-xs">Space</Label>
          <Select
            id="space-select"
            value={selectedSpace}
            onChange={(e) => { setSelectedSpace(e.target.value); setSelectedGraph(''); }}
            disabled={spacesLoading}
          >
            <option value="">Choose a space...</option>
            {spaces.map((s) => (
              <option key={s.space} value={s.space}>{s.space_name || s.space}</option>
            ))}
          </Select>
        </div>
        <div className="flex-1 max-w-xs">
          <Label htmlFor="graph-select" className="text-xs">Graph</Label>
          <Select
            id="graph-select"
            value={selectedGraph}
            onChange={(e) => setSelectedGraph(e.target.value)}
            disabled={!selectedSpace || graphsLoading}
          >
            <option value="">Choose a graph...</option>
            {graphs.map((g) => (
              <option key={g.graph_uri} value={g.graph_uri}>
                {g.graph_uri.split('/').pop() || g.graph_uri}
              </option>
            ))}
          </Select>
        </div>
      </div>

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <p className="text-gray-500 dark:text-gray-400 text-sm">
            {hasSelection && !loading && `${totalCount.toLocaleString()} entit${totalCount !== 1 ? 'ies' : 'y'}`}
          </p>
        </div>
        {hasSelection && (
          <Button size="sm" color="blue" onClick={() => navigate(`/space/${selectedSpace}/graph/${encodeURIComponent(selectedGraph)}/entity/new?mode=create`)}>
            <HiPlus className="mr-1.5 h-4 w-4" />Add Entity
          </Button>
        )}
      </div>

      {/* Search + filters */}
      {hasSelection && (
        <div className="flex flex-col sm:flex-row gap-3">
          <div className="flex-1 flex gap-2">
            <TextInput
              className="flex-1"
              icon={HiSearch}
              placeholder="Search entities..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleSearch(); }}
            />
            <Button size="sm" color="blue" onClick={handleSearch}>Search</Button>
          </div>
          <div className="w-44 flex-shrink-0">
            <TextInput
              placeholder="Filter by type URI..."
              value={entityTypeFilter}
              onChange={(e) => { setEntityTypeFilter(e.target.value); setCurrentPage(1); }}
              sizing="md"
            />
          </div>
          <div className="w-36 flex-shrink-0">
            <Select value={sortBy} data-testid="sort-select" onChange={(e) => { setSortBy(e.target.value); setCurrentPage(1); }}>
              <option value="">Sort by...</option>
              {SORT_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </Select>
          </div>
          <div className="w-32 flex-shrink-0">
            <Select value={itemsPerPage} onChange={(e) => { setItemsPerPage(parseInt(e.target.value)); setCurrentPage(1); }}>
              <option value={10}>10 / page</option>
              <option value={25}>25 / page</option>
              <option value={50}>50 / page</option>
              <option value={100}>100 / page</option>
            </Select>
          </div>
          <div className="flex-shrink-0">
            <Button size="sm" color={filterCount ? 'blue' : 'light'}
                    data-testid="toggle-filters"
                    onClick={() => setShowFilters(v => !v)}>
              <HiFilter className="w-4 h-4 mr-1" />
              Filters{filterCount ? ` (${filterCount})` : ''}
            </Button>
          </div>
        </div>
      )}

      {/* Property filters. Behind a toggle rather than always visible: seven
          more inputs would crowd out the search box, which is the control most
          people reach for first. The count on the button is what makes a
          collapsed filter discoverable — a filter left set and out of sight is
          why a list "has no results". */}
      {hasSelection && showFilters && (
        <div className="rounded-lg border border-gray-200 dark:border-gray-700 p-4 space-y-3"
             data-testid="entity-filters">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div>
              <Label htmlFor="f-status">Status URI</Label>
              <TextInput id="f-status" sizing="sm" placeholder="hasObjectStatusType value"
                         value={statusFilter} data-testid="filter-status"
                         onChange={(e) => { setStatusFilter(e.target.value); setCurrentPage(1); }} />
            </div>
            <div>
              <Label htmlFor="f-action">Action type URI</Label>
              <TextInput id="f-action" sizing="sm" placeholder="entity has this action type"
                         value={actionTypeFilter} data-testid="filter-action"
                         onChange={(e) => { setActionTypeFilter(e.target.value); setCurrentPage(1); }} />
            </div>
            <div>
              <Label htmlFor="f-prov">Provenance URI</Label>
              <TextInput id="f-prov" sizing="sm" placeholder="hasKGProvenanceType value"
                         value={provenanceFilter} data-testid="filter-provenance"
                         onChange={(e) => { setProvenanceFilter(e.target.value); setCurrentPage(1); }} />
            </div>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div>
              <Label htmlFor="f-ca">Created after</Label>
              <TextInput id="f-ca" type="date" sizing="sm" value={createdAfter}
                         data-testid="filter-created-after"
                         onChange={(e) => { setCreatedAfter(e.target.value); setCurrentPage(1); }} />
            </div>
            <div>
              <Label htmlFor="f-cb">Created before</Label>
              <TextInput id="f-cb" type="date" sizing="sm" value={createdBefore}
                         onChange={(e) => { setCreatedBefore(e.target.value); setCurrentPage(1); }} />
            </div>
            <div>
              <Label htmlFor="f-ma">Modified after</Label>
              <TextInput id="f-ma" type="date" sizing="sm" value={modifiedAfter}
                         onChange={(e) => { setModifiedAfter(e.target.value); setCurrentPage(1); }} />
            </div>
            <div>
              <Label htmlFor="f-mb">Modified before</Label>
              <TextInput id="f-mb" type="date" sizing="sm" value={modifiedBefore}
                         onChange={(e) => { setModifiedBefore(e.target.value); setCurrentPage(1); }} />
            </div>
          </div>
          <div className="flex justify-end">
            <Button size="xs" color="light" onClick={clearFilters}
                    disabled={!filterCount} data-testid="clear-filters">
              Clear filters
            </Button>
          </div>
        </div>
      )}

      {error && <Alert color="failure" onDismiss={() => setError(null)}>{error}</Alert>}

      {/* Empty / prompt states */}
      {!selectedSpace && (
        <div className="text-center py-16 text-gray-500 dark:text-gray-400">
          <HiCube className="w-16 h-16 mx-auto mb-4 text-gray-300 dark:text-gray-600" />
          <p className="text-lg font-medium">Select a space</p>
          <p className="text-sm mt-1">Choose a space from the dropdown above</p>
        </div>
      )}
      {selectedSpace && !selectedGraph && (
        <div className="text-center py-16 text-gray-500 dark:text-gray-400">
          <HiCube className="w-16 h-16 mx-auto mb-4 text-gray-300 dark:text-gray-600" />
          <p className="text-lg font-medium">Select a graph</p>
          <p className="text-sm mt-1">Choose a graph to browse its entities</p>
        </div>
      )}

      {hasSelection && loading && (
        <div className="flex justify-center py-12"><Spinner size="xl" /></div>
      )}

      {hasSelection && !loading && entities.length === 0 && !error && (
        <div className="text-center py-16 text-gray-500 dark:text-gray-400">
          <HiCube className="w-16 h-16 mx-auto mb-4 text-gray-300 dark:text-gray-600" />
          {committedSearch ? (
            <>
              <p className="text-lg font-medium">No results for &quot;{committedSearch}&quot;</p>
              <p className="text-sm mt-1">Try a different search term</p>
            </>
          ) : (
            <>
              <p className="text-lg font-medium">No entities yet</p>
              <p className="text-sm mt-1">Add your first KG entity to get started</p>
            </>
          )}
        </div>
      )}

      {/* Entities table */}
      {hasSelection && !loading && entities.length > 0 && (
        <>
          <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
            <table className="w-full text-sm text-left" data-testid="entities-table">
              <thead className="text-xs text-gray-500 dark:text-gray-400 uppercase bg-gray-50 dark:bg-gray-800">
                <tr>
                  <th className="px-4 py-3">
                    <button onClick={() => toggleSort('http://vital.ai/ontology/vital-core#hasName')} className="flex items-center gap-1 hover:text-gray-700 dark:hover:text-gray-200" data-testid="sort-entity">
                      Entity <SortIcon field="http://vital.ai/ontology/vital-core#hasName" />
                    </button>
                  </th>
                  <th className="px-4 py-3">Type</th>
                  <th className="px-4 py-3 w-28">Properties</th>
                  <th className="px-4 py-3 w-24"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                {entities.map((entity) => (
                  <tr key={entity.uri} data-testid="entity-row" className="bg-white dark:bg-gray-900 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">
                    <td className="px-4 py-2.5">
                      <div className="max-w-xs">
                        <p className="text-sm font-medium text-gray-900 dark:text-white truncate">{entity.name}</p>
                        <p className="text-xs font-mono text-gray-400 truncate inline-flex items-center gap-0.5" title={entity.uri}><span className="truncate">{entity.uri}</span><CopyButton text={entity.uri} /></p>
                      </div>
                    </td>
                    <td className="px-4 py-2.5">
                      <Badge color="blue" size="xs">{shortenUri(entity.rdf_type)}</Badge>
                    </td>
                    <td className="px-4 py-2.5 text-xs text-gray-500 dark:text-gray-400">
                      {entity.properties_count}
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="flex gap-1">
                        <button
                          onClick={() => navigate(`/space/${selectedSpace}/graph/${encodeURIComponent(selectedGraph)}/entity/${encodeURIComponent(entity.uri)}`)}
                          className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-400 hover:text-blue-500 transition-colors" title="View"
                          data-testid={`entity-view-${entity.uri}`}
                        >
                          <HiEye className="h-4 w-4" />
                        </button>
                        <button
                          onClick={() => setDeletingEntity(entity)}
                          className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-400 hover:text-red-500 transition-colors" title="Delete"
                        >
                          <HiTrash className="h-4 w-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="flex justify-center">
              <Pagination currentPage={currentPage} totalPages={totalPages} onPageChange={setCurrentPage} showIcons />
            </div>
          )}
        </>
      )}

      {/* Delete Modal */}
      <ConfirmDialog
        open={!!deletingEntity}
        onConfirm={() => deletingEntity && handleDelete(deletingEntity)}
        onCancel={() => setDeletingEntity(null)}
        title="Delete Entity"
        confirmLabel="Delete"
        variant="danger"
        detail={
          deletingEntity && (
            <>
              <p className="font-medium text-gray-800 dark:text-gray-200">{deletingEntity.name}</p>
              <p className="text-gray-400">{deletingEntity.uri}</p>
            </>
          )
        }
      />
    </div>
  );
};

export default KGEntities;

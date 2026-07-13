import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { apiService } from '../services/ApiService';
import {
  Alert, Badge, Button, Label, Pagination, Select, Spinner, TextInput
} from 'flowbite-react';
import { type SpaceInfo } from '../types/api';
import { type GraphInfo } from '../types/graphs';
import { HiPlus, HiEye, HiTrash } from 'react-icons/hi2';
import { HiSearch, HiCube, HiCollection, HiSortAscending, HiSortDescending } from 'react-icons/hi';
import CopyButton from '../components/CopyButton';
import {
  parseEntitiesFromQuads,
  shortenUri,
  type Quad,
} from '../utils/QuadUtils';
import ConfirmDialog from '../components/ConfirmDialog';

const SORT_OPTIONS: { label: string; value: string }[] = [
  { label: 'Name', value: 'http://vital.ai/ontology/vital-core#hasName' },
  { label: 'Modified', value: 'http://vital.ai/ontology/vital#hasObjectModificationDateTime' },
  { label: 'Created', value: 'http://vital.ai/ontology/vital-aimp#hasObjectCreationTime' },
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
      setGraphs(await apiService.getGraphs(selectedSpace));
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

  const fetchEntities = useCallback(async () => {
    if (!selectedSpace || !selectedGraph) return;
    try {
      setLoading(true);
      setError(null);
      const data = await apiService.getEntities(selectedSpace, selectedGraph, {
        page_size: itemsPerPage,
        offset: (currentPage - 1) * itemsPerPage,
        search: committedSearch || undefined,
        entity_type_uri: entityTypeFilter || undefined,
        sort_by: sortBy || undefined,
        sort_order: sortBy ? sortOrder : undefined,
      });
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
      setError('Failed to load KG entities.');
      setEntities([]);
    } finally {
      setLoading(false);
    }
  }, [selectedSpace, selectedGraph, itemsPerPage, currentPage, committedSearch, entityTypeFilter, sortBy, sortOrder]);

  useEffect(() => { fetchEntities(); }, [fetchEntities]);

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
            <Select value={sortBy} onChange={(e) => { setSortBy(e.target.value); setCurrentPage(1); }}>
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
                    <button onClick={() => toggleSort('http://vital.ai/ontology/vital-core#hasName')} className="flex items-center gap-1 hover:text-gray-700 dark:hover:text-gray-200">
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

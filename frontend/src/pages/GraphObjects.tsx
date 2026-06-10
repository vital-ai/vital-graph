import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { apiService } from '../services/ApiService';
import {
  Alert, Badge, Button, Label, Pagination, Select, Spinner, TextInput
} from 'flowbite-react';
import { type SpaceInfo } from '../types/api';
import { type GraphInfo } from '../types/graphs';
import ObjectIcon from '../components/icons/ObjectIcon';
import { HiPlus, HiEye, HiTrash } from 'react-icons/hi2';
import { HiSearch, HiCollection } from 'react-icons/hi';
import {
  parseEntitiesFromQuads,
  buildDeleteAllPayload,
  shortenUri,
  type Quad,
} from '../utils/QuadUtils';
import ConfirmDialog from '../components/ConfirmDialog';

interface RDFObject {
  uri: string;
  rdf_type: string;
  object_type: 'Node' | 'Edge';
  properties_count: number;
}

const GraphObjects: React.FC = () => {
  const navigate = useNavigate();
  const { spaceId, graphId } = useParams<{ spaceId?: string; graphId?: string }>();

  const [spaces, setSpaces] = useState<SpaceInfo[]>([]);
  const [graphs, setGraphs] = useState<GraphInfo[]>([]);
  const [selectedSpace, setSelectedSpace] = useState(spaceId || '');
  const [selectedGraph, setSelectedGraph] = useState(graphId ? decodeURIComponent(graphId) : '');
  const [spacesLoading, setSpacesLoading] = useState(true);
  const [graphsLoading, setGraphsLoading] = useState(false);

  const [objects, setObjects] = useState<RDFObject[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [totalCount, setTotalCount] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [itemsPerPage, setItemsPerPage] = useState(25);
  const [searchTerm, setSearchTerm] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [deletingObject, setDeletingObject] = useState<RDFObject | null>(null);

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
      navigate(`/space/${selectedSpace}/graph/${encodeURIComponent(selectedGraph)}/objects/graphobjects`, { replace: true });
    }
  }, [selectedSpace, selectedGraph, navigate, spaceId]);

  // Debounce search
  useEffect(() => {
    const timer = setTimeout(() => { setDebouncedSearch(searchTerm); setCurrentPage(1); }, 400);
    return () => clearTimeout(timer);
  }, [searchTerm]);

  const fetchObjects = useCallback(async () => {
    if (!selectedSpace || !selectedGraph) return;
    try {
      setLoading(true);
      setError(null);
      const data = await apiService.getObjects(selectedSpace, selectedGraph, {
        page_size: itemsPerPage,
        offset: (currentPage - 1) * itemsPerPage,
        search: debouncedSearch || undefined,
      });
      const quads: Quad[] = data.results || [];
      const grouped = parseEntitiesFromQuads(quads);
      const parsed: RDFObject[] = grouped.map(e => ({
        uri: e.uri,
        rdf_type: e.rdf_type,
        object_type: e.rdf_type.toLowerCase().includes('edge') ? 'Edge' as const : 'Node' as const,
        properties_count: e.properties_count,
      }));

      setObjects(parsed);
      setTotalCount(data.total_count ?? parsed.length);
    } catch {
      setError('Failed to load objects.');
      setObjects([]);
    } finally {
      setLoading(false);
    }
  }, [selectedSpace, selectedGraph, itemsPerPage, currentPage, debouncedSearch]);

  useEffect(() => { fetchObjects(); }, [fetchObjects]);

  const totalPages = Math.max(1, Math.ceil(totalCount / itemsPerPage));
  const hasSelection = selectedSpace && selectedGraph;

  const handleDelete = async (obj: RDFObject) => {
    try {
      await apiService.deleteTriples(selectedSpace, selectedGraph,
        buildDeleteAllPayload(obj.uri, selectedGraph)
      );
      setDeletingObject(null);
      await fetchObjects();
    } catch {
      setError('Failed to delete object.');
      setDeletingObject(null);
    }
  };

  return (
    <div className="space-y-5">
      {/* Page Title */}
      <div className="flex items-center gap-2 mb-2">
        <ObjectIcon className="w-6 h-6 text-blue-600" />
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Graph Objects</h1>
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
            {hasSelection && !loading && `${totalCount.toLocaleString()} object${totalCount !== 1 ? 's' : ''}`}
          </p>
        </div>
        {hasSelection && (
          <Button size="sm" color="blue" onClick={() => navigate(`/space/${selectedSpace}/graph/${encodeURIComponent(selectedGraph)}/objects/new?mode=create`)}>
            <HiPlus className="mr-1.5 h-4 w-4" />Add Object
          </Button>
        )}
      </div>

      {/* Search + page size */}
      {hasSelection && (
        <div className="flex flex-col sm:flex-row gap-3">
          <div className="flex-1">
            <TextInput icon={HiSearch} placeholder="Search objects..." value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)} />
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

      {!selectedSpace && (
        <div className="text-center py-16 text-gray-500 dark:text-gray-400">
          <HiCollection className="w-16 h-16 mx-auto mb-4 text-gray-300 dark:text-gray-600" />
          <p className="text-lg font-medium">Select a space</p>
          <p className="text-sm mt-1">Choose a space from the dropdown above</p>
        </div>
      )}
      {selectedSpace && !selectedGraph && (
        <div className="text-center py-16 text-gray-500 dark:text-gray-400">
          <HiCollection className="w-16 h-16 mx-auto mb-4 text-gray-300 dark:text-gray-600" />
          <p className="text-lg font-medium">Select a graph</p>
          <p className="text-sm mt-1">Choose a graph to browse its objects</p>
        </div>
      )}

      {hasSelection && loading && (
        <div className="flex justify-center py-12"><Spinner size="xl" /></div>
      )}

      {hasSelection && !loading && objects.length === 0 && !error && (
        <div className="text-center py-16 text-gray-500 dark:text-gray-400">
          <HiCollection className="w-16 h-16 mx-auto mb-4 text-gray-300 dark:text-gray-600" />
          {debouncedSearch ? (
            <>
              <p className="text-lg font-medium">No results for &quot;{debouncedSearch}&quot;</p>
              <p className="text-sm mt-1">Try a different search term</p>
            </>
          ) : (
            <>
              <p className="text-lg font-medium">No objects yet</p>
              <p className="text-sm mt-1">Add your first graph object to get started</p>
            </>
          )}
        </div>
      )}

      {/* Objects table */}
      {hasSelection && !loading && objects.length > 0 && (
        <>
          <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
            <table className="w-full text-sm text-left">
              <thead className="text-xs text-gray-500 dark:text-gray-400 uppercase bg-gray-50 dark:bg-gray-800">
                <tr>
                  <th className="px-4 py-3">Object</th>
                  <th className="px-4 py-3">Type</th>
                  <th className="px-4 py-3 w-20">Kind</th>
                  <th className="px-4 py-3 w-28">Properties</th>
                  <th className="px-4 py-3 w-24"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                {objects.map((obj) => (
                  <tr key={obj.uri} className="bg-white dark:bg-gray-900 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">
                    <td className="px-4 py-2.5">
                      <div className="max-w-xs">
                        <p className="text-sm font-medium text-gray-900 dark:text-white truncate">{shortenUri(obj.uri)}</p>
                        <p className="text-xs font-mono text-gray-400 truncate" title={obj.uri}>{obj.uri}</p>
                      </div>
                    </td>
                    <td className="px-4 py-2.5">
                      <Badge color="blue" size="xs">{shortenUri(obj.rdf_type)}</Badge>
                    </td>
                    <td className="px-4 py-2.5">
                      <Badge color={obj.object_type === 'Edge' ? 'green' : 'gray'} size="xs">{obj.object_type}</Badge>
                    </td>
                    <td className="px-4 py-2.5 text-xs text-gray-500 dark:text-gray-400">
                      {obj.properties_count}
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="flex gap-1">
                        <button
                          onClick={() => navigate(`/space/${selectedSpace}/graph/${encodeURIComponent(selectedGraph)}/objects/${encodeURIComponent(obj.uri)}`)}
                          className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-400 hover:text-blue-500 transition-colors" title="View"
                        >
                          <HiEye className="h-4 w-4" />
                        </button>
                        <button
                          onClick={() => setDeletingObject(obj)}
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
        open={!!deletingObject}
        onConfirm={() => deletingObject && handleDelete(deletingObject)}
        onCancel={() => setDeletingObject(null)}
        title="Delete Object"
        confirmLabel="Delete"
        variant="danger"
        detail={
          deletingObject && (
            <>
              <p className="font-medium text-gray-800 dark:text-gray-200">{shortenUri(deletingObject.uri)}</p>
              <p className="text-gray-400">{deletingObject.uri}</p>
            </>
          )
        }
      />
    </div>
  );
};

export default GraphObjects;

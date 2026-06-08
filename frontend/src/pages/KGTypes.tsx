import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { apiService } from '../services/ApiService';
import {
  Alert, Badge, Button, Label, Pagination, Select, Spinner, TextInput
} from 'flowbite-react';
import { HiPlus, HiTrash, HiSearch, HiEye } from 'react-icons/hi';
import { type SpaceInfo } from '../types/api';
import { type GraphInfo } from '../types/graphs';
import KGTypesIcon from '../components/icons/KGTypesIcon';
import NavigationBreadcrumb from '../components/NavigationBreadcrumb';
import { shortenUri, extractGraphName } from '../utils/QuadUtils';
import ConfirmDialog from '../components/ConfirmDialog';

interface KGType {
  uri: string;
  type_name: string;
  type_uri: string;
  description: string;
  [key: string]: unknown;
}

const KGTypes: React.FC = () => {
  const navigate = useNavigate();
  const { spaceId, graphId } = useParams<{ spaceId?: string; graphId?: string }>();

  const [spaces, setSpaces] = useState<SpaceInfo[]>([]);
  const [selectedSpace, setSelectedSpace] = useState(spaceId || '');
  const [graphs, setGraphs] = useState<GraphInfo[]>([]);
  const [selectedGraph, setSelectedGraph] = useState(graphId ? decodeURIComponent(graphId) : '');
  const [spacesLoading, setSpacesLoading] = useState(true);
  const [graphsLoading, setGraphsLoading] = useState(false);

  const [kgTypes, setKGTypes] = useState<KGType[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const [itemsPerPage, setItemsPerPage] = useState(25);
  const [deletingType, setDeletingType] = useState<KGType | null>(null);

  // Navigate to hierarchical URL
  useEffect(() => {
    if (selectedSpace && selectedGraph && !spaceId && !graphId) {
      navigate(`/space/${selectedSpace}/graph/${encodeURIComponent(selectedGraph)}/kg-types`);
    }
  }, [selectedSpace, selectedGraph, navigate, spaceId, graphId]);

  // Fetch spaces
  const fetchSpaces = useCallback(async () => {
    try {
      setSpacesLoading(true);
      setSpaces(await apiService.getSpaces());
    } catch { setError('Failed to load spaces.'); }
    finally { setSpacesLoading(false); }
  }, []);
  useEffect(() => { fetchSpaces(); }, [fetchSpaces]);

  // Fetch graphs
  const fetchGraphs = useCallback(async () => {
    if (!selectedSpace) { setGraphs([]); return; }
    try {
      setGraphsLoading(true);
      setGraphs(await apiService.getGraphs(selectedSpace));
    } catch { setError('Failed to load graphs.'); setGraphs([]); }
    finally { setGraphsLoading(false); }
  }, [selectedSpace]);

  useEffect(() => {
    fetchGraphs();
    if (!graphId) setSelectedGraph('');
  }, [fetchGraphs, graphId]);

  // Fetch KG types
  const fetchKGTypes = useCallback(async () => {
    if (!selectedSpace || !selectedGraph) { setKGTypes([]); return; }
    try {
      setLoading(true);
      setError(null);
      const responseData = await apiService.getKGTypes(selectedSpace, selectedGraph, {
        page_size: 100, offset: 0
      });

      // Extract types array from response
      let data: KGType[] = [];
      if (Array.isArray(responseData)) {
        data = responseData;
      } else if (responseData.kgtypes) {
        data = responseData.kgtypes;
      } else if (responseData.data) {
        data = Array.isArray(responseData.data) ? responseData.data : [];
      }

      // Normalize: ensure uri/type_name/type_uri/description fields exist
      const normalized = data.map((t: KGType) => ({
        ...t,
        uri: t.uri || '',
        type_name: t.type_name || shortenUri(t.uri || ''),
        type_uri: t.type_uri || '',
        description: t.description || '',
      }));

      setKGTypes(normalized);
    } catch {
      setError('Failed to load KG types.');
      setKGTypes([]);
    } finally { setLoading(false); }
  }, [selectedSpace, selectedGraph]);

  useEffect(() => { fetchKGTypes(); }, [fetchKGTypes]);

  // Client-side filter
  const filtered = kgTypes.filter(t => {
    const q = searchTerm.toLowerCase();
    return t.type_name.toLowerCase().includes(q) ||
           t.uri.toLowerCase().includes(q) ||
           t.type_uri.toLowerCase().includes(q) ||
           t.description.toLowerCase().includes(q);
  });

  const totalPages = Math.max(1, Math.ceil(filtered.length / itemsPerPage));
  const paginated = filtered.slice((currentPage - 1) * itemsPerPage, currentPage * itemsPerPage);
  const hasSelection = selectedSpace && selectedGraph;

  const handleDelete = async (t: KGType) => {
    try {
      await apiService.deleteTriples(selectedSpace, selectedGraph, {
        quads: [{ s: `<${t.uri}>`, p: '*', o: '*', g: `<${selectedGraph}>` }]
      });
      setDeletingType(null);
      await fetchKGTypes();
    } catch {
      setError('Failed to delete KG type.');
      setDeletingType(null);
    }
  };

  return (
    <div className="space-y-6">
      <NavigationBreadcrumb spaceId={spaceId} graphId={graphId} currentPageName="KG Types" currentPageIcon={KGTypesIcon} />

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <KGTypesIcon className="w-6 h-6 text-indigo-600" />
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">KG Types</h1>
          </div>
          {hasSelection && !loading && (
            <p className="text-gray-500 dark:text-gray-400 text-sm mt-1">{filtered.length} type{filtered.length !== 1 ? 's' : ''}</p>
          )}
        </div>
        {hasSelection && (
          <Button size="sm" color="blue" onClick={() => navigate(`/space/${selectedSpace}/graph/${encodeURIComponent(selectedGraph)}/kg-types/new?mode=create`)}>
            <HiPlus className="mr-1.5 h-4 w-4" />Add Type
          </Button>
        )}
      </div>

      {/* Space / Graph selectors */}
      <div className="flex flex-col sm:flex-row gap-4">
        <div className="flex-1 max-w-xs">
          <Label htmlFor="space-select" className="text-xs">Space</Label>
          <Select id="space-select" value={selectedSpace}
            onChange={(e) => { setSelectedSpace(e.target.value); setSelectedGraph(''); }}
            disabled={spacesLoading}>
            <option value="">Choose a space...</option>
            {spaces.map((s: SpaceInfo) => (
              <option key={s.space} value={s.space}>{s.space_name}</option>
            ))}
          </Select>
        </div>
        <div className="flex-1 max-w-xs">
          <Label htmlFor="graph-select" className="text-xs">Graph</Label>
          <Select id="graph-select" value={selectedGraph}
            onChange={(e) => setSelectedGraph(e.target.value)}
            disabled={!selectedSpace || graphsLoading}>
            <option value="">Choose a graph...</option>
            {graphs.map((g: GraphInfo) => (
              <option key={g.graph_uri} value={g.graph_uri}>{extractGraphName(g.graph_uri)}</option>
            ))}
          </Select>
        </div>
      </div>

      {/* Search + page size */}
      {hasSelection && (
        <div className="flex flex-col sm:flex-row gap-3">
          <div className="flex-1">
            <TextInput icon={HiSearch} placeholder="Search types..." value={searchTerm}
              onChange={(e) => { setSearchTerm(e.target.value); setCurrentPage(1); }} />
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

      {/* Prompt states */}
      {!selectedSpace && !spacesLoading && (
        <div className="text-center py-16 text-gray-500 dark:text-gray-400">
          <KGTypesIcon className="w-16 h-16 mx-auto mb-4 text-gray-300 dark:text-gray-600" />
          <p className="text-lg font-medium">Select a space</p>
          <p className="text-sm mt-1">Choose a space from the dropdown above</p>
        </div>
      )}
      {selectedSpace && !selectedGraph && !graphsLoading && (
        <div className="text-center py-16 text-gray-500 dark:text-gray-400">
          <KGTypesIcon className="w-16 h-16 mx-auto mb-4 text-gray-300 dark:text-gray-600" />
          <p className="text-lg font-medium">Select a graph</p>
          <p className="text-sm mt-1">Choose a graph to browse its KG types</p>
        </div>
      )}

      {hasSelection && loading && (
        <div className="flex justify-center py-12"><Spinner size="xl" /></div>
      )}

      {hasSelection && !loading && filtered.length === 0 && !error && (
        <div className="text-center py-16 text-gray-500 dark:text-gray-400">
          <KGTypesIcon className="w-16 h-16 mx-auto mb-4 text-gray-300 dark:text-gray-600" />
          {searchTerm ? (
            <>
              <p className="text-lg font-medium">No results for &quot;{searchTerm}&quot;</p>
              <p className="text-sm mt-1">Try a different search term</p>
            </>
          ) : (
            <>
              <p className="text-lg font-medium">No KG types yet</p>
              <p className="text-sm mt-1">Add your first KG type to get started</p>
            </>
          )}
        </div>
      )}

      {/* Types table */}
      {hasSelection && !loading && paginated.length > 0 && (
        <>
          <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
            <table className="w-full text-sm text-left">
              <thead className="text-xs text-gray-500 dark:text-gray-400 uppercase bg-gray-50 dark:bg-gray-800">
                <tr>
                  <th className="px-4 py-3">Type</th>
                  <th className="px-4 py-3">RDF Type</th>
                  <th className="px-4 py-3 hidden md:table-cell">Description</th>
                  <th className="px-4 py-3 w-24"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                {paginated.map((t, i) => (
                  <tr key={t.uri || i} className="bg-white dark:bg-gray-900 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">
                    <td className="px-4 py-2.5">
                      <div className="max-w-xs">
                        <p className="text-sm font-medium text-gray-900 dark:text-white truncate">{t.type_name}</p>
                        <p className="text-xs font-mono text-gray-400 truncate" title={t.uri}>{t.uri}</p>
                      </div>
                    </td>
                    <td className="px-4 py-2.5">
                      <Badge color="indigo" size="xs">{shortenUri(t.type_uri) || 'Unknown'}</Badge>
                    </td>
                    <td className="px-4 py-2.5 hidden md:table-cell text-xs text-gray-500 dark:text-gray-400 max-w-xs truncate">
                      {t.description || '-'}
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="flex gap-1">
                        <button
                          onClick={() => navigate(`/space/${selectedSpace}/graph/${encodeURIComponent(selectedGraph)}/kg-types/${encodeURIComponent(t.uri)}?mode=view`)}
                          className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-400 hover:text-blue-500 transition-colors" title="View"
                        >
                          <HiEye className="h-4 w-4" />
                        </button>
                        <button
                          onClick={() => setDeletingType(t)}
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
        open={!!deletingType}
        onConfirm={() => deletingType && handleDelete(deletingType)}
        onCancel={() => setDeletingType(null)}
        title="Delete KG Type"
        confirmLabel="Delete"
        variant="danger"
        detail={
          deletingType && (
            <>
              <p className="font-medium text-gray-800 dark:text-gray-200">{deletingType.type_name}</p>
              <p className="text-gray-400">{deletingType.uri}</p>
            </>
          )
        }
      />
    </div>
  );
};

export default KGTypes;

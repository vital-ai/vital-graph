import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate, useParams, Link } from 'react-router-dom';
import { Button, TextInput, Select, Breadcrumb, BreadcrumbItem } from 'flowbite-react';
import { HiPlus, HiTrash } from 'react-icons/hi2';
import { HiSearch, HiHome, HiViewBoards, HiDatabase, HiChevronRight } from 'react-icons/hi';
import { type GraphInfo } from '../types/graphs';
import { apiService } from '../services/ApiService';
import GraphIcon from '../components/icons/GraphIcon';
import { extractGraphName } from '../utils/QuadUtils';
import { SkeletonTable } from '../components/Skeleton';
import { usePageTitle } from '../hooks/usePageTitle';
import { useApiError } from '../hooks/useApiError';
import ErrorDisplay from '../components/shared/ErrorDisplay';

interface SpaceOption {
  space: string;
  space_name: string;
}

const Graphs: React.FC = () => {
  usePageTitle('Graphs');
  const navigate = useNavigate();
  const { spaceId } = useParams<{ spaceId?: string }>();
  const [graphs, setGraphs] = useState<GraphInfo[]>([]);
  const [spaces, setSpaces] = useState<SpaceOption[]>([]);
  const [selectedSpace, setSelectedSpace] = useState(spaceId || '');
  const [searchTerm, setSearchTerm] = useState('');
  const [loading, setLoading] = useState(false);
  const [spacesLoading, setSpacesLoading] = useState(true);
  const { error, handleError, clearError } = useApiError();
  const [deleting, setDeleting] = useState<string | null>(null);

  // Navigate to hierarchical URL when space changes
  useEffect(() => {
    if (selectedSpace && !spaceId) {
      navigate(`/space/${selectedSpace}/graphs`, { replace: true });
    }
  }, [selectedSpace, navigate, spaceId]);

  // Fetch spaces
  useEffect(() => {
    const load = async () => {
      try {
        setSpacesLoading(true);
        const data = await apiService.getSpaces();
        setSpaces(data.map((s: { space: string; space_name?: string }) => ({
          space: s.space,
          space_name: s.space_name || s.space,
        })));
      } catch (err) {
        handleError(err, 'Failed to load spaces.');
      } finally {
        setSpacesLoading(false);
      }
    };
    load();
  }, []);

  // Fetch graphs
  const fetchGraphs = useCallback(async () => {
    if (!selectedSpace) { setGraphs([]); return; }
    try {
      setLoading(true);
      clearError();
      const data = await apiService.getGraphs(selectedSpace);
      setGraphs(data);
    } catch (err) {
      handleError(err, 'Failed to load graphs.');
      setGraphs([]);
    } finally {
      setLoading(false);
    }
  }, [selectedSpace]);

  useEffect(() => { fetchGraphs(); }, [fetchGraphs]);

  const handleDeleteGraph = async (graphUri: string, graphName: string) => {
    if (!selectedSpace) return;
    if (!window.confirm(`Delete graph "${graphName}"? This cannot be undone.`)) return;
    try {
      setDeleting(graphUri);
      clearError();
      await apiService.deleteGraph(selectedSpace, graphUri, true);
      await fetchGraphs();
    } catch (err) {
      handleError(err, `Failed to delete "${graphName}".`);
    } finally {
      setDeleting(null);
    }
  };

  const currentSpaceName = spaces.find(s => s.space === selectedSpace)?.space_name || selectedSpace;

  const filteredGraphs = searchTerm
    ? graphs.filter(g => {
        const name = extractGraphName(g.graph_uri).toLowerCase();
        const uri = g.graph_uri.toLowerCase();
        const term = searchTerm.toLowerCase();
        return name.includes(term) || uri.includes(term);
      })
    : graphs;

  const totalTriples = graphs.reduce((sum, g) => sum + (g.triple_count || 0), 0);

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      {spaceId && (
        <Breadcrumb>
          <BreadcrumbItem href="/" icon={HiHome}>Home</BreadcrumbItem>
          <BreadcrumbItem href="/spaces" icon={HiViewBoards}>Spaces</BreadcrumbItem>
          <BreadcrumbItem href={`/space/${spaceId}`}>{currentSpaceName}</BreadcrumbItem>
          <BreadcrumbItem icon={GraphIcon}>Graphs</BreadcrumbItem>
        </Breadcrumb>
      )}

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <GraphIcon className="w-6 h-6 text-purple-600" />
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Graphs</h1>
          </div>
          {selectedSpace && !loading && (
            <p className="text-gray-500 dark:text-gray-400 mt-1">
              {graphs.length} graph{graphs.length !== 1 ? 's' : ''} · {totalTriples.toLocaleString()} triples
            </p>
          )}
        </div>
        <div className="flex items-center gap-3">
          {!spaceId && (
            <div className="w-56">
              <Select
                value={selectedSpace}
                onChange={(e) => setSelectedSpace(e.target.value)}
                disabled={spacesLoading}
              >
                <option value="">Select space...</option>
                {spaces.map((s) => (
                  <option key={s.space} value={s.space}>{s.space_name}</option>
                ))}
              </Select>
            </div>
          )}
          {selectedSpace && (
            <Button color="blue" size="sm" onClick={() => navigate(`/space/${selectedSpace}/graph/new`)}>
              <HiPlus className="mr-1.5 h-4 w-4" />
              New Graph
            </Button>
          )}
        </div>
      </div>

      {/* Search */}
      {selectedSpace && graphs.length > 0 && (
        <div className="max-w-sm">
          <TextInput
            icon={HiSearch}
            placeholder="Filter graphs..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>
      )}

      {error && (
        <ErrorDisplay message={error} onRetry={fetchGraphs} onDismiss={clearError} />
      )}

      {/* Loading */}
      {loading && (
        <SkeletonTable rows={4} cols={3} />
      )}

      {/* No space selected */}
      {!selectedSpace && !spacesLoading && !loading && (
        <div className="text-center py-16 text-gray-500 dark:text-gray-400">
          <GraphIcon className="w-16 h-16 mx-auto mb-4 text-gray-300 dark:text-gray-600" />
          <p className="text-lg font-medium">Select a space</p>
          <p className="text-sm mt-1">Choose a space to view its graphs</p>
        </div>
      )}

      {/* Empty state */}
      {selectedSpace && !loading && filteredGraphs.length === 0 && !error && (
        <div className="text-center py-16 text-gray-500 dark:text-gray-400">
          <HiDatabase className="w-16 h-16 mx-auto mb-4 text-gray-300 dark:text-gray-600" />
          {searchTerm ? (
            <>
              <p className="text-lg font-medium">No graphs match &quot;{searchTerm}&quot;</p>
              <p className="text-sm mt-1">Try a different search term</p>
            </>
          ) : (
            <>
              <p className="text-lg font-medium">No graphs</p>
              <p className="text-sm mt-1">Create a graph to get started</p>
            </>
          )}
        </div>
      )}

      {/* Graph cards */}
      {selectedSpace && !loading && filteredGraphs.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {filteredGraphs.map((graph) => {
            const name = extractGraphName(graph.graph_uri);
            const isDeleting = deleting === graph.graph_uri;
            return (
              <div
                key={graph.graph_uri}
                className={`rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-5 transition-all ${
                  isDeleting ? 'opacity-50' : 'hover:shadow-md hover:border-purple-300 dark:hover:border-purple-600'
                }`}
              >
                <div className="flex items-start justify-between mb-2">
                  <Link
                    to={`/space/${selectedSpace}/graph/${encodeURIComponent(graph.graph_uri)}`}
                    className="min-w-0 flex-1 group"
                  >
                    <h3 className="text-lg font-semibold text-gray-900 dark:text-white truncate group-hover:text-purple-600 transition-colors">
                      {name}
                    </h3>
                  </Link>
                  <div className="flex items-center gap-1 flex-shrink-0 ml-2">
                    <Link
                      to={`/space/${selectedSpace}/graph/${encodeURIComponent(graph.graph_uri)}`}
                      className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-400 hover:text-purple-500 transition-colors"
                      title="View details"
                    >
                      <HiChevronRight className="w-4 h-4" />
                    </Link>
                    <button
                      onClick={() => handleDeleteGraph(graph.graph_uri, name)}
                      disabled={isDeleting}
                      className="p-1.5 rounded hover:bg-red-50 dark:hover:bg-red-900/20 text-gray-400 hover:text-red-500 transition-colors"
                      title="Delete graph"
                    >
                      <HiTrash className="w-4 h-4" />
                    </button>
                  </div>
                </div>

                <p className="text-xs text-gray-400 dark:text-gray-500 font-mono truncate mb-3" title={graph.graph_uri}>
                  {graph.graph_uri}
                </p>

                <div className="flex items-center gap-4 pt-3 border-t border-gray-100 dark:border-gray-700">
                  <div className="flex items-center gap-1.5">
                    <HiDatabase className="w-4 h-4 text-indigo-500" />
                    <span className="text-sm text-gray-600 dark:text-gray-300">
                      <span className="font-semibold">{(graph.triple_count || 0).toLocaleString()}</span> triples
                    </span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default Graphs;

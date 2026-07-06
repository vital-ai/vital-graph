import React, { useState, useEffect, useCallback } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { apiService } from '../services/ApiService';
import { Button, Spinner, TextInput } from 'flowbite-react';
import {
  HiSearch,
  HiViewBoards,
  HiChevronRight,
  HiDatabase,
  HiPlus
} from 'react-icons/hi';
import GraphIcon from '../components/icons/GraphIcon';
import { SkeletonCardList } from '../components/Skeleton';
import { usePageTitle } from '../hooks/usePageTitle';
import { useApiError } from '../hooks/useApiError';
import ErrorDisplay from '../components/shared/ErrorDisplay';

interface SpaceWithStats {
  space: string;
  space_name: string;
  space_description?: string;
  graphCount: number;
  tripleCount: number;
  loading: boolean;
}

const Spaces: React.FC = () => {
  usePageTitle('Spaces');
  const navigate = useNavigate();
  const [spaces, setSpaces] = useState<SpaceWithStats[]>([]);
  const [loading, setLoading] = useState(true);
  const { error, handleError, clearError } = useApiError();
  const [filterText, setFilterText] = useState('');

  const fetchSpaces = useCallback(async () => {
    try {
      setLoading(true);
      const spacesData = await apiService.getSpaces();
      // Initialize spaces with loading stats
      const initial: SpaceWithStats[] = spacesData.map((s: { space: string; space_name?: string; space_description?: string }) => ({
        space: s.space,
        space_name: s.space_name || s.space,
        space_description: s.space_description,
        graphCount: 0,
        tripleCount: 0,
        loading: true,
      }));
      setSpaces(initial);
      clearError();
      setLoading(false);

      // Load graph stats per space in parallel
      const updated = await Promise.all(
        initial.map(async (s) => {
          try {
            const graphs = await apiService.getGraphs(s.space);
            return {
              ...s,
              graphCount: graphs.length,
              tripleCount: graphs.reduce((sum: number, g: { triple_count?: number }) => sum + (g.triple_count || 0), 0),
              loading: false,
            };
          } catch {
            return { ...s, loading: false };
          }
        })
      );
      setSpaces(updated);
    } catch (err) {
      handleError(err, 'Failed to load spaces.');
      setSpaces([]);
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSpaces();
  }, [fetchSpaces]);

  const filteredSpaces = filterText
    ? spaces.filter(
        (s) =>
          s.space_name.toLowerCase().includes(filterText.toLowerCase()) ||
          s.space.toLowerCase().includes(filterText.toLowerCase()) ||
          (s.space_description || '').toLowerCase().includes(filterText.toLowerCase())
      )
    : spaces;

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-2">
          <HiViewBoards className="w-6 h-6 text-blue-600" />
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Spaces</h1>
        </div>
        <SkeletonCardList rows={4} />
      </div>
    );
  }

  return (
    <div className="space-y-6" data-testid="spaces-page">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <HiViewBoards className="w-6 h-6 text-blue-600" />
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white" data-testid="spaces-title">Spaces</h1>
          </div>
          <p className="text-gray-500 dark:text-gray-400 mt-1">
            {spaces.length} space{spaces.length !== 1 ? 's' : ''}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="w-full sm:w-72">
            <TextInput
              icon={HiSearch}
              placeholder="Search spaces..."
              value={filterText}
              onChange={(e) => setFilterText(e.target.value)}
            />
          </div>
          <Button color="blue" onClick={() => navigate('/space/new')}>
            <HiPlus className="w-4 h-4 mr-1" />
            Create Space
          </Button>
        </div>
      </div>

      {error && (
        <ErrorDisplay message={error} onRetry={fetchSpaces} onDismiss={clearError} />
      )}

      {filteredSpaces.length === 0 && !error ? (
        <div className="text-center py-16 text-gray-500 dark:text-gray-400">
          <HiDatabase className="w-16 h-16 mx-auto mb-4 text-gray-300 dark:text-gray-600" />
          {filterText ? (
            <>
              <p className="text-lg font-medium">No spaces match &quot;{filterText}&quot;</p>
              <p className="text-sm mt-1">Try a different search term</p>
            </>
          ) : (
            <>
              <p className="text-lg font-medium">No spaces yet</p>
              <p className="text-sm mt-1">Create your first space to get started</p>
            </>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4" data-testid="spaces-grid">
          {filteredSpaces.map((space) => (
            <Link
              key={space.space}
              to={`/space/${space.space}`}
              className="block rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-5 hover:shadow-md hover:border-blue-300 dark:hover:border-blue-600 transition-all group"
              data-testid={`space-card-${space.space}`}
            >
              <div className="flex items-start justify-between mb-3">
                <div className="min-w-0 flex-1">
                  <h3 className="text-lg font-semibold text-gray-900 dark:text-white truncate group-hover:text-blue-600 transition-colors">
                    {space.space_name}
                  </h3>
                  <p className="text-xs text-gray-400 dark:text-gray-500 font-mono mt-0.5">{space.space}</p>
                </div>
                <HiChevronRight className="w-5 h-5 text-gray-300 group-hover:text-blue-500 flex-shrink-0 mt-1 transition-colors" />
              </div>

              {space.space_description && (
                <p className="text-sm text-gray-500 dark:text-gray-400 mb-4 line-clamp-2">
                  {space.space_description}
                </p>
              )}

              <div className="flex items-center gap-6 pt-3 border-t border-gray-100 dark:border-gray-700">
                <div className="flex items-center gap-2">
                  <GraphIcon className="w-4 h-4 text-purple-500" />
                  {space.loading ? (
                    <Spinner size="xs" />
                  ) : (
                    <span className="text-sm text-gray-600 dark:text-gray-300">
                      <span className="font-semibold">{space.graphCount}</span> graph{space.graphCount !== 1 ? 's' : ''}
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <HiDatabase className="w-4 h-4 text-indigo-500" />
                  {space.loading ? (
                    <Spinner size="xs" />
                  ) : (
                    <span className="text-sm text-gray-600 dark:text-gray-300">
                      <span className="font-semibold">{space.tripleCount.toLocaleString()}</span> triple{space.tripleCount !== 1 ? 's' : ''}
                    </span>
                  )}
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
};

export default Spaces;

import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import {
  Alert,
  Badge,
  Button,
  Card,
  Label,
  Select,
  Spinner,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeadCell,
  TableRow,
  TextInput,
  Textarea,
  Breadcrumb,
  BreadcrumbItem,
  RangeSlider,
} from 'flowbite-react';
import { HiSearch, HiRefresh, HiDocumentText, HiHome } from 'react-icons/hi';
import { vectorGeoService } from '../services/VectorGeoService';
import { apiService } from '../services/ApiService';
import type { VectorIndex, ReindexResponse } from '../types/vectorGeo';
import { type SpaceInfo } from '../types/api';

interface SearchResult {
  entity_uri: string;
  score: number;
  type_uri?: string;
  name?: string;
}

const VectorSearch: React.FC = () => {
  const { spaceId } = useParams<{ spaceId?: string }>();

  const [spaces, setSpaces] = useState<SpaceInfo[]>([]);
  const [selectedSpace, setSelectedSpace] = useState<string>(spaceId || '');
  const [indexes, setIndexes] = useState<VectorIndex[]>([]);
  const [selectedIndex, setSelectedIndex] = useState<string>('');
  const [searchText, setSearchText] = useState('');
  const [topK, setTopK] = useState(10);
  const [minScore, setMinScore] = useState(0.5);
  const [loading, setLoading] = useState(false);
  const [spacesLoading, setSpacesLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [queryTime, setQueryTime] = useState<number | null>(null);
  const [searchMode, setSearchMode] = useState<'vector' | 'fulltext'>('vector');

  // Reindex state
  const [reindexing, setReindexing] = useState(false);
  const [reindexResult, setReindexResult] = useState<ReindexResponse | null>(null);

  // Load spaces
  useEffect(() => {
    const loadSpaces = async () => {
      try {
        const data = await apiService.getSpaces();
        setSpaces(data);
        if (!selectedSpace && data.length > 0) {
          setSelectedSpace(data[0].space);
        }
      } catch {
        setError('Failed to load spaces');
      } finally {
        setSpacesLoading(false);
      }
    };
    loadSpaces();
  }, []);

  // Load indexes when space changes
  useEffect(() => {
    if (!selectedSpace) return;
    const loadIndexes = async () => {
      try {
        const data = await vectorGeoService.getVectorIndexes(selectedSpace);
        setIndexes(data);
        if (data.length > 0) {
          setSelectedIndex(data[0].index_name);
        }
      } catch {
        setIndexes([]);
      }
    };
    loadIndexes();
  }, [selectedSpace]);

  // Execute vector similarity search via KGQuery endpoint
  const handleSearch = async () => {
    if (!selectedSpace || !searchText.trim()) return;
    if (searchMode === 'vector' && !selectedIndex) return;
    setLoading(true);
    setError(null);
    setResults([]);
    setQueryTime(null);

    try {
      const startTime = performance.now();
      let response: Response;

      if (searchMode === 'fulltext') {
        // Full-text search via the vector text_search endpoint
        response = await apiService.post(`/api/v1/spaces/${selectedSpace}/vector-search/fulltext`, {
          query: searchText.trim(),
          index_name: selectedIndex || undefined,
          limit: topK,
        });
      } else {
        // Vector similarity search via KGQuery
        response = await apiService.post(`/api/spaces/${selectedSpace}/kgquery`, {
          query_mode: 'entity',
          vector_criteria: {
            search_text: searchText.trim(),
            index_name: selectedIndex,
            top_k: topK,
            min_score: minScore,
          },
          page_size: topK,
        });
      }

      const elapsed = performance.now() - startTime;
      setQueryTime(elapsed);

      if (response.ok) {
        const data = await response.json();
        // Extract entities from the response
        const entities = data.entities || data.results || [];
        const mapped: SearchResult[] = entities.map((e: Record<string, unknown>) => ({
          entity_uri: (e as Record<string, unknown>).uri || (e as Record<string, unknown>).entity_uri || (e as Record<string, unknown>).subject_uri || '',
          score: (e as Record<string, unknown>).similarity_score || (e as Record<string, unknown>).score || (e as Record<string, unknown>).rank || 0,
          type_uri: (e as Record<string, unknown>).type_uri || (e as Record<string, unknown>).kGEntityType || '',
          name: (e as Record<string, unknown>).name || (e as Record<string, unknown>).kGEntityName || (e as Record<string, unknown>).headline || '',
        }));
        setResults(mapped);
      } else {
        const errData = await response.json().catch(() => ({}));
        setError((errData as Record<string, string>).detail || `Search failed: ${response.status}`);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Search failed');
    } finally {
      setLoading(false);
    }
  };

  // Trigger reindex
  const handleReindex = async () => {
    if (!selectedSpace || !selectedIndex) return;
    setReindexing(true);
    setReindexResult(null);
    setError(null);
    try {
      const result = await vectorGeoService.reindex(selectedSpace, selectedIndex);
      setReindexResult(result);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Reindex failed');
    } finally {
      setReindexing(false);
    }
  };

  return (
    <div>
      <Breadcrumb className="mb-6">
        <BreadcrumbItem href="/" icon={HiHome}>Home</BreadcrumbItem>
        <BreadcrumbItem>Vector Search</BreadcrumbItem>
      </Breadcrumb>

      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Vector Search</h1>
        <div className="flex gap-2">
          <Button
            size="sm"
            color={searchMode === 'vector' ? 'blue' : 'gray'}
            onClick={() => setSearchMode('vector')}
          >
            <HiSearch className="mr-1 h-4 w-4" />
            Semantic
          </Button>
          <Button
            size="sm"
            color={searchMode === 'fulltext' ? 'blue' : 'gray'}
            onClick={() => setSearchMode('fulltext')}
          >
            <HiDocumentText className="mr-1 h-4 w-4" />
            Full-Text
          </Button>
        </div>
      </div>

      {/* Controls */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
        {/* Search panel */}
        <div className="lg:col-span-2">
          <Card>
            <div className="space-y-4">
              {/* Space + Index selectors */}
              <div className="flex gap-4">
                {!spaceId && (
                  <div className="flex-1">
                    <Label htmlFor="vs-space">Space</Label>
                    {spacesLoading ? (
                      <Spinner size="sm" />
                    ) : (
                      <Select
                        id="vs-space"
                        value={selectedSpace}
                        onChange={(e) => setSelectedSpace(e.target.value)}
                      >
                        <option value="">Select...</option>
                        {spaces.map((s) => (
                          <option key={s.space} value={s.space}>
                            {s.space_name || s.space}
                          </option>
                        ))}
                      </Select>
                    )}
                  </div>
                )}
                <div className="flex-1">
                  <Label htmlFor="vs-index">Index</Label>
                  <Select
                    id="vs-index"
                    value={selectedIndex}
                    onChange={(e) => setSelectedIndex(e.target.value)}
                    disabled={indexes.length === 0}
                  >
                    {indexes.length === 0 ? (
                      <option value="">No indexes available</option>
                    ) : (
                      indexes.map((idx) => (
                        <option key={idx.index_name} value={idx.index_name}>
                          {idx.index_name} ({idx.dimensions}d)
                        </option>
                      ))
                    )}
                  </Select>
                </div>
              </div>

              {/* Search text */}
              <div>
                <Label htmlFor="vs-text">
                  {searchMode === 'fulltext' ? 'Full-Text Query' : 'Search Text'}
                </Label>
                <Textarea
                  id="vs-text"
                  placeholder={searchMode === 'fulltext'
                    ? 'Enter keywords (supports PostgreSQL tsquery operators: & | !)...'
                    : 'Enter text to find similar entities...'}
                  value={searchText}
                  onChange={(e) => setSearchText(e.target.value)}
                  rows={3}
                />
              </div>

              {/* Parameters */}
              <div className="flex gap-4 items-end">
                <div className="w-24">
                  <Label htmlFor="vs-topk">Top K</Label>
                  <TextInput
                    id="vs-topk"
                    type="number"
                    min={1}
                    max={100}
                    value={topK}
                    onChange={(e) => setTopK(parseInt(e.target.value) || 10)}
                    sizing="sm"
                  />
                </div>
                <div className="flex-1">
                  <Label htmlFor="vs-minscore">
                    Min Score: {minScore.toFixed(2)}
                  </Label>
                  <RangeSlider
                    id="vs-minscore"
                    min={0}
                    max={1}
                    step={0.05}
                    value={minScore}
                    onChange={(e) => setMinScore(parseFloat(e.target.value))}
                  />
                </div>
                <Button
                  onClick={handleSearch}
                  disabled={loading || (searchMode === 'vector' && !selectedIndex) || !searchText.trim()}
                >
                  {loading ? <Spinner size="sm" className="mr-2" /> : <HiSearch className="mr-2 h-4 w-4" />}
                  Search
                </Button>
              </div>
            </div>
          </Card>
        </div>

        {/* Reindex panel */}
        <div>
          <Card>
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">Re-Index</h3>
            <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
              Rebuild embeddings for all entities matching this index's mappings.
            </p>
            <Button
              color="light"
              onClick={handleReindex}
              disabled={reindexing || !selectedIndex}
              className="w-full"
            >
              {reindexing ? <Spinner size="sm" className="mr-2" /> : <HiRefresh className="mr-2 h-4 w-4" />}
              Re-Index: {selectedIndex || '(none)'}
            </Button>
            {reindexResult && (
              <div className="mt-3 p-3 bg-green-50 dark:bg-green-900/20 rounded text-sm">
                <div className="font-medium text-green-700 dark:text-green-400 mb-1">Complete</div>
                <div className="text-gray-600 dark:text-gray-300">
                  {reindexResult.subjects_processed} subjects processed
                </div>
                <div className="text-gray-600 dark:text-gray-300">
                  {reindexResult.embeddings_stored} embeddings stored
                </div>
                <div className="text-gray-600 dark:text-gray-300">
                  {reindexResult.elapsed_seconds.toFixed(1)}s elapsed
                </div>
              </div>
            )}
          </Card>
        </div>
      </div>

      {/* Errors */}
      {error && (
        <Alert color="failure" className="mb-4" onDismiss={() => setError(null)}>
          {error}
        </Alert>
      )}

      {/* Results */}
      {queryTime !== null && (
        <div className="mb-4 flex items-center gap-3">
          <Badge color="gray">
            {results.length} result{results.length !== 1 ? 's' : ''}
          </Badge>
          <span className="text-sm text-gray-500">
            in {queryTime.toFixed(0)}ms
          </span>
        </div>
      )}

      {results.length > 0 && (
        <div className="overflow-x-auto">
          <Table hoverable>
            <TableHead>
              <TableHeadCell className="w-16">#</TableHeadCell>
              <TableHeadCell>Entity</TableHeadCell>
              <TableHeadCell>Type</TableHeadCell>
              <TableHeadCell className="w-28">Score</TableHeadCell>
            </TableHead>
            <TableBody className="divide-y">
              {results.map((r, i) => (
                <TableRow key={r.entity_uri || i} className="bg-white dark:border-gray-700 dark:bg-gray-800">
                  <TableCell className="text-gray-500">{i + 1}</TableCell>
                  <TableCell>
                    <div className="font-medium text-gray-900 dark:text-white">
                      {r.name || '(unnamed)'}
                    </div>
                    <div className="text-xs text-gray-500 truncate max-w-96">
                      {r.entity_uri}
                    </div>
                  </TableCell>
                  <TableCell className="text-sm text-gray-500 max-w-48 truncate">
                    {r.type_uri || '—'}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <div
                        className="h-2 rounded-full bg-blue-500"
                        style={{ width: `${Math.round(r.score * 100)}%`, maxWidth: '60px' }}
                      />
                      <span className="text-sm font-mono">
                        {r.score.toFixed(3)}
                      </span>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {queryTime !== null && results.length === 0 && (
        <div className="text-center py-12 text-gray-500 dark:text-gray-400">
          <p className="text-lg">No matching entities found</p>
          <p className="text-sm mt-1">Try lowering the minimum score or using different search text.</p>
        </div>
      )}
    </div>
  );
};

export default VectorSearch;

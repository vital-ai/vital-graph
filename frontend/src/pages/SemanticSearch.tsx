import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
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
  ToggleSwitch,
} from 'flowbite-react';
import { HiSearch, HiCode, HiHome, HiExternalLink } from 'react-icons/hi';
import { apiService } from '../services/ApiService';
import { vectorGeoService } from '../services/VectorGeoService';
import { searchFtsService } from '../services/SearchFtsService';
import { fuzzyMappingService } from '../services/FuzzyMappingService';
import type { SpaceInfo } from '../types/api';

type SearchMode = 'vector' | 'fts' | 'hybrid' | 'fuzzy' | 'keyword' | 'geo';
type GeoSubMode = 'radius' | 'bounds' | 'polygon';

interface SparqlBinding {
  [key: string]: { type: string; value: string };
}

const SEARCH_MODES: { value: SearchMode; label: string }[] = [
  { value: 'vector', label: 'Vector' },
  { value: 'fts', label: 'FTS' },
  { value: 'hybrid', label: 'Hybrid' },
  { value: 'fuzzy', label: 'Fuzzy' },
  { value: 'keyword', label: 'Keyword' },
  { value: 'geo', label: 'Geo' },
];

const GEO_SUB_MODES: { value: GeoSubMode; label: string }[] = [
  { value: 'radius', label: 'Radius' },
  { value: 'bounds', label: 'Bounds' },
  { value: 'polygon', label: 'Polygon' },
];

function generateSparql(
  mode: SearchMode,
  searchText: string,
  indexName: string,
  topK: number,
  minScore: number,
  alpha: number,
  geoSubMode: GeoSubMode,
  lat: number,
  lon: number,
  radius: number,
  minLat: number,
  minLon: number,
  maxLat: number,
  maxLon: number,
  polygonWkt: string,
  propertyUris: string[],
): string {
  const prefix = 'PREFIX vg: <http://vital.ai/ontology/vitalgraph#>\nPREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>\n';

  const escapedText = searchText.replace(/"/g, '\\"');

  // Build property patterns from the index mapping
  const propPatterns = propertyUris.length > 0
    ? propertyUris.map((uri, i) => `  OPTIONAL { ?entity <${uri}> ?prop${i} }`).join('\n')
    : '  OPTIONAL { ?entity <http://vital.ai/ontology/vital-core#hasName> ?prop0 }';
  const propVars = propertyUris.length > 0
    ? propertyUris.map((_, i) => `?prop${i}`).join(' ')
    : '?prop0';

  switch (mode) {
    case 'vector':
      return `${prefix}
SELECT ?entity ${propVars} ?score
WHERE {
${propPatterns}
  BIND(vg:vectorSimilarity(?entity, "${escapedText}", "${indexName}") AS ?score)
  FILTER(BOUND(?score))
  FILTER(?score > ${minScore})
}
ORDER BY DESC(?score)
LIMIT ${topK}`;

    case 'fts':
      return `${prefix}
SELECT ?entity ${propVars} ?score
WHERE {
${propPatterns}
  BIND(vg:textSearch(?entity, "${escapedText}", "${indexName}") AS ?score)
  FILTER(BOUND(?score))
}
ORDER BY DESC(?score)
LIMIT ${topK}`;

    case 'hybrid':
      return `${prefix}
SELECT ?entity ${propVars} ?score
WHERE {
${propPatterns}
  BIND(vg:hybridSearch(?entity, "${escapedText}", "${indexName}", ${alpha}) AS ?score)
  FILTER(BOUND(?score))
}
ORDER BY DESC(?score)
LIMIT ${topK}`;

    case 'fuzzy':
      return `${prefix}
SELECT ?entity ${propVars} ?score
WHERE {
${propPatterns}
  BIND(vg:fuzzyMatch(?entity, "${escapedText}", ${minScore}) AS ?score)
  FILTER(BOUND(?score))
}
ORDER BY DESC(?score)
LIMIT ${topK}`;

    case 'keyword':
      return `${prefix}
SELECT ?entity ${propVars}
WHERE {
${propPatterns}
  FILTER(CONTAINS(LCASE(?prop0), LCASE("${escapedText}")))
}
LIMIT ${topK}`;

    case 'geo':
      if (geoSubMode === 'radius') {
        return `${prefix}
SELECT ?entity ${propVars} ?distance
WHERE {
${propPatterns}
  BIND(vg:geoDistance(?entity, ${lat}, ${lon}) AS ?distance)
  FILTER(vg:withinRadius(?entity, ${lat}, ${lon}, ${radius}))
}
ORDER BY ?distance
LIMIT ${topK}`;
      } else if (geoSubMode === 'bounds') {
        return `${prefix}
SELECT ?entity ${propVars}
WHERE {
${propPatterns}
  FILTER(vg:withinBounds(?entity, ${minLat}, ${minLon}, ${maxLat}, ${maxLon}))
}
LIMIT ${topK}`;
      } else {
        return `${prefix}
SELECT ?entity ${propVars}
WHERE {
${propPatterns}
  FILTER(vg:withinPolygon(?entity, "${polygonWkt}"))
}
LIMIT ${topK}`;
      }
  }
}

const SemanticSearch: React.FC = () => {
  const navigate = useNavigate();

  // Space
  const [spaces, setSpaces] = useState<SpaceInfo[]>([]);
  const [selectedSpace, setSelectedSpace] = useState<string>('');
  const [spacesLoading, setSpacesLoading] = useState(true);

  // Graphs (for building entity detail links)
  const [graphs, setGraphs] = useState<{ graph_uri: string; graph_id?: string }[]>([]);

  // Search config
  const [searchMode, setSearchMode] = useState<SearchMode>('vector');
  const [searchText, setSearchText] = useState('');
  const [indexName, setIndexName] = useState('');
  const [availableIndexes, setAvailableIndexes] = useState<string[]>([]);
  const [indexesLoading, setIndexesLoading] = useState(false);
  const [mappingProperties, setMappingProperties] = useState<string[]>([]);
  const [topK, setTopK] = useState(10);
  const [minScore, setMinScore] = useState(0.5);
  const [alpha, setAlpha] = useState(0.5);

  // Geo config
  const [geoSubMode, setGeoSubMode] = useState<GeoSubMode>('radius');
  const [lat, setLat] = useState(40.7128);
  const [lon, setLon] = useState(-74.006);
  const [radius, setRadius] = useState(5000);
  const [minLat, setMinLat] = useState(40.7);
  const [minLon, setMinLon] = useState(-74.02);
  const [maxLat, setMaxLat] = useState(40.75);
  const [maxLon, setMaxLon] = useState(-73.97);
  const [polygonWkt, setPolygonWkt] = useState('POLYGON((-74.0 40.7, -73.9 40.7, -73.9 40.8, -74.0 40.8, -74.0 40.7))');

  // Generated SPARQL & results
  const [generatedSparql, setGeneratedSparql] = useState('');
  const [showSparql, setShowSparql] = useState(false);
  const [results, setResults] = useState<SparqlBinding[]>([]);
  const [resultColumns, setResultColumns] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [queryTime, setQueryTime] = useState<number | null>(null);

  const isRegistrySpace = selectedSpace === 'entity_registry' || selectedSpace === 'agent_registry';

  // Load spaces (including registry pseudo-spaces)
  useEffect(() => {
    const loadSpaces = async () => {
      try {
        const data = await apiService.getSpaces();
        const registrySpaces: SpaceInfo[] = [
          { space: 'entity_registry', space_name: 'Entity Registry', created_time: '', updated_time: '' },
          { space: 'agent_registry', space_name: 'Agent Registry', created_time: '', updated_time: '' },
        ];
        const allSpaces = [...registrySpaces, ...data];
        setSpaces(allSpaces);
        if (allSpaces.length > 0) {
          setSelectedSpace(allSpaces[0].space);
        }
      } catch {
        setError('Failed to load spaces');
      } finally {
        setSpacesLoading(false);
      }
    };
    loadSpaces();
  }, []);

  // Load graphs when space changes (needed for entity detail links)
  useEffect(() => {
    const loadGraphs = async () => {
      if (!selectedSpace || isRegistrySpace) {
        setGraphs([]);
        return;
      }
      try {
        const data = await apiService.getGraphs(selectedSpace);
        setGraphs(data);
      } catch {
        setGraphs([]);
      }
    };
    loadGraphs();
  }, [selectedSpace, isRegistrySpace]);

  // Load indexes when space changes (skip for registry spaces)
  const loadIndexes = useCallback(async () => {
    if (!selectedSpace || isRegistrySpace) {
      setAvailableIndexes([]);
      return;
    }
    setIndexesLoading(true);
    try {
      const [vectorIndexes, ftsIndexes] = await Promise.all([
        vectorGeoService.getVectorIndexes(selectedSpace),
        searchFtsService.getFtsIndexes(selectedSpace),
      ]);
      const names = [
        ...vectorIndexes.map((vi) => vi.index_name),
        ...ftsIndexes.map((fi) => fi.index_name),
      ];
      // Deduplicate
      const unique = [...new Set(names)].sort();
      setAvailableIndexes(unique);
      if (unique.length > 0 && !indexName) {
        setIndexName(unique[0]);
      }
    } catch {
      setAvailableIndexes([]);
    } finally {
      setIndexesLoading(false);
    }
  }, [selectedSpace, isRegistrySpace]);

  useEffect(() => {
    loadIndexes();
  }, [loadIndexes]);

  // Load mapping properties based on search mode
  useEffect(() => {
    const loadMapping = async () => {
      if (!selectedSpace) {
        setMappingProperties([]);
        return;
      }
      try {
        if (searchMode === 'fuzzy') {
          // Load properties from fuzzy mapping
          const mappings = await fuzzyMappingService.getFuzzyMappings(selectedSpace);
          if (mappings.length > 0) {
            const props = mappings[0].properties
              .map((p) => p.property_uri);
            setMappingProperties(props);
          } else {
            setMappingProperties([]);
          }
        } else if (searchMode === 'keyword' || searchMode === 'geo') {
          setMappingProperties([]);
        } else {
          // vector/fts/hybrid — load from search mapping
          if (!indexName) {
            setMappingProperties([]);
            return;
          }
          const mappings = await searchFtsService.getSearchMappings(selectedSpace, { index_name: indexName });
          if (mappings.length > 0) {
            const props = mappings[0].properties
              .filter((p) => p.property_role === 'include')
              .map((p) => p.property_uri);
            setMappingProperties(props);
          } else {
            setMappingProperties([]);
          }
        }
      } catch {
        setMappingProperties([]);
      }
    };
    loadMapping();
  }, [selectedSpace, indexName, searchMode]);

  // Regenerate SPARQL when params change
  useEffect(() => {
    const sparql = generateSparql(
      searchMode, searchText, indexName, topK, minScore, alpha,
      geoSubMode, lat, lon, radius, minLat, minLon, maxLat, maxLon, polygonWkt,
      mappingProperties,
    );
    setGeneratedSparql(sparql);
  }, [searchMode, searchText, indexName, topK, minScore, alpha, geoSubMode, lat, lon, radius, minLat, minLon, maxLat, maxLon, polygonWkt, mappingProperties]);

  const handleSearch = async () => {
    if (!selectedSpace) return;
    if (searchMode !== 'geo' && !searchText.trim()) return;

    setLoading(true);
    setError(null);
    setResults([]);
    setResultColumns([]);
    setQueryTime(null);

    try {
      const startTime = performance.now();

      if (selectedSpace === 'entity_registry') {
        // Entity registry: dispatch by search mode
        let rawResults: Record<string, unknown>[] = [];

        if (searchMode === 'vector' || searchMode === 'fts' || searchMode === 'hybrid') {
          // Semantic vector search via Weaviate
          const response = await apiService.searchRegistryEntity({ q: searchText, limit: topK, min_certainty: minScore });
          rawResults = response?.results || [];
        } else if (searchMode === 'fuzzy') {
          // Fuzzy name matching (MinHash LSH)
          const response = await apiService.findSimilarEntities({ name: searchText, limit: topK, min_score: minScore });
          rawResults = response?.candidates || [];
        } else if (searchMode === 'geo') {
          // Geo search via entity search endpoint
          const response = await apiService.searchRegistryEntity({ latitude: lat, longitude: lon, radius_km: radius / 1000, limit: topK });
          rawResults = response?.results || [];
        } else {
          // Keyword (ILIKE)
          const response = await apiService.listRegistryEntities({ query: searchText, limit: topK });
          rawResults = response?.entities || response?.items || [];
        }

        const elapsed = performance.now() - startTime;
        setQueryTime(elapsed);
        const bindings: SparqlBinding[] = rawResults.map((e: Record<string, unknown>) => {
          const row: SparqlBinding = {};
          row['entity_id'] = { type: 'literal', value: String(e.entity_id || e.id || '') };
          row['name'] = { type: 'literal', value: String(e.name || e.canonical_name || '') };
          row['type'] = { type: 'literal', value: String(e.entity_type || e.type_key || '') };
          if (e.score != null) row['score'] = { type: 'literal', value: String(e.score) };
          if (e.certainty != null) row['score'] = { type: 'literal', value: String(e.certainty) };
          if (e.distance != null) row['distance'] = { type: 'literal', value: String(e.distance) };
          return row;
        });
        setResults(bindings);
        if (bindings.length > 0) setResultColumns(Object.keys(bindings[0]));

      } else if (selectedSpace === 'agent_registry') {
        // Agent registry: keyword search only
        const response = await apiService.listAgents({ query: searchText, limit: topK });
        const elapsed = performance.now() - startTime;
        setQueryTime(elapsed);
        const agents = response?.agents || response?.items || [];
        const bindings: SparqlBinding[] = agents.map((a: Record<string, unknown>) => {
          const row: SparqlBinding = {};
          row['agent_id'] = { type: 'literal', value: String(a.agent_id || a.id || '') };
          row['name'] = { type: 'literal', value: String(a.name || a.agent_name || '') };
          row['type'] = { type: 'literal', value: String(a.agent_type || '') };
          row['status'] = { type: 'literal', value: String(a.status || '') };
          return row;
        });
        setResults(bindings);
        if (bindings.length > 0) setResultColumns(Object.keys(bindings[0]));

      } else {
        // Regular space: use SPARQL
        const response = await apiService.executeSparqlQuery(selectedSpace, generatedSparql);
        const elapsed = performance.now() - startTime;
        setQueryTime(elapsed);
        const bindings: SparqlBinding[] = response?.results?.bindings || [];
        setResults(bindings);
        if (bindings.length > 0) {
          setResultColumns(Object.keys(bindings[0]));
        }
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Search failed');
    } finally {
      setLoading(false);
    }
  };

  // Entity registry supports: vector, fuzzy, keyword, geo
  // Agent registry supports: keyword only
  const registryModes: SearchMode[] = selectedSpace === 'entity_registry'
    ? ['vector', 'fuzzy', 'keyword', 'geo']
    : ['keyword'];
  const needsIndex = !isRegistrySpace && (searchMode === 'vector' || searchMode === 'fts' || searchMode === 'hybrid');
  const needsText = searchMode !== 'geo';

  return (
    <div data-testid="semantic-search-page">
      <Breadcrumb className="mb-6">
        <BreadcrumbItem href="/" icon={HiHome}>Home</BreadcrumbItem>
        <BreadcrumbItem>Semantic Search</BreadcrumbItem>
      </Breadcrumb>

      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white" data-testid="semantic-search-title">Semantic Search</h1>
        <Badge color="info">SPARQL Index Testing</Badge>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Controls Panel */}
        <Card className="lg:col-span-1">
          <h2 className="text-lg font-semibold mb-4">Search Configuration</h2>

          {/* Space Selector */}
          <div className="mb-4">
            <Label htmlFor="space">Space</Label>
            {spacesLoading ? (
              <Spinner size="sm" />
            ) : (
              <Select
                id="space"
                value={selectedSpace}
                onChange={(e) => setSelectedSpace(e.target.value)}
              >
                {spaces.map((s) => (
                  <option key={s.space} value={s.space}>{s.space_name || s.space}</option>
                ))}
              </Select>
            )}
          </div>

          {/* Search Mode */}
          <div className="mb-4">
            <Label htmlFor="mode">Search Mode</Label>
            <Select
              id="mode"
              value={searchMode}
              onChange={(e) => setSearchMode(e.target.value as SearchMode)}
            >
              {(isRegistrySpace
                ? SEARCH_MODES.filter((m) => registryModes.includes(m.value as SearchMode))
                : SEARCH_MODES
              ).map((m) => (
                <option key={m.value} value={m.value}>{m.label}</option>
              ))}
            </Select>
          </div>

          {/* Text Input */}
          {needsText && (
            <div className="mb-4">
              <Label htmlFor="searchText">Search Text</Label>
              <TextInput
                id="searchText"
                placeholder="Enter search query..."
                value={searchText}
                onChange={(e) => setSearchText(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
              />
            </div>
          )}

          {/* Index Name */}
          {needsIndex && (
            <div className="mb-4">
              <Label htmlFor="indexName">Index Name</Label>
              {indexesLoading ? (
                <Spinner size="sm" />
              ) : availableIndexes.length > 0 ? (
                <Select
                  id="indexName"
                  value={indexName}
                  onChange={(e) => setIndexName(e.target.value)}
                >
                  {availableIndexes.map((name) => (
                    <option key={name} value={name}>{name}</option>
                  ))}
                </Select>
              ) : (
                <TextInput
                  id="indexName"
                  placeholder="e.g. entity_default"
                  value={indexName}
                  onChange={(e) => setIndexName(e.target.value)}
                />
              )}
            </div>
          )}

          {/* Top-K */}
          <div className="mb-4">
            <Label htmlFor="topK">{`Top-K: ${topK}`}</Label>
            <TextInput
              id="topK"
              type="number"
              value={topK}
              onChange={(e) => setTopK(parseInt(e.target.value) || 10)}
              min={1}
              max={100}
            />
          </div>

          {/* Min Score (vector, fuzzy) */}
          {(searchMode === 'vector' || searchMode === 'fuzzy') && (
            <div className="mb-4">
              <Label htmlFor="minScore">{`Min Score: ${minScore}`}</Label>
              <TextInput
                id="minScore"
                type="number"
                step="0.1"
                value={minScore}
                onChange={(e) => setMinScore(parseFloat(e.target.value) || 0)}
                min={0}
                max={searchMode === 'fuzzy' ? 100 : 1}
              />
            </div>
          )}

          {/* Alpha (hybrid) */}
          {!isRegistrySpace && searchMode === 'hybrid' && (
            <div className="mb-4">
              <Label htmlFor="alpha">{`Alpha (vector weight): ${alpha}`}</Label>
              <TextInput
                id="alpha"
                type="number"
                step="0.1"
                value={alpha}
                onChange={(e) => setAlpha(parseFloat(e.target.value) || 0.5)}
                min={0}
                max={1}
              />
            </div>
          )}

          {/* Geo Controls */}
          {searchMode === 'geo' && (
            <>
              <div className="mb-4">
                <Label htmlFor="geoSubMode">Geo Query Type</Label>
                <Select
                  id="geoSubMode"
                  value={geoSubMode}
                  onChange={(e) => setGeoSubMode(e.target.value as GeoSubMode)}
                >
                  {GEO_SUB_MODES.map((m) => (
                    <option key={m.value} value={m.value}>{m.label}</option>
                  ))}
                </Select>
              </div>

              {geoSubMode === 'radius' && (
                <>
                  <div className="mb-2">
                    <Label htmlFor="lat">Latitude</Label>
                    <TextInput id="lat" type="number" step="0.0001" value={lat} onChange={(e) => setLat(parseFloat(e.target.value))} />
                  </div>
                  <div className="mb-2">
                    <Label htmlFor="lon">Longitude</Label>
                    <TextInput id="lon" type="number" step="0.0001" value={lon} onChange={(e) => setLon(parseFloat(e.target.value))} />
                  </div>
                  <div className="mb-4">
                    <Label htmlFor="radius">{`Radius (meters): ${radius}`}</Label>
                    <TextInput id="radius" type="number" value={radius} onChange={(e) => setRadius(parseInt(e.target.value) || 5000)} />
                  </div>
                </>
              )}

              {geoSubMode === 'bounds' && (
                <>
                  <div className="grid grid-cols-2 gap-2 mb-4">
                    <div>
                      <Label htmlFor="minLat">Min Lat</Label>
                      <TextInput id="minLat" type="number" step="0.01" value={minLat} onChange={(e) => setMinLat(parseFloat(e.target.value))} />
                    </div>
                    <div>
                      <Label htmlFor="minLon">Min Lon</Label>
                      <TextInput id="minLon" type="number" step="0.01" value={minLon} onChange={(e) => setMinLon(parseFloat(e.target.value))} />
                    </div>
                    <div>
                      <Label htmlFor="maxLat">Max Lat</Label>
                      <TextInput id="maxLat" type="number" step="0.01" value={maxLat} onChange={(e) => setMaxLat(parseFloat(e.target.value))} />
                    </div>
                    <div>
                      <Label htmlFor="maxLon">Max Lon</Label>
                      <TextInput id="maxLon" type="number" step="0.01" value={maxLon} onChange={(e) => setMaxLon(parseFloat(e.target.value))} />
                    </div>
                  </div>
                </>
              )}

              {geoSubMode === 'polygon' && (
                <div className="mb-4">
                  <Label htmlFor="polygonWkt">Polygon (WKT)</Label>
                  <Textarea
                    id="polygonWkt"
                    rows={3}
                    value={polygonWkt}
                    onChange={(e) => setPolygonWkt(e.target.value)}
                    placeholder="POLYGON((-74.0 40.7, ...))"
                  />
                </div>
              )}
            </>
          )}

          {/* Search Button */}
          <Button color="blue" onClick={handleSearch} disabled={loading} className="w-full">
            {loading ? <Spinner size="sm" className="mr-2" /> : <HiSearch className="mr-2 h-4 w-4" />}
            Search
          </Button>

          {/* Show SPARQL Toggle */}
          <div className="mt-4">
            <ToggleSwitch
              checked={showSparql}
              label="Show Generated SPARQL"
              onChange={setShowSparql}
            />
          </div>
        </Card>

        {/* Results Panel */}
        <div className="lg:col-span-2 space-y-4">
          {/* Generated SPARQL */}
          {showSparql && (
            <Card>
              <div className="flex items-center gap-2 mb-2">
                <HiCode className="h-5 w-5 text-gray-500" />
                <h3 className="font-semibold">Generated SPARQL</h3>
              </div>
              <pre className="bg-gray-50 dark:bg-gray-800 p-3 rounded text-xs overflow-x-auto whitespace-pre-wrap font-mono">
                {generatedSparql}
              </pre>
            </Card>
          )}

          {/* Error */}
          {error && (
            <Alert color="failure" onDismiss={() => setError(null)}>
              {error}
            </Alert>
          )}

          {/* Results */}
          <Card>
            <div className="flex items-center justify-between mb-2">
              <h3 className="font-semibold">Results</h3>
              <div className="flex gap-2 text-sm text-gray-500">
                {queryTime !== null && <span>{queryTime.toFixed(0)}ms</span>}
                <span>{results.length} rows</span>
              </div>
            </div>

            {loading ? (
              <div className="flex justify-center py-8">
                <Spinner size="lg" />
              </div>
            ) : results.length === 0 ? (
              <p className="text-gray-500 text-sm py-4">No results. Execute a search to see results.</p>
            ) : (
              <div className="overflow-x-auto">
                <Table striped>
                  <TableHead>
                    <TableRow>
                      <TableHeadCell className="w-16">Detail</TableHeadCell>
                      {resultColumns.map((col) => (
                        <TableHeadCell key={col}>{col}</TableHeadCell>
                      ))}
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {results.map((row, i) => {
                      // Build detail link based on space type
                      let detailPath: string | null = null;
                      if (selectedSpace === 'entity_registry') {
                        const eid = row['entity_id']?.value;
                        if (eid) detailPath = `/entity-registry/${encodeURIComponent(eid)}`;
                      } else if (selectedSpace === 'agent_registry') {
                        const aid = row['agent_id']?.value;
                        if (aid) detailPath = `/agent-registry/${encodeURIComponent(aid)}`;
                      } else {
                        // Regular space: link to search result detail screen
                        const entityUri = row['entity']?.value;
                        if (entityUri && graphs.length > 0) {
                          const graphUri = graphs[0].graph_uri;
                          detailPath = `/space/${encodeURIComponent(selectedSpace)}/graph/${encodeURIComponent(graphUri)}/search-result/${encodeURIComponent(entityUri)}`;
                        }
                      }
                      return (
                        <TableRow key={i}>
                          <TableCell>
                            {detailPath ? (
                              <Button size="xs" color="light" onClick={() => navigate(detailPath!)}>
                                <HiExternalLink className="h-4 w-4" />
                              </Button>
                            ) : (
                              <span className="text-gray-300">—</span>
                            )}
                          </TableCell>
                          {resultColumns.map((col) => (
                            <TableCell key={col} className="max-w-xs truncate" title={row[col]?.value}>
                              {row[col]?.value || ''}
                            </TableCell>
                          ))}
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
};

export default SemanticSearch;

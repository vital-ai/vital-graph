import React, { useState, useEffect, useCallback } from 'react';
import { apiService } from '../services/ApiService';
import {
  Alert, Badge, Breadcrumb, BreadcrumbItem, Button, Card, Label, Select, Spinner, TextInput,
  Table, TableBody, TableCell, TableHead, TableHeadCell, TableRow,
  ToggleSwitch,
} from 'flowbite-react';
import {
  HiSearch, HiPlay, HiTrash, HiPlus, HiCode,
  HiLightningBolt, HiSortAscending, HiSortDescending, HiChevronLeft,
  HiExternalLink,
} from 'react-icons/hi';
import { usePageTitle } from '../hooks/usePageTitle';
import { type SpaceInfo } from '../types/api';
import { type GraphInfo } from '../types/graphs';
import { shortenUri, type Quad, quadsToProperties, type ParsedProperty, RDF_TYPE, HAS_NAME, stripBrackets } from '../utils/QuadUtils';

// ─── Types ───────────────────────────────────────────────────────────

interface PropertyFilter {
  id: string;
  property_uri: string;
  operator: string;
  value: string;
}

interface SlotCriteria {
  id: string;
  slot_type: string;
  value: string;
  comparator: string;
}

interface FrameCriteria {
  id: string;
  frame_type_uri: string;
  slots: SlotCriteria[];
}

interface SortItem {
  id: string;
  sort_type: string;
  property_uri: string;
  direction: string;
}

const OPERATORS = [
  { value: 'eq', label: '= equals' },
  { value: 'ne', label: '≠ not equals' },
  { value: 'contains', label: '∋ contains' },
  { value: 'gt', label: '> greater than' },
  { value: 'lt', label: '< less than' },
  { value: 'gte', label: '≥ greater or equal' },
  { value: 'lte', label: '≤ less or equal' },
  { value: 'exists', label: '∃ exists' },
  { value: 'not_exists', label: '∄ not exists' },
];

const SLOT_COMPARATORS = [
  { value: 'eq', label: '= equals' },
  { value: 'ne', label: '≠ not equals' },
  { value: 'contains', label: '∋ contains' },
  { value: 'gt', label: '> greater than' },
  { value: 'lt', label: '< less than' },
  { value: 'exists', label: '∃ exists' },
  { value: 'not_exists', label: '∄ not exists' },
];

const QUERY_TYPES = [
  { value: 'entity', label: 'Entity Query', desc: 'Find entities matching property/frame criteria' },
  { value: 'relation', label: 'Relation Query', desc: 'Find entities connected via edges' },
  { value: 'frame_query', label: 'Frame Query', desc: 'Find frames matching slot criteria' },
];

interface KGQueryResult {
  query_type: string;
  total_count: number;
  page_size: number;
  offset: number;
  entity_uris?: string[];
  relation_connections?: Array<{ source_entity_uri: string; relation_type_uri: string; destination_entity_uri: string }>;
  frame_results?: Array<{ frame_uri: string; frame_type_uri: string; entity_refs?: Array<{ slot_type_uri: string; entity_uri: string }> }>;
  frame_connections?: Array<{ source_entity_uri: string; shared_frame_uri: string; destination_entity_uri: string }>;
}

interface DetailEntry {
  uri: string;
  label: string;
  kind: 'entity' | 'frame';
}

let _id = 0;
const uid = () => `_${++_id}`;

// ─── Component ───────────────────────────────────────────────────────

const KGQueryBuilder: React.FC = () => {
  usePageTitle('KG Query Builder');

  // Space/Graph selection
  const [spaces, setSpaces] = useState<SpaceInfo[]>([]);
  const [selectedSpace, setSelectedSpace] = useState('');
  const [graphs, setGraphs] = useState<GraphInfo[]>([]);
  const [selectedGraph, setSelectedGraph] = useState('');
  const [spacesLoading, setSpacesLoading] = useState(true);
  const [graphsLoading, setGraphsLoading] = useState(false);

  // Query config
  const [queryType, setQueryType] = useState('entity');
  const [direction, setDirection] = useState('outgoing');
  const [entitySearch, setEntitySearch] = useState('');
  const [entityTypeUri, setEntityTypeUri] = useState('');
  const [propertyFilters, setPropertyFilters] = useState<PropertyFilter[]>([]);
  const [frameCriteria, setFrameCriteria] = useState<FrameCriteria[]>([]);
  const [sortItems, setSortItems] = useState<SortItem[]>([]);
  const [sourceEntityUri, setSourceEntityUri] = useState('');
  const [relationTypeUri, setRelationTypeUri] = useState('');
  const [pageSize, setPageSize] = useState(10);
  const [includeEntityGraph, setIncludeEntityGraph] = useState(false);
  const [includeFrameGraph, setIncludeFrameGraph] = useState(false);

  // Results
  const [results, setResults] = useState<KGQueryResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState<number | null>(null);

  // Tab & view
  const [activeTab, setActiveTab] = useState<'builder' | 'json'>('builder');
  const [view, setView] = useState<'builder' | 'results' | 'detail'>('builder');

  // Detail navigation stack
  const [detailStack, setDetailStack] = useState<DetailEntry[]>([]);
  const [detailQuads, setDetailQuads] = useState<Quad[]>([]);
  const [detailRelations, setDetailRelations] = useState<Array<{ source: string; destination: string; type: string }>>([]);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  // ─── Data loading ───────────────────────────────────────────────

  const fetchSpaces = useCallback(async () => {
    try {
      setSpacesLoading(true);
      const data = await apiService.getSpaces();
      setSpaces(data);
      if (data.length > 0 && !selectedSpace) setSelectedSpace(data[0].space);
    } catch { /* ignore */ } finally { setSpacesLoading(false); }
  }, []);

  const fetchGraphs = useCallback(async () => {
    if (!selectedSpace) { setGraphs([]); return; }
    try {
      setGraphsLoading(true);
      const data = await apiService.getGraphs(selectedSpace);
      setGraphs(data);
      if (data.length > 0) setSelectedGraph(data[0].graph_uri || '');
      else setSelectedGraph('');
    } catch { setGraphs([]); } finally { setGraphsLoading(false); }
  }, [selectedSpace]);

  useEffect(() => { fetchSpaces(); }, [fetchSpaces]);
  useEffect(() => { fetchGraphs(); }, [fetchGraphs]);

  // ─── Query building ─────────────────────────────────────────────

  const buildRequest = (): Record<string, unknown> => {
    const criteria: Record<string, unknown> = { query_type: queryType };

    if (queryType === 'entity') {
      const entityCriteria: Record<string, unknown> = {};
      if (entitySearch) entityCriteria.search_string = entitySearch;
      if (entityTypeUri) entityCriteria.entity_type = entityTypeUri;
      criteria.source_entity_criteria = entityCriteria;

      if (propertyFilters.length > 0) {
        criteria.entity_property_filters = propertyFilters
          .filter(f => f.property_uri)
          .map(f => ({
            property_uri: f.property_uri,
            operator: f.operator,
            value: f.operator === 'exists' || f.operator === 'not_exists' ? undefined : f.value,
          }));
      }
    }

    if (queryType === 'relation') {
      criteria.direction = direction;
      if (sourceEntityUri) criteria.source_entity_uris = [sourceEntityUri];
      if (relationTypeUri) criteria.relation_type_uris = [relationTypeUri];
    }

    if (queryType === 'frame_query' || frameCriteria.length > 0) {
      criteria.frame_criteria = frameCriteria
        .filter(fc => fc.frame_type_uri)
        .map(fc => ({
          frame_type_uri: fc.frame_type_uri,
          slot_criteria: fc.slots
            .filter(s => s.slot_type)
            .map(s => ({
              slot_type: s.slot_type,
              value: s.comparator === 'exists' || s.comparator === 'not_exists' ? undefined : s.value,
              comparator: s.comparator,
            })),
        }));
    }

    if (sortItems.length > 0) {
      criteria.sort_criteria = sortItems
        .filter(s => s.property_uri)
        .map(s => ({
          sort_type: s.sort_type,
          property_uri: s.property_uri,
          direction: s.direction,
        }));
    }

    const request: Record<string, unknown> = {
      criteria,
      page_size: pageSize,
      offset: 0,
    };
    if (includeEntityGraph) request.include_entity_graph = true;
    if (includeFrameGraph) request.include_frame_graph = true;

    return request;
  };

  const executeQuery = async () => {
    if (!selectedSpace || !selectedGraph) return;
    const body = buildRequest();
    try {
      setLoading(true);
      setError(null);
      setResults(null);
      setView('results');
      const t0 = performance.now();
      const data = await apiService.kgQuery(selectedSpace, selectedGraph, body);
      setElapsed(Math.round(performance.now() - t0));
      setResults(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Query failed');
    } finally {
      setLoading(false);
    }
  };

  // ─── Filter management ──────────────────────────────────────────

  const addPropertyFilter = () => setPropertyFilters(f => [...f, { id: uid(), property_uri: '', operator: 'eq', value: '' }]);
  const removePropertyFilter = (id: string) => setPropertyFilters(f => f.filter(x => x.id !== id));
  const updatePropertyFilter = (id: string, field: keyof PropertyFilter, val: string) =>
    setPropertyFilters(f => f.map(x => x.id === id ? { ...x, [field]: val } : x));

  const addFrameCriteria = () => setFrameCriteria(fc => [...fc, { id: uid(), frame_type_uri: '', slots: [] }]);
  const removeFrameCriteria = (id: string) => setFrameCriteria(fc => fc.filter(x => x.id !== id));
  const updateFrameType = (id: string, val: string) => setFrameCriteria(fc => fc.map(x => x.id === id ? { ...x, frame_type_uri: val } : x));
  const addSlot = (fcId: string) => setFrameCriteria(fc => fc.map(x => x.id === fcId ? { ...x, slots: [...x.slots, { id: uid(), slot_type: '', value: '', comparator: 'eq' }] } : x));
  const removeSlot = (fcId: string, slotId: string) => setFrameCriteria(fc => fc.map(x => x.id === fcId ? { ...x, slots: x.slots.filter(s => s.id !== slotId) } : x));
  const updateSlot = (fcId: string, slotId: string, field: keyof SlotCriteria, val: string) =>
    setFrameCriteria(fc => fc.map(x => x.id === fcId ? { ...x, slots: x.slots.map(s => s.id === slotId ? { ...s, [field]: val } : s) } : x));

  const addSort = () => setSortItems(s => [...s, { id: uid(), sort_type: 'entity_property', property_uri: '', direction: 'asc' }]);
  const removeSort = (id: string) => setSortItems(s => s.filter(x => x.id !== id));
  const updateSort = (id: string, field: keyof SortItem, val: string) =>
    setSortItems(s => s.map(x => x.id === id ? { ...x, [field]: val } : x));

  // ─── Detail navigation ─────────────────────────────────────────

  const navigateToDetail = async (uri: string, kind: 'entity' | 'frame') => {
    if (!selectedSpace || !selectedGraph) return;
    const label = shortenUri(uri);
    setDetailStack(prev => [...prev, { uri, label, kind }]);
    setView('detail');
    setDetailLoading(true);
    setDetailError(null);
    setDetailQuads([]);
    setDetailRelations([]);
    try {
      // Fetch entity/frame quads
      const resp = kind === 'entity'
        ? await apiService.getEntity(selectedSpace, selectedGraph, uri)
        : await apiService.getFrame(selectedSpace, selectedGraph, uri);
      setDetailQuads(resp.results || []);
      // Fetch relations (only for entities)
      if (kind === 'entity') {
        try {
          const relResp = await apiService.getRelations(selectedSpace, selectedGraph, {
            entity_source_uri: uri,
            page_size: 50,
          });
          const rels: Array<{ source: string; destination: string; type: string }> = [];
          const relQuads: Quad[] = relResp.results || [];
          const relBySubject = new Map<string, Map<string, string>>();
          for (const rq of relQuads) {
            if (!relBySubject.has(rq.s)) relBySubject.set(rq.s, new Map());
            relBySubject.get(rq.s)!.set(rq.p, rq.o);
          }
          for (const [, preds] of relBySubject) {
            const src = preds.get('http://vital.ai/ontology/vital-core#hasEdgeSource');
            const dst = preds.get('http://vital.ai/ontology/vital-core#hasEdgeDestination');
            const rdfType = preds.get('http://www.w3.org/1999/02/22-rdf-syntax-ns#type');
            if (src && dst) {
              rels.push({
                source: stripBrackets(src),
                destination: stripBrackets(dst),
                type: rdfType ? stripBrackets(rdfType) : 'unknown',
              });
            }
          }
          setDetailRelations(rels);
        } catch { /* relations optional */ }
      }
    } catch (err) {
      setDetailError(err instanceof Error ? err.message : 'Failed to load detail');
    } finally {
      setDetailLoading(false);
    }
  };

  const navigateBack = (toIndex: number) => {
    if (toIndex < 0) {
      setView('results');
      setDetailStack([]);
    } else {
      // Trim stack to clicked item then re-fetch its data
      const entry = detailStack[toIndex];
      setDetailStack(detailStack.slice(0, toIndex));
      navigateToDetail(entry.uri, entry.kind);
    }
  };

  // Helper: render a clickable URI link
  const UriLink: React.FC<{ uri: string; kind?: 'entity' | 'frame' }> = ({ uri, kind = 'entity' }) => (
    <button
      onClick={() => navigateToDetail(uri, kind)}
      className="font-mono text-xs text-blue-600 dark:text-blue-400 hover:underline hover:text-blue-800 dark:hover:text-blue-300 inline-flex items-center gap-1"
      title={uri}
    >
      {shortenUri(uri)}
      <HiExternalLink className="h-3 w-3 opacity-50" />
    </button>
  );

  // ─── Render ─────────────────────────────────────────────────────

  const hasSelection = selectedSpace && selectedGraph;

  const tabCls = (tab: 'builder' | 'json') =>
    `px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
      activeTab === tab
        ? 'border-blue-600 text-blue-600 dark:border-blue-500 dark:text-blue-500'
        : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400'
    }`;

  // ─── Detail View ────────────────────────────────────────────────
  if (view === 'detail' && detailStack.length > 0) {
    const current = detailStack[detailStack.length - 1];
    const properties: ParsedProperty[] = quadsToProperties(detailQuads);
    const entityName = detailQuads.find(q => q.p === HAS_NAME)?.o?.replace(/^"|"$/g, '') || current.label;
    const entityType = detailQuads.find(q => q.p === RDF_TYPE)?.o;

    return (
      <div className="space-y-6">
        {/* Breadcrumb */}
        <Breadcrumb>
          <BreadcrumbItem onClick={() => { setView('builder'); setDetailStack([]); }} href="#">
            KG Query Builder
          </BreadcrumbItem>
          <BreadcrumbItem onClick={() => navigateBack(-1)} href="#">
            Results
          </BreadcrumbItem>
          {detailStack.map((entry, i) => (
            i < detailStack.length - 1 ? (
              <BreadcrumbItem key={i} onClick={() => navigateBack(i)} href="#">
                {entry.label}
              </BreadcrumbItem>
            ) : (
              <BreadcrumbItem key={i}>{entry.label}</BreadcrumbItem>
            )
          ))}
        </Breadcrumb>

        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div className="flex items-center gap-3">
            <Button size="xs" color="light" onClick={() => navigateBack(detailStack.length - 2)}>
              <HiChevronLeft className="h-4 w-4 mr-1" />
              {detailStack.length > 1 ? 'Back' : 'Back to Results'}
            </Button>
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center gap-2">
              {entityName}
              <Badge color={current.kind === 'entity' ? 'info' : 'indigo'} size="sm">
                {current.kind}
              </Badge>
            </h2>
          </div>
        </div>

        {detailError && <Alert color="failure" onDismiss={() => setDetailError(null)}>{detailError}</Alert>}

        {detailLoading ? (
          <div className="flex justify-center py-12"><Spinner size="xl" /></div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Properties */}
            <Card>
              <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3 flex items-center gap-2">
                Properties
                <Badge color="gray" size="xs">{properties.length}</Badge>
              </h3>
              {entityType && (
                <div className="mb-3 flex items-center gap-2">
                  <span className="text-xs text-gray-500">Type:</span>
                  <Badge color="purple" size="xs">{shortenUri(entityType.replace(/^<|>$/g, ''))}</Badge>
                </div>
              )}
              {properties.length === 0 ? (
                <p className="text-xs text-gray-400">No properties found.</p>
              ) : (
                <div className="overflow-x-auto">
                  <Table striped>
                    <TableHead>
                      <TableHeadCell>Property</TableHeadCell>
                      <TableHeadCell>Value</TableHeadCell>
                    </TableHead>
                    <TableBody>
                      {properties.map((prop, i) => (
                        <TableRow key={i}>
                          <TableCell className="font-mono text-xs text-gray-600 dark:text-gray-400">
                            {shortenUri(prop.predicate)}
                          </TableCell>
                          <TableCell className="text-xs">
                            {prop.object_type === 'uri' ? (
                              <UriLink uri={prop.object} kind="entity" />
                            ) : (
                              <span className="text-gray-800 dark:text-gray-200">{prop.object}</span>
                            )}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </Card>

            {/* Relations */}
            {current.kind === 'entity' && (
              <Card>
                <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3 flex items-center gap-2">
                  Relations
                  <Badge color="gray" size="xs">{detailRelations.length}</Badge>
                </h3>
                {detailRelations.length === 0 ? (
                  <p className="text-xs text-gray-400">No relations found from this entity.</p>
                ) : (
                  <div className="overflow-x-auto">
                    <Table striped>
                      <TableHead>
                        <TableHeadCell>Type</TableHeadCell>
                        <TableHeadCell>Destination</TableHeadCell>
                      </TableHead>
                      <TableBody>
                        {detailRelations.map((rel, i) => (
                          <TableRow key={i}>
                            <TableCell>
                              <Badge color="purple" size="xs">{shortenUri(rel.type)}</Badge>
                            </TableCell>
                            <TableCell>
                              <UriLink uri={rel.destination === current.uri ? rel.source : rel.destination} kind="entity" />
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                )}
              </Card>
            )}
          </div>
        )}

        {/* Raw quads */}
        <details>
          <summary className="text-xs text-gray-500 cursor-pointer hover:text-gray-700 dark:hover:text-gray-300">
            Raw Quads ({detailQuads.length})
          </summary>
          <pre className="text-xs bg-gray-50 dark:bg-gray-900 text-gray-800 dark:text-gray-200 p-3 rounded-lg overflow-x-auto max-h-48 font-mono mt-2 border border-gray-200 dark:border-gray-700">
            {JSON.stringify(detailQuads, null, 2)}
          </pre>
        </details>
      </div>
    );
  }

  // ─── Results View ───────────────────────────────────────────────
  if (view === 'results') {
    return (
      <div className="space-y-6">
        {/* Breadcrumb */}
        <Breadcrumb>
          <BreadcrumbItem onClick={() => setView('builder')} href="#">
            KG Query Builder
          </BreadcrumbItem>
          <BreadcrumbItem>Results</BreadcrumbItem>
        </Breadcrumb>

        {/* Header bar */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div className="flex items-center gap-3">
            <Button size="xs" color="light" onClick={() => setView('builder')}>
              <HiChevronLeft className="h-4 w-4 mr-1" />Back to Query
            </Button>
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center gap-2">
              Query Results
              {results && <Badge color="info" size="sm">{String(results.total_count ?? 0)} total</Badge>}
              {elapsed !== null && <Badge color="gray" size="sm">{elapsed}ms</Badge>}
            </h2>
          </div>
          <Button size="sm" color="blue" onClick={executeQuery} disabled={loading}>
            <HiPlay className="mr-1.5 h-4 w-4" />{loading ? 'Running...' : 'Re-run'}
          </Button>
        </div>

        {error && <Alert color="failure" onDismiss={() => setError(null)}>{error}</Alert>}

        {loading ? (
          <div className="flex justify-center py-12"><Spinner size="xl" /></div>
        ) : results && (
          <Card>
            <div className="space-y-4">
              {/* Entity results */}
              {results.query_type === 'entity' && results.entity_uris && (
                <div className="overflow-x-auto">
                  <Table striped>
                    <TableHead>
                      <TableHeadCell>#</TableHeadCell>
                      <TableHeadCell>Entity URI</TableHeadCell>
                    </TableHead>
                    <TableBody>
                      {(results.entity_uris as string[]).map((uri: string, i: number) => (
                        <TableRow key={uri}>
                          <TableCell className="text-xs text-gray-400">{i + 1}</TableCell>
                          <TableCell><UriLink uri={uri} kind="entity" /></TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}

              {/* Relation results */}
              {results.query_type === 'relation' && results.relation_connections && (
                <div className="overflow-x-auto">
                  <Table striped>
                    <TableHead>
                      <TableHeadCell>Source</TableHeadCell>
                      <TableHeadCell>Relation Type</TableHeadCell>
                      <TableHeadCell>Destination</TableHeadCell>
                    </TableHead>
                    <TableBody>
                      {results.relation_connections!.map((c, i) => (
                        <TableRow key={i}>
                          <TableCell><UriLink uri={c.source_entity_uri} kind="entity" /></TableCell>
                          <TableCell><Badge color="purple" size="xs">{shortenUri(c.relation_type_uri)}</Badge></TableCell>
                          <TableCell><UriLink uri={c.destination_entity_uri} kind="entity" /></TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}

              {/* Frame query results */}
              {results.query_type === 'frame_query' && results.frame_results && (
                <div className="overflow-x-auto">
                  <Table striped>
                    <TableHead>
                      <TableHeadCell>Frame URI</TableHeadCell>
                      <TableHeadCell>Frame Type</TableHeadCell>
                      <TableHeadCell>Entity Refs</TableHeadCell>
                    </TableHead>
                    <TableBody>
                      {results.frame_results!.map((fr, i) => (
                        <TableRow key={i}>
                          <TableCell><UriLink uri={fr.frame_uri} kind="frame" /></TableCell>
                          <TableCell><Badge color="indigo" size="xs">{shortenUri(fr.frame_type_uri)}</Badge></TableCell>
                          <TableCell className="text-xs">
                            {fr.entity_refs?.map((er, j) => (
                              <span key={j} className="inline-block mr-2">
                                <Badge color="gray" size="xs">{shortenUri(er.slot_type_uri)}</Badge>
                                <span className="ml-1"><UriLink uri={er.entity_uri} kind="entity" /></span>
                              </span>
                            ))}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}

              {/* Frame connections (legacy) */}
              {results.query_type === 'frame' && results.frame_connections && (
                <div className="overflow-x-auto">
                  <Table striped>
                    <TableHead>
                      <TableHeadCell>Source</TableHeadCell>
                      <TableHeadCell>Frame</TableHeadCell>
                      <TableHeadCell>Destination</TableHeadCell>
                    </TableHead>
                    <TableBody>
                      {results.frame_connections!.map((c, i) => (
                        <TableRow key={i}>
                          <TableCell><UriLink uri={c.source_entity_uri} kind="entity" /></TableCell>
                          <TableCell><UriLink uri={c.shared_frame_uri} kind="frame" /></TableCell>
                          <TableCell><UriLink uri={c.destination_entity_uri} kind="entity" /></TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}

              {/* Raw response JSON */}
              <details className="mt-4">
                <summary className="text-xs text-gray-500 cursor-pointer hover:text-gray-700 dark:hover:text-gray-300">
                  Raw Response JSON
                </summary>
                <pre className="text-xs bg-gray-50 dark:bg-gray-900 text-gray-800 dark:text-gray-200 p-3 rounded-lg overflow-x-auto max-h-64 font-mono mt-2 border border-gray-200 dark:border-gray-700">
                  {JSON.stringify(results, null, 2)}
                </pre>
              </details>
            </div>
          </Card>
        )}
      </div>
    );
  }

  // ─── Builder View ─────────────────────────────────────────────

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white flex items-center gap-2">
            <HiLightningBolt className="h-6 w-6 text-amber-500" />
            KG Query Builder
          </h2>
          <p className="text-gray-500 dark:text-gray-400 text-sm mt-1">
            Build and execute structured knowledge graph queries
          </p>
        </div>
        <Button size="sm" color="blue" onClick={executeQuery} disabled={!hasSelection || loading}>
          <HiPlay className="mr-1.5 h-4 w-4" />{loading ? 'Running...' : 'Execute'}
        </Button>
      </div>

      {error && <Alert color="failure" onDismiss={() => setError(null)}>{error}</Alert>}

      {/* Space/Graph selectors */}
      <Card>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div>
            <Label>Space</Label>
            {spacesLoading ? <Spinner size="sm" /> : (
              <Select value={selectedSpace} onChange={(e) => setSelectedSpace(e.target.value)}>
                {spaces.map(s => <option key={s.space} value={s.space}>{s.space_name || s.space}</option>)}
              </Select>
            )}
          </div>
          <div>
            <Label>Graph</Label>
            {graphsLoading ? <Spinner size="sm" /> : (
              <Select value={selectedGraph} onChange={(e) => setSelectedGraph(e.target.value)}>
                {graphs.map(g => <option key={g.graph_uri} value={g.graph_uri}>{shortenUri(g.graph_uri)}</option>)}
              </Select>
            )}
          </div>
          <div>
            <Label>Query Type</Label>
            <Select value={queryType} onChange={(e) => setQueryType(e.target.value)}>
              {QUERY_TYPES.map(qt => <option key={qt.value} value={qt.value}>{qt.label}</option>)}
            </Select>
          </div>
        </div>
        <p className="text-xs text-gray-400 mt-2">
          {QUERY_TYPES.find(q => q.value === queryType)?.desc}
        </p>
      </Card>

      {/* Tabs */}
      <div className="border-b border-gray-200 dark:border-gray-700">
        <nav className="flex gap-4">
          <button onClick={() => setActiveTab('builder')} className={tabCls('builder')}>
            <HiLightningBolt className="inline-block h-4 w-4 mr-1.5 -mt-0.5" />Builder
          </button>
          <button onClick={() => setActiveTab('json')} className={tabCls('json')}>
            <HiCode className="inline-block h-4 w-4 mr-1.5 -mt-0.5" />JSON
          </button>
        </nav>
      </div>

      {/* ─── Builder Tab ─────────────────────────────────────────── */}
      {activeTab === 'builder' && hasSelection && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Left: Criteria */}
          <div className="space-y-4">
            {/* Entity criteria (entity + frame_query types) */}
            {(queryType === 'entity' || queryType === 'frame_query') && (
              <Card>
                <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">Entity Criteria</h3>
                <div className="space-y-3">
                  <div>
                    <Label className="text-xs">Search (name/label)</Label>
                    <TextInput sizing="sm" icon={HiSearch} placeholder="e.g. John" value={entitySearch} onChange={(e) => setEntitySearch(e.target.value)} />
                  </div>
                  <div>
                    <Label className="text-xs">Entity Type URI</Label>
                    <TextInput sizing="sm" placeholder="e.g. haley-ai-kg#KGEntity" value={entityTypeUri} onChange={(e) => setEntityTypeUri(e.target.value)} />
                  </div>
                </div>
              </Card>
            )}

            {/* Relation-specific */}
            {queryType === 'relation' && (
              <Card>
                <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">Relation Criteria</h3>
                <div className="space-y-3">
                  <div>
                    <Label className="text-xs">Source Entity URI</Label>
                    <TextInput sizing="sm" placeholder="urn:entity-123" value={sourceEntityUri} onChange={(e) => setSourceEntityUri(e.target.value)} />
                  </div>
                  <div>
                    <Label className="text-xs">Relation Type URI</Label>
                    <TextInput sizing="sm" placeholder="urn:relation-type" value={relationTypeUri} onChange={(e) => setRelationTypeUri(e.target.value)} />
                  </div>
                  <div>
                    <Label className="text-xs">Direction</Label>
                    <Select sizing="sm" value={direction} onChange={(e) => setDirection(e.target.value)}>
                      <option value="outgoing">Outgoing</option>
                      <option value="incoming">Incoming</option>
                      <option value="bidirectional">Bidirectional</option>
                    </Select>
                  </div>
                </div>
              </Card>
            )}

            {/* Property Filters */}
            <Card>
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Property Filters</h3>
                <Button size="xs" color="light" onClick={addPropertyFilter}><HiPlus className="h-3 w-3 mr-1" />Add</Button>
              </div>
              {propertyFilters.length === 0 ? (
                <p className="text-xs text-gray-400">No property filters. Click Add to constrain by entity properties.</p>
              ) : (
                <div className="space-y-2">
                  {propertyFilters.map(f => (
                    <div key={f.id} className="flex gap-2 items-center">
                      <TextInput sizing="sm" className="flex-1" placeholder="Property URI" value={f.property_uri} onChange={(e) => updatePropertyFilter(f.id, 'property_uri', e.target.value)} />
                      <Select sizing="sm" className="w-28" value={f.operator} onChange={(e) => updatePropertyFilter(f.id, 'operator', e.target.value)}>
                        {OPERATORS.map(op => <option key={op.value} value={op.value}>{op.label}</option>)}
                      </Select>
                      {f.operator !== 'exists' && f.operator !== 'not_exists' && (
                        <TextInput sizing="sm" className="flex-1" placeholder="Value" value={f.value} onChange={(e) => updatePropertyFilter(f.id, 'value', e.target.value)} />
                      )}
                      <Button size="xs" color="failure" onClick={() => removePropertyFilter(f.id)}><HiTrash className="h-3 w-3" /></Button>
                    </div>
                  ))}
                </div>
              )}
            </Card>

            {/* Frame Criteria */}
            <Card>
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Frame / Slot Criteria</h3>
                <Button size="xs" color="light" onClick={addFrameCriteria}><HiPlus className="h-3 w-3 mr-1" />Add Frame</Button>
              </div>
              {frameCriteria.length === 0 ? (
                <p className="text-xs text-gray-400">No frame criteria. Add frames to filter by connected frame/slot values.</p>
              ) : (
                <div className="space-y-3">
                  {frameCriteria.map(fc => (
                    <div key={fc.id} className="p-3 border border-gray-200 dark:border-gray-600 rounded-lg space-y-2">
                      <div className="flex gap-2 items-center">
                        <TextInput sizing="sm" className="flex-1" placeholder="Frame Type URI" value={fc.frame_type_uri} onChange={(e) => updateFrameType(fc.id, e.target.value)} />
                        <Button size="xs" color="failure" onClick={() => removeFrameCriteria(fc.id)}><HiTrash className="h-3 w-3" /></Button>
                      </div>
                      {fc.slots.map(slot => (
                        <div key={slot.id} className="flex gap-2 items-center pl-4">
                          <TextInput sizing="sm" className="flex-1" placeholder="Slot Type URI" value={slot.slot_type} onChange={(e) => updateSlot(fc.id, slot.id, 'slot_type', e.target.value)} />
                          <Select sizing="sm" className="w-24" value={slot.comparator} onChange={(e) => updateSlot(fc.id, slot.id, 'comparator', e.target.value)}>
                            {SLOT_COMPARATORS.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
                          </Select>
                          {slot.comparator !== 'exists' && slot.comparator !== 'not_exists' && (
                            <TextInput sizing="sm" className="flex-1" placeholder="Value" value={slot.value} onChange={(e) => updateSlot(fc.id, slot.id, 'value', e.target.value)} />
                          )}
                          <Button size="xs" color="failure" onClick={() => removeSlot(fc.id, slot.id)}><HiTrash className="h-3 w-3" /></Button>
                        </div>
                      ))}
                      <Button size="xs" color="light" onClick={() => addSlot(fc.id)} className="ml-4"><HiPlus className="h-3 w-3 mr-1" />Add Slot</Button>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </div>

          {/* Right: Sort + Options */}
          <div className="space-y-4">
            {/* Sort */}
            <Card>
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Sort Criteria</h3>
                <Button size="xs" color="light" onClick={addSort}><HiPlus className="h-3 w-3 mr-1" />Add</Button>
              </div>
              {sortItems.length === 0 ? (
                <p className="text-xs text-gray-400">No sorting. Results returned in default order.</p>
              ) : (
                <div className="space-y-2">
                  {sortItems.map(s => (
                    <div key={s.id} className="flex gap-2 items-center">
                      <Select sizing="sm" className="w-36" value={s.sort_type} onChange={(e) => updateSort(s.id, 'sort_type', e.target.value)}>
                        <option value="entity_property">Entity Property</option>
                        <option value="slot_value">Slot Value</option>
                      </Select>
                      <TextInput sizing="sm" className="flex-1" placeholder="Property/Slot URI" value={s.property_uri} onChange={(e) => updateSort(s.id, 'property_uri', e.target.value)} />
                      <Button size="xs" color="light" onClick={() => updateSort(s.id, 'direction', s.direction === 'asc' ? 'desc' : 'asc')}>
                        {s.direction === 'asc' ? <HiSortAscending className="h-4 w-4" /> : <HiSortDescending className="h-4 w-4" />}
                      </Button>
                      <Button size="xs" color="failure" onClick={() => removeSort(s.id)}><HiTrash className="h-3 w-3" /></Button>
                    </div>
                  ))}
                </div>
              )}
            </Card>

            {/* Options */}
            <Card>
              <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">Options</h3>
              <div className="space-y-3">
                <div className="flex items-center gap-4">
                  <Label className="text-xs w-24">Page Size</Label>
                  <Select sizing="sm" value={pageSize} onChange={(e) => setPageSize(Number(e.target.value))}>
                    <option value={5}>5</option>
                    <option value={10}>10</option>
                    <option value={25}>25</option>
                    <option value={50}>50</option>
                    <option value={100}>100</option>
                  </Select>
                </div>
                <div className="flex items-center justify-between">
                  <Label className="text-xs">Include Entity Graph Data</Label>
                  <ToggleSwitch checked={includeEntityGraph} onChange={setIncludeEntityGraph} />
                </div>
                <div className="flex items-center justify-between">
                  <Label className="text-xs">Include Frame Graph Data</Label>
                  <ToggleSwitch checked={includeFrameGraph} onChange={setIncludeFrameGraph} />
                </div>
              </div>
            </Card>
          </div>
        </div>
      )}

      {/* ─── JSON Tab ────────────────────────────────────────────── */}
      {activeTab === 'json' && (
        <div className="space-y-4">
          <Card>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Request Body (read-only)</h3>
              <Badge color="gray" size="xs">POST /api/graphs/kgqueries</Badge>
            </div>
            <pre className="text-xs bg-gray-50 dark:bg-gray-900 text-gray-800 dark:text-gray-200 p-4 rounded-lg overflow-x-auto font-mono leading-relaxed border border-gray-200 dark:border-gray-700" style={{ minHeight: '300px' }}>
              {JSON.stringify(buildRequest(), null, 2)}
            </pre>
          </Card>

          {results && (
            <Card>
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Response (read-only)</h3>
                <div className="flex gap-2">
                  <Badge color="info" size="xs">{String(results.total_count ?? 0)} results</Badge>
                  {elapsed !== null && <Badge color="gray" size="xs">{elapsed}ms</Badge>}
                </div>
              </div>
              <pre className="text-xs bg-gray-50 dark:bg-gray-900 text-gray-800 dark:text-gray-200 p-4 rounded-lg overflow-x-auto max-h-96 font-mono leading-relaxed border border-gray-200 dark:border-gray-700">
                {JSON.stringify(results, null, 2)}
              </pre>
            </Card>
          )}
        </div>
      )}
    </div>
  );
};

export default KGQueryBuilder;

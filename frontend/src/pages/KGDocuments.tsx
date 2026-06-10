import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { apiService } from '../services/ApiService';
import { Alert, Badge, Button, Select, Spinner, TextInput, ToggleSwitch, Card } from 'flowbite-react';
import { HiSearch, HiDocumentText, HiChevronRight, HiRefresh } from 'react-icons/hi';
import { type SpaceInfo } from '../types/api';
import { type GraphInfo } from '../types/graphs';
import NavigationBreadcrumb from '../components/NavigationBreadcrumb';
import {
  shortenUri,
  extractGraphName,
} from '../utils/QuadUtils';


interface DocumentEntry {
  uri: string;
  name: string;
  headline: string;
  document_type: string;
  segment_index: number | null;
  segment_method: string;
  segment_type: string;
  token_length: number | null;
  url: string;
  index_datetime: string;
}

const KGDocuments: React.FC = () => {
  const navigate = useNavigate();
  const { spaceId, graphId } = useParams<{ spaceId?: string; graphId?: string }>();

  const [spaces, setSpaces] = useState<SpaceInfo[]>([]);
  const [selectedSpace, setSelectedSpace] = useState(spaceId || '');
  const [graphs, setGraphs] = useState<GraphInfo[]>([]);
  const [selectedGraph, setSelectedGraph] = useState(graphId ? decodeURIComponent(graphId) : '');
  const [spacesLoading, setSpacesLoading] = useState(true);
  const [graphsLoading, setGraphsLoading] = useState(false);

  const [documents, setDocuments] = useState<DocumentEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [showSegments, setShowSegments] = useState(false);
  const [segStatusMap, setSegStatusMap] = useState<Record<string, { status: string; segment_count?: number }>>({});
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Navigate to hierarchical URL
  useEffect(() => {
    if (selectedSpace && selectedGraph && !spaceId && !graphId) {
      navigate(`/space/${selectedSpace}/graph/${encodeURIComponent(selectedGraph)}/kgdocuments`);
    }
  }, [selectedSpace, selectedGraph, navigate, spaceId, graphId]);

  // Debounce search
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(searchTerm), 400);
    return () => clearTimeout(timer);
  }, [searchTerm]);

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
  useEffect(() => { fetchGraphs(); }, [fetchGraphs]);

  // Fetch documents
  const fetchDocuments = useCallback(async () => {
    if (!selectedSpace || !selectedGraph) {
      setDocuments([]);
      return;
    }
    try {
      setLoading(true);
      setError(null);

      // Use SPARQL to list KGDocuments
      const sparql = `
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

        SELECT ?s ?name ?headline ?docType ?segIndex ?segMethod ?segType ?tokenLen ?docUrl ?indexDt
        WHERE {
          GRAPH <${selectedGraph}> {
            ?s rdf:type haley:KGDocument .
            OPTIONAL { ?s vital:hasName ?name }
            OPTIONAL { ?s haley:hasKGDocumentHeadline ?headline }
            OPTIONAL { ?s haley:hasKGDocumentType ?docType }
            OPTIONAL { ?s haley:hasKGDocumentSegmentIndex ?segIndex }
            OPTIONAL { ?s haley:hasKGDocumentSegmentMethodURI ?segMethod }
            OPTIONAL { ?s haley:hasKGDocumentSegmentTypeURI ?segType }
            OPTIONAL { ?s haley:hasKGDocumentSegmentTokenLength ?tokenLen }
            OPTIONAL { ?s haley:hasKGDocumentURL ?docUrl }
            OPTIONAL { ?s haley:hasKGIndexDateTime ?indexDt }
          }
        }
        ORDER BY ?segIndex ?s
        LIMIT 200
      `;

      const response = await apiService.executeSparqlQuery(selectedSpace, sparql);
      const results: DocumentEntry[] = (response?.results?.bindings || []).map((row: Record<string, {value?: string}>) => ({
        uri: row.s?.value || '',
        name: row.name?.value || '',
        headline: row.headline?.value || '',
        document_type: row.docType?.value || '',
        segment_index: row.segIndex?.value != null ? parseInt(row.segIndex.value) : null,
        segment_method: row.segMethod?.value || '',
        segment_type: row.segType?.value || '',
        token_length: row.tokenLen?.value != null ? parseInt(row.tokenLen.value) : null,
        url: row.docUrl?.value || '',
        index_datetime: row.indexDt?.value || '',
      }));

      setDocuments(results);
    } catch (e: unknown) {
      setError(`Failed to load documents: ${e instanceof Error ? e.message : String(e)}`);
      setDocuments([]);
    } finally {
      setLoading(false);
    }
  }, [selectedSpace, selectedGraph]);

  useEffect(() => { fetchDocuments(); }, [fetchDocuments]);

  // Fetch segmentation statuses for all documents in this space
  const fetchSegStatuses = useCallback(async () => {
    if (!selectedSpace) return;
    try {
      const resp = await apiService.getSegmentationStatus(selectedSpace, undefined, undefined, 200, 0);
      const jobs = resp?.jobs ?? [];
      const map: Record<string, { status: string; segment_count?: number }> = {};
      for (const j of jobs) {
        // Keep latest job per document_uri
        const existing = map[j.document_uri];
        if (!existing || j.job_id > ((existing as Record<string, unknown>).job_id as number ?? 0)) {
          map[j.document_uri] = { status: j.status, segment_count: j.segment_count };
        }
      }
      setSegStatusMap(map);
    } catch {
      // silently ignore
    }
  }, [selectedSpace]);

  useEffect(() => {
    if (documents.length > 0) fetchSegStatuses();
  }, [documents, fetchSegStatuses]);

  // Auto-poll while any job is pending/in_progress
  useEffect(() => {
    const hasActive = Object.values(segStatusMap).some(s => s.status === 'pending' || s.status === 'in_progress');
    if (hasActive) {
      pollRef.current = setInterval(fetchSegStatuses, 4000);
    } else if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } };
  }, [segStatusMap, fetchSegStatuses]);

  // Filter documents based on search and segment visibility
  const filteredDocuments = documents.filter(doc => {
    // Hide segments unless toggle is on
    if (!showSegments && doc.segment_index !== null && doc.segment_index > 0) {
      return false;
    }
    // Also hide segmentation parents unless toggle is on
    if (!showSegments && doc.segment_type === 'urn:segtype:segmentation_parent') {
      return false;
    }
    // Search filter
    if (debouncedSearch) {
      const term = debouncedSearch.toLowerCase();
      return (
        doc.name.toLowerCase().includes(term) ||
        doc.headline.toLowerCase().includes(term) ||
        doc.uri.toLowerCase().includes(term)
      );
    }
    return true;
  });

  const getDocTypeBadge = (doc: DocumentEntry) => {
    if (doc.segment_type === 'urn:segtype:segmentation_parent') {
      return <Badge color="purple" size="xs">Parent Copy</Badge>;
    }
    if (doc.segment_index !== null && doc.segment_index > 0) {
      return <Badge color="info" size="xs">Segment #{doc.segment_index}</Badge>;
    }
    return <Badge color="gray" size="xs">Original</Badge>;
  };

  const getMethodLabel = (uri: string) => {
    if (uri.includes('markdown')) return 'Markdown';
    if (uri.includes('plain')) return 'Plain';
    return uri.split(':').pop() || uri;
  };

  return (
    <div className="p-4 max-w-7xl mx-auto">
      <NavigationBreadcrumb
        spaceId={spaceId}
        graphId={graphId}
        currentPageName="KG Documents"
        currentPageIcon={HiDocumentText}
      />

      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
          <HiDocumentText className="h-7 w-7 text-blue-600 dark:text-blue-400" />
          KG Documents
        </h1>
        <div className="flex items-center gap-3">
          <Button size="xs" color="light" onClick={fetchDocuments}>
            <HiRefresh className="h-4 w-4 mr-1" /> Refresh
          </Button>
        </div>
      </div>

      {/* Selectors */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        <div>
          <label htmlFor="space-select" className="mb-1 block text-sm font-medium text-gray-900 dark:text-white">Space</label>
          <Select
            id="space-select"
            value={selectedSpace}
            onChange={(e) => { setSelectedSpace(e.target.value); setSelectedGraph(''); }}
            disabled={spacesLoading}
          >
            <option value="">Select a space...</option>
            {spaces.map((s: SpaceInfo) => (
              <option key={s.space} value={s.space}>{s.space_name}</option>
            ))}
          </Select>
        </div>
        <div>
          <label htmlFor="graph-select" className="mb-1 block text-sm font-medium text-gray-900 dark:text-white">Graph</label>
          <Select
            id="graph-select"
            value={selectedGraph}
            onChange={(e) => setSelectedGraph(e.target.value)}
            disabled={graphsLoading || !selectedSpace}
          >
            <option value="">Select a graph...</option>
            {graphs.map((g: GraphInfo) => (
              <option key={g.graph_uri} value={g.graph_uri}>{extractGraphName(g.graph_uri)}</option>
            ))}
          </Select>
        </div>
      </div>

      {/* Controls */}
      <div className="flex items-center gap-4 mb-4">
        <div className="flex-1 max-w-md">
          <TextInput
            icon={HiSearch}
            placeholder="Search documents..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>
        <div className="flex items-center gap-2">
          <ToggleSwitch
            checked={showSegments}
            onChange={setShowSegments}
            label="Show Segments"
          />
        </div>
        <div className="text-sm text-gray-500 dark:text-gray-400">
          {filteredDocuments.length} of {documents.length} documents
        </div>
      </div>

      {error && <Alert color="failure" className="mb-4">{error}</Alert>}

      {/* Document List */}
      {loading ? (
        <div className="flex justify-center py-12">
          <Spinner size="xl" />
        </div>
      ) : filteredDocuments.length === 0 ? (
        <Card className="text-center py-8">
          <HiDocumentText className="h-12 w-12 text-gray-400 mx-auto mb-3" />
          <p className="text-gray-500 dark:text-gray-400">
            {documents.length === 0
              ? 'No documents found in this graph.'
              : 'No documents match the current filters.'}
          </p>
        </Card>
      ) : (
        <div className="space-y-2">
          {filteredDocuments.map((doc) => (
            <Card
              key={doc.uri}
              className="hover:bg-gray-50 dark:hover:bg-gray-750 cursor-pointer transition-colors"
              onClick={() => {
                const encodedUri = encodeURIComponent(doc.uri);
                navigate(`/space/${selectedSpace}/graph/${encodeURIComponent(selectedGraph)}/document/${encodedUri}`);
              }}
            >
              <div className="flex items-center justify-between">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    {getDocTypeBadge(doc)}
                    {doc.segment_method && (
                      <Badge color="dark" size="xs">
                        {getMethodLabel(doc.segment_method)}
                      </Badge>
                    )}
                    {doc.token_length !== null && (
                      <Badge color="light" size="xs">
                        {doc.token_length} tokens
                      </Badge>
                    )}
                    {segStatusMap[doc.uri] && (
                      <Badge
                        color={
                          segStatusMap[doc.uri].status === 'completed' ? 'success'
                          : segStatusMap[doc.uri].status === 'failed' ? 'failure'
                          : segStatusMap[doc.uri].status === 'in_progress' ? 'info'
                          : segStatusMap[doc.uri].status === 'pending' ? 'warning'
                          : 'gray'
                        }
                        size="xs"
                      >
                        {segStatusMap[doc.uri].status === 'in_progress' ? 'Segmenting...' : `Seg: ${segStatusMap[doc.uri].status}`}
                      </Badge>
                    )}
                  </div>
                  <h3 className="text-sm font-medium text-gray-900 dark:text-white truncate">
                    {doc.headline || doc.name || shortenUri(doc.uri)}
                  </h3>
                  <p className="text-xs text-gray-500 dark:text-gray-400 truncate mt-0.5">
                    {shortenUri(doc.uri)}
                  </p>
                  {doc.url && (
                    <p className="text-xs text-blue-600 dark:text-blue-400 truncate mt-0.5">
                      {doc.url}
                    </p>
                  )}
                </div>
                <HiChevronRight className="h-5 w-5 text-gray-400 flex-shrink-0 ml-2" />
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
};

export default KGDocuments;

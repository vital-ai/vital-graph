import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { apiService } from '../services/ApiService';
import { Alert, Badge, Button, FileInput, Modal, Pagination, Select, Spinner, TextInput, ToggleSwitch, Card } from 'flowbite-react';
import { HiSearch, HiDocumentText, HiChevronRight, HiRefresh, HiPlus, HiUpload } from 'react-icons/hi';
import { type SpaceInfo } from '../types/api';
import { type GraphInfo } from '../types/graphs';
import NavigationBreadcrumb from '../components/NavigationBreadcrumb';
import { vgClient } from '../services/ApiService';
import {
  shortenUri,
  extractGraphName,
  groupQuadsBySubject,
  getFirstValue,
  HAS_NAME,
} from '../utils/QuadUtils';

// KGDocument property predicates (for parsing endpoint quads → DocumentEntry)
const HALEY = 'http://vital.ai/ontology/haley-ai-kg#';
const DOC_PRED = {
  headline: `${HALEY}hasKGDocumentHeadline`,
  docType: `${HALEY}hasKGDocumentType`,
  segIndex: `${HALEY}hasKGDocumentSegmentIndex`,
  segMethod: `${HALEY}hasKGDocumentSegmentMethodURI`,
  segType: `${HALEY}hasKGDocumentSegmentTypeURI`,
  tokenLen: `${HALEY}hasKGDocumentSegmentTokenLength`,
  url: `${HALEY}hasKGDocumentURL`,
  indexDt: `${HALEY}hasKGIndexDateTime`,
};


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
  const [currentPage, setCurrentPage] = useState(1);
  const [itemsPerPage] = useState(25);
  const [totalCount, setTotalCount] = useState(0);
  const [segStatusMap, setSegStatusMap] = useState<Record<string, { status: string; segment_count?: number }>>({});
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Upload modal state
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadHeadline, setUploadHeadline] = useState('');
  const [uploadUrl, setUploadUrl] = useState('');
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

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

  // Fetch documents via the paginated /kgdocuments endpoint. Segment
  // inclusion/exclusion is handled server-side by the include_segments flag
  // (default off = top-level documents only), so the whole space is browsable
  // page-by-page rather than capped client-side.
  const fetchDocuments = useCallback(async () => {
    if (!selectedSpace || !selectedGraph) {
      setDocuments([]);
      setTotalCount(0);
      return;
    }
    try {
      setLoading(true);
      setError(null);

      const data = await apiService.getDocuments(selectedSpace, selectedGraph, {
        page_size: itemsPerPage,
        offset: (currentPage - 1) * itemsPerPage,
        search: debouncedSearch || undefined,
        include_segments: showSegments,
      });

      const bySubject = groupQuadsBySubject(data.results || []);
      const results: DocumentEntry[] = [];
      for (const [uri, preds] of bySubject) {
        const segIdx = getFirstValue(preds, DOC_PRED.segIndex);
        const tokLen = getFirstValue(preds, DOC_PRED.tokenLen);
        results.push({
          uri,
          name: getFirstValue(preds, HAS_NAME) || shortenUri(uri),
          headline: getFirstValue(preds, DOC_PRED.headline),
          document_type: getFirstValue(preds, DOC_PRED.docType),
          segment_index: segIdx ? parseInt(segIdx) : null,
          segment_method: getFirstValue(preds, DOC_PRED.segMethod),
          segment_type: getFirstValue(preds, DOC_PRED.segType),
          token_length: tokLen ? parseInt(tokLen) : null,
          url: getFirstValue(preds, DOC_PRED.url),
          index_datetime: getFirstValue(preds, DOC_PRED.indexDt),
        });
      }

      setDocuments(results);
      setTotalCount(data.total_count ?? results.length);
    } catch (e: unknown) {
      setError(`Failed to load documents: ${e instanceof Error ? e.message : String(e)}`);
      setDocuments([]);
      setTotalCount(0);
    } finally {
      setLoading(false);
    }
  }, [selectedSpace, selectedGraph, itemsPerPage, currentPage, debouncedSearch, showSegments]);

  useEffect(() => { fetchDocuments(); }, [fetchDocuments]);

  // Reset to page 1 when the search term or segment toggle changes.
  useEffect(() => { setCurrentPage(1); }, [debouncedSearch, showSegments]);

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

  // Auto-poll while any job is pending/in_progress/vectorizing
  useEffect(() => {
    const hasActive = Object.values(segStatusMap).some(s => s.status === 'pending' || s.status === 'in_progress' || s.status === 'vectorizing');
    if (hasActive) {
      pollRef.current = setInterval(fetchSegStatuses, 4000);
    } else if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } };
  }, [segStatusMap, fetchSegStatuses]);

  // Segment inclusion and search are handled server-side (include_segments +
  // the endpoint's search), so the page renders the returned set directly.
  const filteredDocuments = documents;
  const totalPages = Math.max(1, Math.ceil(totalCount / itemsPerPage));

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

  const handleUploadDocument = async () => {
    if (!uploadFile || !selectedSpace || !selectedGraph) return;
    try {
      setUploading(true);
      setUploadError(null);

      const text = await uploadFile.text();
      const headline = uploadHeadline || uploadFile.name;
      const docUri = `urn:kgdocument:${Date.now()}:${uploadFile.name.replace(/[^a-zA-Z0-9]/g, '_')}`;

      const quads = [
        { s: docUri, p: 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', o: 'http://vital.ai/ontology/haley-ai-kg#KGDocument', o_type: 'uri' },
        { s: docUri, p: 'http://vital.ai/ontology/vital-core#hasName', o: headline, o_type: 'literal' },
        { s: docUri, p: 'http://vital.ai/ontology/haley-ai-kg#hasKGDocumentHeadline', o: headline, o_type: 'literal' },
        { s: docUri, p: 'http://vital.ai/ontology/haley-ai-kg#hasKGDocumentContent', o: text, o_type: 'literal' },
      ];

      if (uploadUrl) {
        quads.push({ s: docUri, p: 'http://vital.ai/ontology/haley-ai-kg#hasKGDocumentURL', o: uploadUrl, o_type: 'literal' });
      }

      await vgClient.kgdocuments.create(selectedSpace, selectedGraph, { quads });

      setShowUploadModal(false);
      setUploadFile(null);
      setUploadHeadline('');
      setUploadUrl('');
      fetchDocuments();
    } catch (e: unknown) {
      setUploadError(e instanceof Error ? e.message : 'Upload failed');
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="p-4 max-w-7xl mx-auto" data-testid="kgdocuments-page">
      <NavigationBreadcrumb
        spaceId={spaceId}
        graphId={graphId}
        currentPageName="KG Documents"
        currentPageIcon={HiDocumentText}
      />

      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2" data-testid="kgdocuments-title">
          <HiDocumentText className="h-7 w-7 text-blue-600 dark:text-blue-400" />
          KG Documents
        </h1>
        <div className="flex items-center gap-3">
          <Button size="xs" color="light" onClick={fetchDocuments}>
            <HiRefresh className="h-4 w-4 mr-1" /> Refresh
          </Button>
          {selectedSpace && selectedGraph && (
            <>
              <Button size="xs" color="blue" onClick={() => navigate(`/space/${selectedSpace}/graph/${encodeURIComponent(selectedGraph)}/document/new?mode=create`)}>
                <HiPlus className="h-4 w-4 mr-1" /> Add Document
              </Button>
              <Button size="xs" color="purple" onClick={() => setShowUploadModal(true)}>
                <HiUpload className="h-4 w-4 mr-1" /> Upload Document
              </Button>
            </>
          )}
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
          {totalCount} {showSegments ? 'documents + segments' : 'document' + (totalCount === 1 ? '' : 's')}
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
              data-testid="document-card"
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
                          : segStatusMap[doc.uri].status === 'vectorizing' ? 'success'
                          : segStatusMap[doc.uri].status === 'failed' ? 'failure'
                          : segStatusMap[doc.uri].status === 'in_progress' ? 'info'
                          : segStatusMap[doc.uri].status === 'pending' ? 'warning'
                          : 'gray'
                        }
                        size="xs"
                      >
                        {segStatusMap[doc.uri].status === 'pending' ? '⏳ Pending'
                          : segStatusMap[doc.uri].status === 'in_progress' ? '🔄 Segmenting…'
                          : segStatusMap[doc.uri].status === 'vectorizing' ? '✅🔄 Vectorizing…'
                          : segStatusMap[doc.uri].status === 'completed' ? '✅ Ready'
                          : segStatusMap[doc.uri].status === 'failed' ? '❌ Failed'
                          : segStatusMap[doc.uri].status}
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
                <HiChevronRight className="h-5 w-5 text-gray-400 shrink-0 ml-2" />
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* Pagination */}
      {!loading && totalPages > 1 && (
        <div className="flex justify-center mt-4">
          <Pagination
            currentPage={currentPage}
            totalPages={totalPages}
            onPageChange={setCurrentPage}
            showIcons
          />
        </div>
      )}

      {/* Upload Document Modal */}
      <Modal show={showUploadModal} onClose={() => setShowUploadModal(false)} size="lg">
        <div className="p-6">
          <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-4">Upload Document</h3>
          {uploadError && <Alert color="failure" className="mb-4">{uploadError}</Alert>}
          <div className="space-y-4">
            <div>
              <label htmlFor="upload-file" className="mb-1 block text-sm font-medium text-gray-900 dark:text-white">File (text, markdown, HTML)</label>
              <FileInput
                id="upload-file"
                accept=".txt,.md,.html,.htm,.csv,.json"
                onChange={(e) => {
                  const file = e.target.files?.[0] || null;
                  setUploadFile(file);
                  if (file && !uploadHeadline) setUploadHeadline(file.name);
                }}
              />
              <p className="mt-1 text-xs text-gray-500">Text content will be extracted and stored as document content.</p>
            </div>
            <div>
              <label htmlFor="upload-headline" className="mb-1 block text-sm font-medium text-gray-900 dark:text-white">Headline / Title</label>
              <TextInput
                id="upload-headline"
                placeholder="Document title (defaults to filename)"
                value={uploadHeadline}
                onChange={(e) => setUploadHeadline(e.target.value)}
              />
            </div>
            <div>
              <label htmlFor="upload-url" className="mb-1 block text-sm font-medium text-gray-900 dark:text-white">Source URL (optional)</label>
              <TextInput
                id="upload-url"
                placeholder="https://..."
                value={uploadUrl}
                onChange={(e) => setUploadUrl(e.target.value)}
              />
            </div>
          </div>
          <div className="flex justify-end gap-3 mt-6">
            <Button color="purple" onClick={handleUploadDocument} disabled={!uploadFile || uploading}>
              {uploading ? <><Spinner size="sm" className="mr-2" /> Creating...</> : <><HiUpload className="mr-2 h-4 w-4" /> Create Document</>}
            </Button>
            <Button color="gray" onClick={() => setShowUploadModal(false)}>Cancel</Button>
          </div>
        </div>
      </Modal>
    </div>
  );
};

export default KGDocuments;

import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { apiService } from '../services/ApiService';
import { Alert, Badge, Button, Label, Select, Spinner, TextInput } from 'flowbite-react';
import { HiPlus, HiEye } from 'react-icons/hi2';
import { HiSearch, HiDocumentDuplicate } from 'react-icons/hi';
import { type SpaceInfo } from '../types/api';
import { type GraphInfo } from '../types/graphs';
import NavigationBreadcrumb from '../components/NavigationBreadcrumb';
import {
  groupQuadsBySubject,
  getFirstValue,
  shortenUri,
  extractGraphName,
  RDF_TYPE,
  HAS_NAME,
  type Quad,
} from '../utils/QuadUtils';

interface FileEntry {
  uri: string;
  rdf_type: string;
  filename: string;
  file_type: string;
  properties_count: number;
}

const HAS_FILE_TYPE = 'http://vital.ai/ontology/vital-core#hasFileType';

const Files: React.FC = () => {
  const navigate = useNavigate();
  const { spaceId, graphId } = useParams<{ spaceId?: string; graphId?: string }>();

  const [spaces, setSpaces] = useState<SpaceInfo[]>([]);
  const [selectedSpace, setSelectedSpace] = useState(spaceId || '');
  const [graphs, setGraphs] = useState<GraphInfo[]>([]);
  const [selectedGraph, setSelectedGraph] = useState(graphId ? decodeURIComponent(graphId) : '');
  const [spacesLoading, setSpacesLoading] = useState(true);
  const [graphsLoading, setGraphsLoading] = useState(false);

  const [files, setFiles] = useState<FileEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');

  // Navigate to hierarchical URL
  useEffect(() => {
    if (selectedSpace && selectedGraph && !spaceId && !graphId) {
      navigate(`/space/${selectedSpace}/graph/${encodeURIComponent(selectedGraph)}/files`);
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

  useEffect(() => {
    fetchGraphs();
    if (!graphId) setSelectedGraph('');
  }, [fetchGraphs, graphId]);

  // Fetch files
  const fetchFiles = useCallback(async () => {
    if (!selectedSpace || !selectedGraph) return;
    try {
      setLoading(true);
      setError(null);
      const data = await apiService.getFiles(selectedSpace, selectedGraph, {
        page_size: 100,
        offset: 0,
        search: debouncedSearch || undefined,
      });
      const quads: Quad[] = data.results || [];
      const subjectMap = groupQuadsBySubject(quads);

      const parsed: FileEntry[] = [];
      for (const [uri, preds] of subjectMap) {
        const rdfType = getFirstValue(preds, RDF_TYPE, 'Unknown');
        const filename = getFirstValue(preds, HAS_NAME) || shortenUri(uri);
        const fileType = getFirstValue(preds, HAS_FILE_TYPE);
        parsed.push({ uri, rdf_type: rdfType, filename, file_type: fileType, properties_count: preds.size });
      }
      setFiles(parsed);
    } catch {
      setError('Failed to load files.');
      setFiles([]);
    } finally { setLoading(false); }
  }, [selectedSpace, selectedGraph, debouncedSearch]);

  useEffect(() => {
    if (selectedSpace && selectedGraph) fetchFiles();
    else setFiles([]);
  }, [selectedSpace, selectedGraph, fetchFiles]);

  const hasSelection = selectedSpace && selectedGraph;
  const detailUrl = (uri: string) => {
    const s = spaceId || selectedSpace;
    const g = graphId || encodeURIComponent(selectedGraph);
    return `/space/${s}/graph/${g}/file/${encodeURIComponent(uri)}`;
  };

  return (
    <div className="space-y-6" data-testid="files-page">
      <NavigationBreadcrumb spaceId={spaceId} graphId={graphId} currentPageName="Files" currentPageIcon={HiDocumentDuplicate} />

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <HiDocumentDuplicate className="w-6 h-6 text-blue-600" />
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Files</h1>
          </div>
          {hasSelection && !loading && (
            <p className="text-gray-500 dark:text-gray-400 text-sm mt-1">{files.length} file{files.length !== 1 ? 's' : ''}</p>
          )}
        </div>
        {hasSelection && (
          <Button size="sm" color="blue" onClick={() => navigate(`/space/${selectedSpace}/graph/${encodeURIComponent(selectedGraph)}/file/new`)}>
            <HiPlus className="mr-1.5 h-4 w-4" />Upload File
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

      {/* Search */}
      {hasSelection && (
        <TextInput
          icon={HiSearch}
          placeholder="Search files..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
        />
      )}

      {error && <Alert color="failure" onDismiss={() => setError(null)}>{error}</Alert>}

      {/* Prompt states */}
      {!selectedSpace && !spacesLoading && (
        <div className="text-center py-16 text-gray-500 dark:text-gray-400">
          <HiDocumentDuplicate className="w-16 h-16 mx-auto mb-4 text-gray-300 dark:text-gray-600" />
          <p className="text-lg font-medium">Select a space</p>
          <p className="text-sm mt-1">Choose a space from the dropdown above</p>
        </div>
      )}
      {selectedSpace && !selectedGraph && !graphsLoading && (
        <div className="text-center py-16 text-gray-500 dark:text-gray-400">
          <HiDocumentDuplicate className="w-16 h-16 mx-auto mb-4 text-gray-300 dark:text-gray-600" />
          <p className="text-lg font-medium">Select a graph</p>
          <p className="text-sm mt-1">Choose a graph to browse its files</p>
        </div>
      )}

      {hasSelection && loading && (
        <div className="flex justify-center py-12"><Spinner size="xl" /></div>
      )}

      {hasSelection && !loading && files.length === 0 && !error && (
        <div className="text-center py-16 text-gray-500 dark:text-gray-400">
          <HiDocumentDuplicate className="w-16 h-16 mx-auto mb-4 text-gray-300 dark:text-gray-600" />
          {debouncedSearch ? (
            <>
              <p className="text-lg font-medium">No results for &quot;{debouncedSearch}&quot;</p>
              <p className="text-sm mt-1">Try a different search term</p>
            </>
          ) : (
            <>
              <p className="text-lg font-medium">No files yet</p>
              <p className="text-sm mt-1">Upload your first file to get started</p>
            </>
          )}
        </div>
      )}

      {/* Files table */}
      {hasSelection && !loading && files.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
          <table className="w-full text-sm text-left">
            <thead className="text-xs text-gray-500 dark:text-gray-400 uppercase bg-gray-50 dark:bg-gray-800">
              <tr>
                <th className="px-4 py-3">File</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3 w-28">Properties</th>
                <th className="px-4 py-3 w-20"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
              {files.map((file) => (
                <tr key={file.uri} className="bg-white dark:bg-gray-900 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">
                  <td className="px-4 py-2.5">
                    <div className="max-w-sm">
                      <p className="text-sm font-medium text-gray-900 dark:text-white truncate">{file.filename}</p>
                      <p className="text-xs font-mono text-gray-400 truncate" title={file.uri}>{file.uri}</p>
                    </div>
                  </td>
                  <td className="px-4 py-2.5">
                    <Badge color="purple" size="xs">{file.file_type || shortenUri(file.rdf_type)}</Badge>
                  </td>
                  <td className="px-4 py-2.5 text-xs text-gray-500 dark:text-gray-400">
                    {file.properties_count}
                  </td>
                  <td className="px-4 py-2.5">
                    <button
                      onClick={() => navigate(detailUrl(file.uri))}
                      className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-400 hover:text-blue-500 transition-colors" title="View details"
                    >
                      <HiEye className="h-4 w-4" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

export default Files;

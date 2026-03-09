import React, { useState, useEffect, useCallback, useRef, useLayoutEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import axios from 'axios';
import { Alert, Button, Card, Spinner, Table, TableBody, TableCell, TableHead, TableHeadCell, TableRow, TextInput, Select, Label } from 'flowbite-react';
import { HiPlus, HiEye } from 'react-icons/hi2';
import { HiSearch, HiDocumentDuplicate } from 'react-icons/hi';
import NavigationBreadcrumb from '../components/NavigationBreadcrumb';

interface FileEntry {
  uri: string;
  rdf_type: string;
  filename: string;
  file_type: string;
  file_size: number;
  properties_count: number;
}

interface Space {
  space: string;
  space_name: string;
}

interface Graph {
  graph_uri: string;
  graph_name: string;
  triple_count: number;
}

const Files: React.FC = () => {
  const navigate = useNavigate();
  const { spaceId, graphId } = useParams<{ spaceId?: string; graphId?: string }>();
  const filterInputRef = useRef<HTMLInputElement>(null);
  const cursorPositionRef = useRef<number>(0);
  const [files, setFiles] = useState<FileEntry[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [filterText, setFilterText] = useState<string>('');
  const [spaces, setSpaces] = useState<Space[]>([]);
  const [selectedSpace, setSelectedSpace] = useState<string>(spaceId || '');
  const [spacesLoading, setSpacesLoading] = useState<boolean>(true);
  const [graphs, setGraphs] = useState<Graph[]>([]);
  const [selectedGraph, setSelectedGraph] = useState<string>(graphId ? decodeURIComponent(graphId) : '');
  const [graphsLoading, setGraphsLoading] = useState<boolean>(false);

  // Navigate to hierarchical URL when space/graph selection changes
  useEffect(() => {
    if (selectedSpace && selectedGraph && !spaceId && !graphId) {
      navigate(`/space/${selectedSpace}/graph/${encodeURIComponent(selectedGraph)}/files`);
    }
  }, [selectedSpace, selectedGraph, navigate, spaceId, graphId]);

  // Fetch available spaces
  const fetchSpaces = useCallback(async () => {
    try {
      setSpacesLoading(true);
      const response = await axios.get('/api/spaces');
      const spacesData = Array.isArray(response.data) ? response.data : response.data.spaces || [];
      setSpaces(spacesData);
      setError(null);
    } catch (err) {
      console.error('Error fetching spaces:', err);
      setError('Failed to load spaces.');
      setSpaces([]);
    } finally {
      setSpacesLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSpaces();
  }, [fetchSpaces]);

  // Fetch graphs for selected space
  const fetchGraphs = useCallback(async () => {
    if (!selectedSpace) {
      setGraphs([]);
      return;
    }

    try {
      setGraphsLoading(true);
      const response = await axios.get(`/api/graphs/sparql/${selectedSpace}/graphs`);
      const graphsData = Array.isArray(response.data) ? response.data : [];
      const converted: Graph[] = graphsData.map((g: Record<string, unknown>) => ({
        graph_uri: (g.graph_uri as string) || '',
        graph_name: (g.graph_uri as string)?.split(/[/#]/).pop() || 'Unknown',
        triple_count: (g.triple_count as number) || 0,
      }));
      setGraphs(converted);
      setError(null);
    } catch (err) {
      console.error('Error fetching graphs:', err);
      setError('Failed to load graphs.');
      setGraphs([]);
    } finally {
      setGraphsLoading(false);
    }
  }, [selectedSpace]);

  useEffect(() => {
    fetchGraphs();
    if (!graphId) {
      setSelectedGraph(''); // Reset graph selection when space changes only if not from URL
    }
  }, [fetchGraphs, graphId]);


  // Fetch files for selected space and graph
  const fetchFiles = useCallback(async () => {
    if (!selectedSpace || !selectedGraph) return;
    
    try {
      setLoading(true);
      setError(null);
      
      const response = await axios.get('/api/graphs/files', {
        params: {
          space_id: selectedSpace,
          graph_id: selectedGraph,
          page_size: 100,
          offset: 0,
          file_filter: filterText || undefined,
        }
      });
      
      const data = response.data;
      // API returns QuadResponse: { results: [{s, p, o, g}], total_count, ... }
      const quads: Array<{s: string; p: string; o: string; g?: string}> = data.results || [];
      
      // Group quads by subject to form file entries
      const subjectMap = new Map<string, Map<string, string[]>>();
      for (const quad of quads) {
        const subj = quad.s.replace(/^<|>$/g, '');
        if (!subjectMap.has(subj)) subjectMap.set(subj, new Map());
        const preds = subjectMap.get(subj)!;
        const pred = quad.p.replace(/^<|>$/g, '');
        if (!preds.has(pred)) preds.set(pred, []);
        preds.get(pred)!.push(quad.o);
      }
      
      const RDF_TYPE = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type';
      const HAS_NAME = 'http://vital.ai/ontology/vital-core#hasName';
      const HAS_FILE_TYPE = 'http://vital.ai/ontology/vital-core#hasFileType';
      
      const fileEntries: FileEntry[] = [];
      for (const [uri, preds] of subjectMap) {
        const typeVals = preds.get(RDF_TYPE) || [];
        const rdfType = typeVals.length > 0 ? typeVals[0].replace(/^<|>$/g, '') : 'Unknown';
        
        const stripLiteral = (v: string) => v.replace(/^"/, '').replace(/"(@[a-z-]+|\^\^<[^>]+>)?$/, '');
        const nameVals = preds.get(HAS_NAME) || [];
        const filename = nameVals.length > 0 ? stripLiteral(nameVals[0]) : uri.split(/[/#]/).pop() || uri;
        const ftVals = preds.get(HAS_FILE_TYPE) || [];
        const fileType = ftVals.length > 0 ? stripLiteral(ftVals[0]) : '';
        
        fileEntries.push({
          uri,
          rdf_type: rdfType,
          filename,
          file_type: fileType,
          file_size: 0,
          properties_count: preds.size,
        });
      }
      
      setFiles(fileEntries);
      console.log(`Files: ${fileEntries.length} of ${data.total_count ?? fileEntries.length} total`);
    } catch (err) {
      console.error('Error fetching files:', err);
      setError('Failed to load files. Please try again later.');
      setFiles([]);
    } finally {
      setLoading(false);
    }
  }, [selectedSpace, selectedGraph, filterText]);

  // Fetch files when selectedSpace/selectedGraph/filterText changes (debounced via fetchFiles dependency)
  useEffect(() => {
    if (selectedSpace && selectedGraph) {
      fetchFiles();
    } else {
      setFiles([]);
    }
  }, [selectedSpace, selectedGraph, fetchFiles]);

  // Preserve cursor position in filter input
  useLayoutEffect(() => {
    if (filterInputRef.current) {
      filterInputRef.current.setSelectionRange(cursorPositionRef.current, cursorPositionRef.current);
    }
  }, [filterText]);

  const handleDetailsClick = (file: FileEntry) => {
    if (spaceId && graphId) {
      navigate(`/space/${spaceId}/graph/${graphId}/file/${encodeURIComponent(file.uri)}`);
    } else if (selectedSpace && selectedGraph) {
      navigate(`/space/${selectedSpace}/graph/${encodeURIComponent(selectedGraph)}/file/${encodeURIComponent(file.uri)}`);
    }
  };

  const extractLocalName = (uri: string): string => {
    if (!uri) return '';
    const parts = uri.split(/[#/]/);
    return parts[parts.length - 1] || uri;
  };

  return (
    <div className="space-y-6">
      {/* Breadcrumb Navigation */}
      <NavigationBreadcrumb 
        spaceId={spaceId} 
        graphId={graphId} 
        currentPageName="Files" 
        currentPageIcon={HiDocumentDuplicate} 
      />

      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between">
        <div className="mb-6">
          <div className="flex items-center gap-2 mb-2">
            <HiDocumentDuplicate className="w-6 h-6 text-blue-600" />
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
              Files
            </h1>
          </div>
          <p className="text-gray-600 dark:text-gray-400">
            Manage files and documents within your graphs
          </p>
        </div>
        {selectedSpace && selectedGraph && (
          <Button 
            color="blue" 
            className="mt-4 sm:mt-0"
            onClick={() => navigate(`/space/${selectedSpace}/graph/${encodeURIComponent(selectedGraph)}/file/new`)}
          >
            <HiPlus className="mr-2 h-4 w-4" />
            Upload File
          </Button>
        )}
      </div>

      {/* Space and Graph Selection */}
      <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-end">
        <div className="flex-1 max-w-xs">
          <Label htmlFor="space-select">Select Space</Label>
          <Select
            id="space-select"
            value={selectedSpace}
            onChange={(e) => setSelectedSpace(e.target.value)}
            disabled={spacesLoading}
          >
            <option value="">Choose a space...</option>
            {spacesLoading ? (
              <option value="" disabled>Loading spaces...</option>
            ) : spaces.length === 0 ? (
              <option value="" disabled>No spaces available</option>
            ) : (
              spaces.map((space) => (
                <option key={space.space} value={space.space}>
                  {space.space_name || space.space}
                </option>
              ))
            )}
          </Select>
        </div>
        
        <div className="flex-1 max-w-xs">
          <Label htmlFor="graph-select">Select Graph</Label>
          <Select
            id="graph-select"
            value={selectedGraph}
            onChange={(e) => setSelectedGraph(e.target.value)}
            disabled={!selectedSpace || graphsLoading}
          >
            <option value="">Choose a graph...</option>
            {graphsLoading ? (
              <option value="" disabled>Loading graphs...</option>
            ) : graphs.length === 0 ? (
              <option value="" disabled>No graphs available</option>
            ) : (
              graphs.map((graph) => (
                <option key={graph.graph_uri} value={graph.graph_uri}>
                  {graph.graph_name} ({graph.triple_count} triples)
                </option>
              ))
            )}
          </Select>
        </div>
      </div>

      {/* Search Filter */}
      {selectedSpace && selectedGraph && (
        <div className="relative">
          <div className="relative">
            <HiSearch className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
            <TextInput
              ref={filterInputRef}
              type="text"
              placeholder="Search files by name..."
              value={filterText}
              onChange={(e) => {
                cursorPositionRef.current = e.target.selectionStart || 0;
                setFilterText(e.target.value);
              }}
              className="pl-10"
              onKeyDown={(e) => {
                cursorPositionRef.current = e.currentTarget.selectionStart || 0;
              }}
              onClick={(e) => {
                cursorPositionRef.current = e.currentTarget.selectionStart || 0;
              }}
              disabled={loading}
            />
            {loading && (
              <div className="absolute right-3 top-1/2 transform -translate-y-1/2">
                <Spinner size="sm" />
              </div>
            )}
          </div>
          {filterText && (
            <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
              {loading ? 'Filtering...' : `Showing results for "${filterText}"`}
            </p>
          )}
        </div>
      )}

      {/* Error Display */}
      {error && (
        <Alert color="failure" className="mb-6">
          <span className="font-medium">Error:</span> {error}
        </Alert>
      )}

      {/* Space and Graph Selection Required */}
      {!selectedSpace && !spacesLoading && (
        <div className="text-center py-12">
          <div className="text-gray-500 dark:text-gray-400">
            <p className="text-lg mb-2">Select a space to view files</p>
            <p className="text-sm">Choose a space from the dropdown above to see available graphs.</p>
          </div>
        </div>
      )}
      
      {selectedSpace && !selectedGraph && !graphsLoading && (
        <div className="text-center py-12">
          <div className="text-gray-500 dark:text-gray-400">
            <p className="text-lg mb-2">Select a graph to view files</p>
            <p className="text-sm">Choose a graph from the dropdown above to see its files.</p>
          </div>
        </div>
      )}

      {/* Files Table */}
      {selectedSpace && selectedGraph && files.length === 0 && !loading && !error ? (
        <Alert color="info">
          {filterText ? 
            `No files found matching "${filterText}". Try a different search term.` :
            'No files found in this graph. Upload your first file to get started.'
          }
        </Alert>
      ) : selectedSpace && selectedGraph && (
        <>
          {/* Desktop Table View */}
          <div className="hidden md:block overflow-x-auto">
            <Table striped>
              <TableHead>
                <TableRow>
                  <TableHeadCell>URI</TableHeadCell>
                  <TableHeadCell>Name</TableHeadCell>
                  <TableHeadCell>Type</TableHeadCell>
                  <TableHeadCell>Properties</TableHeadCell>
                  <TableHeadCell>Actions</TableHeadCell>
                </TableRow>
              </TableHead>
              <TableBody className="divide-y">
                {files.map((file) => (
                  <TableRow key={file.uri} className="bg-white dark:border-gray-700 dark:bg-gray-800">
                    <TableCell className="whitespace-nowrap font-medium text-gray-900 dark:text-white max-w-xs truncate" title={file.uri}>
                      {extractLocalName(file.uri)}
                    </TableCell>
                    <TableCell className="font-medium text-gray-900 dark:text-white">
                      {file.filename}
                    </TableCell>
                    <TableCell className="text-gray-500 dark:text-gray-400">
                      {file.file_type || extractLocalName(file.rdf_type)}
                    </TableCell>
                    <TableCell className="text-gray-500 dark:text-gray-400">
                      {file.properties_count} properties
                    </TableCell>
                    <TableCell>
                      <Button
                        size="sm"
                        color="blue"
                        onClick={() => handleDetailsClick(file)}
                      >
                        <HiEye className="mr-2 h-4 w-4" />
                        Details
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          {/* Mobile Card View */}
          <div className="md:hidden space-y-4">
            {files.map((file) => (
              <Card key={file.uri} className="w-full">
                <div className="space-y-3">
                  <div className="flex justify-between items-start">
                    <div>
                      <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                        {file.filename}
                      </h3>
                      <p className="text-sm text-gray-500 dark:text-gray-400 truncate max-w-xs" title={file.uri}>
                        {extractLocalName(file.uri)}
                      </p>
                    </div>
                    <Button
                      size="sm"
                      color="blue"
                      onClick={() => handleDetailsClick(file)}
                    >
                      <HiEye className="mr-1 h-4 w-4" />
                      Details
                    </Button>
                  </div>
                  <div className="grid grid-cols-2 gap-4 text-sm">
                    <div>
                      <span className="font-medium text-gray-900 dark:text-white">Type:</span>
                      <p className="text-gray-500 dark:text-gray-400">{file.file_type || extractLocalName(file.rdf_type)}</p>
                    </div>
                    <div>
                      <span className="font-medium text-gray-900 dark:text-white">Properties:</span>
                      <p className="text-gray-500 dark:text-gray-400">{file.properties_count}</p>
                    </div>
                  </div>
                </div>
              </Card>
            ))}
          </div>
        </>
      )}

      {/* Loading Spinner */}
      {loading && selectedSpace && selectedGraph && (
        <div className="flex justify-center py-8">
          <Spinner size="lg" />
        </div>
      )}
    </div>
  );
};

export default Files;

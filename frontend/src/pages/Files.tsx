import React, { useState, useEffect, useCallback, useRef, useLayoutEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Alert, Button, Card, Spinner, Table, TableBody, TableCell, TableHead, TableHeadCell, TableRow, TextInput, Select, Label } from 'flowbite-react';
import { HiPlus, HiEye } from 'react-icons/hi2';
import { HiSearch, HiDocumentDuplicate } from 'react-icons/hi';
import NavigationBreadcrumb from '../components/NavigationBreadcrumb';

interface File {
  id: number;
  space_id: string;
  graph_id: number;
  filename: string;
  file_path: string;
  file_size: number;
  file_type: string;
  upload_time: string;
  last_modified: string;
}

interface Space {
  id: number;
  tenant: string;
  space: string;
  space_name: string;
  space_description: string;
  update_time: string;
}

interface Graph {
  id: number;
  space_id: string;
  graph_name: string;
  graph_uri: string;
  graph_type: string;
  triple_count: number;
  created_time: string;
  last_modified: string;
  description: string;
  status: 'active' | 'inactive' | 'processing';
}

const Files: React.FC = () => {
  const navigate = useNavigate();
  const { spaceId, graphId } = useParams<{ spaceId?: string; graphId?: string }>();
  const filterInputRef = useRef<HTMLInputElement>(null);
  const cursorPositionRef = useRef<number>(0);
  const [files, setFiles] = useState<File[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [filterText, setFilterText] = useState<string>('');
  const [filterLoading, setFilterLoading] = useState<boolean>(false);
  const [spaces, setSpaces] = useState<Space[]>([]);
  const [selectedSpace, setSelectedSpace] = useState<string>(spaceId || '');
  const [spacesLoading, setSpacesLoading] = useState<boolean>(true);
  const [graphs, setGraphs] = useState<Graph[]>([]);
  const [selectedGraph, setSelectedGraph] = useState<number | ''>(graphId ? parseInt(graphId) : '');

  // Navigate to hierarchical URL when space/graph selection changes
  useEffect(() => {
    if (selectedSpace && selectedGraph !== '' && !spaceId && !graphId) {
      navigate(`/space/${selectedSpace}/graph/${selectedGraph}/files`);
    }
  }, [selectedSpace, selectedGraph, navigate, spaceId, graphId]);
  const [graphsLoading, setGraphsLoading] = useState<boolean>(false);

  // Fetch available spaces
  const fetchSpaces = useCallback(async () => {
    // Mock spaces data - replace with API call when backend is ready
    const mockSpaces = [
      { 
        id: 1, 
        tenant: 'default', 
        space: 'space1', 
        space_name: 'Default Space', 
        space_description: 'Default workspace for general files',
        update_time: '2024-01-15T10:00:00Z'
      },
      { 
        id: 2, 
        tenant: 'default', 
        space: 'space2', 
        space_name: 'Project Alpha', 
        space_description: 'Files related to Project Alpha',
        update_time: '2024-01-14T15:30:00Z'
      },
      { 
        id: 3, 
        tenant: 'default', 
        space: 'space3', 
        space_name: 'Research Data', 
        space_description: 'Research datasets and documentation',
        update_time: '2024-01-13T09:20:00Z'
      }
    ];
    setSpaces(mockSpaces);
    setSpacesLoading(false);
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

    setGraphsLoading(true);
    // Mock graphs data - same as used in Objects screen
    const mockGraphs: Graph[] = [
      // Space1 graphs
      { id: 0, space_id: 'space1', graph_name: 'Global', graph_uri: 'http://vital.ai/graph/global', graph_type: 'Global Graph', triple_count: 0, created_time: '2024-01-01T00:00:00Z', last_modified: '2024-01-01T00:00:00Z', description: 'Global graph for files not assigned to a specific graph', status: 'active' },
      { id: 1, space_id: 'space1', graph_name: 'knowledge-base', graph_uri: 'http://vital.ai/graph/knowledge-base', graph_type: 'Knowledge Graph', triple_count: 15420, created_time: '2024-01-15T10:30:00Z', last_modified: '2024-01-20T14:15:00Z', description: 'Main knowledge base graph', status: 'active' },
      { id: 2, space_id: 'space1', graph_name: 'ontology-core', graph_uri: 'http://vital.ai/graph/ontology-core', graph_type: 'Ontology', triple_count: 8750, created_time: '2024-01-14T14:20:00Z', last_modified: '2024-01-19T11:30:00Z', description: 'Core ontology definitions', status: 'active' },
      // Space2 graphs
      { id: 0, space_id: 'space2', graph_name: 'Global', graph_uri: 'http://vital.ai/graph/global', graph_type: 'Global Graph', triple_count: 0, created_time: '2024-01-01T00:00:00Z', last_modified: '2024-01-01T00:00:00Z', description: 'Global graph for files not assigned to a specific graph', status: 'active' },
      { id: 3, space_id: 'space2', graph_name: 'alpha-entities', graph_uri: 'http://vital.ai/graph/alpha-entities', graph_type: 'Entity Graph', triple_count: 25680, created_time: '2024-01-13T16:45:00Z', last_modified: '2024-01-18T09:20:00Z', description: 'Project Alpha entity relationships', status: 'active' },
      { id: 4, space_id: 'space2', graph_name: 'alpha-workflow', graph_uri: 'http://vital.ai/graph/alpha-workflow', graph_type: 'Process Graph', triple_count: 12340, created_time: '2024-01-12T11:20:00Z', last_modified: '2024-01-17T15:45:00Z', description: 'Alpha project workflow definitions', status: 'processing' },
      // Space3 graphs
      { id: 0, space_id: 'space3', graph_name: 'Global', graph_uri: 'http://vital.ai/graph/global', graph_type: 'Global Graph', triple_count: 0, created_time: '2024-01-01T00:00:00Z', last_modified: '2024-01-01T00:00:00Z', description: 'Global graph for files not assigned to a specific graph', status: 'active' },
      { id: 5, space_id: 'space3', graph_name: 'research-dataset', graph_uri: 'http://vital.ai/graph/research-dataset', graph_type: 'Data Graph', triple_count: 45230, created_time: '2024-01-11T09:15:00Z', last_modified: '2024-01-16T13:25:00Z', description: 'Research data relationships', status: 'active' },
      { id: 6, space_id: 'space3', graph_name: 'analysis-results', graph_uri: 'http://vital.ai/graph/analysis-results', graph_type: 'Results Graph', triple_count: 18920, created_time: '2024-01-10T13:30:00Z', last_modified: '2024-01-15T10:40:00Z', description: 'Analysis results and conclusions', status: 'inactive' }
    ];

    const spaceGraphs = mockGraphs.filter(graph => graph.space_id === selectedSpace);
    setGraphs(spaceGraphs);
    setGraphsLoading(false);
  }, [selectedSpace]);

  useEffect(() => {
    fetchGraphs();
    if (!graphId) {
      setSelectedGraph(''); // Reset graph selection when space changes only if not from URL
    }
  }, [fetchGraphs, graphId]);


  // Fetch all files for selected space
  const fetchFiles = useCallback(async () => {
    if (!selectedSpace) return;
    
    try {
      setLoading(true);
      // Mock files data - different files for each space and graph
      const allMockFiles = [
        // Space1 files
        {
          id: 1,
          space_id: 'space1',
          graph_id: 0, // Global
          filename: 'document1.pdf',
          file_path: '/uploads/document1.pdf',
          file_size: 2048576,
          file_type: 'application/pdf',
          upload_time: '2024-01-15T10:30:00Z',
          last_modified: '2024-01-15T10:30:00Z'
        },
        {
          id: 2,
          space_id: 'space1',
          graph_id: 1, // knowledge-base
          filename: 'meeting-notes.docx',
          file_path: '/uploads/meeting-notes.docx',
          file_size: 512000,
          file_type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
          upload_time: '2024-01-14T14:20:00Z',
          last_modified: '2024-01-16T09:15:00Z'
        },
        {
          id: 7,
          space_id: 'space1',
          graph_id: 2, // ontology-core
          filename: 'ontology-spec.owl',
          file_path: '/uploads/ontology-spec.owl',
          file_size: 1024000,
          file_type: 'application/rdf+xml',
          upload_time: '2024-01-13T12:00:00Z',
          last_modified: '2024-01-18T16:30:00Z'
        },
        // Space2 files
        {
          id: 3,
          space_id: 'space2',
          graph_id: 0, // Global
          filename: 'alpha-requirements.pdf',
          file_path: '/uploads/alpha-requirements.pdf',
          file_size: 1536000,
          file_type: 'application/pdf',
          upload_time: '2024-01-13T16:45:00Z',
          last_modified: '2024-01-13T16:45:00Z'
        },
        {
          id: 4,
          space_id: 'space2',
          graph_id: 3, // alpha-entities
          filename: 'alpha-timeline.xlsx',
          file_path: '/uploads/alpha-timeline.xlsx',
          file_size: 768000,
          file_type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
          upload_time: '2024-01-12T11:20:00Z',
          last_modified: '2024-01-15T14:30:00Z'
        },
        {
          id: 8,
          space_id: 'space2',
          graph_id: 4, // alpha-workflow
          filename: 'workflow-definition.json',
          file_path: '/uploads/workflow-definition.json',
          file_size: 256000,
          file_type: 'application/json',
          upload_time: '2024-01-11T14:15:00Z',
          last_modified: '2024-01-17T10:45:00Z'
        },
        // Space3 files
        {
          id: 5,
          space_id: 'space3',
          graph_id: 0, // Global
          filename: 'research-data.csv',
          file_path: '/uploads/research-data.csv',
          file_size: 3072000,
          file_type: 'text/csv',
          upload_time: '2024-01-11T09:15:00Z',
          last_modified: '2024-01-14T16:45:00Z'
        },
        {
          id: 6,
          space_id: 'space3',
          graph_id: 5, // research-dataset
          filename: 'analysis-report.pdf',
          file_path: '/uploads/analysis-report.pdf',
          file_size: 2560000,
          file_type: 'application/pdf',
          upload_time: '2024-01-10T13:30:00Z',
          last_modified: '2024-01-12T10:20:00Z'
        },
        {
          id: 9,
          space_id: 'space3',
          graph_id: 6, // analysis-results
          filename: 'statistical-output.txt',
          file_path: '/uploads/statistical-output.txt',
          file_size: 128000,
          file_type: 'text/plain',
          upload_time: '2024-01-09T11:00:00Z',
          last_modified: '2024-01-15T09:20:00Z'
        }
      ];
      
      // Filter files for the selected space and graph
      const spaceFiles = allMockFiles.filter(file => file.space_id === selectedSpace);
      const mockFiles = selectedGraph !== '' ? 
        spaceFiles.filter(file => file.graph_id === selectedGraph) : 
        [];
      
      console.log('Files Debug:', {
        selectedSpace,
        selectedGraph,
        totalFiles: allMockFiles.length,
        spaceFiles: spaceFiles.length,
        filteredFiles: mockFiles.length,
        mockFiles
      });
      
      setFiles(mockFiles);
      setError(null);
    } catch (err) {
      setError('Failed to load files. Please try again later.');
      setFiles([]);
    } finally {
      setLoading(false);
    }
  }, [selectedSpace, selectedGraph]);

  // Filter files by name
  const filterFiles = useCallback(async (nameFilter: string) => {
    if (!selectedSpace || selectedGraph === '') return;
    
    if (!nameFilter.trim()) {
      // If filter is empty and not already loading data, fetch all files
      if (loading) {
        return;
      }
      await fetchFiles();
      return;
    }

    try {
      setFilterLoading(true);
      // Use the same mock data as fetchFiles but with graph_id
      const allMockFiles = [
        // Space1 files
        {
          id: 1,
          space_id: 'space1',
          graph_id: 0,
          filename: 'document1.pdf',
          file_path: '/uploads/document1.pdf',
          file_size: 2048576,
          file_type: 'application/pdf',
          upload_time: '2024-01-15T10:30:00Z',
          last_modified: '2024-01-15T10:30:00Z'
        },
        {
          id: 2,
          space_id: 'space1',
          graph_id: 1,
          filename: 'meeting-notes.docx',
          file_path: '/uploads/meeting-notes.docx',
          file_size: 512000,
          file_type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
          upload_time: '2024-01-14T14:20:00Z',
          last_modified: '2024-01-16T09:15:00Z'
        },
        {
          id: 7,
          space_id: 'space1',
          graph_id: 2,
          filename: 'ontology-spec.owl',
          file_path: '/uploads/ontology-spec.owl',
          file_size: 1024000,
          file_type: 'application/rdf+xml',
          upload_time: '2024-01-13T12:00:00Z',
          last_modified: '2024-01-18T16:30:00Z'
        },
        // Space2 files
        {
          id: 3,
          space_id: 'space2',
          graph_id: 0,
          filename: 'alpha-requirements.pdf',
          file_path: '/uploads/alpha-requirements.pdf',
          file_size: 1536000,
          file_type: 'application/pdf',
          upload_time: '2024-01-13T16:45:00Z',
          last_modified: '2024-01-13T16:45:00Z'
        },
        {
          id: 4,
          space_id: 'space2',
          graph_id: 3,
          filename: 'alpha-timeline.xlsx',
          file_path: '/uploads/alpha-timeline.xlsx',
          file_size: 768000,
          file_type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
          upload_time: '2024-01-12T11:20:00Z',
          last_modified: '2024-01-15T14:30:00Z'
        },
        {
          id: 8,
          space_id: 'space2',
          graph_id: 4,
          filename: 'workflow-definition.json',
          file_path: '/uploads/workflow-definition.json',
          file_size: 256000,
          file_type: 'application/json',
          upload_time: '2024-01-11T14:15:00Z',
          last_modified: '2024-01-17T10:45:00Z'
        },
        // Space3 files
        {
          id: 5,
          space_id: 'space3',
          graph_id: 0,
          filename: 'research-data.csv',
          file_path: '/uploads/research-data.csv',
          file_size: 3072000,
          file_type: 'text/csv',
          upload_time: '2024-01-11T09:15:00Z',
          last_modified: '2024-01-14T16:45:00Z'
        },
        {
          id: 6,
          space_id: 'space3',
          graph_id: 5,
          filename: 'analysis-report.pdf',
          file_path: '/uploads/analysis-report.pdf',
          file_size: 2560000,
          file_type: 'application/pdf',
          upload_time: '2024-01-10T13:30:00Z',
          last_modified: '2024-01-12T10:20:00Z'
        },
        {
          id: 9,
          space_id: 'space3',
          graph_id: 6,
          filename: 'statistical-output.txt',
          file_path: '/uploads/statistical-output.txt',
          file_size: 128000,
          file_type: 'text/plain',
          upload_time: '2024-01-09T11:00:00Z',
          last_modified: '2024-01-15T09:20:00Z'
        }
      ];
      
      // Filter files for the selected space, graph, and by filename
      const spaceFiles = allMockFiles.filter(file => file.space_id === selectedSpace && file.graph_id === selectedGraph);
      const filteredFiles = spaceFiles.filter(file => 
        file.filename.toLowerCase().includes(nameFilter.toLowerCase())
      );
      
      setFiles(filteredFiles);
      setError(null);
    } catch (err) {
      console.error('Error filtering files:', err);
      setError('Failed to filter files. Please try again later.');
      setFiles([]);
    } finally {
      setFilterLoading(false);
    }
  }, [selectedSpace, selectedGraph, loading, fetchFiles]);

  // Fetch files when selectedSpace or selectedGraph changes
  useEffect(() => {
    if (selectedSpace && selectedGraph !== '') {
      fetchFiles();
    } else {
      setFiles([]);
    }
  }, [selectedSpace, selectedGraph, fetchFiles]);

  // Handle filter input changes with debouncing
  useEffect(() => {
    const timeoutId = setTimeout(() => {
      filterFiles(filterText);
    }, 300);

    return () => clearTimeout(timeoutId);
  }, [filterText, filterFiles]);

  // Preserve cursor position in filter input
  useLayoutEffect(() => {
    if (filterInputRef.current) {
      filterInputRef.current.setSelectionRange(cursorPositionRef.current, cursorPositionRef.current);
    }
  }, [filterText]);

  const handleDetailsClick = (file: File) => {
    // Use hierarchical URL structure
    if (spaceId && graphId) {
      navigate(`/space/${spaceId}/graph/${graphId}/file/${file.id}`);
    } else {
      navigate(`/file/${file.id}`);
    }
  };

  const formatDate = (dateString: string): string => {
    try {
      return new Date(dateString).toLocaleString();
    } catch {
      return 'Invalid date';
    }
  };

  const formatFileSize = (bytes: number): string => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
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
        {selectedSpace && selectedGraph !== '' && (
          <Button 
            color="blue" 
            className="mt-4 sm:mt-0"
            onClick={() => navigate(`/space/${selectedSpace}/graph/${selectedGraph}/file/new`)}
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
            onChange={(e) => setSelectedGraph(e.target.value === '' ? '' : parseInt(e.target.value))}
            disabled={!selectedSpace || graphsLoading}
          >
            <option value="">Choose a graph...</option>
            {graphsLoading ? (
              <option value="" disabled>Loading graphs...</option>
            ) : graphs.length === 0 ? (
              <option value="" disabled>No graphs available</option>
            ) : (
              graphs.map((graph) => (
                <option key={graph.id} value={graph.id}>
                  {graph.graph_name}
                </option>
              ))
            )}
          </Select>
        </div>
      </div>

      {/* Search Filter */}
      {selectedSpace && selectedGraph !== '' && (
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
              disabled={filterLoading}
            />
            {filterLoading && (
              <div className="absolute right-3 top-1/2 transform -translate-y-1/2">
                <Spinner size="sm" />
              </div>
            )}
          </div>
          {filterText && (
            <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
              {filterLoading ? 'Filtering...' : `Showing results for "${filterText}"`}
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
      
      {selectedSpace && selectedGraph === '' && !graphsLoading && (
        <div className="text-center py-12">
          <div className="text-gray-500 dark:text-gray-400">
            <p className="text-lg mb-2">Select a graph to view files</p>
            <p className="text-sm">Choose a graph from the dropdown above to see its files.</p>
          </div>
        </div>
      )}

      {/* Files Table */}
      {selectedSpace && selectedGraph !== '' && files.length === 0 && !loading && !error ? (
        <Alert color="info">
          {filterText ? 
            `No files found matching "${filterText}". Try a different search term.` :
            'No files found in this graph. Upload your first file to get started.'
          }
        </Alert>
      ) : selectedSpace && selectedGraph !== '' && (
        <>
          {/* Desktop Table View */}
          <div className="hidden md:block overflow-x-auto">
            <Table striped>
              <TableHead>
                <TableRow>
                  <TableHeadCell>ID</TableHeadCell>
                  <TableHeadCell>Filename</TableHeadCell>
                  <TableHeadCell>Type</TableHeadCell>
                  <TableHeadCell>Size</TableHeadCell>
                  <TableHeadCell>Upload Time</TableHeadCell>
                  <TableHeadCell>Last Modified</TableHeadCell>
                  <TableHeadCell>Actions</TableHeadCell>
                </TableRow>
              </TableHead>
              <TableBody className="divide-y">
                {files.map((file) => (
                  <TableRow key={file.id} className="bg-white dark:border-gray-700 dark:bg-gray-800">
                    <TableCell className="whitespace-nowrap font-medium text-gray-900 dark:text-white">
                      {file.id}
                    </TableCell>
                    <TableCell className="font-medium text-gray-900 dark:text-white">
                      {file.filename}
                    </TableCell>
                    <TableCell className="text-gray-500 dark:text-gray-400">
                      {file.file_type || 'Unknown'}
                    </TableCell>
                    <TableCell className="text-gray-500 dark:text-gray-400">
                      {formatFileSize(file.file_size)}
                    </TableCell>
                    <TableCell className="text-gray-500 dark:text-gray-400">
                      {formatDate(file.upload_time)}
                    </TableCell>
                    <TableCell className="text-gray-500 dark:text-gray-400">
                      {formatDate(file.last_modified)}
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
              <Card key={file.id} className="w-full">
                <div className="space-y-3">
                  <div className="flex justify-between items-start">
                    <div>
                      <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                        {file.filename}
                      </h3>
                      <p className="text-sm text-gray-500 dark:text-gray-400">
                        ID: {file.id}
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
                      <p className="text-gray-500 dark:text-gray-400">{file.file_type || 'Unknown'}</p>
                    </div>
                    <div>
                      <span className="font-medium text-gray-900 dark:text-white">Size:</span>
                      <p className="text-gray-500 dark:text-gray-400">{formatFileSize(file.file_size)}</p>
                    </div>
                    <div>
                      <span className="font-medium text-gray-900 dark:text-white">Uploaded:</span>
                      <p className="text-gray-500 dark:text-gray-400">{formatDate(file.upload_time)}</p>
                    </div>
                    <div>
                      <span className="font-medium text-gray-900 dark:text-white">Modified:</span>
                      <p className="text-gray-500 dark:text-gray-400">{formatDate(file.last_modified)}</p>
                    </div>
                  </div>
                </div>
              </Card>
            ))}
          </div>
        </>
      )}

      {/* Loading Spinner */}
      {loading && selectedSpace && selectedGraph !== '' && (
        <div className="flex justify-center py-8">
          <Spinner size="lg" />
        </div>
      )}
    </div>
  );
};

export default Files;

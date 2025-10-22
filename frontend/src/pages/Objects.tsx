import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Button,
  Select,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeadCell,
  TableRow,
  Breadcrumb,
  BreadcrumbItem,
  TextInput,
  Badge,
  Label,
  Spinner
} from 'flowbite-react';
import {
  HiTrash,
  HiEye,
  HiSearch,
  HiHome,
  HiViewBoards
} from 'react-icons/hi';
import { mockSpaces, mockGraphs, mockObjects, type Space, type Graph, type RDFObject } from '../mock';
import ObjectIcon from '../components/icons/ObjectIcon';
import GraphIcon from '../components/icons/GraphIcon';

const Objects: React.FC = () => {
  const navigate = useNavigate();
  const { spaceId, graphId } = useParams<{ spaceId?: string; graphId?: string }>();
  const [spaces, setSpaces] = useState<Space[]>([]);
  const [selectedSpace, setSelectedSpace] = useState<string>(spaceId || '');
  const [spacesLoading, setSpacesLoading] = useState<boolean>(true);
  const [graphs, setGraphs] = useState<Graph[]>([]);
  const [selectedGraph, setSelectedGraph] = useState<number | ''>(graphId ? parseInt(graphId) : '');

  // Navigate to hierarchical URL when space/graph selection changes
  useEffect(() => {
    if (selectedSpace && selectedGraph !== '' && !spaceId && !graphId) {
      navigate(`/space/${selectedSpace}/graph/${selectedGraph}/objects`);
    }
  }, [selectedSpace, selectedGraph, navigate, spaceId, graphId]);

  const [searchTerm, setSearchTerm] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(false);
  const [graphsLoading, setGraphsLoading] = useState<boolean>(false);
  const [objects, setObjects] = useState<RDFObject[]>([]);
  const [currentSpace, setCurrentSpace] = useState<Space | null>(null);
  const [currentGraph, setCurrentGraph] = useState<Graph | null>(null);
  const [showDeleteModal, setShowDeleteModal] = useState<boolean>(false);
  const [objectToDelete, setObjectToDelete] = useState<RDFObject | null>(null);
  const [filterLoading, setFilterLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch spaces on component mount
  useEffect(() => {
    // Simulate loading with mock data
    setTimeout(() => {
      setSpaces(mockSpaces);
      setSpacesLoading(false);
    }, 500);
  }, []);

  // Fetch graphs when space is selected
  const fetchGraphs = useCallback(async () => {
    if (!selectedSpace) {
      setGraphs([]);
      setSelectedGraph('');
      return;
    }

    try {
      setGraphsLoading(true);
      // Filter graphs for the selected space
      const spaceGraphs = mockGraphs.filter((graph: Graph) => graph.space_id === selectedSpace);
      
      setTimeout(() => {
        setGraphs(spaceGraphs);
        setGraphsLoading(false);
      }, 300);
    } catch (err) {
      console.error('Error fetching graphs:', err);
      setGraphs([]);
      setGraphsLoading(false);
    }
  }, [selectedSpace]);

  // Reset graph selection when space changes
  useEffect(() => {
    fetchGraphs();
    if (!graphId) {
      setSelectedGraph(''); // Reset graph selection when space changes only if not from URL
    }
  }, [fetchGraphs, graphId]);

  // Update current space and graph for breadcrumbs
  useEffect(() => {
    if (selectedSpace && spaces.length > 0) {
      const space = spaces.find(s => s.space === selectedSpace);
      setCurrentSpace(space || null);
    }
  }, [selectedSpace, spaces]);

  useEffect(() => {
    if (selectedGraph !== '' && graphs.length > 0) {
      const graph = graphs.find(g => g.id === selectedGraph);
      setCurrentGraph(graph || null);
    }
  }, [selectedGraph, graphs]);

  const handleDeleteObject = async () => {
    if (!objectToDelete) return;
    
    try {
      // Simulate API call
      await new Promise(resolve => setTimeout(resolve, 1000));
      
      // Remove object from list
      setObjects(prev => prev.filter(obj => obj.id !== objectToDelete.id));
      setShowDeleteModal(false);
      setObjectToDelete(null);
    } catch (error) {
      console.error('Failed to delete object:', error);
    }
  };

  // Fetch objects when space and graph are selected
  const handleSearch = useCallback(async () => {
    if (!selectedSpace || selectedGraph === '') {
      setError('Please select both space and graph');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      // Simulate API call
      await new Promise(resolve => setTimeout(resolve, 800));
      
      // Filter mock objects based on search term and selected graph
      const filteredObjects = mockObjects.filter(obj => {
        const matchesGraph = obj.graph_id === selectedGraph;
        const matchesSearch = !searchTerm || 
          obj.subject.toLowerCase().includes(searchTerm.toLowerCase()) ||
          obj.object_type.toLowerCase().includes(searchTerm.toLowerCase());
        return matchesGraph && matchesSearch;
      });
      
      setObjects(filteredObjects);
    } catch (err) {
      setError('Failed to fetch objects. Please try again.');
    } finally {
      setLoading(false);
    }
  }, [selectedSpace, selectedGraph, searchTerm]);

  // Auto-fetch objects when space and graph are selected
  useEffect(() => {
    if (selectedSpace && selectedGraph !== '') {
      handleSearch();
    }
  }, [selectedSpace, selectedGraph, handleSearch]);

  // Filter objects by URI or type
  const filterObjects = useCallback(async (nameFilter: string) => {
    if (!selectedSpace || selectedGraph === '') return;
    
    if (!nameFilter.trim()) {
      // If filter is empty, show all objects for the selected graph
      handleSearch();
      return;
    }

    try {
      setFilterLoading(true);
      // Mock filtering - use the same data structure as fetchObjects
      const allMockObjects = [
        // Space1 objects
        {
          id: 1,
          space_id: 'space1',
          graph_id: 1,
          object_uri: 'http://vital.ai/ontology/Person#john-doe',
          object_type: 'Node' as const,
          rdf_type: 'http://vital.ai/ontology/Person',
          subject: 'http://vital.ai/ontology/Person#john-doe',
          predicate: 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
          object: 'http://vital.ai/ontology/Person',
          context: 'http://vital.ai/graph/knowledge-base',
          created_time: '2024-01-15T10:30:00Z',
          last_modified: '2024-01-20T14:15:00Z',
          properties_count: 8
        },
        {
          id: 2,
          space_id: 'space1',
          graph_id: 1,
          object_uri: 'http://vital.ai/ontology/Organization#acme-corp',
          object_type: 'Node' as const,
          rdf_type: 'http://vital.ai/ontology/Organization',
          subject: 'http://vital.ai/ontology/Organization#acme-corp',
          predicate: 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
          object: 'http://vital.ai/ontology/Organization',
          context: 'http://vital.ai/graph/knowledge-base',
          created_time: '2024-01-14T14:20:00Z',
          last_modified: '2024-01-19T11:30:00Z',
          properties_count: 12
        },
        {
          id: 3,
          space_id: 'space1',
          graph_id: 2,
          object_uri: 'http://vital.ai/ontology/WorksFor#john-acme',
          object_type: 'Edge' as const,
          rdf_type: 'http://vital.ai/ontology/WorksFor',
          subject: 'http://vital.ai/ontology/Person#john-doe',
          predicate: 'http://vital.ai/ontology/worksFor',
          object: 'http://vital.ai/ontology/Organization#acme-corp',
          context: 'http://vital.ai/graph/ontology-core',
          created_time: '2024-01-16T09:15:00Z',
          last_modified: '2024-01-18T16:45:00Z',
          properties_count: 5
        },
        // Space2 objects
        {
          id: 4,
          space_id: 'space2',
          graph_id: 3,
          object_uri: 'http://vital.ai/ontology/Project#alpha-project',
          object_type: 'Node' as const,
          rdf_type: 'http://vital.ai/ontology/Project',
          subject: 'http://vital.ai/ontology/Project#alpha-project',
          predicate: 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
          object: 'http://vital.ai/ontology/Project',
          context: 'http://vital.ai/graph/alpha-entities',
          created_time: '2024-01-13T16:45:00Z',
          last_modified: '2024-01-18T09:20:00Z',
          properties_count: 15
        },
        {
          id: 5,
          space_id: 'space2',
          graph_id: 4,
          object_uri: 'http://vital.ai/ontology/Task#alpha-task-001',
          object_type: 'Node' as const,
          rdf_type: 'http://vital.ai/ontology/Task',
          subject: 'http://vital.ai/ontology/Task#alpha-task-001',
          predicate: 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
          object: 'http://vital.ai/ontology/Task',
          context: 'http://vital.ai/graph/alpha-workflow',
          created_time: '2024-01-12T11:20:00Z',
          last_modified: '2024-01-17T15:45:00Z',
          properties_count: 9
        },
        {
          id: 6,
          space_id: 'space2',
          graph_id: 4,
          object_uri: 'http://vital.ai/ontology/PartOf#task-project',
          object_type: 'Edge' as const,
          rdf_type: 'http://vital.ai/ontology/PartOf',
          subject: 'http://vital.ai/ontology/Task#alpha-task-001',
          predicate: 'http://vital.ai/ontology/partOf',
          object: 'http://vital.ai/ontology/Project#alpha-project',
          context: 'http://vital.ai/graph/alpha-workflow',
          created_time: '2024-01-12T12:30:00Z',
          last_modified: '2024-01-17T16:00:00Z',
          properties_count: 3
        },
        // Space3 objects
        {
          id: 7,
          space_id: 'space3',
          graph_id: 5,
          object_uri: 'http://vital.ai/ontology/Dataset#research-data-001',
          object_type: 'Node' as const,
          rdf_type: 'http://vital.ai/ontology/Dataset',
          subject: 'http://vital.ai/ontology/Dataset#research-data-001',
          predicate: 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
          object: 'http://vital.ai/ontology/Dataset',
          context: 'http://vital.ai/graph/research-dataset',
          created_time: '2024-01-11T09:15:00Z',
          last_modified: '2024-01-16T13:25:00Z',
          properties_count: 18
        },
        {
          id: 8,
          space_id: 'space3',
          graph_id: 6,
          object_uri: 'http://vital.ai/ontology/Analysis#analysis-001',
          object_type: 'Node' as const,
          rdf_type: 'http://vital.ai/ontology/Analysis',
          subject: 'http://vital.ai/ontology/Analysis#analysis-001',
          predicate: 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
          object: 'http://vital.ai/ontology/Analysis',
          context: 'http://vital.ai/graph/analysis-results',
          created_time: '2024-01-10T13:30:00Z',
          last_modified: '2024-01-15T10:40:00Z',
          properties_count: 22
        },
        {
          id: 9,
          space_id: 'space3',
          graph_id: 6,
          object_uri: 'http://vital.ai/ontology/AnalyzedBy#data-analysis',
          object_type: 'Edge' as const,
          rdf_type: 'http://vital.ai/ontology/AnalyzedBy',
          subject: 'http://vital.ai/ontology/Dataset#research-data-001',
          predicate: 'http://vital.ai/ontology/analyzedBy',
          object: 'http://vital.ai/ontology/Analysis#analysis-001',
          context: 'http://vital.ai/graph/analysis-results',
          created_time: '2024-01-11T14:20:00Z',
          last_modified: '2024-01-15T11:15:00Z',
          properties_count: 4
        }
      ];

      // Filter objects for the selected space, graph, and by URI or type
      const spaceObjects = allMockObjects.filter(obj => 
        obj.space_id === selectedSpace && obj.graph_id === selectedGraph
      );
      const filteredObjects = spaceObjects.filter(obj => 
        obj.object_uri.toLowerCase().includes(nameFilter.toLowerCase()) ||
        obj.rdf_type.toLowerCase().includes(nameFilter.toLowerCase())
      ).map(obj => ({
        ...obj,
        properties: (obj as any).properties || []
      }));
      
      setObjects(filteredObjects);
      setError(null);
    } catch (err) {
      console.error('Error filtering objects:', err);
      setError('Failed to filter objects. Please try again later.');
      setObjects([]);
    } finally {
      setFilterLoading(false);
    }
  }, [selectedSpace, selectedGraph, loading]);

  const handleSearchClick = () => {
    filterObjects(searchTerm);
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleSearchClick();
    }
  };

  const formatDateTime = (dateString: string): string => {
    return new Date(dateString).toLocaleString();
  };

  const getObjectTypeBadge = (type: string) => {
    return type === 'Node' ? 
      <Badge color="blue">Node</Badge> : 
      <Badge color="green">Edge</Badge>;
  };

  const extractLocalName = (uri: string): string => {
    const parts = uri.split(/[#/]/);
    return parts[parts.length - 1] || uri;
  };

  return (
    <div className="space-y-6">
      {/* Breadcrumb - only show if we have URL parameters */}
      {(spaceId || graphId) && (
        <Breadcrumb className="mb-6">
          <BreadcrumbItem href="/" icon={HiHome}>
            Home
          </BreadcrumbItem>
          <BreadcrumbItem href="/spaces" icon={HiViewBoards}>Spaces</BreadcrumbItem>
          {currentSpace && (
            <BreadcrumbItem href={`/space/${spaceId}`}>
              {currentSpace.space_name}
            </BreadcrumbItem>
          )}
          <BreadcrumbItem href={`/space/${spaceId}/graphs`} icon={GraphIcon}>Graphs</BreadcrumbItem>
          {currentGraph && (
            <BreadcrumbItem href={`/space/${spaceId}/graph/${graphId}`}>
              {currentGraph.graph_name}
            </BreadcrumbItem>
          )}
          <BreadcrumbItem icon={ObjectIcon}>Objects</BreadcrumbItem>
        </Breadcrumb>
      )}

      {/* Page Header */}
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-2">
          <ObjectIcon className="w-6 h-6 text-blue-600" />
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            Objects
          </h1>
        </div>
        <p className="text-gray-600 dark:text-gray-400">
          Manage RDF objects (nodes and edges) within your graphs
        </p>
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
            onChange={(e) => {
              const newGraphId = e.target.value === '' ? '' : parseInt(e.target.value);
              setSelectedGraph(newGraphId);
              
              // Navigate to new URL when graph changes
              if (selectedSpace && newGraphId !== '' && spaceId) {
                navigate(`/space/${selectedSpace}/graph/${newGraphId}/objects`);
              }
            }}
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

      {/* Search Section */}
      {selectedSpace && selectedGraph !== '' && (
        <div className="mt-6 flex flex-col sm:flex-row gap-4 items-start sm:items-end">
          <div className="flex-1 max-w-md">
            <Label htmlFor="search-input">Search Objects</Label>
            <TextInput
              id="search-input"
              type="text"
              placeholder="Enter object URI or type..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              onKeyPress={handleKeyPress}
              disabled={loading || filterLoading}
            />
          </div>
          <Button
            onClick={handleSearchClick}
            disabled={loading || filterLoading}
            className="whitespace-nowrap"
          >
            <HiSearch className="mr-2 h-4 w-4" />
            {filterLoading ? 'Searching...' : 'Search'}
          </Button>
        </div>
      )}

      {/* Error Message */}
      {error && (
        <div className="mt-4 p-4 bg-red-50 border border-red-200 rounded-lg dark:bg-red-900/20 dark:border-red-800">
          <p className="text-red-800 dark:text-red-200">{error}</p>
        </div>
      )}

      {/* Loading Spinner */}
      {selectedSpace && selectedGraph !== '' && loading && (
        <div className="mt-8 flex justify-center">
          <Spinner size="lg" />
          <span className="ml-2 text-gray-600 dark:text-gray-400">Loading objects...</span>
        </div>
      )}

      {/* Objects Table */}
      {selectedSpace && selectedGraph !== '' && !loading && objects.length > 0 && (
        <div className="mt-6">
          <div className="overflow-x-auto">
            <Table>
              <TableHead>
                <TableRow>
                  <TableHeadCell>Object URI</TableHeadCell>
                  <TableHeadCell>Type</TableHeadCell>
                  <TableHeadCell>RDF Type</TableHeadCell>
                  <TableHeadCell>Properties</TableHeadCell>
                  <TableHeadCell>Last Modified</TableHeadCell>
                  <TableHeadCell>Actions</TableHeadCell>
                </TableRow>
              </TableHead>
              <TableBody className="divide-y">
                {objects.map((obj) => (
                  <TableRow key={obj.id} className="bg-white dark:border-gray-700 dark:bg-gray-800">
                    <TableCell className="whitespace-nowrap font-medium text-gray-900 dark:text-white">
                      <div>
                        <div className="font-semibold">{extractLocalName(obj.object_uri)}</div>
                        <div className="text-xs text-gray-500 dark:text-gray-400 truncate max-w-xs font-mono">
                          {obj.object_uri}
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>
                      {getObjectTypeBadge(obj.object_type)}
                    </TableCell>
                    <TableCell>
                      <div className="text-sm font-mono">
                        {extractLocalName(obj.rdf_type)}
                      </div>
                    </TableCell>
                    <TableCell className="text-center">
                      <Badge color="gray">{obj.properties_count}</Badge>
                    </TableCell>
                    <TableCell className="text-sm text-gray-600 dark:text-gray-400">
                      {formatDateTime(obj.last_modified)}
                    </TableCell>
                    <TableCell>
                      <div className="flex gap-2">
                        <Button
                          size="xs"
                          color="blue"
                          onClick={() => {
                            // Use hierarchical URL structure
                            if (spaceId && graphId) {
                              navigate(`/space/${spaceId}/graph/${graphId}/object/${obj.id}`);
                            } else {
                              navigate(`/object/${obj.id}`);
                            }
                          }}
                        >
                          <HiEye className="h-3 w-3 mr-1" />
                          Details
                        </Button>
                        <Button
                          size="xs"
                          color="red"
                          onClick={() => {
                            setObjectToDelete(obj);
                            setShowDeleteModal(true);
                          }}
                        >
                          <HiTrash className="h-3 w-3" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </div>
      )}

      {/* No Objects Message */}
      {selectedSpace && selectedGraph !== '' && !loading && objects.length === 0 && !error && (
        <div className="mt-8 text-center py-12">
          <div className="text-gray-500 dark:text-gray-400">
            <p className="text-lg mb-2">No objects found</p>
            <p className="text-sm">
              {searchTerm 
                ? `No objects match "${searchTerm}" in the selected graph.`
                : 'No objects are available in the selected graph.'
              }
            </p>
          </div>
        </div>
      )}

      {/* No Space/Graph Selected Message */}
      {(!selectedSpace || selectedGraph === '') && !spacesLoading && (
        <div className="mt-8 text-center py-12">
          <div className="text-gray-500 dark:text-gray-400">
            {!selectedSpace ? (
              <>
                <p className="text-lg mb-2">Select a space to view objects</p>
                <p className="text-sm">Choose a space from the dropdown above to see available graphs.</p>
              </>
            ) : (
              <>
                <p className="text-lg mb-2">Select a graph to view objects</p>
                <p className="text-sm">Choose a graph from the dropdown above to see its RDF objects.</p>
              </>
            )}
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {showDeleteModal && objectToDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50">
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-lg max-w-md w-full mx-4">
            <div className="p-6">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
                Confirm Object Deletion
              </h3>
              <div className="space-y-4">
                <div className="flex justify-center">
                  <HiTrash className="h-14 w-14 text-red-400" />
                </div>
                <p className="text-gray-500 dark:text-gray-400">
                  Are you sure you want to delete the object <strong>{objectToDelete.subject}</strong>? This action will permanently remove the object and all its properties.
                </p>
                <p className="text-sm text-red-600 dark:text-red-400">
                  <strong>Warning:</strong> This action cannot be undone.
                </p>
              </div>
              <div className="flex gap-2 mt-6">
                <Button color="red" onClick={handleDeleteObject} className="flex-1">
                  Yes, Delete Object
                </Button>
                <Button color="gray" onClick={() => {
                  setShowDeleteModal(false);
                  setObjectToDelete(null);
                }} className="flex-1">
                  Cancel
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default Objects;

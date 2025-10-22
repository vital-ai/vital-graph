import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Button, Spinner, Table, TableBody, TableCell, TableHead, TableHeadCell, TableRow, TextInput, Select, Label, Badge, Breadcrumb, BreadcrumbItem } from 'flowbite-react';
import { HiPlus, HiTrash, HiEye } from 'react-icons/hi2';
import { HiSearch, HiHome, HiViewBoards } from 'react-icons/hi';
import { type Space, type Graph } from '../mock';
import { type GraphInfo, type SpaceInfo } from '../types/api';
import { apiService } from '../services/ApiService';
import GraphIcon from '../components/icons/GraphIcon';

// Helper functions for graph data conversion
const extractGraphName = (graphUri: string): string => {
  if (!graphUri) return 'Unknown Graph';
  
  // Extract name from URI (last part after / or #)
  const parts = graphUri.split(/[/#]/);
  const name = parts[parts.length - 1];
  
  // If empty or just a fragment, use a more descriptive approach
  if (!name || name.length === 0) {
    if (graphUri.includes('global')) return 'Global';
    if (graphUri.includes('default')) return 'Default';
    return 'Graph';
  }
  
  // Convert kebab-case or snake_case to Title Case
  return name
    .replace(/[-_]/g, ' ')
    .replace(/\b\w/g, l => l.toUpperCase());
};

const inferGraphType = (graphUri: string): string => {
  if (!graphUri) return 'Graph';
  
  const uri = graphUri.toLowerCase();
  if (uri.includes('global')) return 'Global Graph';
  if (uri.includes('ontology')) return 'Ontology';
  if (uri.includes('knowledge')) return 'Knowledge Graph';
  if (uri.includes('user')) return 'User Graph';
  if (uri.includes('entity')) return 'Entity Graph';
  if (uri.includes('process') || uri.includes('workflow')) return 'Process Graph';
  if (uri.includes('experiment')) return 'Experimental Graph';
  if (uri.includes('data') || uri.includes('dataset')) return 'Data Graph';
  if (uri.includes('result') || uri.includes('analysis')) return 'Results Graph';
  
  return 'Graph';
};

const Graphs: React.FC = () => {
  const navigate = useNavigate();
  const { spaceId } = useParams<{ spaceId?: string }>();
  const [graphs, setGraphs] = useState<Graph[]>([]);
  const [spaces, setSpaces] = useState<Space[]>([]);
  const [selectedSpace, setSelectedSpace] = useState<string>(spaceId || '');
  const [currentSpace, setCurrentSpace] = useState<Space | null>(null);
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(false);
  const [spacesLoading, setSpacesLoading] = useState<boolean>(true);
  const [filterLoading, setFilterLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Navigate to hierarchical URL when space selection changes
  useEffect(() => {
    if (selectedSpace && !spaceId) {
      navigate(`/space/${selectedSpace}/graphs`);
    }
  }, [selectedSpace, navigate, spaceId]);


  // Fetch spaces on component mount
  useEffect(() => {
    const fetchSpaces = async () => {
      try {
        setSpacesLoading(true);
        setError(null);
        
        const spacesData = await apiService.getSpaces();
        
        // Convert backend format to frontend format
        const convertedSpaces: Space[] = spacesData.map((space: SpaceInfo) => ({
          id: space.id || 0,
          tenant: space.tenant || 'default',
          space: space.space,
          space_name: space.space_name,
          description: space.space_description || '',
          created_time: space.created_time,
          last_modified: space.updated_time
        }));
        
        setSpaces(convertedSpaces);
      } catch (err) {
        console.error('Error fetching spaces:', err);
        setError('Failed to load spaces. Please try again later.');
        setSpaces([]);
      } finally {
        setSpacesLoading(false);
      }
    };

    fetchSpaces();
  }, []);

  // Fetch graphs when space is selected
  const fetchGraphs = useCallback(async () => {
    if (!selectedSpace) {
      setGraphs([]);
      return;
    }

    try {
      setLoading(true);
      setError(null);
      
      const graphsData = await apiService.getGraphs(selectedSpace);
      
      // Convert backend format to frontend format
      const convertedGraphs: Graph[] = graphsData.map((graph: GraphInfo, index: number) => ({
        id: index,
        space_id: selectedSpace,
        graph_name: extractGraphName(graph.graph_uri),
        graph_uri: graph.graph_uri,
        graph_type: inferGraphType(graph.graph_uri),
        triple_count: graph.triple_count || 0,
        created_time: graph.created_time || new Date().toISOString(),
        last_modified: graph.updated_time || new Date().toISOString(),
        description: `Graph containing ${graph.triple_count || 0} triples`,
        status: 'active'
      }));
      
      setGraphs(convertedGraphs);
    } catch (err) {
      console.error('Error fetching graphs:', err);
      setError('Failed to load graphs. Please try again later.');
      setGraphs([]);
    } finally {
      setLoading(false);
    }
  }, [selectedSpace]);

  useEffect(() => {
    fetchGraphs();
  }, [fetchGraphs]);

  // Update current space for breadcrumbs
  useEffect(() => {
    if (selectedSpace && spaces.length > 0) {
      const space = spaces.find(s => s.space === selectedSpace);
      setCurrentSpace(space || null);
    }
  }, [selectedSpace, spaces]);

  // Filter graphs by name
  const filterGraphs = useCallback(async (nameFilter: string) => {
    if (!selectedSpace) return;
    
    if (!nameFilter.trim()) {
      // If filter is empty and not already loading data, fetch all graphs
      if (loading) {
        return;
      }
      await fetchGraphs();
      return;
    }

    try {
      setFilterLoading(true);
      setError(null);
      
      // Fetch all graphs and filter client-side
      // In a production app, you might want to implement server-side filtering
      const graphsData = await apiService.getGraphs(selectedSpace);
      
      // Convert and filter graphs
      const convertedGraphs: Graph[] = graphsData
        .map((graph: GraphInfo, index: number) => ({
          id: index,
          space_id: selectedSpace,
          graph_name: extractGraphName(graph.graph_uri),
          graph_uri: graph.graph_uri,
          graph_type: inferGraphType(graph.graph_uri),
          triple_count: graph.triple_count || 0,
          created_time: graph.created_time || new Date().toISOString(),
          last_modified: graph.updated_time || new Date().toISOString(),
          description: `Graph containing ${graph.triple_count || 0} triples`,
          status: 'active'
        }))
        .filter((graph: Graph) => 
          graph.graph_name.toLowerCase().includes(nameFilter.toLowerCase()) ||
          graph.graph_uri.toLowerCase().includes(nameFilter.toLowerCase())
        );
      
      setGraphs(convertedGraphs);
    } catch (err) {
      console.error('Error filtering graphs:', err);
      setError('Failed to filter graphs. Please try again later.');
      setGraphs([]);
    } finally {
      setFilterLoading(false);
    }
  }, [selectedSpace, loading, fetchGraphs]);

  const handleSearch = () => {
    filterGraphs(searchTerm);
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleSearch();
    }
  };

  const formatTripleCount = (count: number): string => {
    if (count >= 1000000) {
      return `${(count / 1000000).toFixed(1)}M`;
    } else if (count >= 1000) {
      return `${(count / 1000).toFixed(1)}K`;
    }
    return count.toString();
  };

  const formatDateTime = (dateString: string): string => {
    return new Date(dateString).toLocaleString();
  };

  const getStatusBadge = (status: string) => {
    const statusConfig = {
      active: { color: 'success', text: 'Active' },
      inactive: { color: 'failure', text: 'Inactive' },
      processing: { color: 'warning', text: 'Processing' }
    };
    
    const config = statusConfig[status as keyof typeof statusConfig] || statusConfig.inactive;
    return <Badge color={config.color}>{config.text}</Badge>;
  };

  const handleDeleteGraph = async (graph: Graph) => {
    if (!selectedSpace) return;
    
    const confirmed = window.confirm(
      `Are you sure you want to delete the graph "${graph.graph_name}"? This action cannot be undone.`
    );
    
    if (!confirmed) return;
    
    try {
      setLoading(true);
      setError(null);
      
      await apiService.deleteGraph(selectedSpace, graph.graph_uri, true); // silent=true
      
      // Refresh the graphs list
      await fetchGraphs();
      
      // Show success message (you could use a toast notification here)
      console.log(`Graph "${graph.graph_name}" deleted successfully`);
      
    } catch (err) {
      console.error('Error deleting graph:', err);
      setError(`Failed to delete graph "${graph.graph_name}". Please try again later.`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Breadcrumb - only show if we have URL parameter */}
      {spaceId && (
        <Breadcrumb className="mb-6">
          <BreadcrumbItem href="/" icon={HiHome}>
            Home
          </BreadcrumbItem>
          <BreadcrumbItem href="/spaces" icon={HiViewBoards}>Spaces</BreadcrumbItem>
          {currentSpace && (
            <BreadcrumbItem href={`/space/${currentSpace.id}`}>
              {currentSpace.space_name}
            </BreadcrumbItem>
          )}
          <BreadcrumbItem icon={GraphIcon}>Graphs</BreadcrumbItem>
        </Breadcrumb>
      )}

      <div className="mb-6">
        <div className="flex items-center gap-2 mb-2">
          <GraphIcon className="w-6 h-6 text-blue-600" />
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            Graphs
          </h1>
        </div>
        <p className="text-gray-600 dark:text-gray-400">
          Manage RDF graphs within your spaces
        </p>
      </div>

      {/* Space Selection and Add Graph Button */}
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
        
        {selectedSpace && (
          <Button
            color="blue"
            onClick={() => navigate(`/space/${selectedSpace}/graph/new`)}
          >
            <HiPlus className="mr-2 h-4 w-4" />
            Add Graph
          </Button>
        )}
      </div>

      {/* Search Section */}
      {selectedSpace && (
        <div className="mt-6 flex flex-col sm:flex-row gap-4 items-start sm:items-end">
          <div className="flex-1 max-w-md">
            <Label htmlFor="search-input">Search Graphs</Label>
            <TextInput
              id="search-input"
              type="text"
              placeholder="Enter graph name..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              onKeyPress={handleKeyPress}
              disabled={loading || filterLoading}
            />
          </div>
          <Button
            onClick={handleSearch}
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
      {selectedSpace && loading && (
        <div className="mt-8 flex justify-center">
          <Spinner size="lg" />
          <span className="ml-2 text-gray-600 dark:text-gray-400">Loading graphs...</span>
        </div>
      )}

      {/* Graphs Table */}
      {selectedSpace && !loading && graphs.length > 0 && (
        <div className="mt-6">
          <div className="overflow-x-auto">
            <Table>
              <TableHead>
                <TableRow>
                  <TableHeadCell>Graph Name</TableHeadCell>
                  <TableHeadCell>Type</TableHeadCell>
                  <TableHeadCell>Triples</TableHeadCell>
                  <TableHeadCell>Status</TableHeadCell>
                  <TableHeadCell>Last Modified</TableHeadCell>
                  <TableHeadCell>Actions</TableHeadCell>
                </TableRow>
              </TableHead>
              <TableBody className="divide-y">
                {graphs.map((graph) => (
                  <TableRow key={graph.id} className="bg-white dark:border-gray-700 dark:bg-gray-800">
                    <TableCell className="whitespace-nowrap font-medium text-gray-900 dark:text-white">
                      <div>
                        <div className="font-semibold">{graph.graph_name}</div>
                        <div className="text-sm text-gray-500 dark:text-gray-400 truncate max-w-xs">
                          {graph.description}
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge color="info">{graph.graph_type}</Badge>
                    </TableCell>
                    <TableCell className="font-mono">
                      {formatTripleCount(graph.triple_count)}
                    </TableCell>
                    <TableCell>
                      {getStatusBadge(graph.status)}
                    </TableCell>
                    <TableCell className="text-sm text-gray-600 dark:text-gray-400">
                      {formatDateTime(graph.last_modified)}
                    </TableCell>
                    <TableCell>
                      <div className="flex gap-2">
                        <Button
                          size="xs"
                          color="blue"
                          onClick={() => navigate(`/space/${selectedSpace}/graph/${graph.id}`)}
                        >
                          <HiEye className="h-3 w-3 mr-1" />
                          Details
                        </Button>
                        <Button
                          size="xs"
                          color="failure"
                          onClick={() => handleDeleteGraph(graph)}
                          disabled={loading}
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

      {/* No Graphs Message */}
      {selectedSpace && !loading && graphs.length === 0 && !error && (
        <div className="mt-8 text-center py-12">
          <div className="text-gray-500 dark:text-gray-400">
            <p className="text-lg mb-2">No graphs found</p>
            <p className="text-sm">
              {searchTerm 
                ? `No graphs match "${searchTerm}" in the selected space.`
                : 'No graphs are available in the selected space.'
              }
            </p>
          </div>
        </div>
      )}

      {/* No Space Selected Message */}
      {!selectedSpace && !spacesLoading && (
        <div className="mt-8 text-center py-12">
          <div className="text-gray-500 dark:text-gray-400">
            <p className="text-lg mb-2">Select a space to view graphs</p>
            <p className="text-sm">Choose a space from the dropdown above to see its graphs.</p>
          </div>
        </div>
      )}
    </div>
  );
};

export default Graphs;

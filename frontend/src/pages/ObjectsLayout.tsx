import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate, useParams, useLocation, Outlet } from 'react-router-dom';
import axios from 'axios';
import { HiCube, HiCollection } from 'react-icons/hi';
import { Select, Label } from 'flowbite-react';
import NavigationBreadcrumb from '../components/NavigationBreadcrumb';
import ObjectIcon from '../components/icons/ObjectIcon';
import FrameIcon from '../components/icons/FrameIcon';
import { type Space, type Graph } from '../mock';

const ObjectsLayout: React.FC = () => {
  const navigate = useNavigate();
  const { spaceId, graphId } = useParams<{ spaceId?: string; graphId?: string }>();
  const location = useLocation();

  // Shared state for space and graph selection
  const [spaces, setSpaces] = useState<Space[]>([]);
  const [graphs, setGraphs] = useState<Graph[]>([]);
  const [selectedSpace, setSelectedSpace] = useState<string>(spaceId || '');
  const [selectedGraph, setSelectedGraph] = useState<number | ''>('');
  const [spacesLoading, setSpacesLoading] = useState<boolean>(true);
  const [graphsLoading, setGraphsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Determine which tab is active based on the current path
  const getActiveTab = () => {
    const path = location.pathname;
    if (path.includes('/kgentities')) return 'kgentities';
    if (path.includes('/kgframes')) return 'kgframes';
    return 'graphobjects'; // Default to graphobjects
  };

  const handleTabChange = (tab: string) => {
    const basePath = spaceId && graphId 
      ? `/space/${spaceId}/graph/${graphId}/objects`
      : '/objects';
    
    navigate(`${basePath}/${tab}`);
  };

  // Fetch spaces
  const fetchSpaces = useCallback(async () => {
    try {
      setSpacesLoading(true);
      const response = await axios.get('/api/spaces');
      const spacesData = Array.isArray(response.data) ? response.data : response.data.spaces || [];
      setSpaces(spacesData);
      setError(null);
    } catch (err) {
      console.error('Error fetching spaces:', err);
      setError('Failed to load spaces. Please try again later.');
      setSpaces([]);
    } finally {
      setSpacesLoading(false);
    }
  }, []);

  // Fetch graphs for selected space
  const fetchGraphs = useCallback(async (space: string) => {
    try {
      setGraphsLoading(true);
      const response = await axios.get(`/api/graphs/sparql/${space}/graphs`);
      const graphsData = Array.isArray(response.data) ? response.data : [];
      
      // Transform GraphInfo objects to match our Graph interface
      const transformedGraphs = graphsData.map((graphInfo: any, index: number) => ({
        id: index,
        space_id: space,
        graph_name: graphInfo.graph_uri ? (graphInfo.graph_uri.split('/').pop() || graphInfo.graph_uri) : `Graph ${index}`,
        graph_uri: graphInfo.graph_uri || `http://example.org/graph${index}`,
        graph_type: 'Graph',
        triple_count: graphInfo.triple_count || 0,
        created_time: graphInfo.created_time || new Date().toISOString(),
        last_modified: graphInfo.updated_time || new Date().toISOString(),
        description: `Graph: ${graphInfo.graph_uri || 'Unknown'}`,
        status: 'active'
      }));
      
      // If no graphs exist, add a default graph option
      if (transformedGraphs.length === 0) {
        transformedGraphs.push({
          id: 0,
          space_id: space,
          graph_name: 'Default Graph',
          graph_uri: 'http://vital.ai/haley.ai/graph/default',
          graph_type: 'Default',
          triple_count: 0,
          created_time: new Date().toISOString(),
          last_modified: new Date().toISOString(),
          description: 'Default graph for this space',
          status: 'active'
        });
      }
      
      setGraphs(transformedGraphs);
      setError(null);
    } catch (err) {
      console.error('Error fetching graphs:', err);
      setError('Failed to load graphs. Please try again later.');
      setGraphs([]);
    } finally {
      setGraphsLoading(false);
    }
  }, []);

  // Handle space selection
  const handleSpaceChange = (space: string) => {
    setSelectedSpace(space);
    setSelectedGraph('');
    setGraphs([]);
    // Navigate to clear any graph from URL when space changes
    // Use the base objects route without graph when space changes
    const currentTab = getActiveTab();
    navigate(`/objects/${currentTab}`);
  };

  // Handle graph selection
  const handleGraphChange = (graph: number | '') => {
    setSelectedGraph(graph);
    // Navigate to the new URL when graph is selected
    if (selectedSpace && graph !== '') {
      const selectedGraphObj = graphs.find(g => g.id === graph);
      const graphUri = selectedGraphObj ? selectedGraphObj.graph_uri : graph;
      const currentTab = getActiveTab();
      navigate(`/space/${selectedSpace}/graph/${encodeURIComponent(graphUri)}/objects/${currentTab}`);
    }
  };

  // Initialize data
  useEffect(() => {
    fetchSpaces();
  }, [fetchSpaces]);

  useEffect(() => {
    if (selectedSpace) {
      fetchGraphs(selectedSpace);
    }
  }, [selectedSpace, fetchGraphs]);

  // Handle URL with graph URI - find matching graph after graphs are loaded
  // Only auto-select graph if we're on a URL that actually includes a graph
  useEffect(() => {
    if (graphId && spaceId && graphs.length > 0 && selectedGraph === '') {
      console.log('Looking for graph with URI:', decodeURIComponent(graphId));
      
      // Try to find graph by URI (if graphId is a URI)
      const graphByUri = graphs.find(g => g.graph_uri === decodeURIComponent(graphId));
      if (graphByUri) {
        console.log('Found matching graph:', graphByUri);
        setSelectedGraph(graphByUri.id);
      } else {
        console.log('No matching graph found, trying as index');
        // Try as index if it's a number
        const graphIndex = parseInt(graphId);
        if (!isNaN(graphIndex) && graphs[graphIndex]) {
          setSelectedGraph(graphIndex);
        }
      }
    }
  }, [graphId, spaceId, graphs, selectedGraph]);

  const activeTab = getActiveTab();

  return (
    <div className="space-y-6">
      {/* Breadcrumb Navigation */}
      <NavigationBreadcrumb 
        spaceId={spaceId} 
        graphId={graphId} 
        currentPageName="Objects" 
        currentPageIcon={ObjectIcon} 
      />

      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between">
        <div className="mb-6">
          <div className="flex items-center gap-2 mb-2">
            <ObjectIcon className="w-6 h-6 text-blue-600" />
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
              Objects
            </h1>
          </div>
          <p className="text-gray-600 dark:text-gray-400">
            Manage RDF objects, entities, and frames within your graphs
          </p>
        </div>
      </div>

      {/* Space and Graph Selection */}
      <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-end mb-6">
        <div className="flex-1 max-w-xs">
          <Label htmlFor="space-select">Select Space</Label>
          <Select
            id="space-select"
            value={selectedSpace}
            onChange={(e) => handleSpaceChange(e.target.value)}
            disabled={spacesLoading}
          >
            <option value="">Choose a space...</option>
            {spaces.map((space) => (
              <option key={space.space} value={space.space}>
                {space.space_name}
              </option>
            ))}
          </Select>
        </div>

        <div className="flex-1 max-w-xs">
          <Label htmlFor="graph-select">Select Graph</Label>
          <Select
            id="graph-select"
            value={selectedGraph}
            onChange={(e) => handleGraphChange(e.target.value ? parseInt(e.target.value) : '')}
            disabled={!selectedSpace || graphsLoading}
          >
            <option value="">Choose a graph...</option>
            {graphs.map((graph) => (
              <option key={graph.id} value={graph.id}>
                {graph.graph_name}
              </option>
            ))}
          </Select>
        </div>
      </div>

      {/* Custom Tab Navigation */}
      <div className="border-b border-gray-200 dark:border-gray-700">
        <nav className="-mb-px flex space-x-8">
          <button
            onClick={() => handleTabChange('graphobjects')}
            className={`flex items-center gap-2 py-2 px-1 border-b-2 font-medium text-sm ${
              activeTab === 'graphobjects'
                ? 'border-blue-500 text-blue-600 dark:text-blue-500'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
            }`}
          >
            <HiCube className="w-5 h-5" />
            Graph Objects
          </button>
          <button
            onClick={() => handleTabChange('kgentities')}
            className={`flex items-center gap-2 py-2 px-1 border-b-2 font-medium text-sm ${
              activeTab === 'kgentities'
                ? 'border-blue-500 text-blue-600 dark:text-blue-500'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
            }`}
          >
            <HiCollection className="w-5 h-5" />
            KG Entities
          </button>
          <button
            onClick={() => handleTabChange('kgframes')}
            className={`flex items-center gap-2 py-2 px-1 border-b-2 font-medium text-sm ${
              activeTab === 'kgframes'
                ? 'border-blue-500 text-blue-600 dark:text-blue-500'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
            }`}
          >
            <FrameIcon className="w-5 h-5" />
            KG Frames
          </button>
        </nav>
      </div>

      {/* Tab Content */}
      <div className="mt-6">
        <Outlet context={{ 
          selectedSpace, 
          selectedGraph, 
          spaces, 
          graphs, 
          spacesLoading, 
          graphsLoading, 
          error 
        }} />
      </div>
    </div>
  );
};

export default ObjectsLayout;

import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate, useParams, useLocation, Outlet } from 'react-router-dom';
import { apiService } from '../services/ApiService';
import { HiCube, HiCollection, HiLink } from 'react-icons/hi';
import { Select, Label } from 'flowbite-react';
import { type SpaceInfo } from '../types/api';
import { type GraphInfo } from '../types/graphs';
import NavigationBreadcrumb from '../components/NavigationBreadcrumb';
import ObjectIcon from '../components/icons/ObjectIcon';
import FrameIcon from '../components/icons/FrameIcon';

const ObjectsLayout: React.FC = () => {
  const navigate = useNavigate();
  const { spaceId, graphId } = useParams<{ spaceId?: string; graphId?: string }>();
  const location = useLocation();

  // Shared state for space and graph selection
  const [spaces, setSpaces] = useState<SpaceInfo[]>([]);
  const [graphs, setGraphs] = useState<GraphInfo[]>([]);
  const [selectedSpace, setSelectedSpace] = useState<string>(spaceId || '');
  const [selectedGraph, setSelectedGraph] = useState<string>('');
  const [spacesLoading, setSpacesLoading] = useState<boolean>(true);
  const [graphsLoading, setGraphsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Determine which tab is active based on the current path
  const getActiveTab = () => {
    const path = location.pathname;
    if (path.includes('/kgentities')) return 'kgentities';
    if (path.includes('/kgframes')) return 'kgframes';
    if (path.includes('/kgrelations')) return 'kgrelations';
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
      const spacesData = await apiService.getSpaces();
      setSpaces(spacesData);
      setError(null);
    } catch {
      setError('Failed to load spaces.');
      setSpaces([]);
    } finally {
      setSpacesLoading(false);
    }
  }, []);

  // Fetch graphs for selected space
  const fetchGraphs = useCallback(async (space: string) => {
    try {
      setGraphsLoading(true);
      setGraphs(await apiService.getGraphs(space));
      setError(null);
    } catch {
      setError('Failed to load graphs.');
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
  const handleGraphChange = (graphUri: string) => {
    setSelectedGraph(graphUri);
    if (selectedSpace && graphUri) {
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

  // Sync selectedGraph from URL param
  useEffect(() => {
    if (graphId && spaceId && !selectedGraph) {
      const decodedUri = decodeURIComponent(graphId);
      setSelectedGraph(decodedUri);
    }
  }, [graphId, spaceId, selectedGraph]);

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
                {space.space_name || space.space}
              </option>
            ))}
          </Select>
        </div>

        <div className="flex-1 max-w-xs">
          <Label htmlFor="graph-select">Select Graph</Label>
          <Select
            id="graph-select"
            value={selectedGraph}
            onChange={(e) => handleGraphChange(e.target.value)}
            disabled={!selectedSpace || graphsLoading}
          >
            <option value="">Choose a graph...</option>
            {graphs.map((g) => (
              <option key={g.graph_uri} value={g.graph_uri}>
                {g.graph_uri.split('/').pop() || g.graph_uri} ({g.triple_count || 0} triples)
              </option>
            ))}
          </Select>
        </div>
      </div>

      {/* Custom Tab Navigation */}
      <div className="border-b border-gray-200 dark:border-gray-700 overflow-x-auto">
        <nav className="-mb-px flex space-x-4 sm:space-x-8 min-w-max">
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
          <button
            onClick={() => handleTabChange('kgrelations')}
            className={`flex items-center gap-2 py-2 px-1 border-b-2 font-medium text-sm ${
              activeTab === 'kgrelations'
                ? 'border-blue-500 text-blue-600 dark:text-blue-500'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
            }`}
          >
            <HiLink className="w-5 h-5" />
            KG Relations
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

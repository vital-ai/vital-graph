import React, { useState, useEffect } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { Button, Card, Badge, Spinner, Breadcrumb, BreadcrumbItem, Label, TextInput, Textarea, Select } from 'flowbite-react';
import { HiHome, HiDownload, HiPencil, HiTrash, HiChartBar, HiSave, HiX, HiViewBoards, HiExclamation } from 'react-icons/hi';
import { type Space, type Graph } from '../mock';
import { type SpaceInfo } from '../types/api';
import { apiService } from '../services/ApiService';
import GraphIcon from '../components/icons/GraphIcon';

interface BannerMessage {
  type: 'success' | 'error';
  message: string;
}

// Helper functions for graph data conversion (same as in Graphs.tsx)
const extractGraphName = (graphUri: string): string => {
  if (!graphUri) return 'Unknown Graph';
  
  const parts = graphUri.split(/[/#]/);
  const name = parts[parts.length - 1];
  
  if (!name || name.length === 0) {
    if (graphUri.includes('global')) return 'Global';
    if (graphUri.includes('default')) return 'Default';
    return 'Graph';
  }
  
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

const GraphDetail: React.FC = () => {
  const { spaceId, graphId } = useParams<{ spaceId: string; graphId: string }>();
  const navigate = useNavigate();
  
  // Check if this is creation mode
  const isCreating = graphId === 'new';
  const spaceFromUrl = spaceId;
  
  const [graph, setGraph] = useState<Graph | null>(null);
  const [space, setSpace] = useState<Space | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [isEditing, setIsEditing] = useState<boolean>(isCreating);
  const [saving, setSaving] = useState<boolean>(false);
  const [bannerMessage, setBannerMessage] = useState<BannerMessage | null>(null);
  const [showPurgeModal, setShowPurgeModal] = useState<boolean>(false);
  const [showDeleteModal, setShowDeleteModal] = useState<boolean>(false);
  
  // Form state for editing/creating
  const [editForm, setEditForm] = useState({
    graph_name: '',
    graph_uri: '',
    graph_type: 'Knowledge Graph',
    description: '',
    space_id: spaceFromUrl || ''
  });
  
  // Track if form has changes
  const [hasChanges, setHasChanges] = useState<boolean>(false);

  // Data loading or initialization for creation
  useEffect(() => {
    const fetchGraph = async () => {
      if (!graphId || !spaceId) {
        setLoading(false);
        return;
      }
      
      if (isCreating) {
        // Initialize for creation mode
        try {
          // Fetch space info for creation context
          const spacesData = await apiService.getSpaces();
          const spaceInfo = spacesData.find((s: SpaceInfo) => s.space === spaceId);
          
          if (spaceInfo) {
            const convertedSpace: Space = {
              id: spaceInfo.id || 0,
              tenant: spaceInfo.tenant || 'default',
              space: spaceInfo.space,
              space_name: spaceInfo.space_name,
              description: spaceInfo.space_description || '',
              created_time: spaceInfo.created_time,
              last_modified: spaceInfo.updated_time
            };
            setSpace(convertedSpace);
          }
        } catch (err) {
          console.error('Error fetching space info:', err);
        }
        
        setGraph(null);
        setEditForm({
          graph_name: '',
          graph_uri: '',
          graph_type: 'Knowledge Graph',
          description: '',
          space_id: spaceFromUrl || ''
        });
        setLoading(false);
        return;
      }
      
      // Load existing graph data from backend
      try {
        setLoading(true);
        
        // Fetch all graphs for the space and find the one we need
        const graphsData = await apiService.getGraphs(spaceId);
        
        // Since graphId is the index from the frontend, we need to find by URI or position
        // For now, let's use the index approach (this could be improved with proper graph IDs)
        const graphIndex = parseInt(graphId);
        const graphInfo = graphsData[graphIndex];
        
        if (!graphInfo) {
          setBannerMessage({ type: 'error', message: 'Graph not found' });
          setLoading(false);
          return;
        }
        
        // Convert backend format to frontend format
        const convertedGraph: Graph = {
          id: graphIndex,
          space_id: spaceId,
          graph_name: extractGraphName(graphInfo.graph_uri),
          graph_uri: graphInfo.graph_uri,
          graph_type: inferGraphType(graphInfo.graph_uri),
          triple_count: graphInfo.triple_count || 0,
          created_time: graphInfo.created_time || new Date().toISOString(),
          last_modified: graphInfo.updated_time || new Date().toISOString(),
          description: `Graph containing ${graphInfo.triple_count || 0} triples`,
          status: 'active'
        };
        
        // Fetch space info
        const spacesData = await apiService.getSpaces();
        const spaceInfo = spacesData.find((s: SpaceInfo) => s.space === spaceId);
        
        if (spaceInfo) {
          const convertedSpace: Space = {
            id: spaceInfo.id || 0,
            tenant: spaceInfo.tenant || 'default',
            space: spaceInfo.space,
            space_name: spaceInfo.space_name,
            description: spaceInfo.space_description || '',
            created_time: spaceInfo.created_time,
            last_modified: spaceInfo.updated_time
          };
          setSpace(convertedSpace);
        }
        
        setGraph(convertedGraph);
        
        // Initialize edit form with existing data
        setEditForm({
          graph_name: convertedGraph.graph_name,
          graph_uri: convertedGraph.graph_uri,
          graph_type: convertedGraph.graph_type,
          description: convertedGraph.description,
          space_id: convertedGraph.space_id
        });
        
      } catch (err) {
        console.error('Error fetching graph:', err);
        setBannerMessage({ type: 'error', message: 'Failed to load graph data' });
      } finally {
        setLoading(false);
      }
    };
    
    fetchGraph();
  }, [graphId, isCreating, spaceFromUrl, spaceId]);

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

  const handleInputChange = (field: string, value: string) => {
    setEditForm(prev => ({ ...prev, [field]: value }));
    setHasChanges(true);
  };

  const handleSave = async () => {
    if (!spaceId) return;
    
    setSaving(true);
    try {
      if (isCreating) {
        // Create new graph
        await apiService.createGraph(spaceId, editForm.graph_uri);
        setBannerMessage({ type: 'success', message: 'Graph created successfully!' });
        
        // Navigate back to graphs list
        setTimeout(() => {
          navigate(`/space/${spaceId}/graphs`);
        }, 2000);
      } else {
        // For updates, we would need an update graph API endpoint
        // For now, show a message that updates aren't supported yet
        setBannerMessage({ 
          type: 'error', 
          message: 'Graph updates not yet supported by backend API' 
        });
        setIsEditing(false);
        setHasChanges(false);
      }
    } catch (error) {
      console.error('Error saving graph:', error);
      setBannerMessage({ 
        type: 'error', 
        message: `Failed to ${isCreating ? 'create' : 'update'} graph. Please try again.` 
      });
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    if (isCreating) {
      navigate('/graphs');
    } else {
      setIsEditing(false);
      setHasChanges(false);
      // Reset form to original values
      if (graph) {
        setEditForm({
          graph_name: graph.graph_name,
          graph_uri: graph.graph_uri,
          graph_type: graph.graph_type,
          description: graph.description,
          space_id: graph.space_id
        });
      }
    }
  };

  const handlePurge = async () => {
    if (!spaceId || !graph) return;
    
    try {
      // Use CLEAR operation to purge graph content
      await apiService.executeGraphOperation(spaceId, 'CLEAR', graph.graph_uri, undefined, true);
      setBannerMessage({ type: 'success', message: 'Graph purged successfully!' });
      setShowPurgeModal(false);
      
      // Clear banner after 3 seconds
      setTimeout(() => setBannerMessage(null), 3000);
    } catch (error) {
      console.error('Error purging graph:', error);
      setBannerMessage({ type: 'error', message: 'Failed to purge graph. Please try again.' });
      setShowPurgeModal(false);
    }
  };

  const handleDelete = async () => {
    if (!spaceId || !graph) return;
    
    try {
      // Delete the graph
      await apiService.deleteGraph(spaceId, graph.graph_uri, true);
      setBannerMessage({ type: 'success', message: 'Graph deleted successfully!' });
      setShowDeleteModal(false);
      
      // Navigate back to graphs list after deletion
      setTimeout(() => navigate(`/space/${spaceId}/graphs`), 1500);
    } catch (error) {
      console.error('Error deleting graph:', error);
      setBannerMessage({ type: 'error', message: 'Failed to delete graph. Please try again.' });
      setShowDeleteModal(false);
    }
  };

if (loading) {
  return (
    <div className="p-6">
      <div className="flex justify-center items-center h-64">
        <Spinner size="xl" />
        <span className="ml-3 text-lg text-gray-600 dark:text-gray-400">Loading graph details...</span>
      </div>
    </div>
  );
}

if (!isCreating && !graph && !loading) {
  return (
    <div className="mb-6">
      <div className="flex items-center gap-2 mb-4">
        <GraphIcon className="w-6 h-6 text-blue-600" />
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
          Graph Details
        </h1>
      </div>
      <Link to="/graphs">
        <Button>Back to Graphs</Button>
      </Link>
    </div>
  );
}

return (
  <div className="p-6">
    {/* Breadcrumb */}
    <Breadcrumb className="mb-6">
      <BreadcrumbItem href="/" icon={HiHome}>
        Home
      </BreadcrumbItem>
      <BreadcrumbItem href="/spaces" icon={HiViewBoards}>
        Spaces
      </BreadcrumbItem>
      {spaceId && space && (
        <BreadcrumbItem href={`/space/${space.id}`}>
          {space.space_name}
        </BreadcrumbItem>
      )}
      <BreadcrumbItem href={spaceId ? `/space/${spaceId}/graphs` : "/graphs"} icon={GraphIcon}>
        Graphs
      </BreadcrumbItem>
      {!isCreating && graphId && (
        <BreadcrumbItem>
          {graph?.graph_name || graphId}
        </BreadcrumbItem>
      )}
      {isCreating && (
        <BreadcrumbItem>
          New Graph
        </BreadcrumbItem>
      )}
    </Breadcrumb>

    {/* Banner Message */}
    {bannerMessage && (
      <div className={`mb-6 p-4 rounded-lg ${
        bannerMessage.type === 'success'
          ? 'bg-green-50 border border-green-200 text-green-800 dark:bg-green-900/20 dark:border-green-800 dark:text-green-200'
          : 'bg-red-50 border border-red-200 text-red-800 dark:bg-red-900/20 dark:border-red-800 dark:text-red-200'
      }`}>
        {bannerMessage.message}
      </div>
    )}

    {/* Header */}
    <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-6">
      <div className="flex items-center gap-2">
        <GraphIcon className="w-8 h-8 text-blue-600" />
        <h1 className="text-3xl font-bold text-gray-900 dark:text-white mb-2">
          {isCreating ? 'Create New Graph' : (graph?.graph_name || 'Loading...')}
        </h1>
        {!isCreating && graph && (
          <div className="flex items-center gap-3">
            <Badge color="info">{graph.graph_type}</Badge>
            {getStatusBadge(graph.status)}
          </div>
        )}
      </div>

      {!isCreating && graph && (
        <div className="flex gap-2">
          {isEditing ? (
            <>
              <Button
                color="gray"
                onClick={handleCancel}
                disabled={saving}
              >
                <HiX className="mr-2 h-4 w-4" />
                Cancel
              </Button>
              <Button
                color="blue"
                onClick={handleSave}
                disabled={saving || !hasChanges}
              >
                <HiSave className="mr-2 h-4 w-4" />
                {saving ? 'Saving...' : 'Save'}
              </Button>
            </>
          ) : (
            <>
              <Button
                color="blue"
                onClick={() => navigate(`/data/import/new?spaceId=${spaceId}&graphId=${graphId}`)}
              >
                <HiDownload className="mr-2 h-4 w-4" />
                Import
              </Button>
              <Button
                color="gray"
                onClick={() => navigate(`/data/export/new?spaceId=${spaceId}&graphId=${graphId}`)}
              >
                <HiDownload className="mr-2 h-4 w-4" />
                Export
              </Button>
              <Button
                color="blue"
                onClick={() => setIsEditing(true)}
              >
                <HiPencil className="mr-2 h-4 w-4" />
                Edit
              </Button>
              <Button
                color="red"
                onClick={() => setShowPurgeModal(true)}
              >
                <HiExclamation className="mr-2 h-4 w-4" />
                Purge
              </Button>
              <Button
                color="red"
                onClick={() => setShowDeleteModal(true)}
              >
                <HiTrash className="mr-2 h-4 w-4" />
                Delete
              </Button>
            </>
          )}
        </div>
      )}

      {isCreating && (
        <div className="flex gap-2">
          <Button
            color="success"
            onClick={handleSave}
            disabled={saving || !editForm.graph_name || !editForm.space_id}
          >
            <HiSave className="mr-2 h-4 w-4" />
            {saving ? 'Creating...' : 'Create Graph'}
          </Button>
          <Button
            color="gray"
            onClick={handleCancel}
            disabled={saving}
          >
            <HiX className="mr-2 h-4 w-4" />
            Cancel
          </Button>
        </div>
      )}
    </div>

    {/* Graph Details */}
    <div className="mb-6">
      {/* Basic Information */}
      {!isCreating && !isEditing && (
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">
          Basic Information
        </h2>
      )}
      <Card>
        {(isCreating || isEditing) && (
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">
            Graph Information
          </h2>
        )}

        {isCreating || isEditing ? (
          <div className="space-y-4">
            <div>
              <Label htmlFor="graph_name">Graph Name *</Label>
              <TextInput
                id="graph_name"
                type="text"
                value={editForm.graph_name}
                onChange={(e) => handleInputChange('graph_name', e.target.value)}
                placeholder="Enter graph name"
                required
              />
            </div>

            <div>
              <Label htmlFor="graph_uri">Graph URI</Label>
              <TextInput
                id="graph_uri"
                type="text"
                value={editForm.graph_uri}
                onChange={(e) => handleInputChange('graph_uri', e.target.value)}
                placeholder="http://example.com/graph/my-graph"
              />
            </div>

            <div>
              <Label htmlFor="graph_type">Graph Type</Label>
              <Select
                id="graph_type"
                value={editForm.graph_type}
                onChange={(e) => handleInputChange('graph_type', e.target.value)}
              >
                <option value="Knowledge Graph">Knowledge Graph</option>
                <option value="Ontology">Ontology</option>
                <option value="Dataset">Dataset</option>
                <option value="Workflow">Workflow</option>
              </Select>
            </div>

            <div>
              <Label htmlFor="description">Description</Label>
              <Textarea
                id="description"
                rows={3}
                value={editForm.description}
                onChange={(e) => handleInputChange('description', e.target.value)}
                placeholder="Enter graph description"
              />
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3 w-full">
            <div>
              <span className="font-medium text-gray-700 dark:text-gray-300">Space:</span>
              <p className="text-sm text-gray-600 dark:text-gray-400">
                {space?.space_name || 'Unknown Space'} ({space?.space || 'N/A'})
              </p>
            </div>
            <div>
              <span className="font-medium text-gray-700 dark:text-gray-300">Graph Name:</span>
              <p className="text-sm text-gray-600 dark:text-gray-400">
                {graph?.graph_name}
              </p>
            </div>
            <div>
              <span className="font-medium text-gray-700 dark:text-gray-300">Type:</span>
              <p className="text-sm text-gray-600 dark:text-gray-400">
                {graph?.graph_type}
              </p>
            </div>
            <div>
              <span className="font-medium text-gray-700 dark:text-gray-300">Status:</span>
              <div className="text-sm">
                {graph && getStatusBadge(graph.status)}
              </div>
            </div>
            <div>
              <span className="font-medium text-gray-700 dark:text-gray-300">Triple Count:</span>
              <p className="text-sm text-gray-600 dark:text-gray-400">
                {graph?.triple_count.toLocaleString()} triples
              </p>
            </div>
            <div>
              <span className="font-medium text-gray-700 dark:text-gray-300">Created:</span>
              <p className="text-sm text-gray-600 dark:text-gray-400">
                {graph?.created_time ? formatDateTime(graph.created_time) : 'N/A'}
              </p>
            </div>
            <div>
              <span className="font-medium text-gray-700 dark:text-gray-300">Last Modified:</span>
              <p className="text-sm text-gray-600 dark:text-gray-400">
                {graph?.last_modified ? formatDateTime(graph.last_modified) : 'N/A'}
              </p>
            </div>
            <div className="sm:col-span-2">
              <span className="font-medium text-gray-700 dark:text-gray-300">Graph URI:</span>
              <p className="text-sm text-gray-600 dark:text-gray-400 font-mono break-all">
                {graph?.graph_uri}
              </p>
            </div>
            <div className="sm:col-span-2">
              <span className="font-medium text-gray-700 dark:text-gray-300">Description:</span>
              <p className="text-sm text-gray-600 dark:text-gray-400">
                {graph?.description || 'No description provided'}
              </p>
            </div>
          </div>
        )}
      </Card>
    </div>

    {/* Space Selection for Creation Mode */}
    {isCreating && (
      <Card className="mb-6">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">
          Space Assignment
        </h2>
        <div>
          <Label htmlFor="space_id">Target Space *</Label>
          <Select
            id="space_id"
            value={editForm.space_id}
            onChange={(e) => handleInputChange('space_id', e.target.value)}
            required
          >
            <option value="">Select a space...</option>
            <option value="space1">Default Space</option>
            <option value="space2">Project Alpha</option>
            <option value="space3">Research Data</option>
          </Select>
        </div>
      </Card>
    )}

    {/* Quick Actions - Only show for existing graphs */}
    {!isCreating && graph && (
      <Card>
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">
          Quick Actions
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          <Button
            color="blue"
            onClick={() => navigate(`/data/import/new?spaceId=${spaceId}&graphId=${graphId}`)}
            className="w-full"
          >
            <HiDownload className="mr-2 h-4 w-4" />
            Import
          </Button>
          <Button
            color="gray"
            onClick={() => navigate(`/data/export/new?spaceId=${spaceId}&graphId=${graphId}`)}
            className="w-full"
          >
            <HiDownload className="mr-2 h-4 w-4" />
            Export
          </Button>
          <Button
            color="purple"
            onClick={() => navigate(`/space/${spaceId}/graph/${graphId}/analysis`)}
            className="w-full"
          >
            <HiChartBar className="mr-2 h-4 w-4" />
            Analysis
          </Button>
        </div>
      </Card>
    )}

    {/* Purge Confirmation Modal */}
    {showPurgeModal && (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50">
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-lg max-w-md w-full mx-4">
          <div className="p-6">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
              Confirm Graph Purge
            </h3>
            <div className="space-y-4">
              <div className="flex justify-center">
                <HiExclamation className="h-14 w-14 text-yellow-400" />
              </div>
              <p className="text-gray-500 dark:text-gray-400">
                Are you sure you want to purge this graph? This action will remove all data from the graph but keep the graph structure intact.
              </p>
              <p className="text-sm text-red-600 dark:text-red-400">
                <strong>Warning:</strong> This action cannot be undone.
              </p>
            </div>
            <div className="flex gap-2 mt-6">
              <Button color="red" onClick={handlePurge} className="flex-1">
                Yes, Purge Graph
              </Button>
              <Button color="gray" onClick={() => setShowPurgeModal(false)} className="flex-1">
                Cancel
              </Button>
            </div>
          </div>
        </div>
      </div>
    )}

    {/* Delete Confirmation Modal */}
    {showDeleteModal && (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50">
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-lg max-w-md w-full mx-4">
          <div className="p-6">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
              Confirm Graph Deletion
            </h3>
            <div className="space-y-4">
              <div className="flex justify-center">
                <HiTrash className="h-14 w-14 text-red-400" />
              </div>
              <p className="text-gray-500 dark:text-gray-400">
                Are you sure you want to delete this graph? This action will permanently remove the graph and all its data.
              </p>
              <p className="text-sm text-red-600 dark:text-red-400">
                <strong>Warning:</strong> This action cannot be undone.
              </p>
            </div>
            <div className="flex gap-2 mt-6">
              <Button color="red" onClick={handleDelete} className="flex-1">
                Yes, Delete Graph
              </Button>
              <Button color="gray" onClick={() => setShowDeleteModal(false)} className="flex-1">
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

export default GraphDetail;
